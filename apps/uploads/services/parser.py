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
                    # Heuristic: a line starts a new entry if it begins with
                    # an uppercase letter/word (like "SCL.", "PRODUCT", etc.)
                    # AND the previous entry has at least 1 line already.
                    #
                    # We need exactly `num_rows` groups.
                    entry_starts: list[int] = [0]  # first line always starts entry 1
                    for li in range(1, total_lines):
                        line = text_lines[li].strip()
                        prev_line = text_lines[li - 1].strip()
                        if not line:
                            continue
                        # A continuation line is typically a leftover fragment
                        # (short, doesn't start with the same prefix pattern).
                        # A new entry line looks like a full product name start.
                        # Heuristic: if the line starts with an uppercase letter
                        # AND has length > 15 chars, it's likely a new entry.
                        is_new = (
                            len(line) > 15
                            and line[0].isupper()
                            and len(entry_starts) < num_rows
                        )
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


def _parse_pdf_tables(pdf) -> tuple[list[str], list[dict]]:
    """Extract tables from PDF using multiple strategies.

    Tries "lines" first (best for bordered invoice tables),
    then "mixed", then "text" (borderless) as fallback.
    Handles merged cells (multiple rows joined by \\n in a single cell).
    """
    strategies = [
        {
            "vertical_strategy": "lines",
            "horizontal_strategy": "lines",
        },
        {
            "vertical_strategy": "text",
            "horizontal_strategy": "lines",
        },
        {
            "vertical_strategy": "text",
            "horizontal_strategy": "text",
            "snap_x_tolerance": 5,
            "snap_y_tolerance": 5,
        },
    ]

    for settings in strategies:
        headers: list[str] = []
        all_rows: list[dict] = []

        for page in pdf.pages:
            tables = page.extract_tables(table_settings=settings)
            for table in tables:
                if not table:
                    continue

                # First row = headers (only from first table found)
                start_idx = 0
                if not headers:
                    for i, row in enumerate(table):
                        cleaned = [str(c).strip() if c else "" for c in row]
                        if any(cleaned):
                            headers = cleaned
                            start_idx = i + 1
                            break

                # Remaining rows — handle merged cells
                raw_rows = table[start_idx:]
                if raw_rows:
                    # Skip rows that repeat the header
                    filtered = []
                    for row in raw_rows:
                        cleaned = [str(c).strip() if c else "" for c in row]
                        if not _is_header_repeat(cleaned, headers):
                            filtered.append(row)
                    rows = _split_merged_cells(headers, filtered)
                    all_rows.extend(rows)

        if _validate_table_quality(headers, all_rows):
            headers, all_rows = _clean_table_result(headers, all_rows)
            if all_rows:
                logger.info("PDF table extraction succeeded with strategy: %s", settings)
                return headers, all_rows

        headers = []
        all_rows = []

    return [], []


def _parse_pdf_lines(pdf) -> tuple[list[str], list[dict]]:
    """Fallback: parse raw text line by line using word positions."""
    all_words = []
    for page in pdf.pages:
        words = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=True)
        page_height = page.height
        page_idx = page.page_number - 1
        for w in words:
            w["top"] = w["top"] + (page_idx * page_height)
            w["bottom"] = w["bottom"] + (page_idx * page_height)
            all_words.append(w)

    if not all_words:
        return [], []

    # Group words into lines by Y position
    lines: dict[float, list] = {}
    y_tolerance = 5
    for w in all_words:
        y_key = round(w["top"] / y_tolerance) * y_tolerance
        if y_key not in lines:
            lines[y_key] = []
        lines[y_key].append(w)

    sorted_lines = []
    for y_key in sorted(lines.keys()):
        words_in_line = sorted(lines[y_key], key=lambda w: w["x0"])
        line_text = " ".join(w["text"] for w in words_in_line).strip()
        if line_text:
            sorted_lines.append({"text": line_text, "words": words_in_line, "y": y_key})

    if not sorted_lines:
        return [], []

    # Detect header line using keywords
    header_idx = None
    for i, line in enumerate(sorted_lines):
        text = line["text"].lower()
        tokens = re.split(r'[\s./_%]+', text)
        keyword_count = sum(1 for t in tokens if t in _TABLE_HEADER_KEYWORDS)
        if keyword_count >= 2 and len(line["text"]) < 200:
            header_idx = i
            break

    if header_idx is None:
        return [], []

    # Build columns from header word positions
    header_words = sorted_lines[header_idx]["words"]
    columns = []
    current_col_words = [header_words[0]]
    for w in header_words[1:]:
        prev = current_col_words[-1]
        gap = w["x0"] - prev["x1"]
        if gap > 15:
            col_name = " ".join(cw["text"] for cw in current_col_words).strip()
            columns.append({"name": col_name, "x0": current_col_words[0]["x0"], "x1": current_col_words[-1]["x1"]})
            current_col_words = [w]
        else:
            current_col_words.append(w)
    if current_col_words:
        col_name = " ".join(cw["text"] for cw in current_col_words).strip()
        columns.append({"name": col_name, "x0": current_col_words[0]["x0"], "x1": current_col_words[-1]["x1"]})

    if len(columns) < 2:
        return [], []

    headers = [c["name"] for c in columns]
    all_rows = []

    for line in sorted_lines[header_idx + 1:]:
        row_dict = {h: "" for h in headers}
        for w in line["words"]:
            wx_center = (w["x0"] + w["x1"]) / 2
            best_col = None
            best_dist = float("inf")
            for ci, col in enumerate(columns):
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

            logger.info("PDF parsed: %d headers, %d rows — %s", len(headers), len(rows), headers)
            return ParseResult(headers=headers, rows=rows, row_count=len(rows))

    except Exception as exc:
        logger.exception("Failed to parse PDF: %s", file_path)
        return ParseResult(
            headers=[], rows=[], row_count=0,
            parse_errors=[f"PDF parse error: {exc}"],
        )
