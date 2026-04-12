"""CSV / TSV parser with multi-encoding support."""
from __future__ import annotations

import logging

import pandas as pd

from .base import BaseParser, ParseResult
from .helpers.dataframe import dataframe_to_result

logger = logging.getLogger(__name__)


class CsvParser(BaseParser):
    """Parse .csv and .tsv files, trying multiple encodings."""

    file_extensions = [".csv", ".tsv"]

    def parse(self, file_path: str) -> ParseResult:
        encodings = ["utf-8", "utf-8-sig", "latin-1", "cp1252"]
        for encoding in encodings:
            try:
                df = pd.read_csv(
                    file_path, dtype=str, header=0,
                    encoding=encoding, sep=None, engine="python",
                )
                result = dataframe_to_result(df)
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
