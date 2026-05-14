"""Tests for ``game.topic_generator``.

Strategy: monkeypatch ``llm_client.generate`` so no real LLM is called.
Each test uses a Flask app pointed at a throwaway SQLite file so the
Topic cache starts empty.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from flask import Flask

from app import create_app
from game import topic_generator
from game.card_generator import generate_card
from game.topic_generator import (
    TopicGenerationError,
    generate_word_list,
)
from models import Topic, db


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    """Throwaway Flask app + SQLite DB per test (mirrors test_models.py)."""
    db_path = tmp_path / "test.db"
    return create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
        }
    )


def _fake_llm_response(entries: list[dict]) -> str:
    """JSON-encode entries the way llm_client would hand them back."""
    return json.dumps(entries)


def _patch_llm(monkeypatch, response: str | list[str]):
    """Replace ``llm_client.generate`` with a MagicMock returning ``response``.

    ``response`` is either a single JSON string (returned each call) or a
    list (one per call, in order). Returns the mock so tests can assert
    on call count / args.
    """
    mock = MagicMock()
    if isinstance(response, list):
        mock.side_effect = response
    else:
        mock.return_value = response
    monkeypatch.setattr(topic_generator.llm_client, "generate", mock)
    return mock


def test_generate_word_list_parses_and_stores(monkeypatch, app: Flask) -> None:
    """First call: LLM is invoked, response is parsed, Topic row is saved."""
    entries = [
        {"word": "Quebec", "description": "A French-speaking province of Canada."},
        {"word": "Toronto", "description": "The largest city in Canada by population."},
    ]
    mock_llm = _patch_llm(monkeypatch, _fake_llm_response(entries))

    with app.app_context():
        result = generate_word_list("Canada", count=2)

        assert result == entries
        mock_llm.assert_called_once()
        # JSON mode is required so the parser can do its job.
        kwargs = mock_llm.call_args.kwargs
        assert kwargs.get("response_format") == "json"

        # Row was persisted with the normalized name and zero usage so
        # far (the *creating* call is not counted as a "hit").
        stored = db.session.scalar(
            db.select(Topic).where(Topic.topic_name == "canada")
        )
        assert stored is not None
        assert stored.generated_words == entries
        assert stored.times_used == 0


def test_cache_hit_skips_llm_and_increments_times_used(
    monkeypatch, app: Flask
) -> None:
    """Second call for the same topic returns the cached list without LLM."""
    entries = [
        {"word": "Quebec", "description": "A French-speaking province of Canada."},
    ]
    mock_llm = _patch_llm(monkeypatch, _fake_llm_response(entries))

    with app.app_context():
        first = generate_word_list("Canada")
        # Same topic, different casing/whitespace → should still hit cache.
        second = generate_word_list("  canada  ")
        third = generate_word_list("CANADA")

        assert first == second == third == entries
        # LLM was called exactly once (the initial miss).
        assert mock_llm.call_count == 1

        stored = db.session.scalar(
            db.select(Topic).where(Topic.topic_name == "canada")
        )
        assert stored is not None
        # Two cache hits after the initial miss.
        assert stored.times_used == 2


def test_card_generator_works_with_topic_words(monkeypatch, app: Flask) -> None:
    """The output of generate_word_list feeds generate_card cleanly."""
    # 30 distinct words is more than the 24 a 5x5 card needs.
    entries = [
        {"word": f"Word{i}", "description": f"Description number {i}."}
        for i in range(30)
    ]
    _patch_llm(monkeypatch, _fake_llm_response(entries))

    with app.app_context():
        words = generate_word_list("anything", count=30)
        word_pool = [w["word"] for w in words]

        card = generate_card(word_pool, seed=42)

        # 5x5 with FREE center; the other 24 cells are drawn from our pool.
        assert len(card) == 5 and all(len(row) == 5 for row in card)
        assert card[2][2] == "FREE"
        flat = {cell for row in card for cell in row if cell != "FREE"}
        assert flat.issubset(set(word_pool))
        assert len(flat) == 24


def test_dedupes_and_drops_malformed_entries(monkeypatch, app: Flask) -> None:
    """LLMs occasionally return dups or junk — we clean them out."""
    entries = [
        {"word": "Quebec", "description": "First desc."},
        # Duplicate (case-insensitive) — dropped.
        {"word": "quebec", "description": "Second desc."},
        # Missing description — dropped.
        {"word": "Ontario"},
        # Wrong shape entirely — dropped.
        "not a dict",
        # Empty strings — dropped.
        {"word": "", "description": "x"},
        {"word": "Alberta", "description": "Valid one."},
    ]
    _patch_llm(monkeypatch, _fake_llm_response(entries))

    with app.app_context():
        result = generate_word_list("Canada")

        assert [e["word"] for e in result] == ["Quebec", "Alberta"]


def test_empty_topic_rejected(monkeypatch, app: Flask) -> None:
    """Empty / whitespace-only topic names raise before touching the LLM."""
    mock_llm = _patch_llm(monkeypatch, _fake_llm_response([]))

    with app.app_context():
        with pytest.raises(ValueError, match="non-empty"):
            generate_word_list("   ")

    mock_llm.assert_not_called()


def test_non_array_response_raises(monkeypatch, app: Flask) -> None:
    """If the LLM returns a JSON object instead of an array, raise clearly."""
    _patch_llm(monkeypatch, json.dumps({"words": ["a", "b"]}))

    with app.app_context():
        with pytest.raises(TopicGenerationError, match="array"):
            generate_word_list("anything")


def test_all_entries_malformed_raises(monkeypatch, app: Flask) -> None:
    """If cleaning removes every entry, surface a clear error."""
    _patch_llm(
        monkeypatch,
        _fake_llm_response([{"word": ""}, "junk", {"description": "x"}]),
    )

    with app.app_context():
        with pytest.raises(TopicGenerationError, match="no usable"):
            generate_word_list("anything")


def test_created_by_email_stored(monkeypatch, app: Flask) -> None:
    """When the host email is passed in, it lands on the Topic row."""
    entries = [{"word": "Maple", "description": "An iconic Canadian tree."}]
    _patch_llm(monkeypatch, _fake_llm_response(entries))

    with app.app_context():
        generate_word_list("Canada", created_by_email="alex@example.com")

        stored = db.session.scalar(
            db.select(Topic).where(Topic.topic_name == "canada")
        )
        assert stored is not None
        assert stored.created_by_email == "alex@example.com"
