"""Main processing pipeline.

This module orchestrates the full upload processing flow:
parse → normalize headers → match template → map rows → validate → persist.

IMPORTANT: This module is called exclusively from Celery tasks, never from views.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

if TYPE_CHECKING:
    from apps.uploads.models import UploadBatch

logger = logging.getLogger(__name__)


def run_processing_pipeline(batch_id: int) -> None:
    """Entry point called by the Celery task.

    Creates a new ProcessingRun for every invocation (including reprocessing).
    Old ProcessingRun and ImportRow records are NEVER deleted.
    """
    from apps.uploads.models import UploadBatch, ProcessingRun, TemplateMatchLog, ImportRow, ValidationIssue
    from apps.field_templates.services.normalization import normalize_headers_list, build_alias_lookup
    from apps.field_templates.services.matching import find_best_template
    from apps.field_templates.models import StandardMasterField
    from .parser import parse_file, compute_file_checksum
    from .validator import (
        validate_file, validate_template_match, validate_row, validate_business,
        compute_row_status, compute_business_key,
    )

    # ── 1. Lock and set batch to processing ───────────────────────────────────
    with transaction.atomic():
        try:
            batch: UploadBatch = UploadBatch.objects.select_for_update().select_related("distributor").get(pk=batch_id)
        except UploadBatch.DoesNotExist:
            logger.error("UploadBatch %d not found", batch_id)
            return

        if batch.status == UploadBatch.STATUS_PROCESSING:
            logger.warning("Batch %d is already processing, skipping", batch_id)
            return

        run_number = batch.processing_runs.count() + 1
        batch.status = UploadBatch.STATUS_PROCESSING
        batch.error_message = ""
        batch.save(update_fields=["status", "error_message", "updated_at"])

    # ── 2. Create ProcessingRun ───────────────────────────────────────────────
    run = ProcessingRun.objects.create(
        batch=batch,
        run_number=run_number,
    )

    try:
        _execute_pipeline(batch, run)
    except Exception as exc:
        logger.exception("Pipeline failed for batch %d run %d", batch_id, run.pk)
        run.error_message = str(exc)
        run.completed_at = timezone.now()
        run.save(update_fields=["error_message", "completed_at"])
        batch.status = UploadBatch.STATUS_ERROR
        batch.error_message = str(exc)
        batch.save(update_fields=["status", "error_message", "updated_at"])
        raise


def _execute_pipeline(batch, run) -> None:
    from apps.uploads.models import UploadBatch, ProcessingRun, TemplateMatchLog, ImportRow, ValidationIssue
    from apps.field_templates.services.normalization import normalize_headers_list, build_alias_lookup
    from apps.field_templates.services.matching import find_best_template
    from apps.field_templates.models import StandardMasterField
    from .parser import parse_file, compute_file_checksum
    from .validator import (
        validate_file, validate_template_match, validate_row, validate_business,
        compute_row_status, compute_business_key,
    )

    import os
    from django.conf import settings as django_settings

    file_path = os.path.join(django_settings.MEDIA_ROOT, batch.file_path)

    # ── 3. Parse file ─────────────────────────────────────────────────────────
    parse_result = parse_file(file_path, batch.original_filename)

    file_issues = validate_file(
        parse_result.parse_errors,
        parse_result.row_count,
        batch.file_checksum,
        batch.distributor_id,
    )

    if parse_result.parse_errors:
        _fail_batch(batch, run, "; ".join(parse_result.parse_errors))
        return

    # ── 4. Normalize headers + build alias lookup ────────────────────────────
    header_map = normalize_headers_list(parse_result.headers)  # {raw: normalized}
    normalized_headers = list(header_map.values())
    standard_fields = list(StandardMasterField.objects.all())
    alias_lookup = build_alias_lookup(standard_fields)

    # ── 5. Find best template ─────────────────────────────────────────────────
    best_match = find_best_template(batch.distributor, normalized_headers, alias_lookup)

    # Persist match logs for every scored template
    for mr in best_match.all_results:
        TemplateMatchLog.objects.create(
            processing_run=run,
            template_version_id=mr.template_version_id,
            match_score=mr.score,
            matched=(best_match.template_version is not None and mr.template_version_id == best_match.template_version.pk),
            is_assigned=mr.is_assigned,
            reason=mr.reason,
            matched_columns=mr.matched_columns,
            unmatched_columns=mr.unmatched_columns,
        )

    if best_match.template_version is None:
        batch.status = UploadBatch.STATUS_MISMATCH
        batch.error_message = "No matching template found."
        batch.save(update_fields=["status", "error_message", "updated_at"])
        from django.utils import timezone as _tz
        run.completed_at = _tz.now()
        run.save(update_fields=["completed_at"])
        return

    template_version = best_match.template_version
    run.template_version = template_version
    run.match_score = best_match.score
    run.used_global = best_match.used_global
    run.fallback_happened = best_match.fallback_happened
    run.save(update_fields=["template_version", "match_score", "used_global", "fallback_happened"])

    # ── 6. Build template mapping lookup ─────────────────────────────────────
    mappings = list(template_version.field_mappings.select_related("standard_field"))
    standard_fields_by_id = {sf.pk: sf for sf in standard_fields}

    # ── 7. Process rows ───────────────────────────────────────────────────────
    import_rows_to_create = []
    row_checksums_in_run: set[str] = set()
    from .parser import compute_row_checksum

    all_import_rows = []

    for i, raw_row in enumerate(parse_result.rows, start=1):
        from .parser import compute_row_checksum as _crc

        row_checksum = _crc(raw_row)
        mapped_data = _map_row(raw_row, header_map, mappings, alias_lookup, standard_fields_by_id)
        _inject_batch_context(mapped_data, batch, standard_fields_by_id)
        business_key = compute_business_key(mapped_data, batch.distributor.code)

        # Row-level validation
        row_issues_dicts = validate_row(mapped_data, standard_fields, i)
        row_status = compute_row_status(row_issues_dicts)

        # Create ImportRow
        import_row = ImportRow(
            processing_run=run,
            row_number=i,
            raw_data=raw_row,
            mapped_data=mapped_data,
            row_checksum=row_checksum,
            row_status=row_status,
            review_decision=ImportRow.DECISION_PENDING,
            business_key=business_key,
        )
        import_row.save()

        # Business validation (after row is saved so we have a PK)
        biz_issues = validate_business(
            mapped_data,
            row_checksum,
            business_key,
            run.pk,
            import_row.pk,
            batch.distributor_id,
        )
        row_issues_dicts.extend(biz_issues)

        # Update status if business issues introduced new warnings
        new_status = compute_row_status(row_issues_dicts)
        if new_status != row_status:
            import_row.row_status = new_status
            import_row.save(update_fields=["row_status"])

        # Bulk create validation issues
        if row_issues_dicts:
            ValidationIssue.objects.bulk_create([
                ValidationIssue(
                    import_row=import_row,
                    **issue_dict,
                )
                for issue_dict in row_issues_dicts
            ])

        all_import_rows.append(import_row)

    # ── 8. Finalize ───────────────────────────────────────────────────────────
    batch.status = UploadBatch.STATUS_PROCESSED
    batch.row_count = len(all_import_rows)
    batch.save(update_fields=["status", "row_count", "updated_at"])

    from django.utils import timezone
    run.completed_at = timezone.now()
    run.save(update_fields=["completed_at"])

    logger.info(
        "Batch %d processed: %d rows, template_version=%d, score=%.2f",
        batch.pk,
        len(all_import_rows),
        template_version.pk,
        best_match.score,
    )


def _map_row(
    raw_row: dict,
    header_map: dict[str, str],   # {raw_header: normalized_header}
    mappings: list,                 # list of TemplateFieldMapping
    alias_lookup: dict[str, int],  # {normalized_alias: standard_field_id}
    standard_fields_by_id: dict[int, object],
) -> dict:
    """Map raw row values to standard field names.

    Pass 1: Template-driven — source_column_normalized or alias for each TemplateFieldMapping.
    Pass 2: Alias-driven fallback — for standard fields not covered by the template,
            check if any file column matches a field alias. This allows fields like
            'date' to be populated via alias even without an explicit template mapping.
    """
    # Build {normalized_header: raw_value} for this row
    normalized_row: dict[str, str] = {}
    for raw_header, raw_value in raw_row.items():
        norm = header_map.get(raw_header, "")
        if norm:
            normalized_row[norm] = str(raw_value)

    result: dict[str, str] = {}
    mapped_field_ids: set[int] = set()

    # Pass 1: Template field mappings
    for mapping in mappings:
        sf = mapping.standard_field
        value: str | None = None

        # 1a. Direct match via template source_column
        if mapping.source_column_normalized in normalized_row:
            value = normalized_row[mapping.source_column_normalized]

        # 1b. Alias match for this field
        if value is None:
            for alias_norm, field_id in alias_lookup.items():
                if field_id == sf.pk and alias_norm in normalized_row:
                    value = normalized_row[alias_norm]
                    break

        if value is not None:
            result[sf.name] = value
            mapped_field_ids.add(sf.pk)

    # Pass 2: Alias-driven fallback for fields not covered by the template.
    # If a file column matches any alias (including the field's own name) for a
    # standard field that the template didn't map, still populate it.
    for alias_norm, field_id in alias_lookup.items():
        if field_id in mapped_field_ids:
            continue
        sf = standard_fields_by_id.get(field_id)
        if sf is None:
            continue
        if alias_norm in normalized_row:
            result[sf.name] = normalized_row[alias_norm]
            mapped_field_ids.add(field_id)

    return result


def _inject_batch_context(mapped_data: dict, batch, standard_fields_by_id: dict) -> None:
    """Fill standard fields whose batch_context_source is configured.

    Reads the attribute path from StandardMasterField.batch_context_source.
    Only injects if the field is not already populated from the file.
    """
    for sf in standard_fields_by_id.values():
        if sf.name in mapped_data:
            continue
        attr_path = sf.batch_context_source  # e.g. "distributor.name"
        if not attr_path:
            continue
        try:
            obj = batch
            for attr in attr_path.split("."):
                obj = getattr(obj, attr)
            if obj is not None:
                mapped_data[sf.name] = str(obj)
        except Exception:
            pass


def _fail_batch(batch, run, error_message: str) -> None:
    from django.utils import timezone
    batch.status = batch.STATUS_ERROR
    batch.error_message = error_message
    batch.save(update_fields=["status", "error_message", "updated_at"])
    run.error_message = error_message
    run.completed_at = timezone.now()
    run.save(update_fields=["error_message", "completed_at"])
