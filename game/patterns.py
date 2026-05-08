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
PATTERN_TYPES: dict[str, list[Pattern]] = {
    "horizontal": HORIZONTAL_LINE,
    "vertical": VERTICAL_LINE,
    "diagonal": DIAGONAL,
    "full_house": FULL_HOUSE,
}
