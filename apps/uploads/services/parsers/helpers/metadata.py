"""PDF metadata extraction and parsed-JSON persistence."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from ..base import ParseResult
from ..config import ParserConfig

logger = logging.getLogger(__name__)

# Pre-compiled invoice-ID patterns (module-level cache, built once per config).
_compiled_patterns_cache: dict[int, list[re.Pattern]] = {}


def _get_compiled_patterns(config: ParserConfig) -> list[re.Pattern]:
    """Return compiled regex patterns for invoice ID extraction."""
    key = id(config)
    if key not in _compiled_patterns_cache:
        _compiled_patterns_cache[key] = [
            re.compile(p, re.IGNORECASE) for p in config.invoice_id_patterns
        ]
    return _compiled_patterns_cache[key]


def extract_pdf_metadata(pdf, config: ParserConfig) -> dict:
    """Extract metadata (invoice ID, date, etc.) from PDF header area.

    Scans the first page's text lines BEFORE the table header for known patterns.
    """
    metadata: dict = {}
    page = pdf.pages[0]
    text = page.extract_text()
    if not text:
        return metadata

    lines = text.split("\n")
    patterns = _get_compiled_patterns(config)

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Stop scanning if we hit the table header
        tokens = re.split(r'[\s./_%]+', stripped.lower())
        kw_count = sum(1 for t in tokens if t in config.header_keywords)
        if kw_count >= 3:
            break

        # Try invoice ID patterns
        if "invoice_id" not in metadata:
            for pattern in patterns:
                m = pattern.search(stripped)
                if m:
                    val = m.group(1).strip()
                    val = re.split(r'\s{2,}', val)[0].strip()
                    if val and len(val) < 100:
                        metadata["invoice_id"] = val
                        break

    # Fallback: if "Nomor Faktur" was in header but value is on next line
    # (e.g., Line 0: "...Nomor Faktur", Line 1: "16 Feb 2026 FJ2026-020583")
    if "invoice_id" not in metadata:
        for i, line in enumerate(lines):
            if re.search(r'Nomor\s*Faktur|Invoice\s*Id', line, re.IGNORECASE):
                # Check next line for an ID-like value (contains letters + numbers)
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    # Look for pattern like FJ2026-020583 (alphanumeric with dash)
                    id_match = re.search(r'([A-Z]{1,5}[\d-]{5,}[\d]+)', next_line)
                    if id_match:
                        metadata["invoice_id"] = id_match.group(1)
                break

    return metadata


def extract_header_fields_from_text(text: str, label_field_map: dict[str, str]) -> dict:
    """Extract values from PDF/image header text by matching labels.

    Label-based: admin defines label text (e.g. "Invoice Id", "Customer", "Telp")
    and the system finds the line containing that label and extracts the value after it.

    Args:
        text: Raw text from first page of PDF/image
        label_field_map: {"Invoice Id": "invoice_id", "Customer": "customer_name", ...}

    Returns:
        {"invoice_id": "INV-2501-...", "customer_name": "PT. CANTIK...", ...}
    """
    if not text or not label_field_map:
        return {}

    result = {}
    lines = text.split("\n")

    # Collect all labels lowercase for "stop at next label" logic
    all_labels_lower = [l.lower() for l in label_field_map.keys()]

    for label, field_name in label_field_map.items():
        label_lower = label.lower()
        for line in lines:
            line_lower = line.lower()
            if label_lower in line_lower:
                # Find where the label ends in the line
                idx = line_lower.index(label_lower) + len(label)
                after = line[idx:].strip()
                # Strip separators: colon, dash, dot, spaces
                after = re.sub(r'^[\s:.\-/]+', '', after).strip()

                # Stop at next known label on same line
                # e.g. "081911630168 Customer: PT. CANTIK..." → stop before "Customer"
                best_end = len(after)
                for other_label in all_labels_lower:
                    if other_label == label_lower:
                        continue
                    pos = after.lower().find(other_label)
                    if pos > 0 and pos < best_end:
                        best_end = pos
                after = after[:best_end].strip()

                # Also strip trailing multi-space junk
                after = re.split(r'\s{3,}', after)[0].strip()
                # Strip trailing separators
                after = after.rstrip(":.-/ ")

                if after:
                    result[field_name] = after
                    break

    return result


def save_parsed_json(file_path: str, result: ParseResult, original_filename: str) -> str:
    """Save ParseResult as JSON file alongside the original upload."""
    path = Path(file_path)
    json_path = path.with_name(path.stem + ".parsed.json")
    data = {
        "source_file": original_filename,
        "headers": result.headers,
        "row_count": result.row_count,
        "encoding_used": result.encoding_used,
        "metadata": result.metadata,
        "parse_errors": result.parse_errors,
        "rows": result.rows,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return str(json_path)
