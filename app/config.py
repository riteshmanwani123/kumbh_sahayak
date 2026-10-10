"""Settings loaded from environment / .env. The API key is never logged or returned."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))
KNOWLEDGE_DIR = ROOT / "knowledge"
LOG_DIR = DATA_DIR / "logs"
for d in (DATA_DIR, LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)

INDEX_PATH = DATA_DIR / "kb_index.npz"
TICKETS_DB = DATA_DIR / "tickets.sqlite"
CACHE_DB = DATA_DIR / "cache.sqlite"


def openai_key() -> str:
    return os.getenv("OPENAI_API_KEY", "").strip()


def has_key() -> bool:
    return openai_key().startswith("sk-")


REALTIME_MODEL = os.getenv("REALTIME_MODEL", "gpt-realtime-2.1")
REALTIME_VOICE = os.getenv("REALTIME_VOICE", "marin")
TRANSCRIBE_MODEL = os.getenv("TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
TEXT_MODEL = os.getenv("TEXT_MODEL", "gpt-5.4-mini")
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")

# Optional: if set, the voice token endpoint requires this code (protects your key when deployed publicly).
DEMO_ACCESS_CODE = os.getenv("DEMO_ACCESS_CODE", "").strip()

USER_AGENT = os.getenv(
    "HTTP_USER_AGENT",
    "KumbhSahayakDemo/0.1 (+https://github.com/; contact: set HTTP_USER_AGENT in .env)",
)
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "8"))

# Nashik–Trimbakeshwar bias box (lon_min, lat_max, lon_max, lat_min) for Nominatim viewbox
VIEWBOX = (73.40, 20.20, 74.10, 19.80)
NASHIK_CENTER = (20.0072639, 73.7924901)  # Ramkund

HELPLINE_FALLBACK = "112"
