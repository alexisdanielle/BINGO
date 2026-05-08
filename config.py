"""Application configuration loaded from environment variables.

Why a class: ``app.config.from_object(Config)`` copies every uppercase
attribute into Flask's config dict — the standard Flask pattern.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
# Make sure the instance dir exists before SQLite tries to write into it.
INSTANCE_DIR.mkdir(exist_ok=True)


class Config:
    """Settings read from environment with safe defaults for local dev."""

    SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    PORT: int = int(os.environ.get("PORT", "5000"))

    # ``sqlite:///<absolute path>`` is the SQLAlchemy convention for a
    # file-backed SQLite database. Named ``SQLALCHEMY_DATABASE_URI`` because
    # that is the exact key Flask-SQLAlchemy reads from ``app.config``.
    SQLALCHEMY_DATABASE_URI: str = os.environ.get(
        "DATABASE_URL", f"sqlite:///{INSTANCE_DIR / 'bingo.db'}"
    )

    # Default seconds between auto-called words. Per decision D4 each game
    # can override this; this is just the fallback.
    DEFAULT_CALL_INTERVAL_SECONDS: int = int(
        os.environ.get("DEFAULT_CALL_INTERVAL_SECONDS", "5")
    )

    # Optional. Only the AI announcement layer (built last) reads this. The
    # game must work fine when it's unset.
    ANTHROPIC_API_KEY: str | None = os.environ.get("ANTHROPIC_API_KEY")
