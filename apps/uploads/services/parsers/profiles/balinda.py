"""Parser profile for CV Balinda Anugerah Mulia.

Invoice format: borderless table with columns
No. | Prod. Id | Name | Qty | Price | Disc. % | Disc. Amt | Total
"""
from apps.uploads.services.parsers.config import ParserConfig

PROFILE = ParserConfig(
    header_keywords=frozenset({
        "no", "prod", "id", "name", "qty", "price", "disc", "total", "amt",
    }),
    summary_keywords=frozenset({
        "sub total", "grand total", "terbilang", "notes",
        "discount", "discount amount", "total qty",
        "mengetahui", "pengirim", "penerima",
    }),
    invoice_id_patterns=[
        r"Invoice\s*Id\s*[:\-]\s*(.+)",
    ],
    product_prefix="SCARLETT",
)
