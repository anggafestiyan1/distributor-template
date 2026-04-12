"""Post-processing: row merging, cleanup, and normalization."""
from __future__ import annotations

import re

from ..config import ParserConfig
from .validation import is_summary_row


def merge_continuation_rows(
    headers: list[str],
    rows: list[dict],
) -> list[dict]:
    """Merge continuation rows (no Qty/numeric data) into the previous row.

    Some PDF pages extract multi-line product names as separate rows where
    the continuation row only has text in the name column and empty elsewhere.
    """
    if not rows:
        return rows

    # Find columns that typically have numeric values (Qty, Price, Total)
    numeric_cols = []
    text_cols = []
    for h in headers:
        # Check first few rows to determine if column is numeric
        has_numbers = False
        for row in rows[:5]:
            val = str(row.get(h, "")).strip()
            if val and re.match(r'^[\d.,]+$', val):
                has_numbers = True
                break
        if has_numbers:
            numeric_cols.append(h)
        else:
            text_cols.append(h)

    if not numeric_cols:
        return rows

    merged: list[dict] = []
    for row in rows:
        # Check if this row has any numeric values
        has_data = any(
            str(row.get(col, "")).strip()
            for col in numeric_cols
        )

        if has_data or not merged:
            merged.append(dict(row))
        else:
            # Continuation row -- merge text columns into previous row
            prev = merged[-1]
            for col in text_cols:
                val = str(row.get(col, "")).strip()
                if val:
                    existing = str(prev.get(col, "")).strip()
                    if existing:
                        prev[col] = existing + " " + val
                    else:
                        prev[col] = val

    return merged


def clean_table_result(
    headers: list[str],
    all_rows: list[dict],
    config: ParserConfig,
) -> tuple[list[str], list[dict]]:
    """Post-process: drop configured columns, filter summary rows, clean empty headers."""
    # Drop columns listed in config.drop_columns FIRST (e.g. "No.")
    # so that "No." column containing "Total" doesn't confuse summary detection
    for drop_name in config.drop_columns:
        no_col = None
        for h in headers:
            if h.strip().lower().rstrip('.') == drop_name.strip().lower().rstrip('.'):
                no_col = h
                break
        if no_col is not None:
            headers = [h for h in headers if h != no_col]
            all_rows = [{k: v for k, v in row.items() if k != no_col} for row in all_rows]

    # Filter summary rows (AFTER dropping No. column so "Total" in No. is gone)
    all_rows = [r for r in all_rows if not is_summary_row(r, config)]

    # Drop empty-name headers
    empty_headers = [h for h in headers if not h.strip()]
    if empty_headers:
        headers = [h for h in headers if h.strip()]
        all_rows = [{k: v for k, v in row.items() if k.strip()} for row in all_rows]

    # Clean up numeric values with trailing unit text:
    #   "12.00 PCS" -> "12"
    #   "12.00"     -> "12"
    #   "48,500.00" -> "48,500.00" (keep prices as-is, they have commas)
    _UNIT_SUFFIXES = re.compile(
        r'\s+(PCS|PC|BOX|KG|SET|BTL|UNIT|PACK|DUS|LSN|LBR|CTN)\b',
        re.IGNORECASE,
    )
    for row in all_rows:
        for h, v in row.items():
            if not v:
                continue
            val = v.strip()
            # Strip unit suffix: "12.00 PCS" -> "12.00"
            val = _UNIT_SUFFIXES.sub("", val).strip()
            # Strip trailing .00: "12.00" -> "12"
            m = re.match(r'^(\d+)\.0+$', val)
            if m:
                val = m.group(1)
            row[h] = val

    return headers, all_rows


def merge_incomplete_ocr_rows(
    headers: list[str],
    rows: list[dict],
) -> list[dict]:
    """Merge rows where OCR split a single table row into fragments.

    If row N has text but no numeric, and row N+1 has numeric but no text,
    merge them into one row.
    """
    if not rows:
        return rows

    # Find which columns are typically numeric
    numeric_cols: set[str] = set()
    text_cols: set[str] = set()
    for h in headers:
        has_num = False
        has_text = False
        for row in rows:
            val = str(row.get(h, "")).strip()
            if not val:
                continue
            if re.match(r'^[\d.,]+$', val):
                has_num = True
            else:
                has_text = True
        if has_num and not has_text:
            numeric_cols.add(h)
        elif has_text:
            text_cols.add(h)

    merged: list[dict] = []
    i = 0
    while i < len(rows):
        row = dict(rows[i])
        # Look ahead: if next row has complementary data, merge
        while i + 1 < len(rows):
            next_row = rows[i + 1]
            # Check if current has text but missing numeric, and next fills numeric
            current_num = [c for c in numeric_cols if str(row.get(c, "")).strip()]
            next_num = [c for c in numeric_cols if str(next_row.get(c, "")).strip()]
            current_text = [c for c in text_cols if str(row.get(c, "")).strip()]
            next_text = [c for c in text_cols if str(next_row.get(c, "")).strip()]

            # Case 1: current has text, next has only numeric (no text) -> merge
            if current_text and next_num and not next_text:
                for c in numeric_cols:
                    if not str(row.get(c, "")).strip() and str(next_row.get(c, "")).strip():
                        row[c] = next_row[c]
                i += 1
                continue
            # Case 2: current has numeric only (no text), next has text -> merge into next
            if current_num and not current_text and next_text and not next_num:
                for c in text_cols:
                    if not str(row.get(c, "")).strip() and str(next_row.get(c, "")).strip():
                        row[c] = next_row[c]
                i += 1
                continue
            break
        merged.append(row)
        i += 1

    return merged
