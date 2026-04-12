"""Handle pdfplumber merged cells -- split multi-value cells into proper rows."""
from __future__ import annotations

import re


def split_merged_cells(headers: list[str], raw_rows: list[list[str]]) -> list[dict]:
    """Handle pdfplumber merged cells -- cells contain multiple values joined by \\n.

    Strategy: Use the "No." column as the anchor -- each number in that column
    marks a new row. All lines between two numbers belong to the same row
    (multi-line product names get merged).

    If no "No." column, fall back to counting numeric columns.
    """
    result_rows: list[dict] = []

    for raw_row in raw_rows:
        cells = [str(c) if c else "" for c in raw_row]
        has_newlines = any("\n" in c for c in cells)

        if not has_newlines:
            row_dict = {}
            for j, cell in enumerate(cells):
                if j < len(headers) and headers[j]:
                    row_dict[headers[j]] = cell.strip()
            if any(row_dict.values()):
                result_rows.append(row_dict)
            continue

        # Split each cell by newline
        split_cols = [c.split("\n") for c in cells]

        # Find "No." column index
        no_col_idx = None
        for idx, h in enumerate(headers):
            if h.strip().lower().rstrip('.') == 'no':
                no_col_idx = idx
                break

        if no_col_idx is not None:
            # === Anchor-based approach ===
            # Use a "short" numeric column (Qty, Total, No.) to determine row count.
            # The No. column has exactly N lines for N rows.
            # Other numeric columns also have exactly N non-empty values.
            # Text columns (Nama Barang) have MORE lines due to multi-line names.

            no_lines = split_cols[no_col_idx]
            num_rows = len([v for v in no_lines if v.strip() and re.match(r'^\d+$', v.strip())])
            if num_rows == 0:
                continue

            col_values: list[list[str]] = []
            for ci, col_lines in enumerate(split_cols):
                non_empty = [v.strip() for v in col_lines if v.strip()]

                if len(non_empty) <= num_rows:
                    # Short column (numeric) -- take non-empty values, pad if needed
                    padded = list(non_empty) + [""] * (num_rows - len(non_empty))
                    col_values.append(padded[:num_rows])
                else:
                    # Long column (text with multi-line names) -- need to figure out
                    # which lines belong to which row.
                    #
                    # Strategy: use a reference short column to find line boundaries.
                    # Find a short column where non-empty count == num_rows.
                    # The positions of non-empty values in that column mark row boundaries
                    # in this (text) column.
                    ref_col_idx = no_col_idx  # default: use No. column
                    ref_col = split_cols[ref_col_idx]

                    # Find line indices where reference column has values
                    ref_positions: list[int] = []
                    for li, val in enumerate(ref_col):
                        if val.strip():
                            ref_positions.append(li)

                    # But text column has more lines -- the ref positions don't map directly.
                    # Instead, count non-empty lines in the text column per "segment".
                    # Each segment: from ref_positions[i] to ref_positions[i+1] in the
                    # LONGEST column, not the ref column.
                    #
                    # Better approach: just distribute text lines proportionally.
                    # Since numeric columns have N values and text has M > N lines,
                    # we know some text entries span multiple lines.
                    # Use the total line count: text_lines / num_rows to find rough grouping.

                    grouped: list[str] = []
                    text_lines = col_lines  # all lines for this column
                    total_lines = len(text_lines)

                    # Smart grouping: find which text lines start a NEW entry
                    # vs which are continuations of the previous entry.
                    #
                    # Strategy: detect the common prefix pattern from the first
                    # few entries (e.g., "SCL." or "PRODUCT"). Lines starting
                    # with this prefix are new entries; others are continuations.
                    #
                    # We need exactly `num_rows` groups.

                    # Detect common prefix from non-empty lines
                    non_empty_lines = [l.strip() for l in text_lines if l.strip()]
                    common_prefix = ""
                    if len(non_empty_lines) >= 2:
                        # Find longest common prefix among lines that look like
                        # product entries (longer lines, not fragments)
                        long_lines = [l for l in non_empty_lines if len(l) > 20]
                        if len(long_lines) >= 2:
                            prefix = long_lines[0]
                            for ll in long_lines[1:]:
                                while prefix and not ll.startswith(prefix):
                                    prefix = prefix[:-1]
                            common_prefix = prefix.strip()
                            # Use at least 3 chars of prefix
                            if len(common_prefix) < 3:
                                common_prefix = ""

                    entry_starts: list[int] = [0]
                    for li in range(1, total_lines):
                        line = text_lines[li].strip()
                        if not line:
                            continue
                        if len(entry_starts) >= num_rows:
                            break

                        is_new = False
                        if common_prefix:
                            # Line starts with the common prefix -> new entry
                            is_new = line.startswith(common_prefix)
                        else:
                            # Fallback: line > 25 chars + starts uppercase
                            is_new = len(line) > 25 and line[0].isupper()

                        if is_new:
                            entry_starts.append(li)

                    # If we found exactly num_rows starts, great.
                    # If fewer, pad by splitting the last group.
                    # If more (shouldn't happen), take first num_rows.
                    if len(entry_starts) < num_rows:
                        # Distribute remaining lines evenly from the last start
                        last = entry_starts[-1]
                        remaining_lines = total_lines - last
                        remaining_entries = num_rows - len(entry_starts)
                        if remaining_entries > 0 and remaining_lines > 0:
                            step = remaining_lines / (remaining_entries + 1)
                            for k in range(1, remaining_entries + 1):
                                entry_starts.append(last + round(k * step))

                    entry_starts = entry_starts[:num_rows]

                    for ri in range(num_rows):
                        start = entry_starts[ri]
                        end = entry_starts[ri + 1] if ri + 1 < len(entry_starts) else total_lines
                        chunk = " ".join(text_lines[start:end]).strip()
                        grouped.append(chunk)

                    if not grouped:
                        grouped = [" ".join(non_empty)]
                        grouped += [""] * (num_rows - 1)

                    col_values.append(grouped[:num_rows])

            # Build row dicts
            for ri in range(num_rows):
                row_dict = {}
                for j in range(len(headers)):
                    if j < len(col_values) and headers[j]:
                        row_dict[headers[j]] = col_values[j][ri] if ri < len(col_values[j]) else ""
                if any(row_dict.values()):
                    result_rows.append(row_dict)

        else:
            # === Fallback: no "No." column, use numeric count heuristic ===
            max_lines = max(len(col) for col in split_cols)
            pending_row: dict | None = None

            for line_idx in range(max_lines):
                line_values = [
                    col[line_idx].strip() if line_idx < len(col) else ""
                    for col in split_cols
                ]
                if not any(line_values):
                    continue

                numeric_count = sum(
                    1 for v in line_values
                    if v and re.match(r'^[\d.,]+$', v)
                )
                is_new_row = numeric_count >= 2

                if is_new_row:
                    if pending_row and any(pending_row.values()):
                        result_rows.append(pending_row)
                    pending_row = {}
                    for j, val in enumerate(line_values):
                        if j < len(headers) and headers[j]:
                            pending_row[headers[j]] = val
                elif pending_row is not None:
                    for j, val in enumerate(line_values):
                        if j < len(headers) and headers[j] and val:
                            h = headers[j]
                            existing = pending_row.get(h, "")
                            pending_row[h] = (existing + " " + val).strip() if existing else val

            if pending_row and any(pending_row.values()):
                result_rows.append(pending_row)

    return result_rows
