import json
import os
import sys
import tempfile
from pathlib import Path

# Isolate data (cache, tickets, logs) and make sure no real key is used by unit tests.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="kumbh_test_")
os.environ["OPENAI_API_KEY"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
import pytest  # noqa: E402

from app import net  # noqa: E402


def osrm_response(distance=12100.0, duration=700.0):
    steps = [
        {"maneuver": {"type": "depart"}, "name": "Station Road", "distance": 400},
        {"maneuver": {"type": "turn", "modifier": "right"}, "name": "Nashik Pune Highway", "distance": 5500},
        {"maneuver": {"type": "turn", "modifier": "left"}, "name": "Dwarka Road", "distance": 3000},
        {"maneuver": {"type": "roundabout", "exit": 2}, "name": "", "distance": 200},
        {"maneuver": {"type": "continue"}, "name": "Panchavati Karanja", "distance": 2500},
        {"maneuver": {"type": "turn", "modifier": "left"}, "name": "Ramkund Road", "distance": 500},
        {"maneuver": {"type": "arrive"}, "name": "", "distance": 0},
    ]
    return {"code": "Ok", "routes": [{"distance": distance, "duration": duration, "legs": [{"steps": steps}]}]}


def make_handler(overrides=None):
    """Fake OSM/Open-Meteo services. `overrides` maps host substring -> callable(request) -> httpx.Response."""
    overrides = overrides or {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for k, fn in overrides.items():
            if k in url:
                return fn(request)
        if "nominatim" in url:
            return httpx.Response(200, json=[{"lat": "20.0050", "lon": "73.7900", "display_name": "Test Place, Nashik, Maharashtra"}])
        if "router.project-osrm.org" in url or "routing.openstreetmap.de" in url:
            return httpx.Response(200, json=osrm_response())
        if "photon" in url:
            return httpx.Response(200, json={"features": [
                {"properties": {"name": "Near Hospital"}, "geometry": {"coordinates": [73.7930, 20.0080]}},
                {"properties": {"name": "Far Hospital"}, "geometry": {"coordinates": [73.8100, 20.0200]}},
            ]})
        if "overpass" in url or "mail.ru" in url:
            return httpx.Response(200, headers={"content-type": "application/json"}, json={"elements": [
                {"type": "node", "lat": 20.0075, "lon": 73.7926, "tags": {"name": "Ghat Clinic", "phone": "0253-000"}},
                {"type": "way", "center": {"lat": 20.0080, "lon": 73.7930}, "tags": {"name": "Near Hospital"}},
            ]})
        if "open-meteo" in url:
            return httpx.Response(200, json={
                "current": {"temperature_2m": 28.5, "relative_humidity_2m": 70, "precipitation": 0.2,
                            "weather_code": 61, "wind_speed_10m": 9},
                "daily": {"time": ["2027-08-02"], "weather_code": [63], "temperature_2m_max": [29],
                          "temperature_2m_min": [23], "precipitation_probability_max": [80]}})
        return httpx.Response(404)

    return handler


@pytest.fixture
def fake_http():
    def install(overrides=None, clear=True):
        net.set_client(httpx.AsyncClient(transport=httpx.MockTransport(make_handler(overrides))))
        # Fresh cache per test
        if clear:
            from app.db import connect
            with connect() as con:
                con.execute("DELETE FROM cache")
        net._last_call.clear()

    install()
    yield install
    net.set_client(None)


def pytest_configure(config):
    config.addinivalue_line("markers", "live: hits real free APIs (run with -m live)")
