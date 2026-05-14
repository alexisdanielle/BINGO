"""End-to-end-ish tests for the iteration 2 topic flow.

Covers the route + engine wiring added in Layer 2:
    - POST /api/topics/preview generates/caches a word list
    - POST /api/games requires a valid game_words payload
    - POST /api/games/<id>/join generates cards from game.game_words
    - run_call_loop pulls from game_words and writes descriptions

The LLM client is monkeypatched so no real network call is made.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from flask import Flask

from app import create_app
from game import game_engine, topic_generator
from models import Call, Game, Topic, db


def _entries(n: int = 30) -> list[dict]:
    """Build a deterministic list of valid {word, description} entries."""
    return [
        {"word": f"Word{i:02d}", "description": f"Fact number {i} on the topic."}
        for i in range(n)
    ]


def _patch_llm(monkeypatch, entries: list[dict]) -> MagicMock:
    """Stub ``llm_client.generate`` so topic_generator never hits the network."""
    mock = MagicMock(return_value=json.dumps(entries))
    monkeypatch.setattr(topic_generator.llm_client, "generate", mock)
    return mock


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    """Throwaway Flask app + DB per test."""
    db_path = tmp_path / "test.db"
    return create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
        }
    )


@pytest.fixture
def client(app: Flask):
    """Flask test client — fires requests without spinning a real server."""
    return app.test_client()


# --- /api/topics/preview ---------------------------------------------------


def test_preview_returns_generated_words_on_cache_miss(
    monkeypatch, app: Flask, client
) -> None:
    """First preview call goes through the LLM and returns the parsed list."""
    entries = _entries(30)
    mock_llm = _patch_llm(monkeypatch, entries)

    res = client.post(
        "/api/topics/preview",
        json={"topic": "Canada", "count": 30},
    )

    assert res.status_code == 200
    body = res.get_json()
    assert body["topic"] == "Canada"
    assert body["words"] == entries
    assert mock_llm.call_count == 1

    # The Topic row is saved with the normalized name.
    with app.app_context():
        stored = db.session.scalar(
            db.select(Topic).where(Topic.topic_name == "canada")
        )
        assert stored is not None
        assert stored.times_used == 0


def test_preview_second_call_hits_cache(
    monkeypatch, app: Flask, client
) -> None:
    """Two previews for the same topic only call the LLM once."""
    entries = _entries(30)
    mock_llm = _patch_llm(monkeypatch, entries)

    client.post("/api/topics/preview", json={"topic": "Canada", "count": 30})
    res2 = client.post(
        "/api/topics/preview", json={"topic": "canada", "count": 30}
    )

    assert res2.status_code == 200
    assert res2.get_json()["words"] == entries
    assert mock_llm.call_count == 1


def test_preview_requires_topic(client) -> None:
    """Missing/empty topic is a 400 — no LLM call made."""
    res = client.post("/api/topics/preview", json={"topic": "  "})
    assert res.status_code == 400
    assert "topic" in res.get_json()["error"]


# --- POST /api/games -------------------------------------------------------


def test_create_game_persists_game_words(
    monkeypatch, app: Flask, client
) -> None:
    """POST /api/games stores the host-accepted word list on the game."""
    entries = _entries(30)

    res = client.post(
        "/api/games",
        json={
            "host_name": "Alex",
            "pattern": "horizontal",
            "call_interval_seconds": 5,
            "game_words": entries,
        },
    )

    assert res.status_code == 201
    body = res.get_json()
    assert body["word_count"] == 30

    with app.app_context():
        game = db.session.get(Game, body["game_id"])
        assert game is not None
        assert game.game_words == entries


def test_create_game_rejects_fewer_than_min_words(client) -> None:
    """Fewer than 25 words → 400 with a clear message."""
    res = client.post(
        "/api/games",
        json={"game_words": _entries(20)},
    )
    assert res.status_code == 400
    assert "25" in res.get_json()["error"]


def test_create_game_rejects_malformed_word_list(client) -> None:
    """A non-list (or entries missing fields) → 400."""
    res = client.post(
        "/api/games",
        json={"game_words": "not a list"},
    )
    assert res.status_code == 400


def test_create_game_dedupes_case_insensitively(client, app: Flask) -> None:
    """Duplicate-by-casing entries are collapsed before the count check."""
    # 30 unique + 1 dup-by-casing should collapse to 30.
    entries = _entries(30) + [
        {"word": "word00", "description": "duplicate of Word00"}
    ]
    res = client.post("/api/games", json={"game_words": entries})
    assert res.status_code == 201
    assert res.get_json()["word_count"] == 30


# --- /api/games/<id>/join --------------------------------------------------


def test_join_generates_card_from_topic_words(
    monkeypatch, app: Flask, client
) -> None:
    """A joining player gets a card whose words come from game.game_words."""
    entries = _entries(30)
    create = client.post("/api/games", json={"game_words": entries})
    game_id = create.get_json()["game_id"]

    res = client.post(
        f"/api/games/{game_id}/join", json={"player_name": "Sam"}
    )
    assert res.status_code == 201
    card = res.get_json()["card"]

    # 5x5 grid, FREE center, all other cells drawn from our pool.
    assert len(card) == 5 and all(len(row) == 5 for row in card)
    assert card[2][2] == "FREE"
    pool = {e["word"] for e in entries}
    non_free = {cell for row in card for cell in row if cell != "FREE"}
    assert non_free.issubset(pool)


# --- run_call_loop ---------------------------------------------------------


def test_call_loop_persists_descriptions(monkeypatch, app: Flask) -> None:
    """run_call_loop writes descriptions onto Call rows for one iteration.

    Strategy: stub ``socketio.sleep`` to raise after the first call, so
    the loop's broad except catches it and exits cleanly. That gives us
    a deterministic single-iteration run we can assert against. Using
    an exception rather than a status flip avoids cross-context session
    visibility issues with SQLite.
    """
    entries = _entries(30)
    create_res = app.test_client().post(
        "/api/games", json={"game_words": entries}
    )
    game_id = create_res.get_json()["game_id"]

    # Move the game into "active" so run_call_loop's status guard passes.
    with app.app_context():
        game = db.session.get(Game, game_id)
        assert game is not None
        game.status = "active"
        db.session.commit()

    emitted: list[dict] = []

    # Capture socket emits so we can assert the description rides along.
    def fake_emit(event, payload=None, **_kw):
        emitted.append({"event": event, "payload": payload})

    class _StopLoop(Exception):
        """Sentinel exception used only to break the loop in this test."""

    def fake_sleep(_seconds):
        raise _StopLoop

    monkeypatch.setattr(game_engine.socketio, "emit", fake_emit)
    monkeypatch.setattr(game_engine.socketio, "sleep", fake_sleep)

    # Run synchronously — easier to assert against than a real background task.
    game_engine.run_call_loop(app, game_id)

    with app.app_context():
        calls = db.session.scalars(db.select(Call)).all()
        assert len(calls) == 1
        c = calls[0]
        # The word must come from our topic, and its description must
        # match the description we provided for that word.
        assert any(
            e["word"] == c.word and e["description"] == c.description
            for e in entries
        )
        called_word = c.word
        called_desc = c.description

    word_called = [e for e in emitted if e["event"] == "word_called"]
    assert len(word_called) == 1
    payload = word_called[0]["payload"]
    assert payload["word"] == called_word
    assert payload["description"] == called_desc
