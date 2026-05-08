"""Flask entry point for the Virtual Bingo app.

Run locally:
    pip install -r requirements.txt
    python app.py
"""
from flask import Flask

from config import Config


def create_app() -> Flask:
    """Build and return the Flask app.

    Why a factory function: keeps app construction in one place so future
    tests can spin up a fresh app instance without import side effects.
    (Standard Flask pattern.)
    """
    app = Flask(__name__)
    app.config.from_object(Config)

    @app.get("/")
    def index() -> str:
        """Landing page — temporary smoke test until the host UI ships."""
        return "Hello Bingo"

    return app


if __name__ == "__main__":
    app = create_app()
    # debug=True enables auto-reload + verbose errors in dev. Off in prod.
    app.run(host="0.0.0.0", port=Config.PORT, debug=True)
