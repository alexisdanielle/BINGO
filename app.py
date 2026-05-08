"""Flask entry point for the Virtual Bingo app.

Run locally:
    pip install -r requirements.txt
    python app.py
"""
from __future__ import annotations

from flask import Flask

from config import Config
from models import db, init_db
from sockets import socketio


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
        app.config.update(test_config)

    # Bind SQLAlchemy + SocketIO to this app, then create any missing tables.
    # ``async_mode="threading"`` keeps things simple — no eventlet/gevent
    # required, just real Python threads for the per-game call loops.
    db.init_app(app)
    init_db(app)
    socketio.init_app(app, cors_allowed_origins="*", async_mode="threading")

    # Register HTTP route blueprints. Imported here (not at module top)
    # to avoid circular imports — the route modules reference ``socketio``
    # and ``db`` which are defined above.
    from routes.host_routes import host_bp
    from routes.player_routes import player_bp

    app.register_blueprint(host_bp)
    app.register_blueprint(player_bp)

    # Side-effect import: triggers the @socketio.on decorators in
    # sockets.py. Game-engine and routes already import sockets, so this
    # is belt-and-suspenders, but it's the explicit place to wire it.
    import sockets  # noqa: F401

    @app.get("/")
    def index() -> str:
        """Landing page — temporary smoke test until the host UI ships."""
        return "Hello Bingo"

    return app


if __name__ == "__main__":
    app = create_app()
    # ``socketio.run`` starts a WebSocket-aware dev server. Reloader is
    # off so per-game background loops aren't spawned twice on file
    # changes. ``allow_unsafe_werkzeug`` opts into Werkzeug for the dev
    # server (Flask-SocketIO refuses it otherwise as a prod safeguard).
    socketio.run(
        app,
        host="0.0.0.0",
        port=Config.PORT,
        debug=False,
        allow_unsafe_werkzeug=True,
    )
