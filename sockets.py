"""Flask-SocketIO singleton and connection-management handlers.

The singleton ``socketio`` is bound to a Flask app via ``init_app`` in
``create_app``. HTTP routes and the background call loop import this
same instance to broadcast events, so all socket I/O routes through
one place.

Broadcast events emitted from elsewhere (rooms keyed ``game:<id>``):
    player_joined  — player joined a waiting game
    game_started   — host moved a game to active
    word_called    — runner called a new word
    win_declared   — player's bingo claim was validated
    game_ended     — third winner, or pool exhausted
"""
from __future__ import annotations

from flask_socketio import SocketIO, join_room

# Module-level singleton. Bound to the Flask app in create_app().
socketio = SocketIO()


@socketio.on("join_game_room")
def on_join_game_room(data: dict | None) -> None:
    """Subscribe this client to its game's broadcast room.

    Per v1 design, every game has a SocketIO room named ``game:<id>``.
    The client emits this event after connecting so it receives only
    the events for the game it actually cares about.
    """
    if not isinstance(data, dict):
        return
    game_id = data.get("game_id")
    if game_id is None:
        return
    join_room(f"game:{game_id}")
