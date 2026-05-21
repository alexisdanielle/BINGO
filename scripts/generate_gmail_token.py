"""One-time script to generate Gmail OAuth2 credentials for Render.

Run this locally (not on the server) — it opens a browser so you can
authorize the app with your Google account. After you click Allow, it
prints the three values you need to add as Render environment variables.

Usage:
    python scripts/generate_gmail_token.py

Requires credentials.json in the project root (downloaded from Google
Cloud Console → APIs & Services → Credentials).
"""
from __future__ import annotations

from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

# Only requesting send permission — never reads your emails.
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

CREDENTIALS_FILE = Path(__file__).resolve().parent.parent / "credentials.json"


def main() -> None:
    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(
            f"credentials.json not found at {CREDENTIALS_FILE}\n"
            "Download it from Google Cloud Console → APIs & Services → "
            "Credentials → your OAuth client → Download JSON."
        )

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CREDENTIALS_FILE), SCOPES
    )
    # Opens a browser tab for the Google consent screen.
    creds = flow.run_local_server(port=0)

    print("\n✅ Authorization successful! Add these to Render environment variables:\n")
    print(f"GMAIL_CLIENT_ID     = {creds.client_id}")
    print(f"GMAIL_CLIENT_SECRET = {creds.client_secret}")
    print(f"GMAIL_REFRESH_TOKEN = {creds.refresh_token}")
    print(f"GMAIL_SENDER        = kumarjayesh012@gmail.com")
    print("\nDone. You can delete credentials.json after copying these values.")


if __name__ == "__main__":
    main()
