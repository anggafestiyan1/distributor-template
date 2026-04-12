"""OCR helpers -- PaddleOCR word extraction and table reconstruction."""
from __future__ import annotations

import re

from ..config import ParserConfig
from .post_process import clean_table_result, merge_continuation_rows

_paddle_ocr_instance = None


def get_paddle_ocr():
    """Lazy-init PaddleOCR instance (heavy to initialize)."""
    global _paddle_ocr_instance
    if _paddle_ocr_instance is None:
        from paddleocr import PaddleOCR
        _paddle_ocr_instance = PaddleOCR(
            use_angle_cls=True,
            lang="en",  # "en" handles Indonesian text + numbers fine
            show_log=False,
        )
    return _paddle_ocr_instance


def correct_ocr_text(text: str) -> str:
    """Fix common OCR misreads — e.g. digit 0 read as letter O.

    Rules:
    - O between digits → 0:  "1O5" → "105"
    - O after digit before letter → 0:  "3OML" → "30ML"
    - O after digit at end → 0:  "1O" → "10"
    """
    text = re.sub(r'(\d)O(\d)', r'\g<1>0\2', text)       # 1O5 → 105
    text = re.sub(r'(\d)O([A-Z])', r'\g<1>0\2', text)    # 3OML → 30ML
    text = re.sub(r'(\d)O\b', r'\g<1>0', text)           # 1O → 10
    return text


def ocr_image_to_words(image_path: str) -> list[dict]:
    """Run PaddleOCR on an image and return list of word dicts with positions.

    Each word dict has: text, x0, x1, top, bottom (compatible with pdfplumber word format).
    Applies OCR text correction (e.g. O → 0) automatically.
    """
    ocr = get_paddle_ocr()
    result = ocr.ocr(image_path, cls=True)
    if not result or not result[0]:
        return []

    words: list[dict] = []
    for line in result[0]:
        box, (text, confidence) = line
        x0 = min(p[0] for p in box)
        x1 = max(p[0] for p in box)
        y0 = min(p[1] for p in box)
        y1 = max(p[1] for p in box)
        words.append({
            "text": correct_ocr_text(text.strip()),
            "x0": float(x0),
            "x1": float(x1),
            "top": float(y0),
            "bottom": float(y1),
        })
    return words


