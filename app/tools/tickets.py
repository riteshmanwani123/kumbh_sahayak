"""create_ticket: lost & found / complaint / emergency tickets in SQLite."""
import datetime as dt
import secrets

from ..db import connect

TYPES = {"lost_found", "complaint", "emergency"}
TYPE_ALIASES = {"lost": "lost_found", "lost_person": "lost_found", "lost_and_found": "lost_found",
                "missing": "lost_found", "khoya_paya": "lost_found", "medical": "emergency",
                "fire": "emergency", "crime": "emergency", "stampede": "emergency"}

EMERGENCY_CONTACTS = [
    {"name": "Emergency (police / fire / ambulance)", "number": "112"},
    {"name": "Ambulance", "number": "108"},
    {"name": "Fire", "number": "101"},
    {"name": "Nashik disaster helpline", "number": "1077"},
]
LOST_CONTACTS = [{"name": "Emergency", "number": "112"}, {"name": "Childline (lost child)", "number": "1098"}]


def _db(path=None):
    """Tickets share the main database (SQLite locally, Neon Postgres on Vercel); `path` is for tests."""
    return connect(path)


def create_ticket(type: str, details: str, caller_language: str = "en", session_id: str = "", db_path=None,
                  caller_id: str | None = None) -> dict:
    t = (type or "").strip().lower().replace(" ", "_").replace("-", "_")
    t = TYPE_ALIASES.get(t, t)
    if t not in TYPES:
        t = "complaint"
    prefix = {"lost_found": "LF", "complaint": "CP", "emergency": "EM"}[t]
    tid = f"KS-{prefix}-{dt.datetime.now():%m%d}-{secrets.token_hex(2).upper()}"
    with _db(db_path) as con:
        con.execute("INSERT INTO tickets (id, type, details, caller_language, session_id, created_at, status, "
                    "caller_id) VALUES (?,?,?,?,?,?,?,?)",
                    (tid, t, (details or "")[:2000], caller_language or "en", session_id,
                     dt.datetime.now().isoformat(timespec="seconds"), "open", caller_id))
    out = {"ok": True, "ticket_id": tid, "type": t, "status": "open",
           "note": "Demo ticket stored locally; this is not an official police record."}
    if t == "emergency":
        out["call_now"] = EMERGENCY_CONTACTS
    elif t == "lost_found":
        out["call_now"] = LOST_CONTACTS
    return out


def list_tickets(limit: int = 50, db_path=None) -> list[dict]:
    with _db(db_path) as con:
        rows = con.execute("SELECT id,type,details,caller_language,created_at,status FROM tickets "
                           "ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return list(rows)


def lookup_tickets(caller_id: str | None, ticket_id: str = "", db_path=None) -> dict:
    """Tickets for this caller (or one ticket by ID that belongs to them)."""
    if not caller_id:
        return {"ok": True, "tickets": [], "note": "Caller not identified; ask them to read out the ticket ID."}
    q = "SELECT id AS ticket_id,type,details,status,created_at FROM tickets WHERE caller_id=?"
    args: list = [caller_id]
    if ticket_id:
        q += " AND upper(id)=upper(?)"
        args.append(ticket_id.strip())
    with _db(db_path) as con:
        rows = con.execute(q + " ORDER BY created_at DESC LIMIT 5", args).fetchall()
    return {"ok": True, "tickets": list(rows),
            "note": "Demo tickets are logged locally; no officer has updated them. For urgent help: 112."}
