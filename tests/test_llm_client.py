"""Tests for ``game.llm_client``.

These tests replace ``google.generativeai`` with a fake module in
``sys.modules`` so the real SDK doesn't need to be installed and no
network call is made. The fake is wired through monkeypatch fixtures
so each test gets a fresh, isolated copy.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from game import llm_client


def _install_fake_gemini(monkeypatch, response_text):
    """Replace ``google.generativeai`` with a controllable fake.

    ``response_text`` is either a single string (returned every call)
    or a list of strings (one per call, in order). The list form lets
    JSON-retry tests serve a bad response followed by a good one.

    Returns the fake module and the fake model object so individual
    tests can assert on call args.
    """
    fake_genai = types.ModuleType("google.generativeai")
    fake_genai.configure = MagicMock()

    fake_model = MagicMock()
    if isinstance(response_text, list):
        # ``SimpleNamespace`` lets us mimic Gemini's response shape
        # (``response.text``) without pulling in the real types.
        fake_model.generate_content.side_effect = [
            types.SimpleNamespace(text=t) for t in response_text
        ]
    else:
        fake_model.generate_content.return_value = types.SimpleNamespace(
            text=response_text
        )

    fake_genai.GenerativeModel = MagicMock(return_value=fake_model)

    # Stuff a ``google`` placeholder in too, in case the real package
    # isn't installed — the import machinery checks the parent package
    # before resolving the submodule.
    if "google" not in sys.modules:
        monkeypatch.setitem(sys.modules, "google", types.ModuleType("google"))
    monkeypatch.setitem(sys.modules, "google.generativeai", fake_genai)
    return fake_genai, fake_model


@pytest.fixture
def gemini_env(monkeypatch):
    """Only GEMINI_API_KEY is set — Anthropic/OpenAI cleared explicitly.

    Tests inherit the developer's real env otherwise; clearing the
    others guarantees the priority logic actually picks Gemini.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def test_text_mode_returns_raw_response(monkeypatch, gemini_env):
    _, fake_model = _install_fake_gemini(monkeypatch, "hello world")

    result = llm_client.generate("say hello")

    assert result == "hello world"
    fake_model.generate_content.assert_called_once_with("say hello")


def test_uses_configured_model_and_api_key(monkeypatch, gemini_env):
    fake_genai, _ = _install_fake_gemini(monkeypatch, "ok")

    llm_client.generate("ping")

    fake_genai.GenerativeModel.assert_called_once_with("gemini-2.5-flash")
    fake_genai.configure.assert_called_once_with(api_key="test-key")


def test_json_mode_accepts_unfenced_response(monkeypatch, gemini_env):
    _install_fake_gemini(monkeypatch, '{"word": "apple"}')

    result = llm_client.generate("give me a word", response_format="json")

    assert result == '{"word": "apple"}'


def test_json_mode_strips_json_labeled_fence(monkeypatch, gemini_env):
    _install_fake_gemini(
        monkeypatch,
        '```json\n{"word": "apple"}\n```',
    )

    result = llm_client.generate("give me a word", response_format="json")

    assert result == '{"word": "apple"}'


def test_json_mode_strips_unlabeled_fence(monkeypatch, gemini_env):
    _install_fake_gemini(
        monkeypatch,
        '```\n{"word": "apple"}\n```',
    )

    result = llm_client.generate("give me a word", response_format="json")

    assert result == '{"word": "apple"}'


def test_json_mode_strips_fence_with_chatter_around_it(
    monkeypatch, gemini_env
):
    # Real-world Gemini outputs sometimes have a prose sentence before
    # the fence. The regex grabs the fenced block regardless.
    _install_fake_gemini(
        monkeypatch,
        'Here you go:\n```json\n{"word": "apple"}\n```\nLet me know!',
    )

    result = llm_client.generate("give me a word", response_format="json")

    assert result == '{"word": "apple"}'


def test_json_mode_retries_once_on_parse_failure(monkeypatch, gemini_env):
    _, fake_model = _install_fake_gemini(
        monkeypatch,
        ["not json at all", '{"word": "apple"}'],
    )

    result = llm_client.generate("give me a word", response_format="json")

    assert result == '{"word": "apple"}'
    assert fake_model.generate_content.call_count == 2


def test_json_mode_raises_after_two_bad_responses(monkeypatch, gemini_env):
    _install_fake_gemini(monkeypatch, ["still not json", "also bad"])

    with pytest.raises(ValueError, match="valid JSON"):
        llm_client.generate("give me a word", response_format="json")


def test_invalid_response_format_raises(monkeypatch, gemini_env):
    _install_fake_gemini(monkeypatch, "anything")

    with pytest.raises(ValueError, match="response_format"):
        llm_client.generate("hi", response_format="yaml")  # type: ignore[arg-type]


def test_raises_clear_error_when_no_key_set(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(llm_client.LLMConfigError, match="No LLM provider"):
        llm_client.generate("anything")


def test_gemini_takes_priority_when_multiple_keys_set(monkeypatch):
    # All three keys present. Gemini wins per the priority order.
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    _install_fake_gemini(monkeypatch, "gemini wins")

    assert llm_client.generate("?") == "gemini wins"


def test_anthropic_stub_raises_not_implemented(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(NotImplementedError, match="Anthropic"):
        llm_client.generate("?")


def test_openai_stub_raises_not_implemented(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "o")

    with pytest.raises(NotImplementedError, match="OpenAI"):
        llm_client.generate("?")
