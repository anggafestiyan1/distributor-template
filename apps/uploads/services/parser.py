"""File parsing service for xlsx, csv, and pdf uploads."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class ParseResult:
    headers: list[str]
    rows: list[dict]
    row_count: int
    parse_errors: list[str] = field(default_factory=list)
    encoding_used: str = "utf-8"
    metadata: dict = field(default_factory=dict)  # e.g. {"invoice_id": "INV-001"}


def compute_file_checksum(file_path: str) -> str:
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def compute_row_checksum(row_data: dict) -> str:
    serialized = json.dumps(row_data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def parse_file(file_path: str, original_filename: str) -> ParseResult:
    """Parse an xlsx, csv, or pdf file and return headers + rows as dicts."""
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".xlsx":
        return _parse_xlsx(file_path)
    elif suffix == ".csv":
        return _parse_csv(file_path)
    elif suffix == ".pdf":
        return _parse_pdf(file_path)
    else:
        return ParseResult(
            headers=[], rows=[], row_count=0,
            parse_errors=[f"Unsupported file type: {suffix}"],
        )


# ── Excel / CSV ─────────────────────────────────────────────────────────────


def _parse_xlsx(file_path: str) -> ParseResult:
    try:
        df = pd.read_excel(file_path, engine="openpyxl", dtype=str, header=0)
        return _dataframe_to_result(df)
    except Exception as exc:
        logger.exception("Failed to parse xlsx: %s", file_path)
        return ParseResult(
            headers=[], rows=[], row_count=0,
            parse_errors=[f"Excel parse error: {exc}"],
        )


def _parse_csv(file_path: str) -> ParseResult:
    encodings = ["utf-8", "utf-8-sig", "latin-1", "cp1252"]
    for encoding in encodings:
        try:
            df = pd.read_csv(
                file_path, dtype=str, header=0,
                encoding=encoding, sep=None, engine="python",
            )
            result = _dataframe_to_result(df)
            result.encoding_used = encoding
            return result
        except UnicodeDecodeError:
            continue
        except Exception as exc:
            logger.exception("Failed to parse csv: %s", file_path)
            return ParseResult(
                headers=[], rows=[], row_count=0,
                parse_errors=[f"CSV parse error: {exc}"],
            )
    return ParseResult(
        headers=[], rows=[], row_count=0,
        parse_errors=["Unable to decode CSV with any supported encoding"],
    )


def _dataframe_to_result(df: pd.DataFrame) -> ParseResult:
    df.columns = [str(c).strip() for c in df.columns]
    df = df.fillna("")
    for col in df.columns:
        df[col] = df[col].astype(str).str.strip()
    return ParseResult(
        headers=list(df.columns),
        rows=df.to_dict(orient="records"),
        row_count=len(df),
    )


# ── PDF parsing ─────────────────────────────────────────────────────────────


# Patterns to extract invoice ID from PDF header text
_INVOICE_ID_PATTERNS = [
    re.compile(r'Invoice\s*Id\s*[:\-]\s*(.+)', re.IGNORECASE),
    re.compile(r'Nomor\s*Faktur\s*[:\-]?\s*(.+)', re.IGNORECASE),
    re.compile(r'No\.?\s*Faktur\s*[:\-]?\s*(.+)', re.IGNORECASE),
    re.compile(r'Invoice\s*(?:No|Number)\s*[:\-]\s*(.+)', re.IGNORECASE),
]


def _extract_pdf_metadata(pdf) -> dict:
    """Extract metadata (invoice ID, date, etc.) from PDF header area.

    Scans the first page's text lines BEFORE the table header for known patterns.
    """
    metadata = {}
    page = pdf.pages[0]
    text = page.extract_text()
    if not text:
        return metadata

    lines = text.split("\n")

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Stop scanning if we hit the table header
        tokens = re.split(r'[\s./_%]+', stripped.lower())
        kw_count = sum(1 for t in tokens if t in _TABLE_HEADER_KEYWORDS)
        if kw_count >= 3:
            break

        # Try invoice ID patterns
        if "invoice_id" not in metadata:
            for pattern in _INVOICE_ID_PATTERNS:
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


# Known column header keywords for invoice/product tables
_TABLE_HEADER_KEYWORDS = frozenset({
    "no", "nama", "qty", "quantity", "satuan", "unit", "harga", "price",
    "total", "disc", "diskon", "jumlah", "barang", "produk", "product",
    "amount", "description", "item", "kode", "code", "date", "tanggal",
})

# Summary/footer row keywords to filter out
_SUMMARY_KEYWORDS = frozenset({
    "sub total", "subtotal", "diskon", "discount", "ppn", "pajak", "tax",
    "total", "grand total", "terbilang", "dp", "uang muka", "penerima",
    "gudang", "pengirim", "mengetahui", "keterangan", "halaman",
})


def _is_digital_pdf(pdf) -> bool:
    for page in pdf.pages:
        text = page.extract_text()
        if text and len(text.strip()) > 50:
            return True
    return False


def _validate_table_quality(headers: list[str], rows: list[dict]) -> bool:
    """Check if extracted table has reasonable quality."""
    if not headers or not rows:
        return False
    if len(headers) < 2:
        return False

    # Reject overly long headers (merged cells)
    if any(len(h) > 100 for h in headers):
        return False

    # Reject overly long cell values in first row
    if rows:
        for v in rows[0].values():
            if len(str(v)) > 200:
                return False

    # Reject fragmented headers: too many tiny headers = split text garbage
    non_empty = [h for h in headers if h.strip()]
    if not non_empty:
        return False
    tiny_count = sum(1 for h in non_empty if len(h.strip()) <= 2)
    if tiny_count > len(non_empty) * 0.4:
        return False

    # Reject if average header length is suspiciously short
    avg_len = sum(len(h.strip()) for h in non_empty) / len(non_empty)
    if avg_len < 3:
        return False

    # Require at least one header word to match a known table keyword
    found_keyword = False
    for h in headers:
        tokens = re.split(r'[\s./_%]+', h.strip().lower())
        if any(t in _TABLE_HEADER_KEYWORDS for t in tokens):
            found_keyword = True
            break
    if not found_keyword:
        return False

    return True


def _is_header_repeat(row: list[str], headers: list[str]) -> bool:
    """Check if a row is a repeat of the header row (fuzzy match)."""
    if len(row) != len(headers):
        return False
    matches = sum(1 for a, b in zip(row, headers) if a.strip().lower() == b.strip().lower())
    return matches >= len(headers) * 0.8


def _is_summary_row(row_dict: dict) -> bool:
    """Detect rows that are invoice summary lines, not product data."""
    values = [str(v).strip().lower() for v in row_dict.values() if str(v).strip()]
    if not values:
        return True  # empty row
    for v in values:
        if v in _SUMMARY_KEYWORDS:
            return True
        for kw in _SUMMARY_KEYWORDS:
            if v.startswith(kw) and len(v) < len(kw) + 15:
                return True
    return False


def _clean_table_result(headers: list[str], all_rows: list[dict]) -> tuple[list[str], list[dict]]:
    """Post-process: filter summary rows, drop 'No.' column, clean empty headers."""
    # Filter summary rows
    all_rows = [r for r in all_rows if not _is_summary_row(r)]

    # Drop "No." / "No" column (row numbering)
    no_col = None
    for h in headers:
        if h.strip().lower().rstrip('.') == 'no':
            no_col = h
            break
    if no_col is not None:
        headers = [h for h in headers if h != no_col]
        all_rows = [{k: v for k, v in row.items() if k != no_col} for row in all_rows]

    # Drop empty-name headers
    empty_headers = [h for h in headers if not h.strip()]
    if empty_headers:
        headers = [h for h in headers if h.strip()]
        all_rows = [{k: v for k, v in row.items() if k.strip()} for row in all_rows]

    # Clean up numeric values with trailing unit text:
    #   "12.00 PCS" → "12"
    #   "12.00"     → "12"
    #   "48,500.00" → "48,500.00" (keep prices as-is, they have commas)
    _UNIT_SUFFIXES = re.compile(
        r'\s+(PCS|PC|BOX|KG|SET|BTL|UNIT|PACK|DUS|LSN|LBR|CTN)\b',
        re.IGNORECASE,
    )
    for row in all_rows:
        for h, v in row.items():
            if not v:
                continue
            val = v.strip()
            # Strip unit suffix: "12.00 PCS" → "12.00"
            val = _UNIT_SUFFIXES.sub("", val).strip()
            # Strip trailing .00: "12.00" → "12"
            m = re.match(r'^(\d+)\.0+$', val)
            if m:
                val = m.group(1)
            row[h] = val

    return headers, all_rows


def _split_merged_cells(headers: list[str], raw_rows: list[list[str]]) -> list[dict]:
    """Handle pdfplumber merged cells — cells contain multiple values joined by \\n.

    Strategy: Use the "No." column as the anchor — each number in that column
    marks a new row. All lines between two numbers belong to the same row
    (multi-line product names get merged).

    If no "No." column, fall back to counting numeric columns.
    """
    result_rows: list[dict] = []

    for raw_row in raw_rows:
        cells = [str(c) if c else "" for c in raw_row]
        has_newlines = any("\n" in c for c in cells)

        if not has_newlines:
            row_dict = {}
            for j, cell in enumerate(cells):
                if j < len(headers) and headers[j]:
                    row_dict[headers[j]] = cell.strip()
            if any(row_dict.values()):
                result_rows.append(row_dict)
            continue

        # Split each cell by newline
        split_cols = [c.split("\n") for c in cells]

        # Find "No." column index
        no_col_idx = None
        for idx, h in enumerate(headers):
            if h.strip().lower().rstrip('.') == 'no':
                no_col_idx = idx
                break

        if no_col_idx is not None:
            # === Anchor-based approach ===
            # Use a "short" numeric column (Qty, Total, No.) to determine row count.
            # The No. column has exactly N lines for N rows.
            # Other numeric columns also have exactly N non-empty values.
            # Text columns (Nama Barang) have MORE lines due to multi-line names.

            no_lines = split_cols[no_col_idx]
            num_rows = len([v for v in no_lines if v.strip() and re.match(r'^\d+$', v.strip())])
            if num_rows == 0:
                continue

            col_values: list[list[str]] = []
            for ci, col_lines in enumerate(split_cols):
                non_empty = [v.strip() for v in col_lines if v.strip()]

                if len(non_empty) <= num_rows:
                    # Short column (numeric) — take non-empty values, pad if needed
                    padded = list(non_empty) + [""] * (num_rows - len(non_empty))
                    col_values.append(padded[:num_rows])
                else:
                    # Long column (text with multi-line names) — need to figure out
                    # which lines belong to which row.
                    #
                    # Strategy: use a reference short column to find line boundaries.
                    # Find a short column where non-empty count == num_rows.
                    # The positions of non-empty values in that column mark row boundaries
                    # in this (text) column.
                    ref_col_idx = no_col_idx  # default: use No. column
                    ref_col = split_cols[ref_col_idx]

                    # Find line indices where reference column has values
                    ref_positions: list[int] = []
                    for li, val in enumerate(ref_col):
                        if val.strip():
                            ref_positions.append(li)

                    # But text column has more lines — the ref positions don't map directly.
                    # Instead, count non-empty lines in the text column per "segment".
                    # Each segment: from ref_positions[i] to ref_positions[i+1] in the
                    # LONGEST column, not the ref column.
                    #
                    # Better approach: just distribute text lines proportionally.
                    # Since numeric columns have N values and text has M > N lines,
                    # we know some text entries span multiple lines.
                    # Use the total line count: text_lines / num_rows to find rough grouping.

                    grouped: list[str] = []
                    text_lines = col_lines  # all lines for this column
                    total_lines = len(text_lines)

                    # Smart grouping: find which text lines start a NEW entry
                    # vs which are continuations of the previous entry.
                    #
                    # Strategy: detect the common prefix pattern from the first
                    # few entries (e.g., "SCL." or "PRODUCT"). Lines starting
                    # with this prefix are new entries; others are continuations.
                    #
                    # We need exactly `num_rows` groups.

                    # Detect common prefix from non-empty lines
                    non_empty_lines = [l.strip() for l in text_lines if l.strip()]
                    common_prefix = ""
                    if len(non_empty_lines) >= 2:
                        # Find longest common prefix among lines that look like
                        # product entries (longer lines, not fragments)
                        long_lines = [l for l in non_empty_lines if len(l) > 20]
                        if len(long_lines) >= 2:
                            prefix = long_lines[0]
                            for ll in long_lines[1:]:
                                while prefix and not ll.startswith(prefix):
                                    prefix = prefix[:-1]
                            common_prefix = prefix.strip()
                            # Use at least 3 chars of prefix
                            if len(common_prefix) < 3:
                                common_prefix = ""

                    entry_starts: list[int] = [0]
                    for li in range(1, total_lines):
                        line = text_lines[li].strip()
                        if not line:
                            continue
                        if len(entry_starts) >= num_rows:
                            break

                        is_new = False
                        if common_prefix:
                            # Line starts with the common prefix → new entry
                            is_new = line.startswith(common_prefix)
                        else:
                            # Fallback: line > 25 chars + starts uppercase
                            is_new = len(line) > 25 and line[0].isupper()

                        if is_new:
                            entry_starts.append(li)

                    # If we found exactly num_rows starts, great.
                    # If fewer, pad by splitting the last group.
                    # If more (shouldn't happen), take first num_rows.
                    if len(entry_starts) < num_rows:
                        # Distribute remaining lines evenly from the last start
                        last = entry_starts[-1]
                        remaining_lines = total_lines - last
                        remaining_entries = num_rows - len(entry_starts)
                        if remaining_entries > 0 and remaining_lines > 0:
                            step = remaining_lines / (remaining_entries + 1)
                            for k in range(1, remaining_entries + 1):
                                entry_starts.append(last + round(k * step))

                    entry_starts = entry_starts[:num_rows]

                    for ri in range(num_rows):
                        start = entry_starts[ri]
                        end = entry_starts[ri + 1] if ri + 1 < len(entry_starts) else total_lines
                        chunk = " ".join(text_lines[start:end]).strip()
                        grouped.append(chunk)

                    if not grouped:
                        grouped = [" ".join(non_empty)]
                        grouped += [""] * (num_rows - 1)

                    col_values.append(grouped[:num_rows])

            # Build row dicts
            for ri in range(num_rows):
                row_dict = {}
                for j in range(len(headers)):
                    if j < len(col_values) and headers[j]:
                        row_dict[headers[j]] = col_values[j][ri] if ri < len(col_values[j]) else ""
                if any(row_dict.values()):
                    result_rows.append(row_dict)

        else:
            # === Fallback: no "No." column, use numeric count heuristic ===
            max_lines = max(len(col) for col in split_cols)
            pending_row: dict | None = None

            for line_idx in range(max_lines):
                line_values = [
                    col[line_idx].strip() if line_idx < len(col) else ""
                    for col in split_cols
                ]
                if not any(line_values):
                    continue

                numeric_count = sum(
                    1 for v in line_values
                    if v and re.match(r'^[\d.,]+$', v)
                )
                is_new_row = numeric_count >= 2

                if is_new_row:
                    if pending_row and any(pending_row.values()):
                        result_rows.append(pending_row)
                    pending_row = {}
                    for j, val in enumerate(line_values):
                        if j < len(headers) and headers[j]:
                            pending_row[headers[j]] = val
                elif pending_row is not None:
                    for j, val in enumerate(line_values):
                        if j < len(headers) and headers[j] and val:
                            h = headers[j]
                            existing = pending_row.get(h, "")
                            pending_row[h] = (existing + " " + val).strip() if existing else val

            if pending_row and any(pending_row.values()):
                result_rows.append(pending_row)

    return result_rows


def _extract_page_tables(page, headers: list[str]) -> tuple[list[str], list[dict]]:
    """Extract tables from a single PDF page, trying multiple strategies per page."""
    strategies = [
        {"vertical_strategy": "lines", "horizontal_strategy": "lines"},
        {"vertical_strategy": "lines", "horizontal_strategy": "text"},
        {"vertical_strategy": "text", "horizontal_strategy": "text",
         "snap_x_tolerance": 5, "snap_y_tolerance": 5},
    ]

    for settings in strategies:
        tables = page.extract_tables(table_settings=settings)
        page_rows: list[dict] = []
        page_headers = list(headers)  # copy

        for table in tables:
            if not table:
                continue

            start_idx = 0
            if not page_headers:
                for i, row in enumerate(table):
                    cleaned = [str(c).strip() if c else "" for c in row]
                    if any(cleaned):
                        page_headers = cleaned
                        start_idx = i + 1
                        break

            raw_rows = table[start_idx:]
            if raw_rows:
                filtered = []
                for row in raw_rows:
                    cleaned = [str(c).strip() if c else "" for c in row]
                    # Skip header repeats and empty rows
                    if page_headers and _is_header_repeat(cleaned, page_headers):
                        continue
                    if not any(cleaned):
                        continue
                    filtered.append(row)
                if filtered:
                    rows = _split_merged_cells(page_headers, filtered)
                    page_rows.extend(rows)

        if page_rows and page_headers:
            return page_headers, page_rows

    return headers, []


def _parse_pdf_tables(pdf) -> tuple[list[str], list[dict]]:
    """Extract tables from PDF — tries multiple strategies PER PAGE.

    Each page may need a different extraction strategy (e.g., page 1 has
    bordered table, page 2 has slightly different borders). This function
    tries all strategies per page independently and merges results.
    """
    headers: list[str] = []
    all_rows: list[dict] = []

    for page in pdf.pages:
        page_headers, page_rows = _extract_page_tables(page, headers)

        if not headers and page_headers:
            headers = page_headers

        all_rows.extend(page_rows)

    if _validate_table_quality(headers, all_rows):
        all_rows = _merge_continuation_rows(headers, all_rows)
        headers, all_rows = _clean_table_result(headers, all_rows)
        if all_rows:
            logger.info("PDF table extraction succeeded: %d headers, %d rows", len(headers), len(all_rows))
            return headers, all_rows

    return [], []


def _merge_continuation_rows(headers: list[str], rows: list[dict]) -> list[dict]:
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
        h_lower = h.strip().lower()
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
            # Continuation row — merge text columns into previous row
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


def _parse_pdf_lines(pdf) -> tuple[list[str], list[dict]]:
    """Fallback: parse raw text from all pages using word positions.

    1. Find header row by keyword matching on each page
    2. Use word X-positions from header row to define column boundaries
    3. Map data row words to columns by X-position
    4. Merge multi-line product names (continuation lines)
    """
    # Process each page independently, merge results
    headers: list[str] = []
    columns: list[dict] = []  # [{name, x0, x1}, ...]
    all_rows: list[dict] = []

    for page in pdf.pages:
        words = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=True)
        if not words:
            continue

        # Group words by Y position into lines
        by_y: dict[float, list] = {}
        y_tol = 4
        for w in words:
            y_key = round(w["top"] / y_tol) * y_tol
            if y_key not in by_y:
                by_y[y_key] = []
            by_y[y_key].append(w)

        sorted_y_keys = sorted(by_y.keys())

        # Find header row on this page (>= 3 keywords)
        header_y = None
        for y_key in sorted_y_keys:
            ws = sorted(by_y[y_key], key=lambda w: w["x0"])
            line_text = " ".join(w["text"] for w in ws).lower()
            tokens = re.split(r'[\s./_%]+', line_text)
            kw_count = sum(1 for t in tokens if t in _TABLE_HEADER_KEYWORDS)
            if kw_count >= 3:
                header_y = y_key

                if not headers:
                    # Build column definitions from header word positions
                    # Group words with small gaps into column names
                    cols = []
                    current_words = [ws[0]]
                    for w in ws[1:]:
                        gap = w["x0"] - current_words[-1]["x1"]
                        if gap > 10:  # significant gap = new column
                            col_name = " ".join(cw["text"] for cw in current_words).strip()
                            cols.append({"name": col_name, "x0": current_words[0]["x0"],
                                         "x1": current_words[-1]["x1"]})
                            current_words = [w]
                        else:
                            current_words.append(w)
                    if current_words:
                        col_name = " ".join(cw["text"] for cw in current_words).strip()
                        cols.append({"name": col_name, "x0": current_words[0]["x0"],
                                     "x1": current_words[-1]["x1"]})

                    if len(cols) >= 2:
                        columns = cols
                        headers = [c["name"] for c in cols]
                break

        if not columns or header_y is None:
            continue

        # Process data lines (after header row on this page)
        for y_key in sorted_y_keys:
            if y_key <= header_y:
                continue

            ws = sorted(by_y[y_key], key=lambda w: w["x0"])
            line_text = " ".join(w["text"] for w in ws).strip()

            # Skip empty / summary / page footer
            lower = line_text.lower()
            if not lower:
                continue
            if any(lower.startswith(kw) for kw in _SUMMARY_KEYWORDS):
                break
            if (lower.startswith("page ") and "of" in lower) or \
               (lower.startswith("halaman ") and "dari" in lower):
                continue
            # Skip repeated header rows
            tokens = re.split(r'[\s./_%]+', lower)
            kw_count = sum(1 for t in tokens if t in _TABLE_HEADER_KEYWORDS)
            if kw_count >= 3:
                continue

            # Map words to columns by X position
            row_dict = {h: "" for h in headers}
            for w in ws:
                wx_center = (w["x0"] + w["x1"]) / 2
                best_col = None
                best_dist = float("inf")
                for ci, col in enumerate(columns):
                    # Check if word center falls within column range (with tolerance)
                    col_center = (col["x0"] + col["x1"]) / 2
                    dist = abs(wx_center - col_center)
                    if dist < best_dist:
                        best_dist = dist
                        best_col = ci
                if best_col is not None:
                    h = headers[best_col]
                    row_dict[h] = (row_dict[h] + " " + w["text"]).strip() if row_dict[h] else w["text"]

            row_dict = {k: v.strip() for k, v in row_dict.items()}
            if any(row_dict.values()):
                all_rows.append(row_dict)

    if not headers or not all_rows:
        return [], []

    all_rows = _merge_continuation_rows(headers, all_rows)
    headers, all_rows = _clean_table_result(headers, all_rows)
    return headers, all_rows


def _parse_pdf(file_path: str) -> ParseResult:
    """Parse a PDF file and extract tabular data.

    Flow:
    1. Detect digital vs scan
    2. Strategy 1: extract_tables (lines → mixed → text)
    3. Strategy 2: fallback to line-by-line word position parsing
    4. Return ParseResult (same format as Excel/CSV)
    """
    try:
        import pdfplumber
    except ImportError:
        return ParseResult(
            headers=[], rows=[], row_count=0,
            parse_errors=["pdfplumber is not installed"],
        )

    try:
        with pdfplumber.open(file_path) as pdf:
            if not _is_digital_pdf(pdf):
                return ParseResult(
                    headers=[], rows=[], row_count=0,
                    parse_errors=[
                        "PDF scan detected — no text layer found. "
                        "Please upload a digital PDF or use Excel/CSV format."
                    ],
                )

            # Try table extraction (multiple strategies)
            headers, rows = _parse_pdf_tables(pdf)

            # Fallback to line-by-line parsing
            if not headers or not rows:
                logger.info("PDF table extraction failed, trying line-by-line parsing")
                headers, rows = _parse_pdf_lines(pdf)

            if not headers:
                return ParseResult(
                    headers=[], rows=[], row_count=0,
                    parse_errors=[
                        "Could not extract tabular data from PDF. "
                        "Try converting to Excel/CSV first."
                    ],
                )

            # Extract metadata (invoice ID, etc.) from PDF header area
            metadata = _extract_pdf_metadata(pdf)
            logger.info("PDF parsed: %d headers, %d rows, metadata=%s — %s", len(headers), len(rows), metadata, headers)
            return ParseResult(headers=headers, rows=rows, row_count=len(rows), metadata=metadata)

    except Exception as exc:
        logger.exception("Failed to parse PDF: %s", file_path)
        return ParseResult(
            headers=[], rows=[], row_count=0,
            parse_errors=[f"PDF parse error: {exc}"],
        )
