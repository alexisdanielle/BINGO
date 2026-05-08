# Virtual Bingo

A web app that replaces the manual virtual bingo workflow (third-party cards + Teams chat + manual verification) with a single tool. See `CLAUDE.md` for the full project context, scope, and decisions.

## Requirements

- Python 3.11 or newer

## Setup

Create a virtual environment and install dependencies.

**Windows (PowerShell):**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```
python app.py
```

The server listens on http://localhost:5000.

- Visit `/` to open the **host UI** — create a game, share the join link, start the round.
- Visit `/play?game_id=<id>` to open the **player UI** — enter a name, get a card, click cells to mark, hit BINGO! when you have a winning pattern.

## Tests

```
pytest
```

## Configuration

Settings come from environment variables, with sensible defaults for local dev:

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | `dev-secret-change-me` | Flask session signing |
| `PORT` | `5000` | HTTP port |
| `DEFAULT_CALL_INTERVAL_SECONDS` | `5` | Auto-call cadence (per game) |
| `ANTHROPIC_API_KEY` | _(unset)_ | Optional, for AI announcements (added later) |

To override locally, set the variable in your shell before running:

```powershell
$env:PORT = "5050"
python app.py
```

## Project layout

See `CLAUDE.md` for the full target structure. Files are added step by step as features land; expect the tree to grow.
