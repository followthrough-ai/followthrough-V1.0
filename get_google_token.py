"""One-time Google sign-in: reads credentials.json, opens a browser, saves token.json.

Run from PowerShell:  python get_google_token.py
"""
from pathlib import Path
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/contacts.readonly",
]

HERE = Path(__file__).resolve().parent
CREDENTIALS = HERE / "credentials.json"
TOKEN = HERE / "token.json"

if not CREDENTIALS.exists():
    sys.exit(f"credentials.json not found. Download it from Google Cloud Console and save it as:\n  {CREDENTIALS}")

flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS), SCOPES)
creds = flow.run_local_server(port=0)
TOKEN.write_text(creds.to_json())
print(f"Saved {TOKEN}")
