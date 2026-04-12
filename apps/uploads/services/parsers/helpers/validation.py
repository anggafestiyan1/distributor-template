"""Table quality validation and row-type detection helpers."""
from __future__ import annotations

import re

from ..config import ParserConfig


def is_digital_pdf(pdf) -> bool:
    """Return True if the PDF has a usable text layer (not a pure scan)."""
    for page in pdf.pages:
        text = page.extract_text()
        if text and len(text.strip()) > 50:
            return True
    return False


def validate_table_quality(
    headers: list[str],
    rows: list[dict],
    config: ParserConfig,
) -> bool:
    """Check if extracted table has reasonable quality."""
    if not headers or not rows:
        return False
    if len(headers) < 2:
        return False

    # Reject overly long headers (merged cells)
    if any(len(h) > config.max_header_len for h in headers):
        return False

    # Reject overly long cell values in first row
    if rows:
        for v in rows[0].values():
            if len(str(v)) > config.max_cell_len:
                return False

    # Reject fragmented headers: too many tiny headers = split text garbage
    non_empty = [h for h in headers if h.strip()]
    if not non_empty:
        return False
    tiny_count = sum(1 for h in non_empty if len(h.strip()) <= 2)
    if tiny_count > len(non_empty) * config.fragment_ratio:
        return False

    # Reject if average header length is suspiciously short
    avg_len = sum(len(h.strip()) for h in non_empty) / len(non_empty)
    if avg_len < config.min_avg_header_len:
        return False

    # Require at least one header word to match a known table keyword
    found_keyword = False
    for h in headers:
        tokens = re.split(r'[\s./_%]+', h.strip().lower())
        if any(t in config.header_keywords for t in tokens):
            found_keyword = True
            break
    if not found_keyword:
        return False

    return True


def is_header_repeat(row: list[str], headers: list[str]) -> bool:
    """Check if a row is a repeat of the header row (fuzzy match)."""
    if len(row) != len(headers):
        return False
    matches = sum(
        1 for a, b in zip(row, headers)
        if a.strip().lower() == b.strip().lower()
    )
    return matches >= len(headers) * 0.8


def is_summary_row(row_dict: dict, config: ParserConfig) -> bool:
    """Detect rows that are invoice summary lines, not product data."""
    values = [str(v).strip().lower() for v in row_dict.values() if str(v).strip()]
    if not values:
        return True  # empty row

    # Check keyword matches (e.g. "sub total", "ppn", "terbilang")
    for v in values:
        if v in config.summary_keywords:
            return True
        for kw in config.summary_keywords:
            if v.startswith(kw) and len(v) < len(kw) + 15:
                return True

    # If ALL non-empty values are numeric (no product name text), it's summary/junk
    # Real product rows always have text like "SCL. SCARLETT..." in at least one column
    if all(re.match(r'^[\d.,\-\s%()]+$', v) for v in values):
        return True

    return False
