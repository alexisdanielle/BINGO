"""Game-engine logic: win detection plus the per-game word-calling loop."""
from __future__ import annotations

import logging
import random
from collections.abc import Iterable
from datetime import datetime, timezone

from flask import Flask

from game.card_generator import FREE_LABEL
from game.patterns import GRID_SIZE, PATTERN_TYPES
from models import Call, Game, db
from sockets import socketio

log = logging.getLogger(__name__)


# Human-readable label for each individual sub-pattern within a pattern
# type. Stored in ``wins.pattern_matched`` so the leaderboard / audit
# trail records *which* line was completed (e.g. "row_2" = third row).
_PATTERN_LABELS: dict[str, list[str]] = {
    # "Any" categories — each sub-pattern gets its own label.
    "horizontal": [f"Row {r + 1}" for r in range(GRID_SIZE)],
    "vertical": [f"Column {c + 1}" for c in range(GRID_SIZE)],
    "diagonal": ["Main diagonal", "Anti-diagonal"],
    "full_house": ["Full house"],
    # Specific single-line patterns — one label each.
    **{f"row_{r + 1}": [f"Row {r + 1}"] for r in range(GRID_SIZE)},
    **{f"col_{c + 1}": [f"Column {c + 1}"] for c in range(GRID_SIZE)},
    "diag_main": ["Main diagonal"],
    "diag_anti": ["Anti-diagonal"],
}


def which_pattern_matched(
    card: list[list[str]],
    called_words: Iterable[str],
    pattern_type: str,
) -> str | None:
    """Return the label of the first matching sub-pattern, else None.

    A cell is "marked" if its word is in ``called_words`` or it's the
    FREE center (D2/D3 — auto-marked).

    Raises:
        ValueError: if ``pattern_type`` is unknown.
    """
    if pattern_type not in PATTERN_TYPES:
        raise ValueError(
            f"Unknown pattern_type {pattern_type!r}; expected one of "
            f"{sorted(PATTERN_TYPES)}"
        )
    # Normalise to lower-case collapsed whitespace so AI-generated capitalisation
    # differences between the card and the called list never cause a mismatch.
    def _norm(w: str) -> str:
        return " ".join(w.strip().lower().split())

    called_norm = {_norm(w) for w in called_words}
    for label, pattern in zip(
        _PATTERN_LABELS[pattern_type], PATTERN_TYPES[pattern_type]
    ):
        if all(
            card[r][c] == FREE_LABEL or _norm(card[r][c]) in called_norm
            for (r, c) in pattern
        ):
            return label
    return None


def check_win(
    card: list[list[str]],
    called_words: Iterable[str],
    pattern_type: str,
) -> bool:
    """True iff ``card`` has any completed pattern of the given type."""
    return which_pattern_matched(card, called_words, pattern_type) is not None


def _utcnow() -> datetime:
    """Timezone-aware UTC timestamp (mirrors the helper in models)."""
    return datetime.now(timezone.utc)


def run_call_loop(app: Flask, game_id: int) -> None:
    """Background task: call one random uncalled word per interval.

    Runs in a thread spawned by ``socketio.start_background_task`` from
    the host's /start handler. Stops when the game's status leaves
    ``"active"`` (e.g. the bingo handler set it to ``"finished"`` after
    the 3rd winner) or when the word pool is exhausted.

    Each iteration: read fresh game state, pick a random uncalled word,
    persist a Call row (with its description), broadcast ``word_called``
    carrying both word and description, then sleep.
    """
    with app.app_context():
        try:
            game = db.session.get(Game, game_id)
            if game is None:
                log.warning("run_call_loop: game %s not found", game_id)
                return

            # Pull the host-finalized topic words. Map word -> description
            # so we can attach descriptions to Call rows and socket
            # broadcasts without re-scanning the list each iteration.
            game_words = game.game_words or []
            descriptions: dict[str, str] = {
                entry["word"]: entry.get("description", "")
                for entry in game_words
            }
            already_called = {c.word for c in game.calls}
            remaining = [
                entry["word"]
                for entry in game_words
                if entry["word"] not in already_called
            ]
            random.shuffle(remaining)

            while True:
                # After each commit, SQLAlchemy expires the game object so
                # the next attribute access re-issues a SELECT — picking up
                # status changes from other requests (win claims, pause).
                if game.status == "paused":
                    # Poll every second while paused; explicit refresh needed
                    # because there's no commit to expire the object.
                    socketio.sleep(1)
                    db.session.refresh(game)
                    continue

                if game.status != "active":
                    return

                if not remaining:
                    # Pool exhausted before 3 winners. Unlikely in normal
                    # play (host-accepted lists are >=25 words and cards
                    # use only 24) but we end the game cleanly so
                    # clients aren't stuck.
                    game.status = "finished"
                    game.finished_at = _utcnow()
                    db.session.commit()
                    socketio.emit(
                        "game_ended",
                        {"game_id": game.id, "reason": "pool_exhausted"},
                        to=f"game:{game.id}",
                    )
                    return

                word = remaining.pop()
                description = descriptions.get(word, "")
                next_index = (
                    max((c.call_index for c in game.calls), default=0) + 1
                )
                call = Call(
                    game_id=game.id,
                    word=word,
                    description=description,
                    call_index=next_index,
                )
                db.session.add(call)
                db.session.commit()

                socketio.emit(
                    "word_called",
                    {
                        "game_id": game.id,
                        "word": word,
                        "description": description,
                        "call_index": next_index,
                    },
                    to=f"game:{game.id}",
                )
                # Sleep in 0.5-second steps so a host pause takes effect
                # within ~0.5 s instead of waiting the full interval.
                elapsed = 0.0
                while elapsed < game.call_interval_seconds:
                    socketio.sleep(0.5)
                    db.session.refresh(game)
                    if game.status == "paused":
                        break  # exit sleep; outer loop polls until resume
                    if game.status != "active":
                        return  # game finished or reset while sleeping
                    elapsed += 0.5
        except Exception:
            # Background tasks swallow exceptions silently otherwise —
            # log so we can debug a misbehaving loop.
            log.exception("run_call_loop crashed for game %s", game_id)
