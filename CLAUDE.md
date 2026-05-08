# Virtual Bingo Game — Project Context

## Project background

This is a CGI co-op project. The goal is to automate a currently manual virtual bingo process used internally by a CGI team. Three co-op groups are each building independent solutions; ours will be compared against the others, so we want it to be solid, demo-able, and explainable.

I am a co-op student. I am learning as I build this. When you write code, prefer clarity over cleverness — I need to be able to read, understand, and explain every line to my mentors. If you use an unfamiliar pattern or library, leave a brief comment explaining why.

## What the system does

The current manual process:
- Host generates bingo cards on a third-party site (MyFreeBingoCards)
- Host emails individual cards to each participant
- Host runs a Microsoft Teams meeting and calls out words verbally
- A team member manually types called words into Teams chat
- Players mark their own cards by hand
- Players announce "Bingo" via voice or chat
- Host manually verifies the winning card
- Top 3 winners get gift cards via email

We are replacing this with a single web app that handles card generation, distribution, calling, marking, win detection, leaderboard, and audit trail in one place.

## Tech stack (locked in — do not switch without asking)

- **Backend:** Python 3.11+ with Flask
- **Real-time:** Flask-SocketIO (WebSockets)
- **Database:** SQLite (single file, easy to demo)
- **Frontend:** Vanilla HTML/CSS/JavaScript — no React, no build step, no npm
- **Text-to-speech:** Browser SpeechSynthesis API (free, no keys needed) for v1; can swap to ElevenLabs later
- **Optional AI layer:** Anthropic Claude API for generating fun word announcements (added last, must be optional — game must work without it)

Reason for these choices: I want to be able to demo this on any laptop without a complicated setup, and I want to be able to explain every dependency.

## Coding standards

- Python: follow PEP 8, use type hints on function signatures, use `snake_case`
- Keep functions short and focused — one job per function
- Add docstrings to every function and class explaining what it does and why
- Comments should explain *why*, not *what* (the code already shows what)
- No silent exception swallowing — log or re-raise
- Use `pathlib.Path` instead of `os.path` for file paths

## Project structure

```
virtual-bingo/
├── CLAUDE.md            # this file
├── README.md            # how to run the project
├── requirements.txt     # Python dependencies
├── app.py               # Flask entry point
├── config.py            # configuration (port, DB path, etc.)
├── models.py            # SQLAlchemy models
├── game/
│   ├── __init__.py
│   ├── card_generator.py   # creates unique 5x5 bingo cards
│   ├── game_engine.py      # game state, calling words, win detection
│   └── patterns.py         # winning pattern definitions
├── routes/
│   ├── __init__.py
│   ├── host_routes.py      # endpoints for the host
│   └── player_routes.py    # endpoints for players
├── sockets.py           # WebSocket event handlers
├── static/
│   ├── css/style.css
│   └── js/
│       ├── host.js
│       └── player.js
├── templates/
│   ├── base.html
│   ├── host.html
│   └── player.html
└── tests/
    ├── test_card_generator.py
    ├── test_game_engine.py
    └── test_patterns.py
```

## Database schema (proposed — confirm before building)

- **games**: id, host_name, pattern, status (waiting/active/finished), created_at, started_at, finished_at
- **cards**: id, game_id, player_name, card_data (JSON: 5x5 grid), join_token
- **calls**: id, game_id, word, called_at (audit trail of every word called)
- **wins**: id, game_id, card_id, place (1/2/3), declared_at, validated

## Game rules (from the BRD)

- Each player uses only the card assigned to them
- Wins are auto-validated by the system (server checks the card against the called words)
- Only the first three valid winners get prizes
- Players click a "Bingo" button to claim a win
- Game continues until 1st, 2nd, and 3rd place are filled
- Patterns supported: horizontal line, vertical line, diagonal, full house

## How I want you to work

1. **Plan before coding.** When I give you a new feature, propose the approach in plain English first. Wait for me to say "go" before writing code.
2. **Build in layers.** Don't try to ship the whole feature at once. Backend logic first, then API, then UI, then polish.
3. **Test as you go.** Write a quick pytest for any non-trivial logic (card generation, win detection). Run it before moving on.
4. **Commit often.** After every working layer, suggest a git commit message and stop.
5. **Stop and ask if unsure.** If I haven't given you enough info, ask. Don't guess and build the wrong thing.
6. **Explain new concepts briefly.** If you use a library or pattern I might not know (e.g., decorators, context managers, SocketIO rooms), drop a 1-2 sentence explanation in a comment.

## What NOT to do

- Don't add dependencies without asking (especially heavy ones like React, Vue, Django)
- Don't refactor working code unless I ask
- Don't build the AI announcement layer until the core game works end-to-end
- Don't use `os.system` or shell=True for subprocess calls
- Don't hardcode secrets — use environment variables (we'll set up a `.env` later)

## Demo scenario I need to support

A CGI mentor opens the host page, creates a game, and gets a join link. They share the link with 3-5 reviewers who each open it on their own device and enter a name. The host picks "horizontal line" as the pattern and clicks Start. The system calls a word every 5 seconds, the word appears on screen and is spoken aloud. Players click squares as words are called. When someone completes a line, they click "Bingo!" — the system validates it server-side and adds them to the leaderboard. After 3 winners, the game ends and shows the final leaderboard.

This is the happy path. Build for this first; edge cases later.
