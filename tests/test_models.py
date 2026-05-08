"""Round-trip persistence test for the SQLAlchemy models.

Confirms a Game + Card can be saved, then reloaded in a fresh session
with the right defaults and relationship intact.
"""
from __future__ import annotations

import secrets
from pathlib import Path

import pytest
from flask import Flask

from app import create_app
from models import Card, Game, db


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    """Build a Flask app pointed at a throwaway SQLite file per test.

    ``tmp_path`` is a built-in pytest fixture that provides a unique temp
    directory and cleans it up automatically — keeps tests isolated
    without touching ``instance/bingo.db``.
    """
    db_path = tmp_path / "test.db"
    return create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
        }
    )


def test_create_game_and_card_round_trip(app: Flask) -> None:
    """A Game with a Card persists, reloads, and exposes the relationship."""
    # --- Write phase: create one Game and one Card, commit. ---
    with app.app_context():
        game = Game(
            host_name="Alex",
            pattern="horizontal",
            host_token=secrets.token_urlsafe(16),
        )
        db.session.add(game)
        # flush() pushes the INSERT so game.id is populated, without ending
        # the transaction — needed to set card.game_id below.
        db.session.flush()

        # 5x5 grid; FREE in the center per D3.
        card_grid = [[f"W{r}{c}" for c in range(5)] for r in range(5)]
        card_grid[2][2] = "FREE"

        card = Card(
            game_id=game.id,
            player_name="Sam",
            card_data=card_grid,
            join_token=secrets.token_urlsafe(16),
        )
        db.session.add(card)
        db.session.commit()

        game_id = game.id

    # --- Read phase: brand new app context = fresh session.
    # If we read on the same session we just wrote on, SQLAlchemy might
    # serve the in-memory object without a real round trip. A fresh
    # session forces a SELECT and proves the data actually persisted.
    with app.app_context():
        loaded = db.session.get(Game, game_id)
        assert loaded is not None
        assert loaded.host_name == "Alex"
        assert loaded.pattern == "horizontal"
        assert loaded.status == "waiting"  # default value applied
        assert loaded.call_interval_seconds == 5  # default value applied
        assert loaded.created_at is not None
        assert loaded.started_at is None
        assert loaded.finished_at is None

        assert len(loaded.cards) == 1
        reloaded_card = loaded.cards[0]
        assert reloaded_card.player_name == "Sam"
        assert reloaded_card.card_data[2][2] == "FREE"
        assert reloaded_card.card_data[0][0] == "W00"
        assert reloaded_card.created_at is not None
