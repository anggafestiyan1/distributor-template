"""Parser profile for PT Artha Manunggal Sejahtera.

Invoice format: bordered table with columns
No. | Nama Barang | Qty | Satuan | Harga Satuan | Disc % | Total Harga
"""
from apps.uploads.services.parsers.config import ParserConfig

PROFILE = ParserConfig(
    header_keywords=frozenset({
        "no", "nama", "barang", "qty", "satuan", "harga", "disc", "total",
    }),
    summary_keywords=frozenset({
        "sub total", "subtotal", "total", "ppn", "terbilang", "penerima",
        "gudang", "pengirim", "mengetahui", "keterangan", "halaman",
        "diskon", "discount", "cash",
    }),
    invoice_id_patterns=[
        r"Nomor\s*Faktur\s*[:\-]?\s*(.+)",
        r"No\.?\s*Faktur\s*[:\-]?\s*(.+)",
    ],
    product_prefix="SCL.",
)
