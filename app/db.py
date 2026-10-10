"""One small storage layer for callers, sessions, messages, tickets and the HTTP cache.

- Locally (no DATABASE_URL): SQLite files in data/ — zero setup.
- On Vercel: Neon Postgres via DATABASE_URL (or POSTGRES_URL, which the Vercel–Neon integration also sets),
  because serverless functions have no persistent disk.

SQL in the app uses "?" placeholders; they are converted to "%s" for Postgres.
"""
import os
import sqlite3
import threading
from contextlib import contextmanager

from . import config

PG_URL = (os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or "").strip()
IS_PG = PG_URL.startswith(("postgres://", "postgresql://"))

_SCHEMA_SQLITE = """
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
CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY, type TEXT, details TEXT, caller_language TEXT,
    session_id TEXT, created_at TEXT, status TEXT, caller_id TEXT);
CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, v TEXT, exp REAL);
"""
_SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS callers (
    caller_id TEXT PRIMARY KEY, name TEXT, preferred_language TEXT, home_city TEXT,
    group_info TEXT, stay_location TEXT, notes TEXT,
    created_at TEXT, last_seen TEXT, visit_count INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY, caller_id TEXT, mode TEXT, started_at TEXT, ended_at TEXT,
    language TEXT, summary TEXT);
CREATE TABLE IF NOT EXISTS messages (
    id BIGSERIAL PRIMARY KEY, session_id TEXT, caller_id TEXT, role TEXT, text TEXT, ts TEXT);
CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_sess_caller ON sessions(caller_id, started_at);
CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY, type TEXT, details TEXT, caller_language TEXT,
    session_id TEXT, created_at TEXT, status TEXT, caller_id TEXT);
CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, v TEXT, exp DOUBLE PRECISION);
"""

_ready: set[str] = set()
_lock = threading.Lock()


class _Conn:
    """Minimal uniform wrapper: execute(sql, params) -> cursor with dict rows."""

    def __init__(self, raw, pg: bool):
        self.raw, self.pg = raw, pg

    def execute(self, sql: str, params=()):
        if self.pg:
            sql = sql.replace("?", "%s")
        cur = self.raw.cursor()
        cur.execute(sql, tuple(params))
        return cur


def _sqlite_connect(path) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = lambda cur, row: {d[0]: v for d, v in zip(cur.description, row)}
    return con


def _ensure_schema(key: str, conn: _Conn) -> None:
    if key in _ready:
        return
    with _lock:
        if key in _ready:
            return
        if conn.pg:
            conn.raw.execute(_SCHEMA_PG)
        else:
            conn.raw.executescript(_SCHEMA_SQLITE)
            cols = {r["name"] for r in conn.raw.execute("PRAGMA table_info(tickets)")}
            if "caller_id" not in cols:  # databases created by older versions
                conn.raw.execute("ALTER TABLE tickets ADD COLUMN caller_id TEXT")
        conn.raw.commit()
        _ready.add(key)


@contextmanager
def connect(sqlite_path=None):
    """Use as `with db.connect() as con: con.execute(...)`. Commits on success, rolls back on error."""
    if IS_PG and sqlite_path is None:
        import psycopg
        from psycopg.rows import dict_row
        raw = psycopg.connect(PG_URL, row_factory=dict_row, connect_timeout=10)
        conn, key = _Conn(raw, True), "pg"
    else:
        path = str(sqlite_path or config.DATA_DIR / "kumbh.sqlite")
        raw = _sqlite_connect(path)
        conn, key = _Conn(raw, False), path
    try:
        _ensure_schema(key, conn)
        yield conn
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def backend_name() -> str:
    return "postgres" if IS_PG else "sqlite"
