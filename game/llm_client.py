"""Provider-agnostic LLM client used by the iteration 2 topic generator.

Every LLM call in the app goes through :func:`generate` so callers don't
care which provider is active. The provider is chosen at runtime by
which ``*_API_KEY`` env var is set, in priority order:

    1. ``GEMINI_API_KEY``    -> google-generativeai (gemini-2.5-flash)
    2. ``ANTHROPIC_API_KEY`` -> NotImplementedError (planned)
    3. ``OPENAI_API_KEY``    -> NotImplementedError (planned)

Only Gemini is wired up in iteration 2; Anthropic and OpenAI are stubs
we'll fill in later. We chose Gemini first because it has a free tier
suitable for the co-op demo.

Why ``python-dotenv``: loading ``.env`` at import keeps the rest of the
code free of bootstrap calls — anyone who imports this module
automatically has env vars populated, same convention Flask uses.
"""
from __future__ import annotations

import json
import os
import re
from typing import Callable, Literal

# python-dotenv reads a local ``.env`` file into ``os.environ`` (it
# leaves existing env vars alone). Side-effecting at import matches the
# rest of config.py's pattern. We tolerate the package being missing —
# if env vars are set another way (shell export, CI secret) we still
# work; ``.env`` is just a developer convenience.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


# Pinned per the iteration 2 spec. Bump deliberately, not silently.
GEMINI_MODEL = "gemini-2.5-flash"


# Matches ```json ... ``` or plain ``` ... ``` wrappers that some models
# add when asked for JSON. ``re.DOTALL`` lets ``.`` match newlines so the
# whole block is captured.
_FENCE_RE = re.compile(
    r"```(?:json)?\s*(.*?)\s*```",
    re.DOTALL | re.IGNORECASE,
)


class LLMConfigError(RuntimeError):
    """Raised when no LLM provider env var is set."""


def _active_provider() -> str:
    """Return the first provider whose API key is in the environment.

    Order is fixed (Gemini first) so behavior is deterministic when
    multiple keys are set — useful for testing and for the eventual
    Teams sideload where the demo machine may carry leftover keys.
    """
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    raise LLMConfigError(
        "No LLM provider configured. Set one of GEMINI_API_KEY, "
        "ANTHROPIC_API_KEY, or OPENAI_API_KEY in your environment "
        "(or in .env)."
    )


def _call_gemini(prompt: str) -> str:
    """Send ``prompt`` to Gemini and return the response text.

    Lazy import: keeps ``google.generativeai`` out of the module's
    import-time cost and lets the test suite swap in a fake module
    via ``sys.modules`` without needing the real SDK installed.
    """
    import google.generativeai as genai

    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model = genai.GenerativeModel(GEMINI_MODEL)
    response = model.generate_content(prompt)
    return response.text


def _call_anthropic(prompt: str) -> str:
    raise NotImplementedError(
        "Anthropic provider is not wired up yet. Use GEMINI_API_KEY for now."
    )


def _call_openai(prompt: str) -> str:
    raise NotImplementedError(
        "OpenAI provider is not wired up yet. Use GEMINI_API_KEY for now."
    )


_PROVIDERS: dict[str, Callable[[str], str]] = {
    "gemini": _call_gemini,
    "anthropic": _call_anthropic,
    "openai": _call_openai,
}


def _strip_fences(text: str) -> str:
    """If ``text`` is wrapped in a ``` code fence, return the inner content.

    Returns the original text trimmed of surrounding whitespace when no
    fence is found. Models are inconsistent about fences even when told
    not to add them — stripping defensively beats prompt-tuning forever.
    """
    match = _FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


def generate(
    prompt: str,
    response_format: Literal["text", "json"] = "text",
) -> str:
    """Call the active LLM provider and return its response as a string.

    Args:
        prompt: prompt text sent verbatim to the model.
        response_format: ``"text"`` (default) returns the raw response.
            ``"json"`` strips any code fence, validates the result
            parses as JSON, and retries the *call* once if it doesn't
            (a fresh sample is the only thing that might fix a bad
            response; re-parsing the same string won't). Returns the
            cleaned JSON string — the caller does ``json.loads`` itself.

    Raises:
        LLMConfigError: no provider env var is set.
        NotImplementedError: configured provider is a stub.
        ValueError: ``response_format='json'`` and both attempts failed
            to produce parseable JSON, or ``response_format`` is not one
            of the two supported values.
    """
    provider = _active_provider()
    call = _PROVIDERS[provider]

    if response_format == "text":
        return call(prompt)

    if response_format != "json":
        raise ValueError(
            f"response_format must be 'text' or 'json', got "
            f"{response_format!r}"
        )

    last_error: Exception | None = None
    last_raw: str = ""
    # Two attempts total: original + one retry on parse failure.
    for _ in range(2):
        raw = call(prompt)
        cleaned = _strip_fences(raw)
        try:
            json.loads(cleaned)
        except json.JSONDecodeError as e:
            last_error = e
            last_raw = raw
            continue
        return cleaned

    raise ValueError(
        f"LLM did not return valid JSON after retry. "
        f"Last parse error: {last_error}. "
        f"Last raw response: {last_raw!r}"
    )
