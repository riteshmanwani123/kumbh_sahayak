import json

import httpx
import pytest

from app import config, net
from app.tools import directions, geocode, kb, nearby, tickets, travel, weather
from app.tools.registry import TOOLS, realtime_tools, run_tool



# ---------- geocode ----------
@pytest.mark.parametrize("q,expected", [
    ("Ramkund", "Ramkund, Panchavati"), ("रामकुंड के पास", "Ramkund, Panchavati"),
    ("कुशावर्त", "Kushavarta Kund, Trimbakeshwar"), ("Tapovan", "Tapovan, Nashik"),
    ("Igatpuri railway station", "Igatpuri"), ("railway station", "Nashik Road Railway Station"),
    ("Ramkund, Panchavati", "Ramkund, Panchavati"), ("Nashik", "Nashik city"),
])
async def test_gazetteer(q, expected):
    assert geocode.gazetteer_lookup(q)["name"] == expected


async def test_geocode_latlon_and_nominatim_fallback(fake_http):
    assert (await geocode.geocode("20.0, 73.79"))["source"] == "coords"
    r = await geocode.geocode("Some Unknown Lane")
    assert r["source"] == "nominatim" and abs(r["lat"] - 20.005) < 1e-6
    # second call is served from cache (no HTTP)
    fake_http({"nominatim": lambda req: httpx.Response(500)}, clear=False)
    assert (await geocode.geocode("Some Unknown Lane"))["lat"] == r["lat"]


async def test_geocode_not_found(fake_http):
    fake_http({"nominatim": lambda req: httpx.Response(200, json=[])})
    assert await geocode.geocode("zzqqxx") is None


# ---------- directions ----------
async def test_directions_ok(fake_http):
    r = await directions.get_directions("Nashik Road station", "Ramkund", "driving")
    assert r["ok"] and r["distance_km"] == 12.1 and r["eta"] == "12 min"
    assert 3 <= len(r["steps"]) <= 5 and r["steps"][-1] == "Arrive at destination"
    assert r["map_links"]["google_maps"].startswith("https://www.google.com/maps/dir/?api=1")
    assert "origin=19.948123,73.841296" in r["map_links"]["google_maps"]


async def test_directions_walking_uses_foot_router(fake_http):
    seen = []

    def foot(req):
        seen.append(str(req.url))
        from tests.conftest import osrm_response
        return httpx.Response(200, json=osrm_response(2800, 2200))

    fake_http({"routing.openstreetmap.de": foot})
    r = await directions.get_directions("Ramkund", "Tapovan", "paidal")
    assert r["mode"] == "walking" and seen and r["eta"] == "37 min"
    assert "travelmode=walking" in r["map_links"]["google_maps"]


async def test_directions_router_down_gives_estimate(fake_http):
    fake_http({"osrm": lambda req: httpx.Response(503), "routing.openstreetmap.de": lambda req: httpx.Response(503)})
    r = await directions.get_directions("Ramkund", "Trimbakeshwar", "driving")
    assert r["ok"] and r["approximate"] and r["map_links"]["google_maps"]


async def test_directions_unknown_place(fake_http):
    fake_http({"nominatim": lambda req: httpx.Response(200, json=[])})
    r = await directions.get_directions("qqqzzz", "Ramkund")
    assert not r["ok"] and "landmark" in r["error"]


@pytest.mark.parametrize("frm", ["caller current area near Nashik", "my location", "", "here"])
async def test_directions_rejects_vague_start(fake_http, frm):
    r = await directions.get_directions(frm, "Ramkund", "walking")
    assert not r["ok"] and "landmark" in r["spoken_fallback"]


async def test_directions_rejects_out_of_region(fake_http):
    fake_http({"nominatim": lambda req: httpx.Response(200, json=[{"lat": "18.52", "lon": "73.85", "display_name": "Pune"}])})
    r = await directions.get_directions("Shaniwar Wada", "Ramkund", "driving")
    assert not r["ok"] and "travel_to_nashik" in r["spoken_fallback"]


def test_kb_unverified_ranked_below_verified():
    r = kb.search_kumbh_info("Shahi Snan dates official schedule")
    assert r["passages"][0]["trust"] == "verified"
    assert any("2 August 2027" in p["text"] or "2 अगस्त 2027" in p["text"] for p in r["passages"][:2])


def test_simplify_steps_limits():
    from tests.conftest import osrm_response
    steps = directions.simplify_steps(osrm_response()["routes"][0]["legs"][0]["steps"])
    assert len(steps) <= 5 and "Nashik Pune Highway" in " ".join(steps)


# ---------- nearby ----------
async def test_nearby_merges_and_sorts(fake_http):
    r = await nearby.find_nearby("Ramkund", "hospital")
    assert r["ok"] and r["source"] == "openstreetmap"
    names = [x["name"] for x in r["results"]]
    assert names[0] == "Ghat Clinic" and names.count("Near Hospital") == 1  # de-duplicated across sources
    assert all(x["distance_m"] <= nearby.MAX_DIST_M for x in r["results"])
    assert r["results"][0]["map_link"].startswith("https://www.google.com/maps")


async def test_nearby_all_sources_down_uses_fallback(fake_http):
    down = lambda req: httpx.Response(504, text="busy")  # noqa: E731
    fake_http({"photon": down, "overpass": down, "mail.ru": down, "nominatim": down})
    r = await nearby.find_nearby("Ramkund", "hospital")
    assert r["ok"] and r["source"] == "fallback" and r["results"][0]["name"] == "Civil Hospital Nashik"


