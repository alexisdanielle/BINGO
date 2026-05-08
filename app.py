"""Flask entry point for the Virtual Bingo app.

Run locally:
    pip install -r requirements.txt
    python app.py
"""
from __future__ import annotations

from flask import Flask

from config import Config
from models import db, init_db


def create_app(test_config: dict | None = None) -> Flask:
    """Build and return the Flask app.

    Why a factory function: keeps app construction in one place so tests
    can spin up a fresh app instance without import side effects. Tests
    pass ``test_config`` to swap in a throwaway DB URI.
    (Standard Flask pattern.)
    """
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        # Apply overrides AFTER from_object so tests can replace DB URI etc.
        app.config.update(test_config)

    # Bind SQLAlchemy to this app, then create any missing tables.
    db.init_app(app)
    init_db(app)

    @app.get("/")
    def index() -> str:
        """Landing page — temporary smoke test until the host UI ships."""
        return "Hello Bingo"

    return app


if __name__ == "__main__":
    app = create_app()
    # debug=True enables auto-reload + verbose errors in dev. Off in prod.
    app.run(host="0.0.0.0", port=Config.PORT, debug=True)
