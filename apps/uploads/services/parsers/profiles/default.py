"""Default parser profile — works for most invoice formats."""
from apps.uploads.services.parsers.config import ParserConfig

PROFILE = ParserConfig()  # All defaults from ParserConfig dataclass
