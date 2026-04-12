"""Distributor profile registry — maps distributor codes to parser configs."""
from __future__ import annotations

import importlib
import logging

from apps.uploads.services.parsers.config import ParserConfig

logger = logging.getLogger(__name__)

# Map distributor.code → profile module name
PROFILE_MAP: dict[str, str] = {
    "ArthaM1": "artha",
    "BAM": "balinda",
}

# Default config (used when no profile matches)
DEFAULT_CONFIG = ParserConfig()


def load_profile(distributor_code: str | None) -> ParserConfig:
    """Load a distributor-specific parser config, or return default."""
    if not distributor_code or distributor_code not in PROFILE_MAP:
        return DEFAULT_CONFIG

    module_name = PROFILE_MAP[distributor_code]
    try:
        mod = importlib.import_module(f".{module_name}", __package__)
        return mod.PROFILE
    except (ImportError, AttributeError) as exc:
        logger.warning("Failed to load profile '%s' for distributor '%s': %s",
                       module_name, distributor_code, exc)
        return DEFAULT_CONFIG
