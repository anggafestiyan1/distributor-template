"""Parser package — modular, config-driven file parsing.

Usage:
    from apps.uploads.services.parsers import parse_file, ParseResult
    result = parse_file(file_path, original_filename, distributor_code="ArthaM1")
"""
from __future__ import annotations

import logging
from pathlib import Path

from .base import BaseParser, ParseResult, compute_file_checksum, compute_row_checksum
from .config import ParserConfig
from .helpers.metadata import save_parsed_json
from .profiles import load_profile

logger = logging.getLogger(__name__)

# ── Parser Registry ─────────────────────────────────────────────────────────

PARSER_REGISTRY: dict[str, type[BaseParser]] = {}


def register(cls: type[BaseParser]) -> type[BaseParser]:
    """Decorator: register a parser class for its declared file extensions."""
    for ext in cls.file_extensions:
        PARSER_REGISTRY[ext.lower()] = cls
    return cls


# ── Auto-register all parsers ───────────────────────────────────────────────
# Import parser modules so their @register decorators run at import time.

from .excel import ExcelParser
from .csv_parser import CsvParser
from .pdf_digital import PdfDigitalParser
from .image_ocr import ImageOcrParser

register(ExcelParser)
register(CsvParser)
register(PdfDigitalParser)
register(ImageOcrParser)


# ── Public API ──────────────────────────────────────────────────────────────


def parse_file(
    file_path: str,
    original_filename: str,
    distributor_code: str | None = None,
) -> ParseResult:
    """Parse any supported file and return headers + rows.

    Dispatches to the correct parser based on file extension.
    Loads distributor-specific config if a matching profile exists.
    Saves a `.parsed.json` audit file alongside the original.
    """
    ext = Path(file_path).suffix.lower()
    parser_cls = PARSER_REGISTRY.get(ext)

    if parser_cls is None:
        return ParseResult(
            headers=[], rows=[], row_count=0,
            parse_errors=[f"Unsupported file type: {ext}"],
        )

    # Load distributor-specific config (or default)
    config = load_profile(distributor_code)
    parser = parser_cls(config=config)

    logger.info("Parsing '%s' with %s (profile=%s)",
                original_filename, parser_cls.__name__, distributor_code or "default")

    result = parser.parse(file_path)

    # Save intermediate JSON for audit / debug
    if result.headers:
        try:
            save_parsed_json(file_path, result, original_filename)
        except Exception as exc:
            logger.warning("Failed to save parsed JSON: %s", exc)

    return result


# ── Re-exports for backward compatibility ───────────────────────────────────

__all__ = [
    "parse_file",
    "ParseResult",
    "ParserConfig",
    "BaseParser",
    "compute_file_checksum",
    "compute_row_checksum",
    "PARSER_REGISTRY",
    "register",
]
