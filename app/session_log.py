"""Per-session JSONL logs (transcripts + tool calls) in data/logs. Secrets are scrubbed defensively."""
import datetime as dt
import json
import re

from . import config

_SECRET = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|ek_[A-Za-z0-9_\-]{6,})")
_SAFE_ID = re.compile(r"[^A-Za-z0-9_\-]")


def _scrub(obj):
    s = json.dumps(obj, ensure_ascii=False, default=str)
    return json.loads(_SECRET.sub("[REDACTED]", s))


def log_event(session_id: str, kind: str, **data) -> None:
    sid = _SAFE_ID.sub("", session_id or "nosession")[:64] or "nosession"
    rec = {"ts": dt.datetime.now().isoformat(timespec="milliseconds"), "kind": kind, **_scrub(data)}
    with open(config.LOG_DIR / f"{dt.date.today():%Y%m%d}_{sid}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
