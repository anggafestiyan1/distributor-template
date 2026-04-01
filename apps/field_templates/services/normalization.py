"""Header normalization utilities.

All alias comparison and template matching depends on this module.
The normalize_header function MUST be deterministic and idempotent.
"""
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.db.models import QuerySet


def normalize_header(raw: str) -> str:
    """Normalize a column header string for consistent comparison.

    Steps applied in order:
    1. Strip leading/trailing whitespace
    2. Lowercase
    3. Replace hyphens and spaces with underscores
    4. Remove all characters that are not alphanumeric or underscore
    5. Collapse consecutive underscores into one
    6. Strip leading/trailing underscores

    Examples:
        "  Product Name " → "product_name"
        "Product-Name"    → "product_name"
        "Product  Name"   → "product_name"
        "product_name"    → "product_name"  (idempotent)
        "(Product) Name!" → "product_name"
        "NAMA BARANG"     → "nama_barang"
        "Nama barang"     → "nama_barang"
        "nama-barang"     → "nama_barang"
    """
    if not raw:
        return ""
    s = raw.strip().lower()
    s = s.replace("-", "_").replace(" ", "_")
    s = re.sub(r"[^a-z0-9_]", "", s)
    s = re.sub(r"_+", "_", s)
    return s.strip("_")


def normalize_headers_list(headers: list[str]) -> dict[str, str]:
    """Normalize a list of headers and return a {raw: normalized} mapping.

    Handles collision: if two raw headers normalize to the same value,
    appends _2, _3, etc. to prevent silent data loss.
    """
    result: dict[str, str] = {}
    seen_normalized: dict[str, int] = {}

    for raw in headers:
        norm = normalize_header(raw)
        if norm in seen_normalized:
            seen_normalized[norm] += 1
            norm = f"{norm}_{seen_normalized[norm]}"
        else:
            seen_normalized[norm] = 1
        result[raw] = norm

    return result


def build_alias_lookup(standard_fields=None) -> dict[str, int]:
    """Build a {normalized_alias: standard_field_id} lookup dict.

    Loads all FieldAlias records (and the field name itself) into memory
    for O(1) alias resolution during processing.

    Args:
        standard_fields: Optional queryset; if None, loads all fields.

    Returns:
        Dict mapping normalized alias strings to StandardMasterField PKs.
    """
    from apps.field_templates.models import FieldAlias, StandardMasterField

    if standard_fields is None:
        standard_fields = StandardMasterField.objects.all()

    lookup: dict[str, int] = {}

    # Include the field's own name as an alias
    for field in standard_fields:
        norm = normalize_header(field.name)
        lookup[norm] = field.pk
        norm_display = normalize_header(field.display_name)
        if norm_display and norm_display not in lookup:
            lookup[norm_display] = field.pk

    # Include all explicit aliases
    aliases = FieldAlias.objects.filter(
        standard_field__in=standard_fields
    ).values_list("alias_normalized", "standard_field_id")

    for alias_norm, field_id in aliases:
        if alias_norm:
            lookup[alias_norm] = field_id

    return lookup
