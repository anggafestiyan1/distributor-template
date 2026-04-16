"""Image OCR parser — extract tabular data from JPG/PNG using PaddleOCR."""
from __future__ import annotations

import logging

from .base import BaseParser, ParseResult
from .helpers.ocr import cluster_words_by_y, ocr_image_to_words, words_to_parse_result

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
            raw_text = _build_raw_text(words)
            metadata = {"_raw_first_page_text": raw_text} if raw_text else {}
            if not headers:
                return ParseResult(
                    headers=[], rows=[], row_count=0,
                    parse_errors=["OCR could not detect a table header in image."],
                    metadata=metadata,
                )
            logger.info(
                "Image OCR parsed: %d headers, %d rows — %s",
                len(headers), len(rows), headers,
            )
            return ParseResult(
                headers=headers, rows=rows, row_count=len(rows),
                metadata=metadata,
            )
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


def _build_raw_text(words: list[dict]) -> str:
    """Reconstruct first-page text from OCR words so header-field extraction works."""
    if not words:
        return ""
    lines = []
    for cluster in cluster_words_by_y(words):
        sorted_words = sorted(cluster, key=lambda w: w["x0"])
        line = " ".join(w["text"] for w in sorted_words).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)
