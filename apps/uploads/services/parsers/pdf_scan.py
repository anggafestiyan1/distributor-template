"""Scanned PDF parser — renders pages to images, then OCR."""
from __future__ import annotations

import logging
import os
import tempfile

from .base import BaseParser, ParseResult
from .helpers.ocr import ocr_image_to_words, words_to_parse_result

logger = logging.getLogger(__name__)


class PdfScanParser(BaseParser):
    """Parse scanned (image-only) PDFs via page rendering + PaddleOCR.

    Not registered via ``file_extensions`` — used as a fallback from
    ``PdfDigitalParser`` when a PDF has no extractable text layer.
    """

    # No file_extensions — not auto-registered.

    def parse(self, file_path: str) -> ParseResult:
        try:
            import pymupdf
        except ImportError:
            return ParseResult(
                headers=[], rows=[], row_count=0,
                parse_errors=["PyMuPDF not installed. Run: pip install pymupdf"],
            )

        try:
            doc = pymupdf.open(file_path)
            all_words: list[dict] = []

            for page_idx, page in enumerate(doc):
                pix = page.get_pixmap(dpi=self.config.ocr_dpi)
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    tmp_path = tmp.name
                try:
                    pix.save(tmp_path)
                    page_words = ocr_image_to_words(tmp_path)
                    page_height = pix.height
                    for w in page_words:
                        w["top"] += page_idx * page_height
                        w["bottom"] += page_idx * page_height
                    all_words.extend(page_words)
                finally:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)

            doc.close()

            if not all_words:
                return ParseResult(
                    headers=[], rows=[], row_count=0,
                    parse_errors=["OCR found no text in scanned PDF."],
                )

            headers, rows = words_to_parse_result(all_words, self.config)
            if not headers:
                return ParseResult(
                    headers=[], rows=[], row_count=0,
                    parse_errors=["OCR could not detect a table header in scanned PDF."],
                )

            logger.info("Scanned PDF OCR parsed: %d headers, %d rows — %s",
                        len(headers), len(rows), headers)
            return ParseResult(headers=headers, rows=rows, row_count=len(rows))

        except Exception as exc:
            logger.exception("Failed to OCR PDF: %s", file_path)
            return ParseResult(
                headers=[], rows=[], row_count=0,
                parse_errors=[f"Scanned PDF OCR error: {exc}"],
            )
