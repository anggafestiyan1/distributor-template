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
    """Build a {normalized_name: standard_field_id} lookup from field names/display_names.

    Used BEFORE template matching (no template-specific mappings yet).
    After template match, the template's own mappings provide the complete alias set.
    """
    from apps.field_templates.models import StandardMasterField

    if standard_fields is None:
        standard_fields = StandardMasterField.objects.all()

    lookup: dict[str, int] = {}
    for field in standard_fields:
        norm = normalize_header(field.name)
        lookup[norm] = field.pk
        norm_display = normalize_header(field.display_name)
        if norm_display and norm_display not in lookup:
            lookup[norm_display] = field.pk

    return lookup


def build_alias_lookup_from_mappings(mappings) -> dict[str, int]:
    """Build {normalized_source_column: standard_field_id} from template mappings.

    Used AFTER template match for row mapping. Each mapping's source_column
    acts as an alias for the standard field.
    """
    lookup: dict[str, int] = {}
    for m in mappings:
        if m.source_column_normalized:
            lookup[m.source_column_normalized] = m.standard_field_id
    return lookup
