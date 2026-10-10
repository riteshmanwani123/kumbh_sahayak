"""Shared HTTP client, a tiny SQLite TTL cache, and per-host rate limiting for free OSM services."""
import asyncio
import hashlib
import json
import math
import sqlite3
import time

import httpx

from . import config

_client: httpx.AsyncClient | None = None
_locks: dict[str, asyncio.Lock] = {}
_last_call: dict[str, float] = {}


def client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=config.HTTP_TIMEOUT,
            headers={"User-Agent": config.USER_AGENT, "Accept-Language": "en,hi,mr"},
        )
    return _client


def set_client(c: httpx.AsyncClient) -> None:
    """Used by tests to inject a mock transport."""
    global _client
    _client = c


async def polite(host: str, min_interval: float) -> None:
    """Serialize calls per host and keep at least min_interval seconds between them (Nominatim: 1 req/s)."""
    lock = _locks.setdefault(host, asyncio.Lock())
    async with lock:
        wait = _last_call.get(host, 0) + min_interval - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call[host] = time.monotonic()


# ---------- cache ----------
def _db() -> sqlite3.Connection:
    con = sqlite3.connect(config.CACHE_DB)
    con.execute("CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, v TEXT, exp REAL)")
    return con


def cache_get(ns: str, key) -> object | None:
    k = ns + ":" + hashlib.sha1(json.dumps(key, sort_keys=True).encode()).hexdigest()
    with _db() as con:
        row = con.execute("SELECT v, exp FROM cache WHERE k=?", (k,)).fetchone()
    if row and row[1] > time.time():
        return json.loads(row[0])
    return None


def cache_set(ns: str, key, value, ttl: float) -> None:
    k = ns + ":" + hashlib.sha1(json.dumps(key, sort_keys=True).encode()).hexdigest()
    with _db() as con:
        con.execute("REPLACE INTO cache VALUES (?,?,?)", (k, json.dumps(value), time.time() + ttl))


# ---------- geo helpers ----------
def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def gmaps_dir_link(dest: tuple[float, float], origin: tuple[float, float] | None = None, mode: str = "driving") -> str:
    tm = {"walking": "walking", "driving": "driving", "transit": "transit", "bicycling": "bicycling"}.get(mode, "driving")
    url = f"https://www.google.com/maps/dir/?api=1&destination={dest[0]:.6f},{dest[1]:.6f}&travelmode={tm}"
    if origin:
        url += f"&origin={origin[0]:.6f},{origin[1]:.6f}"
    return url


def osm_link(dest: tuple[float, float], origin: tuple[float, float] | None = None, mode: str = "driving") -> str:
    if origin:
        engine = "fossgis_osrm_foot" if mode == "walking" else "fossgis_osrm_car"
        return (f"https://www.openstreetmap.org/directions?engine={engine}"
                f"&route={origin[0]:.5f},{origin[1]:.5f};{dest[0]:.5f},{dest[1]:.5f}")
    return f"https://www.openstreetmap.org/?mlat={dest[0]:.6f}&mlon={dest[1]:.6f}#map=17/{dest[0]:.5f}/{dest[1]:.5f}"
