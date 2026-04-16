"""Parser profiles — all distributors use the default config.

Distributor-specific column mappings are handled by Templates (database),
not by code-level profiles. This module just provides the default config.
"""
from apps.uploads.services.parsers.config import ParserConfig

DEFAULT_CONFIG = ParserConfig()


def load_profile(distributor_code: str | None) -> ParserConfig:
    """Return the default parser config. All distributors use the same config."""
    return DEFAULT_CONFIG
