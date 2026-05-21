"""Production WSGI entry point for Render (and any gunicorn deployment).

Gevent monkey-patching MUST happen before any other import — it swaps
out Python's standard socket/threading modules with green (async) versions
so WebSocket upgrades work correctly under gunicorn's gevent worker.
"""
from gevent import monkey
monkey.patch_all()

from app import create_app  # noqa: E402  (import after monkey-patch is intentional)

app = create_app()
