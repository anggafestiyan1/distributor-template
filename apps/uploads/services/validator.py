"""Validation engine for uploaded rows.

Validation is split into 4 categories:
  FILE     — checked once per batch (file-level issues)
  TEMPLATE — checked once per batch (template matching issues)
  ROW      — checked per row (type, required fields)
  BUSINESS — checked per row (duplicates, domain rules)
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.field_templates.models import StandardMasterField
    from apps.uploads.models import ProcessingRun

logger = logging.getLogger(__name__)


# ── Issue builders ────────────────────────────────────────────────────────────

def _issue(
    category: str,
    severity: str,
    code: str,
    message: str,
    field_name: str = "",
) -> dict:
    return {
        "category": category,
        "severity": severity,
        "code": code,
        "message": message,
        "field_name": field_name,
    }


# ── File-level validation (called once per batch) ──────────────────────────────

def validate_file(
    parse_errors: list[str],
    row_count: int,
    file_checksum: str,
    distributor_id: int,
) -> list[dict]:
    """Return a list of file-level issue dicts (not saved to DB here)."""
    from apps.uploads.models import UploadBatch

    issues: list[dict] = []

    if parse_errors:
        for err in parse_errors:
            issues.append(_issue("file", "error", "FILE_PARSE_ERROR", err))

    if row_count == 0 and not parse_errors:
        issues.append(_issue("file", "error", "FILE_EMPTY", "The file contains no data rows."))

    # Duplicate file check (same checksum, same distributor)
    duplicate_exists = UploadBatch.objects.filter(
        file_checksum=file_checksum,
        distributor_id=distributor_id,
        status=UploadBatch.STATUS_PROCESSED,
    ).exists()
    if duplicate_exists:
        issues.append(
            _issue(
                "file",
                "warning",
                "FILE_DUPLICATE_CHECKSUM",
                "A file with the same content has already been successfully processed for this distributor.",
            )
        )

    return issues


# ── Template-level validation ──────────────────────────────────────────────────

def validate_template_match(
    best_match,
    normalized_headers: list[str],
    template_version,
) -> list[dict]:
    """Validate the template matching result."""
    issues: list[dict] = []

    if template_version is None:
        issues.append(
            _issue(
                "template",
                "error",
                "TEMPLATE_MISMATCH",
                "No matching template found for this file's column headers.",
            )
        )
        return issues

    from django.conf import settings
    min_score = getattr(settings, "TEMPLATE_MATCH_MIN_SCORE", 0.8)

    if best_match.score < 1.0:
        issues.append(
            _issue(
                "template",
                "info",
                "TEMPLATE_LOW_SCORE",
                f"Template matched at {best_match.score:.0%}. Some columns may be unmapped.",
            )
        )

    return issues


# ── Row-level validation ───────────────────────────────────────────────────────

def validate_row(
    mapped_data: dict,
    standard_fields: list["StandardMasterField"],
    row_number: int,
) -> list[dict]:
    """Validate a single mapped row against standard field definitions."""
    issues: list[dict] = []

    for sf in standard_fields:
        value = mapped_data.get(sf.name, "")
        str_value = str(value).strip() if value is not None else ""

        if not str_value:
            continue  # Empty is OK — no required fields

        # Type validation
        type_issues = _validate_type(sf, str_value)
        issues.extend(type_issues)

    return issues


def _validate_type(sf, str_value: str) -> list[dict]:
    issues: list[dict] = []
    severity = "warning"

    if sf.data_type == "integer":
        try:
            int(str_value.replace(",", "").replace(".", ""))
        except ValueError:
            issues.append(
                _issue(
                    "row",
                    severity,
                    "ROW_TYPE_MISMATCH",
                    f"Field '{sf.display_name}' expects an integer, got: '{str_value}'",
                    sf.name,
                )
            )

    elif sf.data_type == "decimal":
        try:
            Decimal(str_value.replace(",", "."))
        except InvalidOperation:
            issues.append(
                _issue(
                    "row",
                    severity,
                    "ROW_TYPE_MISMATCH",
                    f"Field '{sf.display_name}' expects a decimal number, got: '{str_value}'",
                    sf.name,
                )
            )

    elif sf.data_type == "date":
        parsed = _try_parse_date(str_value)
        if parsed is None:
            issues.append(
                _issue(
                    "row",
                    severity,
                    "ROW_DATE_PARSE_FAILED",
                    f"Field '{sf.display_name}' could not be parsed as a date: '{str_value}'",
                    sf.name,
                )
            )

    elif sf.data_type == "boolean":
        valid_booleans = {"true", "false", "1", "0", "yes", "no", "y", "n"}
        if str_value.lower() not in valid_booleans:
            issues.append(
                _issue(
                    "row",
                    severity,
                    "ROW_TYPE_MISMATCH",
                    f"Field '{sf.display_name}' expects a boolean value, got: '{str_value}'",
                    sf.name,
                )
            )

    return issues


def _try_parse_date(value: str) -> datetime | None:
    # Strip time component if present (Excel datetimes come as "2026-02-24 00:00:00")
    stripped = value.strip()
    if " " in stripped and ":" in stripped:
        stripped = stripped.split(" ")[0]

    formats = [
        "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d",
        "%d %m %Y", "%Y%m%d", "%d/%m/%y", "%m/%d/%Y",
        "%b %Y", "%B %Y",  # "Feb 2026", "February 2026"
    ]
    for fmt in formats:
        try:
            return datetime.strptime(stripped, fmt)
        except ValueError:
            continue
    return None


# ── Business validation ────────────────────────────────────────────────────────

def validate_business(
    mapped_data: dict,
    row_checksum: str,
    business_key: str,
    processing_run_id: int,
    import_row_id: int,
    distributor_id: int,
) -> list[dict]:
    """Business-level duplicate and domain checks."""
    from apps.uploads.models import ImportRow
    from apps.master_data.models import MasterDataRecord

    issues: list[dict] = []

    # Duplicate row within same batch/run
    duplicate_in_run = ImportRow.objects.filter(
        processing_run_id=processing_run_id,
        row_checksum=row_checksum,
    ).exclude(pk=import_row_id).exists()

    if duplicate_in_run:
        issues.append(
            _issue(
                "business",
                "warning",
                "BIZ_DUPLICATE_IN_BATCH",
                "This row appears to be an exact duplicate of another row in the same upload.",
            )
        )

    # Duplicate row in master data
    if business_key:
        exists_in_master = MasterDataRecord.objects.filter(
            distributor_id=distributor_id,
            business_key=business_key,
        ).exists()
        if exists_in_master:
            issues.append(
                _issue(
                    "business",
                    "warning",
                    "BIZ_DUPLICATE_IN_MASTER",
                    f"A record with business key '{business_key}' already exists in Master Data.",
                )
            )

    return issues


def compute_row_status(issues: list[dict]) -> str:
    """Determine the row_status based on the highest severity issue."""
    severities = {i["severity"] for i in issues}
    if "error" in severities:
        return "invalid"
    if "warning" in severities:
        return "warning"
    return "valid"


def compute_business_key(mapped_data: dict, distributor_code: str) -> str:
    """Compute a composite business key for duplicate detection.

    Uses distributor code + invoice_date + item_name if available,
    falling back to all required fields.
    """
    parts = [distributor_code]
    for key in ["invoice_id", "invoice_date", "item_name", "invoice_number", "product_code"]:
        val = str(mapped_data.get(key, "")).strip()
        if val:
            parts.append(val)
    if len(parts) <= 1:
        # Fallback: use all non-empty values sorted
        parts += sorted(str(v).strip() for v in mapped_data.values() if str(v).strip())
    key = "|".join(parts)
    return key[:255]  # Truncate to fit DB field