async def test_nearby_category_aliases():
    assert nearby.normalize_category("अस्पताल") == "hospital"
    assert nearby.normalize_category("Toilet") == "toilets"
    assert nearby.normalize_category("spaceport") is None


async def test_nearby_bad_category(fake_http):
    r = await nearby.find_nearby("Ramkund", "spaceport")
    assert not r["ok"]


# ---------- weather ----------
async def test_weather(fake_http):
    r = await weather.get_weather("Trimbakeshwar")
    assert r["ok"] and r["now"]["summary"] == "light rain" and r["forecast"][0]["rain_chance_pct"] == 80


async def test_weather_retry_then_stale_cache(fake_http):
    assert (await weather.get_weather("Nashik"))["ok"]                      # primes stale cache
    from app import net as _net
    _net.cache_set("weather", (20.01, 73.79), None, ttl=-1)                # expire fresh cache
    fake_http({"open-meteo": lambda req: httpx.Response(502)}, clear=False)
    r = await weather.get_weather("Nashik")
    assert r["ok"] and "last reading" in r["note"]


async def test_weather_down(fake_http):
    fake_http({"open-meteo": lambda req: httpx.Response(500)})
    r = await weather.get_weather("Nashik")
    assert not r["ok"]


# ---------- tickets ----------
def test_ticket_create_and_list(tmp_path):
    db = tmp_path / "t.sqlite"
    r = tickets.create_ticket("emergency", "mother fainted near Ramkund", "hi", "s1", db_path=db)
    assert r["ok"] and r["ticket_id"].startswith("KS-EM-") and r["call_now"][0]["number"] == "112"
    r2 = tickets.create_ticket("lost person", "child 8y red shirt", "mr", db_path=db)
    assert r2["type"] == "lost_found" and any(c["number"] == "1098" for c in r2["call_now"])
    r3 = tickets.create_ticket("weird", "dirty toilets", db_path=db)
    assert r3["type"] == "complaint"
    rows = tickets.list_tickets(db_path=db)
    assert len(rows) == 3 and {r["type"] for r in rows} == {"emergency", "lost_found", "complaint"}


# ---------- knowledge base ----------
def test_kb_chunks_have_sources():
    chunks = kb.load_chunks()
    assert len(chunks) > 40
    assert all(c["sources"] for c in chunks), "every chunk should carry at least one source URL"


@pytest.mark.parametrize("q,needle", [
    ("second amrut snan date", "31 August 2027"),
    ("अमृत स्नान की तारीखें", "31 अगस्त 2027"),
    ("ambulance emergency number", "112"),
    ("parking on snan day", "outer"),
    ("कुंभमेळा हेल्पलाइन क्रमांक", "112"),
])
def test_kb_keyword_search(q, needle):
    r = kb.search_kumbh_info(q)
    assert r["found"] and r["method"] == "keyword"
    assert any(needle in p["text"] for p in r["passages"]), [p["text"][:80] for p in r["passages"]]


def test_kb_not_found():
    r = kb.search_kumbh_info("xylophone quantum zebra")
    assert r["ok"] and not r["found"] and "112" in r["advice"]


def test_kb_has_no_outdated_dates_as_facts():
    """The wrong dates from outdated sites must only appear in the 'do NOT use' section."""
    text = (config.KNOWLEDGE_DIR / "02_dates_calendar.md").read_text()
    main = text.split("## Old or wrong dates")[0]
    assert "26 Aug" not in main and "14 July 2027" not in main.split("[UNVERIFIED")[0]


# ---------- travel ----------
def test_travel_known_city():
    r = travel.travel_to_nashik("इंदौर")
    assert r["from_city"] == "Indore" and r["road_distance_km"] == 416 and "Nashik Road" in r["rail"]


def test_travel_flight_city_and_unknown():
    assert "flight" in travel.travel_to_nashik("Bangalore")
    r = travel.travel_to_nashik("Timbuktu")
    assert r["ok"] and "road_distance_km" not in r and r["note"]


# ---------- registry ----------
async def test_registry_schema_and_errors(fake_http):
    assert {t["name"] for t in TOOLS} == {"search_kumbh_info", "get_directions", "find_nearby", "travel_to_nashik",
                                          "create_ticket", "get_weather", "remember_caller_details", "get_my_tickets"}
    assert all(t["type"] == "function" and "parameters" in t for t in realtime_tools())
    bad = await run_tool("nope", {})
    assert not bad["ok"] and "112" in bad["spoken_fallback"]
    ok = await run_tool("search_kumbh_info", json.dumps({"query": "Ramkund"}))
    assert ok["ok"] and "_ms" in ok


async def test_registry_tool_exception_is_caught(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("kaput")
    monkeypatch.setattr("app.tools.registry.get_weather", boom)
    r = await run_tool("get_weather", {"place": "Nashik"})
    assert not r["ok"] and "RuntimeError" in r["error"] and r["spoken_fallback"]


# ---------- live (optional) ----------
@pytest.mark.live
async def test_live_directions_and_weather():
    net.set_client(None)
    r = await directions.get_directions("Nashik Road station", "Ramkund", "driving")
    assert r["ok"] and 8 < r["distance_km"] < 16
    w = await weather.get_weather("Nashik")
    assert w["ok"]
