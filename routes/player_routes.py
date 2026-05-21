"""HTTP endpoints used by bingo players: OTP auth, joining, and claiming wins.

Authentication flow (project-enhancement):
    1. POST /api/games/<id>/request-otp  — validate email domain + allowlist,
       send a 6-digit OTP via email.
    2. POST /api/games/<id>/verify-otp   — check the OTP; mark the auth record
       as verified so the player may join.
    3. POST /api/games/<id>/join         — same as before, but now requires a
       verified PlayerAuth for the supplied email.

Players authenticate to ``/bingo`` with the ``X-Join-Token`` header that
was returned to them at /join. We re-validate the card server-side
against the called words before recording a Win.
"""
from __future__ import annotations

import secrets
import threading
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from game.card_generator import generate_card
from game.email_sender import send_otp_email
from game.game_engine import which_pattern_matched
from models import Card, Game, PlayerAuth, Win, db
from sockets import socketio

player_bp = Blueprint("player", __name__)


def _utcnow() -> datetime:
    # SQLite stores naive datetimes, so we strip tzinfo here to keep all
    # comparisons against DB values consistent (naive UTC throughout).
    return datetime.now(timezone.utc).replace(tzinfo=None)


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


def _generate_otp() -> str:
    """Return a random 6-digit OTP string using a cryptographically secure source.

    ``secrets.randbelow`` is safer than ``random.randint`` because it draws
    from the OS entropy pool rather than a seeded PRNG.
    """
    # Range [100000, 999999] — always exactly 6 digits, no leading zeros.
    return str(100000 + secrets.randbelow(900000))


def _email_allowed(email: str, game: Game, domain: str) -> tuple[bool, str]:
    """Check whether ``email`` is permitted to join ``game``.

    Returns (allowed, reason). Two checks in order:
        1. If ``domain`` is set, email must end with @domain (case-insensitive).
           When ``domain`` is empty, any email is accepted — useful for dev/testing
           before the company approves a production SMTP relay.
        2. If ``game.allowed_emails`` is set, email must be in the list.
    """
    if domain and not email.lower().endswith(f"@{domain.lower()}"):
        return False, f"Only @{domain} email addresses may join this game."
    if game.allowed_emails:
        allowed_lower = {e.lower() for e in game.allowed_emails}
        if email.lower() not in allowed_lower:
            return False, "Your email is not on the invite list for this game."
    return True, ""


# ---------------------------------------------------------------------------
# OTP: request
# ---------------------------------------------------------------------------

@player_bp.post("/api/games/<int:game_id>/request-otp")
def request_otp(game_id: int):
    """Step 1 of auth: send a 6-digit OTP to the player's email.

    Validates:
      - Game exists and is in 'waiting' status.
      - Email matches the allowed domain (CGI_EMAIL_DOMAIN env var).
      - Email is in the per-game allowlist, if one was set by the host.
      - 60-second cooldown between OTP requests for the same email+game.
    """
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify(error="email required"), 400

    game = db.session.get(Game, game_id)
    if game is None:
        return jsonify(error="game not found"), 404
    if game.status != "waiting":
        return jsonify(error=f"game is {game.status}, not accepting joins"), 409

    domain = current_app.config.get("CGI_EMAIL_DOMAIN", "cgi.com")
    allowed, reason = _email_allowed(email, game, domain)
    if not allowed:
        return jsonify(error=reason), 403

    # Load or create the auth record for this (game, email) pair.
    auth = db.session.scalar(
        select(PlayerAuth).where(
            PlayerAuth.game_id == game_id,
            PlayerAuth.email == email,
        )
    )

    # Rate-limit: reject a second request within 60 seconds.
    if auth is not None and auth.verified:
        return jsonify(error="You are already verified. Proceed to join."), 409

    if auth is not None:
        elapsed = (_utcnow() - auth.otp_requested_at).total_seconds()
        if elapsed < 60:
            wait = int(60 - elapsed)
            return jsonify(error=f"Please wait {wait}s before requesting another code."), 429

    otp = _generate_otp()
    expiry_minutes = current_app.config.get("OTP_EXPIRY_MINUTES", 10)
    expires_at = _utcnow() + timedelta(minutes=expiry_minutes)

    if auth is None:
        auth = PlayerAuth(
            game_id=game_id,
            email=email,
            otp_code=otp,
            otp_expires_at=expires_at,
            otp_requested_at=_utcnow(),
            verified=False,
        )
        db.session.add(auth)
    else:
        # Overwrite the old code on a re-request.
        auth.otp_code = otp
        auth.otp_expires_at = expires_at
        auth.otp_requested_at = _utcnow()
        auth.verified = False

    db.session.commit()

    sent = send_otp_email(
        to_address=email,
        otp_code=otp,
        game_id=game_id,
        smtp_user=current_app.config.get("SMTP_USER"),
        smtp_password=current_app.config.get("SMTP_PASSWORD"),
        expiry_minutes=expiry_minutes,
    )

    # Return success even when sent=False (SMTP not configured) so the host
    # can demo the auth flow — the OTP is printed to the server console.
    return jsonify(sent=sent, message="Verification code sent. Check your email."), 200


# ---------------------------------------------------------------------------
# OTP: verify
# ---------------------------------------------------------------------------

