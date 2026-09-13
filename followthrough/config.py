"""Central configuration. Credentials come from environment variables, or from a
.env file in the project root (real environment variables take precedence).

REQUIRED FOR REAL MODE (mock mode needs none of these):
  GROQ_API_KEY           - LLM for the three reasoning agents (Groq, `pip install groq`)
  GRANOLA_API_KEY        - Granola transcript ingestion (grn_...)
  GOOGLE_CREDENTIALS_JSON- path to OAuth desktop client JSON (Gmail + Calendar)
  GOOGLE_TOKEN_JSON      - path to stored OAuth token (python get_google_token.py)
  SLACK_BOT_TOKEN        - xoxb-... bot token
  AIRTABLE_API_KEY       - personal access token (pat...)
  AIRTABLE_BASE_ID       - app...
  AIRTABLE_TABLE_NAME    - e.g. "Deals"
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = ROOT / "fixtures"
RUNS_DIR = ROOT / "runs"
SCHEMAS_DIR = ROOT / "schemas"

def _load_dotenv(path: Path):
    """Minimal .env reader (stdlib only). Existing environment variables win."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        val = val.strip()
        if val[:1] in ("'", '"') and val[-1:] == val[:1]:
            val = val[1:-1]
        else:
            val = val.split(" #", 1)[0].strip()   # inline comment
        os.environ.setdefault(key.strip(), val)

_load_dotenv(ROOT / ".env")

def _project_path(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else ROOT / path

# --- mode -------------------------------------------------------------------
# "mock"  : deterministic in-memory apps, safe for eval (default)
# "real"  : allows `run.py live` to perform real actions (emails, posts, edits)
MODE = os.getenv("FOLLOWTHROUGH_MODE", "mock")

# --- LLM --------------------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_REASONING_EFFORT = os.getenv("GROQ_REASONING_EFFORT", "medium")
# Low temperature keeps commitment extraction consistent from run to run.
GROQ_TEMPERATURE = float(os.getenv("GROQ_TEMPERATURE", "0.2"))
# Groq's free tier allows 8000 tokens/minute; long transcripts are split and paced to fit.
GROQ_TPM_LIMIT = int(os.getenv("GROQ_TPM_LIMIT", "8000"))
GROQ_CHUNK_CHARS = int(os.getenv("GROQ_CHUNK_CHARS", "16000"))

# --- Real integration endpoints (update-if-needed list is in README) --------
GRANOLA_API_KEY = os.getenv("GRANOLA_API_KEY", "")
GRANOLA_API_URL = os.getenv("GRANOLA_API_URL", "https://public-api.granola.ai/v1")

GOOGLE_CREDENTIALS_JSON = _project_path(os.getenv("GOOGLE_CREDENTIALS_JSON", "credentials.json"))
GOOGLE_TOKEN_JSON = _project_path(os.getenv("GOOGLE_TOKEN_JSON", "token.json"))
GMAIL_API_URL = os.getenv("GMAIL_API_URL", "https://gmail.googleapis.com/gmail/v1")
GCAL_API_URL = os.getenv("GCAL_API_URL", "https://www.googleapis.com/calendar/v3")
EVENT_MINUTES = int(os.getenv("FT_EVENT_MINUTES", "30"))

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_API_URL = os.getenv("SLACK_API_URL", "https://slack.com/api")

AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY", "")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID", "")
AIRTABLE_TABLE_NAME = os.getenv("AIRTABLE_TABLE_NAME", "Deals")
AIRTABLE_API_URL = os.getenv("AIRTABLE_API_URL", "https://api.airtable.com/v0")

# --- Reliability knobs ------------------------------------------------------
MAX_RETRIES = int(os.getenv("FT_MAX_RETRIES", "3"))
RETRY_BACKOFF_S = float(os.getenv("FT_RETRY_BACKOFF_S", "0.05"))
# Entity resolution below this confidence => clarify, never act.
MIN_ENTITY_CONFIDENCE = float(os.getenv("FT_MIN_ENTITY_CONFIDENCE", "0.85"))
AGENT_VERSION = os.getenv("FT_AGENT_VERSION", "v1.0")
