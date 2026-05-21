"""Production WSGI entry point for Render (and any gunicorn deployment).

Eventlet monkey-patching MUST happen before any other import — it swaps
out Python's standard socket/threading modules with green (async) versions
so WebSocket upgrades work correctly under gunicorn's eventlet worker.
"""
import eventlet
eventlet.monkey_patch()

from app import create_app  # noqa: E402  (import after monkey-patch is intentional)

app = create_app()