def cluster_words_by_y(words: list[dict]) -> list[list[dict]]:
    """Cluster OCR words into rows based on Y position.

    Uses adaptive clustering: sort by Y, group words whose Y center
    is within a fraction of median word height.
    """
    if not words:
        return []

    sorted_words = sorted(words, key=lambda w: (w["top"] + w["bottom"]) / 2)

    # Estimate typical word height
    heights = sorted(w["bottom"] - w["top"] for w in sorted_words)
    median_h = heights[len(heights) // 2] if heights else 10
    # Cluster threshold -- words within 0.7 * median_h are same row
    threshold = max(median_h * 0.7, 5)

    clusters: list[list[dict]] = []
    current_cluster = [sorted_words[0]]
    current_center = (sorted_words[0]["top"] + sorted_words[0]["bottom"]) / 2

    for w in sorted_words[1:]:
        w_center = (w["top"] + w["bottom"]) / 2
        if abs(w_center - current_center) <= threshold:
            current_cluster.append(w)
            # Update running center (average)
            all_centers = [(cw["top"] + cw["bottom"]) / 2 for cw in current_cluster]
            current_center = sum(all_centers) / len(all_centers)
        else:
            clusters.append(current_cluster)
            current_cluster = [w]
            current_center = w_center

    if current_cluster:
        clusters.append(current_cluster)

    return clusters


def words_to_parse_result(
    all_words: list[dict],
    config: ParserConfig,
) -> tuple[list[str], list[dict]]:
    """Convert list of OCR words with positions to headers + rows.

    Flow:
    1. Cluster words into rows (adaptive Y clustering)
    2. Find header row via keyword matching -> extract column NAMES
    3. Find first complete data row -> use its word X positions to calibrate
       column BOUNDARIES (headers are centered but data is left-aligned,
       so header positions are unreliable)
    4. Assign data words to columns via midpoint boundaries
    """
    if not all_words:
        return [], []

    # Cluster words into rows adaptively
    row_clusters = cluster_words_by_y(all_words)
    if not row_clusters:
        return [], []

    # Find header row -- line with >= 2 known keywords
    header_idx = None
    header_columns: list[dict] = []
    for idx, cluster in enumerate(row_clusters):
        ws = sorted(cluster, key=lambda w: w["x0"])
        line_text = " ".join(w["text"] for w in ws).lower()
        tokens = re.split(r'[\s./_%]+', line_text)
        kw_count = sum(1 for t in tokens if t in config.header_keywords)
        if kw_count >= config.header_keyword_min:
            header_idx = idx
            # Group header words into columns by gap
            current = [ws[0]]
            for w in ws[1:]:
                gap = w["x0"] - current[-1]["x1"]
                if gap > config.column_gap_threshold:
                    name = " ".join(cw["text"] for cw in current).strip()
                    header_columns.append({"name": name, "x0": current[0]["x0"], "x1": current[-1]["x1"]})
                    current = [w]
                else:
                    current.append(w)
            if current:
                name = " ".join(cw["text"] for cw in current).strip()
                header_columns.append({"name": name, "x0": current[0]["x0"], "x1": current[-1]["x1"]})
            break

    if not header_columns or len(header_columns) < 2:
        return [], []

    # Find the first complete data row (has at least same column count as headers)
    # to calibrate actual column X positions. Data rows are usually left-aligned
    # while headers are centered, so header X positions don't match data positions.
    num_header_cols = len(header_columns)
    data_row_positions = None
    for idx in range(header_idx + 1, len(row_clusters)):
        ws = sorted(row_clusters[idx], key=lambda w: w["x0"])
        if len(ws) < num_header_cols:
            continue
        # Group data words into columns by same gap logic as headers
        groups: list[list[dict]] = []
        current = [ws[0]]
        for w in ws[1:]:
            gap = w["x0"] - current[-1]["x1"]
            if gap > config.column_gap_threshold:
                groups.append(current)
                current = [w]
            else:
                current.append(w)
        if current:
            groups.append(current)

        if len(groups) == num_header_cols:
            # Use this row's group positions as the calibrated columns
            data_row_positions = [
                {"x0": g[0]["x0"], "x1": g[-1]["x1"]}
                for g in groups
            ]
            break

    # Use data positions if found, else fall back to header positions
    columns: list[dict] = []
    if data_row_positions:
        for i, h in enumerate(header_columns):
            columns.append({
                "name": h["name"],
                "x0": data_row_positions[i]["x0"],
                "x1": data_row_positions[i]["x1"],
            })
    else:
        columns = list(header_columns)

    # Compute column boundaries as midpoints of the GAP between adjacent columns.
    # Using gap midpoint (not center midpoint) handles short text in wide columns:
    # e.g. "MEMORIES" (short) in a column with "SCL. SCARLETT EAU DE PARFUM..." (long).
    boundaries: list[float] = [0.0]
    for i in range(len(columns) - 1):
        boundaries.append((columns[i]["x1"] + columns[i + 1]["x0"]) / 2)
    boundaries.append(float("inf"))

    headers = [c["name"] for c in columns]

    def _assign_col(wx_center: float) -> int:
        for i in range(len(columns)):
            if boundaries[i] <= wx_center < boundaries[i + 1]:
                return i
        return len(columns) - 1

    all_rows: list[dict] = []

    for idx in range(header_idx + 1, len(row_clusters)):
        ws = sorted(row_clusters[idx], key=lambda w: w["x0"])
        line_text = " ".join(w["text"] for w in ws).strip()
        lower = line_text.lower()
        if not lower:
            continue
        # Skip summary
        if any(lower.startswith(kw) for kw in config.summary_keywords):
            break
        # Skip repeated header
        tokens = re.split(r'[\s./_%]+', lower)
        kw_count = sum(1 for t in tokens if t in config.header_keywords)
        if kw_count >= 3:
            continue
        # Skip footer "Halaman X dari Y" / "Page X of Y"
        if lower.startswith("halaman ") or (lower.startswith("page ") and "of" in lower):
            continue

        row_dict = {h: "" for h in headers}
        for w in ws:
            wx_center = (w["x0"] + w["x1"]) / 2
            col_idx = _assign_col(wx_center)
            h = headers[col_idx]
            row_dict[h] = (row_dict[h] + " " + w["text"]).strip() if row_dict[h] else w["text"]

        row_dict = {k: v.strip() for k, v in row_dict.items()}
        if any(row_dict.values()):
            all_rows.append(row_dict)

    if not all_rows:
        return headers, []

    # Merge multi-line text continuation rows FIRST (before clean_table_result drops "No.")
    all_rows = merge_continuation_rows(headers, all_rows)
    headers, all_rows = clean_table_result(headers, all_rows, config)
    return headers, all_rows
