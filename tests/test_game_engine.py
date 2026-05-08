"""Tests for game.game_engine.check_win."""
from __future__ import annotations

import pytest

from game.card_generator import FREE_LABEL
from game.game_engine import check_win


def _make_grid(words: list[str]) -> list[list[str]]:
    """Build a 5x5 grid from 24 words, with FREE in the center.

    Layout (so test expectations are easy to read):
        row 0: words[0..4]
        row 1: words[5..9]
        row 2: words[10], words[11], FREE, words[12], words[13]
        row 3: words[14..18]
        row 4: words[19..23]
    """
    assert len(words) == 24
    grid = [["" for _ in range(5)] for _ in range(5)]
    it = iter(words)
    for r in range(5):
        for c in range(5):
            if (r, c) == (2, 2):
                grid[r][c] = FREE_LABEL
            else:
                grid[r][c] = next(it)
    return grid


# Reusable 24-word vocabulary for hand-crafted cards. W00..W23.
WORDS = [f"W{i:02d}" for i in range(24)]


def test_winning_horizontal_line_top_row() -> None:
    """All 5 words in row 0 called → horizontal win."""
    card = _make_grid(WORDS)
    called = {"W00", "W01", "W02", "W03", "W04"}
    assert check_win(card, called, "horizontal") is True


def test_horizontal_near_miss_4_of_5() -> None:
    """4 of 5 in the top row is not enough."""
    card = _make_grid(WORDS)
    called = {"W00", "W01", "W02", "W03"}  # missing W04
    assert check_win(card, called, "horizontal") is False


def test_winning_vertical_line_left_column() -> None:
    """All 5 cells in column 0 called → vertical win."""
    card = _make_grid(WORDS)
    # Col 0 cells = (0,0)W00, (1,0)W05, (2,0)W10, (3,0)W14, (4,0)W19.
    called = {"W00", "W05", "W10", "W14", "W19"}
    assert check_win(card, called, "vertical") is True


def test_winning_main_diagonal_uses_free_center() -> None:
    """Main diag (TL→BR) wins with 4 calls because FREE auto-counts."""
    card = _make_grid(WORDS)
    # Main diag = (0,0)W00, (1,1)W06, (2,2)FREE, (3,3)W17, (4,4)W23.
    called = {"W00", "W06", "W17", "W23"}  # 4 words + FREE = 5 marks
    assert check_win(card, called, "diagonal") is True


def test_winning_anti_diagonal_uses_free_center() -> None:
    """Anti-diag (TR→BL) wins with 4 calls because FREE auto-counts."""
    card = _make_grid(WORDS)
    # Anti-diag = (0,4)W04, (1,3)W08, (2,2)FREE, (3,1)W15, (4,0)W19.
    called = {"W04", "W08", "W15", "W19"}
    assert check_win(card, called, "diagonal") is True


def test_full_house_win() -> None:
    """All 24 non-free cells called → full house (FREE rounds out the 25)."""
    card = _make_grid(WORDS)
    assert check_win(card, set(WORDS), "full_house") is True


def test_full_house_one_short_is_not_a_win() -> None:
    """Missing even one word means the full house isn't complete."""
    card = _make_grid(WORDS)
    called = set(WORDS[:-1])  # leave W23 uncalled
    assert check_win(card, called, "full_house") is False


def test_card_with_scattered_marks_does_not_win_any_pattern() -> None:
    """A handful of scattered cells should not match any pattern type."""
    card = _make_grid(WORDS)
    # Three corners + two interior — no full row, column, diagonal, or house.
    called = {"W00", "W04", "W19", "W12", "W07"}
    assert check_win(card, called, "horizontal") is False
    assert check_win(card, called, "vertical") is False
    assert check_win(card, called, "diagonal") is False
    assert check_win(card, called, "full_house") is False


def test_unknown_pattern_type_raises() -> None:
    """Misspelled or unsupported pattern names raise rather than silently fail."""
    card = _make_grid(WORDS)
    with pytest.raises(ValueError):
        check_win(card, set(), "spiral")
