"""Shared DataFrame → ParseResult conversion."""
from __future__ import annotations

import pandas as pd

from ..base import ParseResult


def dataframe_to_result(df: pd.DataFrame) -> ParseResult:
    """Convert a pandas DataFrame to ParseResult, cleaning up values."""
    df.columns = [str(c).strip() for c in df.columns]
    df = df.fillna("")
    for col in df.columns:
        df[col] = df[col].astype(str).str.strip()
    return ParseResult(
        headers=list(df.columns),
        rows=df.to_dict(orient="records"),
        row_count=len(df),
    )
