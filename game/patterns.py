"""Winning bingo pattern definitions.

Each "pattern type" is a list of patterns. A pattern is a list of
``(row, col)`` coordinates whose cells must all be marked for that
pattern to count as a win. The game engine walks through these and
returns True on the first pattern that's fully marked.

Coordinate system: row 0 is the top, column 0 is the left.
"""
from __future__ import annotations

GRID_SIZE = 5

# Type aliases — readability over Python's bare tuple/list noise.
Coord = tuple[int, int]
Pattern = list[Coord]

# 5 horizontal lines, one per row.
HORIZONTAL_LINE: list[Pattern] = [
    [(r, c) for c in range(GRID_SIZE)] for r in range(GRID_SIZE)
]

# 5 vertical lines, one per column.
VERTICAL_LINE: list[Pattern] = [
    [(r, c) for r in range(GRID_SIZE)] for c in range(GRID_SIZE)
]

# Two diagonals: main (top-left → bottom-right) + anti (top-right → bottom-left).
DIAGONAL: list[Pattern] = [
    [(i, i) for i in range(GRID_SIZE)],
    [(i, GRID_SIZE - 1 - i) for i in range(GRID_SIZE)],
]

# A single 25-cell pattern covering the whole card.
FULL_HOUSE: list[Pattern] = [
    [(r, c) for r in range(GRID_SIZE) for c in range(GRID_SIZE)]
]

# Lookup keyed by the same string we store in ``games.pattern``. The
# game engine resolves a pattern_type name to a list of patterns here.
#
# "Any" categories — win if ANY sub-pattern in the group is complete.
# "Specific" patterns — the list contains exactly one sub-pattern so the
# host can target one exact line (e.g. "Row 3" only, not any row).
PATTERN_TYPES: dict[str, list[Pattern]] = {
    # Any-line categories
    "horizontal": HORIZONTAL_LINE,
    "vertical": VERTICAL_LINE,
    "diagonal": DIAGONAL,
    "full_house": FULL_HOUSE,
    # Specific rows (row_1 = top, row_5 = bottom)
    **{f"row_{r + 1}": [HORIZONTAL_LINE[r]] for r in range(GRID_SIZE)},
    # Specific columns (col_1 = left, col_5 = right)
    **{f"col_{c + 1}": [VERTICAL_LINE[c]] for c in range(GRID_SIZE)},
    # Individual diagonals
    "diag_main": [DIAGONAL[0]],   # top-left → bottom-right
    "diag_anti": [DIAGONAL[1]],   # top-right → bottom-left
}
