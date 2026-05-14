"""HTTP endpoints used by bingo players: joining a game and claiming wins.

Players authenticate to ``/bingo`` with the ``X-Join-Token`` header that
was returned to them at /join. We re-validate the card server-side
against the called words before recording a Win.
"""
from __future__ import annotations

import secrets
import threading
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from game.card_generator import generate_card
from game.game_engine import which_pattern_matched
from models import Card, Game, Win, db
from sockets import socketio

player_bp = Blueprint("player", __name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Per-game lock so two near-simultaneous /bingo claims don't both
# compute the same place number (e.g., both think they're place 2).
# SQLite's default isolation doesn't serialize the count-then-insert
# sequence on its own — an in-process lock does. Single-process server
# is fine for the demo.
_game_locks: dict[int, threading.Lock] = {}
_game_locks_guard = threading.Lock()


def _lock_for_game(game_id: int) -> threading.Lock:
    """Return (and lazily create) a lock for this game id."""
    with _game_locks_guard:
        lock = _game_locks.get(game_id)
        if lock is None:
            lock = threading.Lock()
            _game_locks[game_id] = lock
        return lock


@player_bp.post("/api/games/<int:game_id>/join")
def join_game(game_id: int):
    """Add a named player to a waiting game; return their card + join_token.

    Rejects with 409 if the game has already started (D6 — no late
    joiners) or if the name is already taken in this game (caught via
    the unique ``(game_id, player_name)`` constraint).
    """
    data = request.get_json(silent=True) or {}
    player_name = (data.get("player_name") or "").strip()
    if not player_name:
        return jsonify(error="player_name required"), 400

    game = db.session.get(Game, game_id)
    if game is None:
        return jsonify(error="game not found"), 404
    if game.status != "waiting":
        return (
            jsonify(error=f"game is {game.status}, not accepting joins"),
            409,
        )
    if not game.game_words:
        # Defensive: create_game enforces this, so we should never get
        # here unless the DB was populated by hand.
        return jsonify(error="game has no word list configured"), 409

    # Cards are drawn from the host-accepted topic words (iteration 2).
    # The descriptions live on the game; cards only carry the words.
    card_data = generate_card([w["word"] for w in game.game_words])
    join_token = secrets.token_urlsafe(16)
    card = Card(
        game_id=game.id,
        player_name=player_name,
        card_data=card_data,
        join_token=join_token,
    )
    db.session.add(card)
    try:
        db.session.commit()
    except IntegrityError:
        # Hit the unique (game_id, player_name) constraint.
        db.session.rollback()
        return jsonify(error="that name is already taken in this game"), 409

    socketio.emit(
        "player_joined",
        {"game_id": game.id, "player_name": player_name},
        to=f"game:{game.id}",
    )
    return (
        jsonify(
            game_id=game.id,
            player_name=player_name,
            card=card_data,
            join_token=join_token,
        ),
        201,
    )


@player_bp.post("/api/games/<int:game_id>/bingo")
def claim_bingo(game_id: int):
    """Validate a Bingo claim server-side; record a top-3 Win on success.

    Auth: ``X-Join-Token`` header. The token is matched against the
    caller's card on this specific game — a token from a different game
    is rejected.

    On the 3rd valid win the game ends (status='finished') and a
    ``game_ended`` event is broadcast.
    """
    join_token = request.headers.get("X-Join-Token")
    if not join_token:
        return jsonify(error="X-Join-Token header required"), 401

    game = db.session.get(Game, game_id)
    if game is None:
        return jsonify(error="game not found"), 404

    card = db.session.scalar(
        select(Card).where(
            Card.join_token == join_token,
            Card.game_id == game_id,
        )
    )
    if card is None:
        return jsonify(error="invalid join token for this game"), 401

    # Serialize per-game so two simultaneous claims don't both grab the
    # same place number.
    with _lock_for_game(game_id):
        # Re-read after grabbing the lock — state might have changed.
        db.session.refresh(game)
        if game.status != "active":
            return (
                jsonify(error=f"game is {game.status}, can't claim now"),
                409,
            )
        if any(w.card_id == card.id for w in game.wins):
            return jsonify(error="you have already won this game"), 409
        if len(game.wins) >= 3:
            return jsonify(error="all 3 places are taken"), 409

        called = {c.word for c in game.calls}
        matched = which_pattern_matched(card.card_data, called, game.pattern)
        if matched is None:
            return (
                jsonify(error="card does not have a winning pattern yet"),
                400,
            )

        place = len(game.wins) + 1
        win = Win(
            game_id=game.id,
            card_id=card.id,
            place=place,
            pattern_matched=matched,
            validated=True,
        )
        db.session.add(win)
        if place == 3:
            game.status = "finished"
            game.finished_at = _utcnow()
        db.session.commit()
        is_final = place == 3

    # Outside the lock so emits don't block other claimants.
    socketio.emit(
        "win_declared",
        {
            "game_id": game.id,
            "place": place,
            "player_name": card.player_name,
            "pattern_matched": matched,
        },
        to=f"game:{game.id}",
    )
    if is_final:
        socketio.emit(
            "game_ended",
            {"game_id": game.id, "reason": "third_winner"},
            to=f"game:{game.id}",
        )

    return jsonify(place=place, pattern_matched=matched), 200
