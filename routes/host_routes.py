"""HTTP endpoints used by the bingo game host.

All host-only actions (start, future stop/reset) authenticate with the
``X-Host-Token`` header — the token is returned at game creation and
must round-trip on subsequent host calls (D9).
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request

from game.card_generator import NON_CENTER_CELLS
from game.game_engine import run_call_loop
from game.patterns import PATTERN_TYPES
from game.topic_generator import (
    DEFAULT_COUNT,
    TopicGenerationError,
    generate_word_list,
)
from models import Game, db
from sockets import socketio

# Block game creation if the host's accepted word list can't fill a
# 5x5 card (24 non-FREE cells). One extra over the strict minimum
# provides a small cushion against duplicate-card collisions when many
# players join.
MIN_GAME_WORDS = NON_CENTER_CELLS + 1  # 25

host_bp = Blueprint("host", __name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _is_host(game: Game) -> bool:
    """Compare the request's host token against the game's stored token."""
    return request.headers.get("X-Host-Token") == game.host_token


@host_bp.post("/api/topics/preview")
def preview_topic():
    """Generate (or fetch cached) words+descriptions for a topic name.

    Body (JSON):
        topic (str, required): free-text topic name.
        count (int, optional): how many words to ask the LLM for on a
            cache miss. Ignored on cache hit. Defaults to DEFAULT_COUNT.
        created_by_email (str, optional): host email recorded on the
            Topic row when this call is the cache-creating one.

    Returns 200 with ``{"topic": str, "words": [{word, description}, ...]}``
    so the host UI can render an editable preview before committing
    to creating a game.
    """
    data = request.get_json(silent=True) or {}
    topic = (data.get("topic") or "").strip()
    if not topic:
        return jsonify(error="topic is required"), 400
    try:
        count = int(data.get("count", DEFAULT_COUNT))
    except (TypeError, ValueError):
        return jsonify(error="count must be an integer"), 400
    if count < MIN_GAME_WORDS:
        return (
            jsonify(error=f"count must be >= {MIN_GAME_WORDS}"),
            400,
        )
    email = data.get("created_by_email") or None

    try:
        words = generate_word_list(
            topic, count=count, created_by_email=email
        )
    except TopicGenerationError as e:
        # The LLM came back but the shape was unusable. 502 because the
        # failure is in an upstream dependency, not the client's request.
        return jsonify(error=f"topic generation failed: {e}"), 502

    return jsonify(topic=topic, words=words), 200


def _validate_game_words(value: object) -> list[dict] | None:
    """Return a cleaned list of {word, description} dicts, or None if invalid.

    The host UI may submit edited / partially-deleted entries, so we
    don't trust the shape: drop malformed rows and dedupe (case-
    insensitive) before returning. Returning ``None`` signals the
    caller that the payload was unusable.
    """
    if not isinstance(value, list):
        return None
    seen: set[str] = set()
    cleaned: list[dict] = []
    for entry in value:
        if not isinstance(entry, dict):
            return None
        word = entry.get("word")
        description = entry.get("description", "")
        if not isinstance(word, str) or not isinstance(description, str):
            return None
        word = word.strip()
        description = description.strip()
        if not word:
            return None
        key = word.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({"word": word, "description": description})
    return cleaned


@host_bp.post("/api/games")
def create_game():
    """Create a new game in 'waiting' status with a finalized word list.

    Body (JSON):
        host_name (str, optional): defaults to "Host"
        pattern (str, optional): one of PATTERN_TYPES keys; defaults to
            "horizontal"
        call_interval_seconds (int, optional): per-game cadence override
            (D4); >= 1
        game_words (list[{word, description}], required): the host's
            accepted topic word list. Must contain at least
            ``MIN_GAME_WORDS`` distinct words.

    Returns 201 with ``game_id``, ``host_token``, ``join_link``.
    """
    data = request.get_json(silent=True) or {}
    host_name = (data.get("host_name") or "").strip() or "Host"
    pattern = data.get("pattern") or "horizontal"
    if pattern not in PATTERN_TYPES:
        return (
            jsonify(
                error=f"unknown pattern {pattern!r}; expected one of "
                f"{sorted(PATTERN_TYPES)}"
            ),
            400,
        )
    try:
        interval = int(data.get("call_interval_seconds", 5))
    except (TypeError, ValueError):
        return jsonify(error="call_interval_seconds must be an integer"), 400
    if interval < 1:
        return jsonify(error="call_interval_seconds must be >= 1"), 400

    cleaned_words = _validate_game_words(data.get("game_words"))
    if cleaned_words is None:
        return (
            jsonify(
                error="game_words must be a list of "
                "{word, description} objects with non-empty words"
            ),
            400,
        )
    if len(cleaned_words) < MIN_GAME_WORDS:
        return (
            jsonify(
                error=f"need at least {MIN_GAME_WORDS} distinct words "
                f"to start a game, got {len(cleaned_words)}"
            ),
            400,
        )

    game = Game(
        host_name=host_name,
        pattern=pattern,
        host_token=secrets.token_urlsafe(16),
        call_interval_seconds=interval,
        game_words=cleaned_words,
    )
    db.session.add(game)
    db.session.commit()

    return (
        jsonify(
            game_id=game.id,
            host_token=game.host_token,
            join_link=f"/play?game_id={game.id}",
            pattern=pattern,
            call_interval_seconds=interval,
            status=game.status,
            word_count=len(cleaned_words),
        ),
        201,
    )


@host_bp.post("/api/games/<int:game_id>/start")
def start_game(game_id: int):
    """Move a 'waiting' game to 'active' and kick off the calling loop."""
    game = db.session.get(Game, game_id)
    if game is None:
        return jsonify(error="game not found"), 404
    if not _is_host(game):
        return jsonify(error="invalid host token"), 401
    if game.status != "waiting":
        return jsonify(error=f"cannot start a {game.status} game"), 409

    game.status = "active"
    game.started_at = _utcnow()
    db.session.commit()

    # ``current_app`` is a request-scoped proxy; the background thread
    # has no request context, so we hand it the underlying app object.
    app = current_app._get_current_object()  # type: ignore[attr-defined]
    socketio.start_background_task(run_call_loop, app, game.id)

    socketio.emit(
        "game_started",
        {
            "game_id": game.id,
            "pattern": game.pattern,
            "call_interval_seconds": game.call_interval_seconds,
        },
        to=f"game:{game.id}",
    )
    return jsonify(status="active", game_id=game.id), 200


@host_bp.get("/api/games/<int:game_id>/state")
def get_state(game_id: int):
    """Snapshot of game state — useful as a polling fallback for clients."""
    game = db.session.get(Game, game_id)
    if game is None:
        return jsonify(error="game not found"), 404

    calls_sorted = sorted(game.calls, key=lambda c: c.call_index)
    wins_sorted = sorted(game.wins, key=lambda w: w.place)

    return jsonify(
        game_id=game.id,
        status=game.status,
        pattern=game.pattern,
        host_name=game.host_name,
        call_interval_seconds=game.call_interval_seconds,
        called_words=[c.word for c in calls_sorted],
        players=[c.player_name for c in game.cards],
        wins=[
            {
                "place": w.place,
                "player_name": w.card.player_name,
                "pattern_matched": w.pattern_matched,
            }
            for w in wins_sorted
        ],
    )
