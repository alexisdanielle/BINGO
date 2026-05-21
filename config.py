"""Application configuration loaded from environment variables.

Why a class: ``app.config.from_object(Config)`` copies every uppercase
attribute into Flask's config dict — the standard Flask pattern.
"""
import os
from pathlib import Path

# Load .env before the Config class is defined so every os.environ.get()
# below sees the values from the file. override=True makes .env win over
# any stale shell-exported variables of the same name.
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

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

    # --- Email / OTP authentication ----------------------------------------
    # Gmail SMTP credentials. Create an App Password at:
    # myaccount.google.com → Security → App Passwords
    SMTP_USER: str | None = os.environ.get("SMTP_USER")
    SMTP_PASSWORD: str | None = os.environ.get("SMTP_PASSWORD")
    # OTP expires this many minutes after being sent.
    OTP_EXPIRY_MINUTES: int = int(os.environ.get("OTP_EXPIRY_MINUTES", "10"))
    # Optional domain restriction — when empty, any email domain is accepted.
    # Set CGI_EMAIL_DOMAIN=cgi.com in .env to re-enable the domain check.
    CGI_EMAIL_DOMAIN: str = os.environ.get("CGI_EMAIL_DOMAIN", "")