@player_bp.post("/api/games/<int:game_id>/verify-otp")
def verify_otp(game_id: int):
    """Step 2 of auth: submit the OTP received by email.

    On success, the PlayerAuth row is marked verified and the player may
    call /join in the next step.
    """
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    otp = (data.get("otp") or "").strip()
    if not email or not otp:
        return jsonify(error="email and otp required"), 400

    auth = db.session.scalar(
        select(PlayerAuth).where(
            PlayerAuth.game_id == game_id,
            PlayerAuth.email == email,
        )
    )
    if auth is None:
        return jsonify(error="No verification code found. Request one first."), 404
    if auth.verified:
        return jsonify(message="Already verified. Proceed to join."), 200
    if _utcnow() > auth.otp_expires_at:
        return jsonify(error="Code has expired. Request a new one."), 410
    if auth.otp_code != otp:
        return jsonify(error="Incorrect code. Please try again."), 400

    auth.verified = True
    db.session.commit()
    return jsonify(message="Verified! You may now join the game."), 200


# ---------------------------------------------------------------------------
# Join
# ---------------------------------------------------------------------------

@player_bp.post("/api/games/<int:game_id>/join")
def join_game(game_id: int):
    """Add a verified player to a waiting game; return their card + join_token.

    Requires:
      - ``player_name``: display name (string).
      - ``email``: must match a verified PlayerAuth for this game.

    Rejects with 409 if the game has already started (D6 — no late
    joiners) or if the name is already taken in this game (caught via
    the unique ``(game_id, player_name)`` constraint). Also rejects if
    the email has already been used to join (prevents one person from
    claiming multiple cards by using different display names).
    """
    data = request.get_json(silent=True) or {}
    player_name = (data.get("player_name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    if not player_name:
        return jsonify(error="player_name required"), 400
    if not email:
        return jsonify(error="email required — complete OTP verification first"), 400

    game = db.session.get(Game, game_id)
    if game is None:
        return jsonify(error="game not found"), 404
    if game.status != "waiting":
        return jsonify(error=f"game is {game.status}, not accepting joins"), 409
    if not game.game_words:
        return jsonify(error="game has no word list configured"), 409

    # Verify the player completed OTP auth for this game.
    auth = db.session.scalar(
        select(PlayerAuth).where(
            PlayerAuth.game_id == game_id,
            PlayerAuth.email == email,
        )
    )
    if auth is None or not auth.verified:
        return jsonify(error="Email not verified. Complete the OTP step first."), 403

    # Prevent the same email from grabbing a second card under a different name.
    existing_card = db.session.scalar(
        select(Card).where(
            Card.game_id == game_id,
            Card.player_email == email,
        )
    )
    if existing_card is not None:
        return jsonify(error="This email has already joined the game."), 409

    card_data = generate_card([w["word"] for w in game.game_words])
    join_token = secrets.token_urlsafe(16)
    card = Card(
        game_id=game.id,
        player_name=player_name,
        player_email=email,
        card_data=card_data,
        join_token=join_token,
    )
    db.session.add(card)
    try:
        db.session.commit()
    except IntegrityError:
        # Hit the unique (game_id, player_name) constraint.
        db.session.rollback()
        return jsonify(error="That display name is already taken. Choose another."), 409

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
            pattern=game.pattern,
            max_winners=game.max_winners,
        ),
        201,
    )


# ---------------------------------------------------------------------------
# Rejoin (session recovery after page refresh)
# ---------------------------------------------------------------------------

@player_bp.post("/api/games/<int:game_id>/rejoin")
def rejoin_game(game_id: int):
    """Return an existing player's card and join token.

    Called when a player refreshes and loses their in-memory session.
    Requires the email to have a verified PlayerAuth and an existing Card
    for this game — prevents anyone from fetching another player's card.
    Works regardless of game status so mid-game rejoins are supported.
    """
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify(error="email required"), 400

    game = db.session.get(Game, game_id)
    if game is None:
        return jsonify(error="game not found"), 404

    auth = db.session.scalar(
        select(PlayerAuth).where(
            PlayerAuth.game_id == game_id,
            PlayerAuth.email == email,
        )
    )
    if auth is None or not auth.verified:
        return jsonify(error="Email not verified. Complete OTP verification first."), 403

    existing_card = db.session.scalar(
        select(Card).where(
            Card.game_id == game_id,
            Card.player_email == email,
        )
    )
    if existing_card is None:
        return jsonify(error="No card found for this email. Join the game first."), 404

    return jsonify(
        game_id=game.id,
        player_name=existing_card.player_name,
        card=existing_card.card_data,
        join_token=existing_card.join_token,
        pattern=game.pattern,
        max_winners=game.max_winners,
        game_status=game.status,
    ), 200


# ---------------------------------------------------------------------------
# Bingo claim (unchanged)
# ---------------------------------------------------------------------------

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
        # Accept claims on "active" games normally.
        # Also accept claims on "finished" games that ended because the word
        # pool exhausted (not because max_winners was hit), so a player who
        # completed their pattern on the very last word isn't unfairly blocked
        # by the calling loop ending the game a fraction of a second earlier.
        if game.status == "finished" and len(game.wins) >= game.max_winners:
            return jsonify(error="all places are taken"), 409
        if game.status not in ("active", "finished"):
            return jsonify(error=f"game is {game.status}, can't claim now"), 409
        if any(w.card_id == card.id for w in game.wins):
            return jsonify(error="you have already won this game"), 409
        if len(game.wins) >= game.max_winners:
            return jsonify(error="all places are taken"), 409

        called = {c.word for c in game.calls}
        matched = which_pattern_matched(card.card_data, called, game.pattern)
        if matched is None:
            return jsonify(error="card does not have a winning pattern yet"), 400

        place = len(game.wins) + 1
        win = Win(
            game_id=game.id,
            card_id=card.id,
            place=place,
            pattern_matched=matched,
            validated=True,
        )
        db.session.add(win)
        if place == game.max_winners:
            game.status = "finished"
            game.finished_at = _utcnow()
        db.session.commit()
        is_final = place == game.max_winners

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
            {"game_id": game.id, "reason": "last_winner"},
            to=f"game:{game.id}",
        )

    return jsonify(place=place, pattern_matched=matched), 200
