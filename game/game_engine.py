"""Game-engine logic.

For now: ``check_win`` only. Other state-machine code (calling words,
recording wins, ending the game after the 3rd valid winner per D8)
will land here as it's added.
"""
from __future__ import annotations

from collections.abc import Iterable

from game.card_generator import FREE_LABEL
from game.patterns import PATTERN_TYPES


def check_win(
    card: list[list[str]],
    called_words: Iterable[str],
    pattern_type: str,
) -> bool:
    """Return True if ``card`` has any completed pattern of the given type.

    A cell is "marked" if its word is in ``called_words`` OR it's the
    FREE center, which is auto-marked per D2/D3.

    ``pattern_type`` is one of the keys of ``PATTERN_TYPES``:
    ``"horizontal"``, ``"vertical"``, ``"diagonal"``, ``"full_house"``.

    Raises:
        ValueError: if ``pattern_type`` is not a recognized name.
    """
    if pattern_type not in PATTERN_TYPES:
        raise ValueError(
            f"Unknown pattern_type {pattern_type!r}; expected one of "
            f"{sorted(PATTERN_TYPES)}"
        )

    # Promote to a set for O(1) membership. Accepting any iterable lets
    # callers pass either an ordered list of calls or an existing set.
    called = set(called_words)

    for pattern in PATTERN_TYPES[pattern_type]:
        if all(
            card[r][c] == FREE_LABEL or card[r][c] in called
            for (r, c) in pattern
        ):
            return True
    return False
