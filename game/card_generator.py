"""Bingo card generation.

Cards are 5x5 grids of words drawn from a configurable word pool. The
center cell is always the literal "FREE" (D2/D3 — auto-marked free
square). Cards are deterministic when a ``seed`` is provided, which is
how tests pin down the output.
"""
from __future__ import annotations

import random

GRID_SIZE = 5
CENTER = (2, 2)
# 5x5 minus the FREE center = 24 cells that need words.
NON_CENTER_CELLS = GRID_SIZE * GRID_SIZE - 1
FREE_LABEL = "FREE"

# Placeholder pool — 75 generic words (animals + foods + colors). Will be
# swapped for the CGI/co-op themed list once the user provides it (D1).
WORD_POOL: list[str] = [
    # Animals (25)
    "Tiger", "Panda", "Koala", "Otter", "Sloth",
    "Falcon", "Moose", "Beaver", "Lynx", "Badger",
    "Llama", "Parrot", "Octopus", "Dolphin", "Hedgehog",
    "Raccoon", "Wolf", "Fox", "Bear", "Eagle",
    "Whale", "Gecko", "Walrus", "Rabbit", "Squirrel",
    # Foods (25)
    "Pizza", "Sushi", "Taco", "Ramen", "Mango",
    "Pancake", "Waffle", "Pretzel", "Dumpling", "Burrito",
    "Croissant", "Donut", "Gnocchi", "Falafel", "Nachos",
    "Kimchi", "Bagel", "Paella", "Gyoza", "Biscuit",
    "Popcorn", "Gelato", "Hummus", "Samosa", "Churro",
    # Colors (25)
    "Red", "Blue", "Green", "Yellow", "Purple",
    "Orange", "Pink", "Teal", "Magenta", "Crimson",
    "Indigo", "Lavender", "Mint", "Scarlet", "Amber",
    "Coral", "Ivory", "Jade", "Ochre", "Maroon",
    "Olive", "Peach", "Salmon", "Tan", "Violet",
]


def generate_card(
    word_pool: list[str], seed: int | None = None
) -> list[list[str]]:
    """Build one 5x5 bingo card.

    Returns a 5x5 list-of-lists where the center is "FREE" and the other
    24 cells are unique words sampled (without replacement) from
    ``word_pool``. When ``seed`` is provided the output is reproducible,
    which is how the tests pin down behavior.

    Raises:
        ValueError: if ``word_pool`` doesn't have at least 24 unique words.
    """
    # Drop duplicate inputs while preserving order. ``dict.fromkeys`` is
    # the standard order-preserving de-dup trick in Python 3.7+.
    unique_pool = list(dict.fromkeys(word_pool))
    if len(unique_pool) < NON_CENTER_CELLS:
        raise ValueError(
            f"word_pool needs at least {NON_CENTER_CELLS} unique words, "
            f"got {len(unique_pool)}"
        )

    # A local Random instance keeps the seed isolated from the global
    # ``random`` state used elsewhere in the process.
    rng = random.Random(seed)
    chosen = rng.sample(unique_pool, NON_CENTER_CELLS)

    grid: list[list[str]] = [
        ["" for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)
    ]
    word_iter = iter(chosen)
    for r in range(GRID_SIZE):
        for c in range(GRID_SIZE):
            if (r, c) == CENTER:
                grid[r][c] = FREE_LABEL
            else:
                grid[r][c] = next(word_iter)
    return grid


def generate_unique_cards(
    word_pool: list[str], count: int
) -> list[list[list[str]]]:
    """Generate ``count`` cards, all distinct from each other.

    "Distinct" compares the full grid including word *positions*, so two
    cards with the same words arranged differently count as different —
    which is the desired behavior: every player gets a visually unique
    card.

    Raises:
        ValueError: if ``count`` is negative, or if the pool is too small
            to produce that many distinct cards within a reasonable
            number of attempts.
    """
    if count < 0:
        raise ValueError("count must be >= 0")

    seen: set[tuple[tuple[str, ...], ...]] = set()
    cards: list[list[list[str]]] = []

    # Cap retries so we don't spin forever if the pool is pathologically
    # small. With a 75-word pool the search space (24! orderings of 24
    # chosen words) is astronomical, so collisions are vanishingly rare
    # in practice.
    max_attempts = max(count * 10, 100)
    attempts = 0

    while len(cards) < count:
        if attempts >= max_attempts:
            raise ValueError(
                f"Could not produce {count} unique cards from a pool of "
                f"{len(word_pool)} words after {attempts} attempts"
            )
        attempts += 1
        card = generate_card(word_pool)
        key = tuple(tuple(row) for row in card)
        if key in seen:
            continue
        seen.add(key)
        cards.append(card)

    return cards
