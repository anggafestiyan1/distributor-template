"""Parser configuration — keywords, thresholds, patterns.

Each distributor can override these via a profile in `profiles/`.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ParserConfig:
    """All configurable parameters for file parsing."""

    # ── Header detection ────────────────────────────────────────────────────
    header_keywords: frozenset[str] = field(default_factory=lambda: frozenset({
        "no", "nama", "qty", "quantity", "satuan", "unit", "harga", "price",
        "total", "disc", "diskon", "jumlah", "barang", "produk", "product",
        "amount", "description", "item", "kode", "code", "date", "tanggal",
        "name", "prod", "amt",
    }))

    # ── Summary / footer row keywords (to filter out) ───────────────────────
    summary_keywords: frozenset[str] = field(default_factory=lambda: frozenset({
        "sub total", "subtotal", "diskon", "discount", "ppn", "pajak", "tax",
        "total", "grand total", "terbilang", "dp", "uang muka", "penerima",
        "gudang", "pengirim", "mengetahui", "keterangan", "halaman",
        "notes", "discount amount", "total qty",
    }))

    # ── Invoice metadata regex patterns ─────────────────────────────────────
    invoice_id_patterns: list[str] = field(default_factory=lambda: [
        r"Invoice\s*Id\s*[:\-]\s*(.+)",
        r"Nomor\s*Faktur\s*[:\-]?\s*(.+)",
        r"No\.?\s*Faktur\s*[:\-]?\s*(.+)",
        r"Invoice\s*(?:No|Number)\s*[:\-]\s*(.+)",
    ])

    # ── Product name common prefix (for multi-line merge heuristic) ─────────
    product_prefix: str = ""

    # ── Thresholds ──────────────────────────────────────────────────────────
    column_gap_threshold: int = 20        # px gap between words = new column
    ocr_y_tolerance_factor: float = 0.7   # fraction of median word height
    ocr_dpi: int = 200                    # DPI for PDF-to-image rendering
    max_header_len: int = 100             # reject headers longer than this
    max_cell_len: int = 200               # reject cells longer than this
    fragment_ratio: float = 0.4           # reject if > 40% headers are tiny
    min_avg_header_len: int = 3           # reject if avg header len < this
    header_keyword_min: int = 2           # min keywords to detect header row

    # ── Columns to drop from output ─────────────────────────────────────────
    drop_columns: list[str] = field(default_factory=lambda: ["No.", "No"])
