"""Header field extraction (label-based) and parsed-JSON persistence."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from ..base import ParseResult

logger = logging.getLogger(__name__)


def extract_header_fields_from_text(text: str, label_field_map: dict[str, str]) -> dict:
    """Extract values from PDF/image header text by matching labels.

    Label-based: admin defines label text (e.g. "Invoice Id", "Customer", "Telp")
    via Header Field Mappings in Templates. The system finds the line containing
    that label and extracts the value after it.

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
