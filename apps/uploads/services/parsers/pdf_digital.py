"""Digital PDF parser — table extraction and line-based fallback via pdfplumber."""
from __future__ import annotations

import logging
import re

from .base import BaseParser, ParseResult
from .helpers.merged_cells import split_merged_cells
from .helpers.post_process import clean_table_result, merge_continuation_rows
from .helpers.validation import (
    is_digital_pdf,
    is_header_repeat,
    is_summary_row,
    validate_table_quality,
)

logger = logging.getLogger(__name__)


class PdfDigitalParser(BaseParser):
    """Parse digital (text-layer) PDFs using pdfplumber.

    Strategy:
    1. Detect digital vs scan using ``_is_digital_pdf()``.
    2. Digital: try table extraction → line parsing → OCR fallback.
    3. Scan: delegate to ``PdfScanParser`` directly.
    """

    file_extensions = [".pdf"]

    # ── public entry-point ─────────────────────────────────────────────────

    def parse(self, file_path: str) -> ParseResult:
        try:
            import pdfplumber
        except ImportError:
            return ParseResult(
                headers=[], rows=[], row_count=0,
                parse_errors=["pdfplumber is not installed"],
            )

        try:
            with pdfplumber.open(file_path) as pdf:
                if not is_digital_pdf(pdf):
                    logger.info("PDF is scan (no text layer), using OCR fallback")
                    return self._delegate_to_scan_parser(file_path)

                # Try table extraction (multiple strategies)
                headers, rows = self._extract_tables(pdf)

                # Fallback to line-by-line parsing
                if not headers or not rows:
                    logger.info("PDF table extraction failed, trying line-by-line parsing")
                    headers, rows = self._extract_lines(pdf)

                if not headers:
                    # Last resort: try OCR even on digital PDFs
                    logger.info("PDF text parsing failed, trying OCR as last resort")
                    return self._delegate_to_scan_parser(file_path)

                logger.info(
                    "PDF parsed: %d headers, %d rows — %s",
                    len(headers), len(rows), headers,
                )
                return ParseResult(
                    headers=headers, rows=rows, row_count=len(rows),
                )

        except Exception as exc:
            logger.exception("Failed to parse PDF: %s", file_path)
            return ParseResult(
                headers=[], rows=[], row_count=0,
                parse_errors=[f"PDF parse error: {exc}"],
            )

    # ── scan delegation ────────────────────────────────────────────────────

    def _delegate_to_scan_parser(self, file_path: str) -> ParseResult:
        from .pdf_scan import PdfScanParser
        return PdfScanParser(config=self.config).parse(file_path)

    # ── digital detection ──────────────────────────────────────────────────

    @staticmethod
    def _is_digital_pdf(pdf) -> bool:
        for page in pdf.pages:
            text = page.extract_text()
            if text and len(text.strip()) > 50:
                return True
        return False

    # ── table extraction ───────────────────────────────────────────────────

    def _extract_tables(self, pdf) -> tuple[list[str], list[dict]]:
        """Extract tables from PDF — tries multiple strategies PER PAGE.

        Each page may need a different extraction strategy (e.g., page 1 has
        bordered table, page 2 has slightly different borders). This function
        tries all strategies per page independently and merges results.
        """
        headers: list[str] = []
        all_rows: list[dict] = []

        for page in pdf.pages:
            page_headers, page_rows = self._extract_page(page, headers)

            if not headers and page_headers:
                headers = page_headers

            all_rows.extend(page_rows)

        if validate_table_quality(headers, all_rows, self.config):
            all_rows = merge_continuation_rows(headers, all_rows)
            headers, all_rows = clean_table_result(headers, all_rows, self.config)
            if all_rows:
                logger.info(
                    "PDF table extraction succeeded: %d headers, %d rows",
                    len(headers), len(all_rows),
                )
                return headers, all_rows

        return [], []

    def _extract_page(self, page, headers: list[str]) -> tuple[list[str], list[dict]]:
        """Extract tables from a single PDF page, trying multiple strategies."""
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
                        if page_headers and is_header_repeat(cleaned, page_headers):
                            continue
                        if not any(cleaned):
                            continue
                        filtered.append(row)
                    if filtered:
                        rows = split_merged_cells(page_headers, filtered)
                        page_rows.extend(rows)

            if page_rows and page_headers:
                return page_headers, page_rows

        return headers, []

    # ── line-based fallback ────────────────────────────────────────────────

    def _extract_lines(self, pdf) -> tuple[list[str], list[dict]]:
        """Fallback: parse raw text from all pages using word positions.

        1. Find header row by keyword matching on each page
        2. Use word X-positions from header row to define column boundaries
        3. Map data row words to columns by X-position
        4. Merge multi-line product names (continuation lines)
        """
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
                kw_count = sum(1 for t in tokens if t in self.config.header_keywords)
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
                                cols.append({
                                    "name": col_name,
                                    "x0": current_words[0]["x0"],
                                    "x1": current_words[-1]["x1"],
                                })
                                current_words = [w]
                            else:
                                current_words.append(w)
                        if current_words:
                            col_name = " ".join(cw["text"] for cw in current_words).strip()
                            cols.append({
                                "name": col_name,
                                "x0": current_words[0]["x0"],
                                "x1": current_words[-1]["x1"],
                            })

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
                if any(lower.startswith(kw) for kw in self.config.summary_keywords):
                    break
                if (lower.startswith("page ") and "of" in lower) or \
                   (lower.startswith("halaman ") and "dari" in lower):
                    continue
                # Skip repeated header rows
                tokens = re.split(r'[\s./_%]+', lower)
                kw_count = sum(1 for t in tokens if t in self.config.header_keywords)
                if kw_count >= 3:
                    continue

                # Map words to columns by X position
                row_dict = {h: "" for h in headers}
                for w in ws:
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

        if not headers or not all_rows:
            return [], []

        all_rows = merge_continuation_rows(headers, all_rows)
        headers, all_rows = clean_table_result(headers, all_rows, self.config)
        return headers, all_rows

