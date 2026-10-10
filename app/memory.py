"""Caller memory: remembers returning callers across voice and text sessions (SQLite: data/kumbh.sqlite).

A caller is identified by an anonymous ID the browser keeps in localStorage (there is no phone number in this
demo). For each caller we store a small profile (name, language, home city, notes they chose to share), every
session with an AI summary, every message, and link their tickets. At the start of a new session a short
"returning caller" brief is injected into the model instructions so it can greet by name and follow up.
"""
import datetime as dt
import json
import re
import sqlite3

from . import config

DB = config.DATA_DIR / "kumbh.sqlite"
_ID = re.compile(r"^[A-Za-z0-9_\-]{6,64}$")
PROFILE_FIELDS = ("name", "preferred_language", "home_city", "group_info", "stay_location", "notes")


def valid_id(caller_id: str | None) -> bool:
    return bool(caller_id and _ID.match(caller_id))


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def db(path=None) -> sqlite3.Connection:
    con = sqlite3.connect(path or DB, timeout=10)
    con.row_factory = sqlite3.Row
    con.executescript("""
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS callers (
        caller_id TEXT PRIMARY KEY, name TEXT, preferred_language TEXT, home_city TEXT,
        group_info TEXT, stay_location TEXT, notes TEXT,
        created_at TEXT, last_seen TEXT, visit_count INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY, caller_id TEXT, mode TEXT, started_at TEXT, ended_at TEXT,
        language TEXT, summary TEXT);
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, caller_id TEXT, role TEXT, text TEXT, ts TEXT);
    CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session_id);
    CREATE INDEX IF NOT EXISTS idx_sess_caller ON sessions(caller_id, started_at);
    """)
    return con


# ---------------- sessions & messages ----------------
def start_session(caller_id: str, session_id: str, mode: str) -> bool:
    """Registers the session. Returns True if this caller has been seen before (returning caller)."""
    if not valid_id(caller_id):
        return False
    with db() as con:
        if con.execute("SELECT 1 FROM sessions WHERE session_id=?", (session_id,)).fetchone():
            return con.execute("SELECT visit_count FROM callers WHERE caller_id=?",
                               (caller_id,)).fetchone()["visit_count"] > 1
        row = con.execute("SELECT visit_count FROM callers WHERE caller_id=?", (caller_id,)).fetchone()
        if row:
            con.execute("UPDATE callers SET last_seen=?, visit_count=visit_count+1 WHERE caller_id=?",
                        (_now(), caller_id))
        else:
            con.execute("INSERT INTO callers (caller_id, created_at, last_seen, visit_count) VALUES (?,?,?,1)",
                        (caller_id, _now(), _now()))
        con.execute("INSERT INTO sessions (session_id, caller_id, mode, started_at) VALUES (?,?,?,?)",
                    (session_id, caller_id, mode, _now()))
    return bool(row)


def caller_for_session(session_id: str) -> str | None:
    with db() as con:
        r = con.execute("SELECT caller_id FROM sessions WHERE session_id=?", (session_id,)).fetchone()
    return r["caller_id"] if r else None


