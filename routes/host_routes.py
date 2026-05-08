"""HTTP endpoints used by the bingo game host.

All host-only actions (start, future stop/reset) authenticate with the
``X-Host-Token`` header — the token is returned at game creation and
must round-trip on subsequent host calls (D9).
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request

from game.game_engine import run_call_loop
from game.patterns import PATTERN_TYPES
from models import Game, db
from sockets import socketio

host_bp = Blueprint("host", __name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _is_host(game: Game) -> bool:
    """Compare the request's host token against the game's stored token."""
    return request.headers.get("X-Host-Token") == game.host_token


@host_bp.post("/api/games")
def create_game():
    """Create a new game in 'waiting' status.

    Body (JSON, all optional):
        host_name (str): defaults to "Host"
        pattern (str): one of the PATTERN_TYPES keys; defaults to "horizontal"
        call_interval_seconds (int): per-game cadence override (D4); >= 1

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

    game = Game(
        host_name=host_name,
        pattern=pattern,
        host_token=secrets.token_urlsafe(16),
        call_interval_seconds=interval,
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
