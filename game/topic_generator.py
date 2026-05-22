"""Generate themed bingo word lists for a topic, with DB-backed caching.

A "topic" is a free-text string the host enters (e.g. ``"CGI history"``).
We ask the active LLM (via :mod:`game.llm_client`) for ``count`` distinct
words plus a short factual description for each, then cache the result in
the ``topics`` table so the next request for the same topic skips the
LLM entirely.

Cache key is the *normalized* topic name (lowercased + stripped) so
``"CGI"`` and ``" cgi "`` share one row. We bump ``times_used`` on every
cache hit so we can see which topics are popular later.

Per-game edits to the word list (regenerate, edit, delete) do *not* feed
back into this cache — the cached row is the canonical generated list;
per-game tweaks live on ``games.game_words`` instead.
"""
from __future__ import annotations

import json
import logging

from game import llm_client
from models import Topic, db

log = logging.getLogger(__name__)


# Ask for 45 so even when the LLM returns slightly fewer than requested
# (common behaviour) the host still gets ~40+ words to work with without
# needing to add any manually.
DEFAULT_COUNT = 45


class TopicGenerationError(RuntimeError):
    """Raised when the LLM response can't be parsed into a word list."""


def _normalize(topic: str) -> str:
    """Lowercase + strip whitespace for case-insensitive cache lookup.

    Kept tiny and pure so tests can pin the exact key shape.
    """
    return topic.strip().lower()


def _build_prompt(topic: str, count: int) -> str:
    """Construct the JSON-mode prompt sent to the LLM.

    We ask explicitly for a JSON *array* (not an object containing one)
    so the response is unambiguous to parse, and pin the field names to
    ``word`` and ``description`` to match what callers expect.
    """
    return (
        f"Generate exactly {count} distinct bingo words about the topic: "
        f'"{topic}".\n\n'
        "Respond with a JSON array. Each element must be an object with:\n"
        '  - "word": a short term (1-3 words) related to the topic\n'
        '  - "description": a factual, educational sentence about that '
        "word, roughly 15 words long\n\n"
        "All words must be distinct (case-insensitive) and clearly on-topic. "
        "Do not include commentary, markdown, or any text outside the JSON "
        "array."
    )


def _clean_entries(raw: list) -> list[dict]:
    """Validate, normalize, and dedupe the parsed LLM response.

    Drops malformed entries, trims whitespace, and keeps only the first
    occurrence of each word (case-insensitive). We tolerate small LLM
    quirks rather than failing the whole call: returning fewer-than-asked
    words is fine, returning zero is not.

    Raises:
        TopicGenerationError: ``raw`` isn't a list, or no valid entries
            survive cleaning.
    """
    if not isinstance(raw, list):
        raise TopicGenerationError(
            f"expected a JSON array, got {type(raw).__name__}"
        )

    seen: set[str] = set()
    cleaned: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        word = entry.get("word")
        description = entry.get("description")
        if not isinstance(word, str) or not isinstance(description, str):
            continue
        word = word.strip()
        description = description.strip()
        if not word or not description:
            continue
        key = word.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({"word": word, "description": description})

    if not cleaned:
        raise TopicGenerationError(
            "LLM response had no usable {word, description} entries"
        )
    return cleaned


def generate_word_list(
    topic: str,
    count: int = DEFAULT_COUNT,
    created_by_email: str | None = None,
) -> list[dict]:
    """Return a list of ``{"word", "description"}`` dicts for ``topic``.

    Cache behavior:
        * If a ``Topic`` row with the normalized name already exists, the
          stored list is returned and ``times_used`` is incremented.
          The LLM is *not* called.
        * Otherwise the LLM is prompted, the response is parsed/cleaned,
          a new Topic row is inserted, and the cleaned list is returned.

    Args:
        topic: free-text topic name from the host.
        count: how many words to ask the LLM for. Ignored on cache hit
            (we return whatever was stored).
        created_by_email: optional email of the host who first triggered
            generation. Stored on the Topic row but not used for lookup.

    Raises:
        ValueError: ``topic`` is empty after normalization.
        TopicGenerationError: LLM response couldn't be parsed into a
            usable list (after llm_client's own one retry).
    """
    name = _normalize(topic)
    if not name:
        raise ValueError("topic must be a non-empty string")

    # SQLAlchemy 2.0 style: ``db.session.scalar(select(...))`` is the
    # idiomatic replacement for the deprecated ``Query.filter_by().first()``.
    existing = db.session.scalar(
        db.select(Topic).where(Topic.topic_name == name)
    )
    if existing is not None:
        existing.times_used += 1
        db.session.commit()
        log.info("topic cache hit: %r (times_used=%s)", name, existing.times_used)
        return list(existing.generated_words)

    prompt = _build_prompt(topic, count)
    raw_json = llm_client.generate(prompt, response_format="json")
    # llm_client guarantees raw_json is parseable JSON; it doesn't
    # interpret the shape, so we do that here.
    parsed = json.loads(raw_json)
    cleaned = _clean_entries(parsed)

    topic_row = Topic(
        topic_name=name,
        generated_words=cleaned,
        created_by_email=created_by_email,
        times_used=0,
    )
    db.session.add(topic_row)
    db.session.commit()
    log.info("topic cache miss: stored new topic %r with %d words", name, len(cleaned))
    return cleaned
