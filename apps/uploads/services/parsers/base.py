"""Base parser class and ParseResult dataclass."""
from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar

from .config import ParserConfig


@dataclass
class ParseResult:
    headers: list[str]
    rows: list[dict]
    row_count: int
    parse_errors: list[str] = field(default_factory=list)
    encoding_used: str = "utf-8"
    metadata: dict = field(default_factory=dict)


class BaseParser(ABC):
    """Abstract base for all file parsers.

    Subclasses declare `file_extensions` and implement `parse()`.
    The registry in `__init__.py` auto-discovers and dispatches.
    """

    file_extensions: ClassVar[list[str]] = []

    def __init__(self, config: ParserConfig | None = None):
        from .profiles import DEFAULT_CONFIG
        self.config = config or DEFAULT_CONFIG

    @abstractmethod
    def parse(self, file_path: str) -> ParseResult:
        """Extract headers + rows from the file."""
        ...


# ── Utility functions (file-format agnostic) ────────────────────────────────


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
