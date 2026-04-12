"""Excel (.xlsx) parser."""
from __future__ import annotations

import logging

import pandas as pd

from .base import BaseParser, ParseResult
from .helpers.dataframe import dataframe_to_result

logger = logging.getLogger(__name__)


class ExcelParser(BaseParser):
    """Parse .xlsx files using openpyxl via pandas."""

    file_extensions = [".xlsx"]

    def parse(self, file_path: str) -> ParseResult:
        try:
            df = pd.read_excel(file_path, engine="openpyxl", dtype=str, header=0)
            return dataframe_to_result(df)
        except Exception as exc:
            logger.exception("Failed to parse xlsx: %s", file_path)
            return ParseResult(
                headers=[], rows=[], row_count=0,
                parse_errors=[f"Excel parse error: {exc}"],
            )
