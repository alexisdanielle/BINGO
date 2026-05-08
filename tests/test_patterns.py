"""Tests for game.patterns — shape and coverage of the static definitions."""
from __future__ import annotations

from game.patterns import (
    DIAGONAL,
    FULL_HOUSE,
    GRID_SIZE,
    HORIZONTAL_LINE,
    PATTERN_TYPES,
    VERTICAL_LINE,
)


def test_horizontal_has_one_pattern_per_row() -> None:
    assert len(HORIZONTAL_LINE) == GRID_SIZE
    for r, pattern in enumerate(HORIZONTAL_LINE):
        assert pattern == [(r, c) for c in range(GRID_SIZE)]


def test_vertical_has_one_pattern_per_column() -> None:
    assert len(VERTICAL_LINE) == GRID_SIZE
    for c, pattern in enumerate(VERTICAL_LINE):
        assert pattern == [(r, c) for r in range(GRID_SIZE)]


def test_diagonal_has_two_patterns_through_center() -> None:
    assert len(DIAGONAL) == 2
    main, anti = DIAGONAL
    # Both cross the center (2, 2) — sanity check on the coords.
    assert (2, 2) in main
    assert (2, 2) in anti
    assert main == [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4)]
    assert anti == [(0, 4), (1, 3), (2, 2), (3, 1), (4, 0)]


def test_full_house_covers_all_25_cells() -> None:
    assert len(FULL_HOUSE) == 1
    cells = FULL_HOUSE[0]
    assert len(cells) == GRID_SIZE * GRID_SIZE
    assert set(cells) == {(r, c) for r in range(GRID_SIZE) for c in range(GRID_SIZE)}


def test_pattern_types_lookup_has_all_four() -> None:
    assert set(PATTERN_TYPES) == {"horizontal", "vertical", "diagonal", "full_house"}
