"""Tests for game.card_generator."""
from __future__ import annotations

from game.card_generator import (
    FREE_LABEL,
    GRID_SIZE,
    WORD_POOL,
    generate_card,
    generate_unique_cards,
)


def test_card_is_5x5() -> None:
    """Every card must be exactly 5 rows of 5 cells."""
    card = generate_card(WORD_POOL)
    assert len(card) == GRID_SIZE
    assert all(len(row) == GRID_SIZE for row in card)


def test_center_is_free() -> None:
    """The middle cell is always the literal "FREE" (D2/D3)."""
    card = generate_card(WORD_POOL)
    assert card[2][2] == FREE_LABEL


def test_non_center_cells_are_unique_within_card() -> None:
    """All 24 non-center cells hold distinct words, none of them "FREE"."""
    card = generate_card(WORD_POOL)
    non_center = [
        card[r][c]
        for r in range(GRID_SIZE)
        for c in range(GRID_SIZE)
        if (r, c) != (2, 2)
    ]
    assert len(non_center) == 24
    assert len(set(non_center)) == 24
    assert FREE_LABEL not in non_center


def test_seed_makes_card_deterministic() -> None:
    """Same seed → identical card; different seed → (almost surely) different."""
    a = generate_card(WORD_POOL, seed=42)
    b = generate_card(WORD_POOL, seed=42)
    assert a == b
    c = generate_card(WORD_POOL, seed=43)
    assert a != c


def test_generate_unique_cards_no_duplicates() -> None:
    """A batch of N cards contains N distinct grids."""
    cards = generate_unique_cards(WORD_POOL, count=20)
    assert len(cards) == 20
    # Hash by (tuple of tuples) so the set can dedupe whole grids.
    keys = {tuple(tuple(row) for row in card) for card in cards}
    assert len(keys) == 20