def add_message(session_id: str, role: str, text: str, language: str | None = None) -> None:
    text = (text or "").strip()
    if not text or role not in ("user", "assistant"):
        return
    with db() as con:
        r = con.execute("SELECT caller_id FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if not r:
            return
        con.execute("INSERT INTO messages (session_id, caller_id, role, text, ts) VALUES (?,?,?,?,?)",
                    (session_id, r["caller_id"], role, text[:4000], _now()))
        if language:
            con.execute("UPDATE sessions SET language=? WHERE session_id=?", (language, session_id))
            if role == "user":
                con.execute("UPDATE callers SET preferred_language=? WHERE caller_id=?", (language, r["caller_id"]))


def session_messages(session_id: str, limit: int = 200) -> list[dict]:
    with db() as con:
        rows = con.execute("SELECT role, text, ts FROM messages WHERE session_id=? ORDER BY id LIMIT ?",
                           (session_id, limit)).fetchall()
    return [dict(r) for r in rows]


def end_session(session_id: str) -> None:
    with db() as con:
        con.execute("UPDATE sessions SET ended_at=COALESCE(ended_at, ?) WHERE session_id=?", (_now(), session_id))


# ---------------- profile ----------------
def get_profile(caller_id: str) -> dict | None:
    with db() as con:
        r = con.execute("SELECT * FROM callers WHERE caller_id=?", (caller_id,)).fetchone()
    return dict(r) if r else None


def update_profile(caller_id: str, **fields) -> dict:
    clean = {k: str(v).strip()[:300] for k, v in fields.items() if k in PROFILE_FIELDS and v and str(v).strip()}
    if not clean or not valid_id(caller_id):
        return {"ok": False, "error": "nothing to save"}
    with db() as con:
        if not con.execute("SELECT 1 FROM callers WHERE caller_id=?", (caller_id,)).fetchone():
            return {"ok": False, "error": "unknown caller"}
        if "notes" in clean:  # notes accumulate instead of overwrite
            old = con.execute("SELECT notes FROM callers WHERE caller_id=?", (caller_id,)).fetchone()["notes"]
            clean["notes"] = "; ".join(x for x in [old, clean["notes"]] if x)[-600:]
        con.execute(f"UPDATE callers SET {', '.join(f'{k}=?' for k in clean)} WHERE caller_id=?",
                    (*clean.values(), caller_id))
    return {"ok": True, "saved": sorted(clean)}


def forget(caller_id: str) -> dict:
    """Delete everything stored about a caller (profile, sessions, messages, tickets)."""
    from .tools.tickets import _db as tickets_db
    with db() as con:
        sids = [r["session_id"] for r in con.execute("SELECT session_id FROM sessions WHERE caller_id=?", (caller_id,))]
        n = con.execute("DELETE FROM messages WHERE caller_id=?", (caller_id,)).rowcount
        con.execute("DELETE FROM sessions WHERE caller_id=?", (caller_id,))
        con.execute("DELETE FROM callers WHERE caller_id=?", (caller_id,))
    with tickets_db() as tcon:
        tcon.execute("DELETE FROM tickets WHERE caller_id=?", (caller_id,))
    for sid in sids:
        for f in config.LOG_DIR.glob(f"*_{sid}.jsonl"):
            f.unlink(missing_ok=True)
    return {"ok": True, "deleted_sessions": len(sids), "deleted_messages": n}


# ---------------- summaries & context ----------------
def _transcript(session_id: str, max_chars: int = 6000) -> str:
    lines = [f"{m['role']}: {m['text']}" for m in session_messages(session_id)]
    return "\n".join(lines)[-max_chars:]


def summarize_session(session_id: str) -> str | None:
    """Summarise a finished session with the text model (falls back to the last user lines without a key)."""
    with db() as con:
        r = con.execute("SELECT summary FROM sessions WHERE session_id=?", (session_id,)).fetchone()
    if not r or r["summary"]:
        return r["summary"] if r else None
    text = _transcript(session_id)
    if not text:
        return None
    summary = None
    if config.has_key():
        try:
            from openai import OpenAI
            resp = OpenAI(api_key=config.openai_key(), timeout=20).chat.completions.create(
                model=config.TEXT_MODEL,
                messages=[{"role": "system", "content":
                           "Summarise this Kumbh Mela helpline conversation in at most 2 short English sentences "
                           "for the next agent: what the caller needed, key facts they shared (name, city, group, "
                           "where staying), tickets created (with IDs), and anything unresolved. No greetings."},
                          {"role": "user", "content": text}])
            summary = (resp.choices[0].message.content or "").strip()[:500]
        except Exception:
            summary = None
    if not summary:
        users = [m["text"] for m in session_messages(session_id) if m["role"] == "user"]
        summary = "Caller asked: " + " | ".join(users[-3:])[:400]
    with db() as con:
        con.execute("UPDATE sessions SET summary=? WHERE session_id=?", (summary, session_id))
    return summary


def summarize_pending(caller_id: str, exclude_session: str = "") -> None:
    with db() as con:
        rows = con.execute("SELECT session_id FROM sessions WHERE caller_id=? AND session_id!=? AND summary IS NULL "
                           "ORDER BY started_at DESC LIMIT 3", (caller_id, exclude_session)).fetchall()
    for r in rows:
        summarize_session(r["session_id"])


def caller_tickets(caller_id: str, limit: int = 5) -> list[dict]:
    from .tools.tickets import _db as tickets_db
    with tickets_db() as con:
        rows = con.execute("SELECT id, type, details, status, created_at FROM tickets WHERE caller_id=? "
                           "ORDER BY created_at DESC LIMIT ?", (caller_id, limit)).fetchall()
    return [dict(zip(("ticket_id", "type", "details", "status", "created_at"), r)) for r in rows]


def build_context(caller_id: str, current_session: str = "") -> str:
    """Short brief for the model about a returning caller. Empty string for first-time callers."""
    p = get_profile(caller_id)
    if not p:
        return ""
    with db() as con:
        prev = con.execute("SELECT session_id, mode, started_at, summary FROM sessions WHERE caller_id=? "
                           "AND session_id!=? ORDER BY started_at DESC LIMIT 3",
                           (caller_id, current_session)).fetchall()
    tickets = caller_tickets(caller_id)
    if not prev and not any(p.get(k) for k in PROFILE_FIELDS) and not tickets:
        return ""
    lines = ["# Returning caller (from your memory database — use naturally, don't recite it)"]
    prof = {k: p[k] for k in PROFILE_FIELDS if p.get(k)}
    if prof:
        lines.append("Profile: " + json.dumps(prof, ensure_ascii=False))
    lines.append(f"Visits: {p['visit_count']} (first {p['created_at'][:10]})")
    for s in prev:
        summ = s["summary"] or ("Recent lines: " + _transcript(s["session_id"], 400).replace("\n", " | "))
        lines.append(f"- {s['started_at'][:16].replace('T', ' ')} ({s['mode']}): {summ}")
    if tickets:
        lines.append("Their tickets: " + "; ".join(f"{t['ticket_id']} {t['type']} [{t['status']}] {t['details'][:80]}"
                                                    for t in tickets))
    lines.append("Use this to greet them by name if known and to follow up (e.g. on an open lost & found ticket). "
                 "Facts about the Kumbh must still come from search_kumbh_info, not from this memory.")
    return "\n".join(lines)
