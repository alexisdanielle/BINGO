"""SQLAlchemy models for the Virtual Bingo app.

Schema mirrors the proposal in CLAUDE.md plus the v1 additions confirmed
on 2026-05-07:
    - ``games.host_token`` for host auth
    - ``games.call_interval_seconds`` (per-game cadence override, D4)
    - ``cards.created_at`` and unique ``(game_id, player_name)``
    - ``calls.call_index``
    - ``wins.pattern_matched``

Iteration 2 (topic generator) additions:
    - ``Topic`` table caches LLM-generated word lists per topic name
    - ``games.game_words`` stores the finalized per-game list of
      {word, description} pairs the host accepted (may differ from the
      cached Topic if the host edited rows for this particular game)
    - ``calls.description`` records the description shown alongside the
      word for that call, so the audit trail is self-contained
"""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import JSON, ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Single declarative base. SQLAlchemy 2.0's typed mapping style."""


# Module-level singleton. Bound to a Flask app via ``db.init_app(app)`` in
# ``create_app``. Routes/sockets import this same ``db`` to share the binding.
db = SQLAlchemy(model_class=Base)


def _utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp.

    Why: ``datetime.utcnow`` is naive and deprecated in 3.12; tz-aware
    values keep comparisons and logs unambiguous.
    """
    return datetime.now(timezone.utc)


class Game(db.Model):
    """A single bingo session, hosted by one person, joined by N players."""

    __tablename__ = "games"

    id: Mapped[int] = mapped_column(primary_key=True)
    host_name: Mapped[str] = mapped_column(nullable=False)
    pattern: Mapped[str] = mapped_column(nullable=False)
    # 'waiting' (accepting joins), 'active' (calling words), 'finished'.
    status: Mapped[str] = mapped_column(default="waiting", nullable=False)
    # Random secret returned to the host at creation; required on host actions.
    host_token: Mapped[str] = mapped_column(nullable=False, unique=True)
    # Per-game cadence (D4). 5s default; host can override at creation.
    call_interval_seconds: Mapped[int] = mapped_column(nullable=False, default=5)
    # Finalized list of {"word": str, "description": str} dicts the host
    # accepted at game creation. Nullable for back-compat with games
    # created before iteration 2; new games always populate it.
    game_words: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # cascade="all, delete-orphan" so deleting a Game also wipes its rows in
    # cards/calls/wins — keeps demo cleanups simple, no orphaned data.
    cards: Mapped[list["Card"]] = relationship(
        back_populates="game", cascade="all, delete-orphan"
    )
    calls: Mapped[list["Call"]] = relationship(
        back_populates="game", cascade="all, delete-orphan"
    )
    wins: Mapped[list["Win"]] = relationship(
        back_populates="game", cascade="all, delete-orphan"
    )


class Card(db.Model):
    """A 5x5 card assigned to one player for one game."""

    __tablename__ = "cards"
    # One player joins each game at most once (D6 — no duplicates / late joins).
    __table_args__ = (
        UniqueConstraint("game_id", "player_name", name="uq_card_game_player"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id"), nullable=False, index=True
    )
    player_name: Mapped[str] = mapped_column(nullable=False)
    # 5x5 grid of words. Free center stored explicitly as the literal "FREE".
    # JSON column type is portable across SQLite (TEXT under the hood) and
    # Postgres (native JSONB) — fine for a list-of-lists.
    card_data: Mapped[list] = mapped_column(JSON, nullable=False)
    # Token sent in the player's join URL. Used to authenticate Bingo claims.
    join_token: Mapped[str] = mapped_column(nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, nullable=False)

    game: Mapped[Game] = relationship(back_populates="cards")
    wins: Mapped[list["Win"]] = relationship(
        back_populates="card", cascade="all, delete-orphan"
    )


class Call(db.Model):
    """One word called during a game. Append-only audit trail."""

    __tablename__ = "calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id"), nullable=False, index=True
    )
    word: Mapped[str] = mapped_column(nullable=False)
    # Description shown alongside the word at call time (iteration 2).
    # Nullable so games that pre-date the topic feature still load.
    description: Mapped[str | None] = mapped_column(nullable=True)
    # 1-indexed position within the game. Useful for replay/UI ordering.
    call_index: Mapped[int] = mapped_column(nullable=False)
    called_at: Mapped[datetime] = mapped_column(default=_utcnow, nullable=False)

    game: Mapped[Game] = relationship(back_populates="calls")


class Win(db.Model):
    """A confirmed top-3 finish for a card in a game."""

    __tablename__ = "wins"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id"), nullable=False, index=True
    )
    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id"), nullable=False, index=True
    )
    # 1, 2, or 3. Game auto-ends after the 3rd is recorded (D8).
    place: Mapped[int] = mapped_column(nullable=False)
    # Which winning pattern was completed (e.g. 'row_2', 'col_4', 'diag_main').
    pattern_matched: Mapped[str] = mapped_column(nullable=False)
    declared_at: Mapped[datetime] = mapped_column(default=_utcnow, nullable=False)
    # Server-validated. False would indicate an attempted cheat or a bug.
    validated: Mapped[bool] = mapped_column(default=True, nullable=False)

    game: Mapped[Game] = relationship(back_populates="wins")
    card: Mapped[Card] = relationship(back_populates="wins")


class Topic(db.Model):
    """Cached LLM-generated word list for a topic name.

    Subsequent ``generate_word_list("CGI")`` calls hit this row instead
    of re-prompting the LLM, which keeps the demo fast and reduces API
    spend. ``topic_name`` is stored normalized (lowercase + stripped)
    so the cache is case-insensitive — see ``topic_generator._normalize``.
    """

    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_name: Mapped[str] = mapped_column(nullable=False, unique=True)
    # List of {"word": str, "description": str} dicts as returned by
    # the LLM (and minimally cleaned/deduped before storage).
    generated_words: Mapped[list] = mapped_column(JSON, nullable=False)
    # Optional — the host's email if we know it. Nullable since the
    # create-game form doesn't collect email yet.
    created_by_email: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, nullable=False)
    # Bumped on every cache hit (see ``topic_generator.generate_word_list``).
    times_used: Mapped[int] = mapped_column(nullable=False, default=0)


def init_db(app: Flask) -> None:
    """Create any missing tables for the app's bound database.

    Idempotent — ``create_all`` is a no-op once tables exist, so it's safe
    to call on every app startup. Keeps "fresh clone, just run" working
    without a separate migration step (we'll add Alembic later if needed).
    """
    with app.app_context():
        db.create_all()
