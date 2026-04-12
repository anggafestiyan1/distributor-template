"""Image OCR parser — extract tabular data from JPG/PNG using PaddleOCR."""
from __future__ import annotations

import logging

from .base import BaseParser, ParseResult
from .helpers.ocr import ocr_image_to_words, words_to_parse_result

logger = logging.getLogger(__name__)


class ImageOcrParser(BaseParser):
    """Parse image files (JPG, PNG) by running PaddleOCR and extracting tables."""

    file_extensions = [".jpg", ".jpeg", ".png"]

    def parse(self, file_path: str) -> ParseResult:
        try:
            words = ocr_image_to_words(file_path)
            if not words:
                return ParseResult(
                    headers=[], rows=[], row_count=0,
                    parse_errors=[
                        "OCR found no text in image. Is the image clear and readable?"
                    ],
                )
            headers, rows = words_to_parse_result(words, self.config)
            if not headers:
                return ParseResult(
                    headers=[], rows=[], row_count=0,
                    parse_errors=["OCR could not detect a table header in image."],
                )
            logger.info(
                "Image OCR parsed: %d headers, %d rows — %s",
                len(headers), len(rows), headers,
            )
            return ParseResult(headers=headers, rows=rows, row_count=len(rows))
        except ImportError:
            return ParseResult(
                headers=[], rows=[], row_count=0,
                parse_errors=[
                    "PaddleOCR not installed. Run: pip install paddleocr paddlepaddle"
                ],
            )
        except Exception as exc:
            logger.exception("Failed to OCR image: %s", file_path)
            return ParseResult(
                headers=[], rows=[], row_count=0,
                parse_errors=[f"Image OCR error: {exc}"],
            )
