"""File parsing service for xlsx and csv uploads."""
from __future__ import annotations

import hashlib
import json
import logging
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
    """Compute SHA-256 checksum of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def compute_row_checksum(row_data: dict) -> str:
    """Compute SHA-256 of a normalized JSON representation of a row."""
    serialized = json.dumps(row_data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def parse_file(file_path: str, original_filename: str) -> ParseResult:
    """Parse an xlsx or csv file and return headers + rows as dicts.

    All values are read as strings (dtype=str) to preserve raw values.
    NaN is replaced with empty string.
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".xlsx":
        return _parse_xlsx(file_path)
    elif suffix == ".csv":
        return _parse_csv(file_path)
    else:
        return ParseResult(
            headers=[],
            rows=[],
            row_count=0,
            parse_errors=[f"Unsupported file type: {suffix}"],
        )


def _parse_xlsx(file_path: str) -> ParseResult:
    try:
        df = pd.read_excel(
            file_path,
            engine="openpyxl",
            dtype=str,
            header=0,
        )
        return _dataframe_to_result(df)
    except Exception as exc:
        logger.exception("Failed to parse xlsx: %s", file_path)
        return ParseResult(
            headers=[],
            rows=[],
            row_count=0,
            parse_errors=[f"Excel parse error: {exc}"],
        )


def _parse_csv(file_path: str) -> ParseResult:
    encodings = ["utf-8", "utf-8-sig", "latin-1", "cp1252"]
    for encoding in encodings:
        try:
            df = pd.read_csv(
                file_path,
                dtype=str,
                header=0,
                encoding=encoding,
                sep=None,          # auto-detect delimiter
                engine="python",
            )
            result = _dataframe_to_result(df)
            result.encoding_used = encoding
            return result
        except UnicodeDecodeError:
            continue
        except Exception as exc:
            logger.exception("Failed to parse csv: %s", file_path)
            return ParseResult(
                headers=[],
                rows=[],
                row_count=0,
                parse_errors=[f"CSV parse error: {exc}"],
            )

    return ParseResult(
        headers=[],
        rows=[],
        row_count=0,
        parse_errors=["Unable to decode CSV with any supported encoding (utf-8, latin-1, cp1252)"],
    )


def _dataframe_to_result(df: pd.DataFrame) -> ParseResult:
    """Convert a DataFrame to ParseResult, cleaning up values."""
    # Strip whitespace from column names
    df.columns = [str(c).strip() for c in df.columns]

    # Replace NaN with empty string
    df = df.fillna("")

    # Strip whitespace from all string cells
    for col in df.columns:
        df[col] = df[col].astype(str).str.strip()

    headers = list(df.columns)
    rows = df.to_dict(orient="records")

    return ParseResult(
        headers=headers,
        rows=rows,
        row_count=len(rows),
    )
