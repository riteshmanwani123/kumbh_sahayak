"""get_directions: geocode both ends, route with OSRM (car) or FOSSGIS OSRM (foot), simplify steps."""
import re

from .. import net
from .geocode import geocode

CAR_URL = "https://router.project-osrm.org/route/v1/driving/{coords}"
FOOT_URL = "https://routing.openstreetmap.de/routed-foot/route/v1/driving/{coords}"
WALK_SPEED_MPS = 1.25


def _step_text(s: dict) -> str | None:
    m = s.get("maneuver", {})
    t, mod, name = m.get("type"), (m.get("modifier") or "").replace("slight ", "slight "), s.get("name") or ""
    dist = s.get("distance", 0)
    d = f"{dist / 1000:.1f} km" if dist >= 1000 else f"{int(round(dist, -1))} m"
    onto = f" onto {name}" if name else ""
    if t == "depart":
        return f"Start on {name}, go {d}" if name else (f"Head out and go {d}" if dist >= 150 else None)
    if t == "arrive":
        return "Arrive at destination"
    if t in ("turn", "end of road", "fork", "on ramp", "off ramp", "merge"):
        return f"Turn {mod or 'ahead'}{onto}, go {d}"
    if t in ("roundabout", "rotary", "roundabout turn"):
        ex = m.get("exit")
        return f"At the roundabout take exit {ex}{onto}, go {d}" if ex else f"Take the roundabout{onto}, go {d}"
    if t in ("new name", "continue") and dist > 300:
        return f"Continue{onto} for {d}"
    return None


def simplify_steps(steps: list[dict], max_steps: int = 5) -> list[str]:
    """Keep the biggest maneuvers so a caller hears 3–5 meaningful steps."""
    candidates = [(i, s) for i, s in enumerate(steps) if s.get("maneuver", {}).get("type") not in ("arrive",)]
    if len(candidates) > max_steps - 1:
        first = candidates[0]
        rest = sorted(candidates[1:], key=lambda x: x[1].get("distance", 0), reverse=True)[: max_steps - 2]
        candidates = sorted([first] + rest, key=lambda x: x[0])
    out = [t for _, s in candidates if (t := _step_text(s))]
    out.append("Arrive at destination")
    return out[:max_steps]


async def _route(url_tmpl: str, a: dict, b: dict) -> dict | None:
    coords = f"{a['lon']},{a['lat']};{b['lon']},{b['lat']}"
    key = (url_tmpl, coords)
    cached = net.cache_get("route", key)
    if cached:
        return cached
    r = await net.client().get(url_tmpl.format(coords=coords), params={"overview": "false", "steps": "true"})
    r.raise_for_status()
    data = r.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        return None
    route = data["routes"][0]
    out = {"distance_m": route["distance"], "duration_s": route["duration"],
           "steps": route["legs"][0].get("steps", [])}
    net.cache_set("route", key, out, ttl=6 * 3600)
    return out


def _fmt_dur(sec: float) -> str:
    m = int(round(sec / 60))
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60} min"


VAGUE = re.compile(r"\b(current|my location|caller|here|unknown|not sure|user|nearby|near me|area near)\b|यहाँ|इथे|इकडे",
                   re.I)
REGION = (19.60, 20.40, 73.30, 74.30)  # lat_min, lat_max, lon_min, lon_max — Nashik & Trimbakeshwar region


def _in_region(p: dict) -> bool:
    return REGION[0] <= p["lat"] <= REGION[1] and REGION[2] <= p["lon"] <= REGION[3]


async def get_directions(from_place: str, to_place: str, mode: str = "driving") -> dict:
    mode = (mode or "driving").lower()
    mode = "walking" if mode in ("walk", "walking", "foot", "paidal", "पैदल", "पायी") else "driving"
    for label, val in (("from_place", from_place), ("to_place", to_place)):
        if not (val or "").strip() or VAGUE.search(val):
            return {"ok": False, "error": f"{label} is not a specific landmark",
                    "spoken_fallback": "Ask the caller which landmark, ghat, station or chowk they are near right now."}
    a, b = await geocode(from_place), await geocode(to_place)
    if not a or not b:
        missing = from_place if not a else to_place
        return {"ok": False, "error": f"Could not find '{missing}'. Ask the caller for a nearby landmark."}

    for label, p in (("from_place", a), ("to_place", b)):
        if not _in_region(p):
            return {"ok": False, "error": f"{label} '{p['name']}' is outside the Nashik–Trimbakeshwar area",
                    "spoken_fallback": "For travel from another city use travel_to_nashik; otherwise ask for a "
                                       "local landmark."}

    straight = net.haversine_m((a["lat"], a["lon"]), (b["lat"], b["lon"]))
    route, engine = None, None
    try:
        if mode == "walking":
            route, engine = await _route(FOOT_URL, a, b), "osrm-foot"
        if not route:
            route, engine = await _route(CAR_URL, a, b), "osrm-car"
            if route and mode == "walking":
                route["duration_s"] = route["distance_m"] / WALK_SPEED_MPS
    except Exception:
        route = None

    links = {"google_maps": net.gmaps_dir_link((b["lat"], b["lon"]), (a["lat"], a["lon"]), mode),
             "openstreetmap": net.osm_link((b["lat"], b["lon"]), (a["lat"], a["lon"]), mode)}
    base = {"from": a["name"], "to": b["name"], "mode": mode, "map_links": links,
            "to_coords": [b["lat"], b["lon"]], "from_coords": [a["lat"], a["lon"]]}
    if not route:
        est = straight * 1.3
        return {"ok": True, **base, "approximate": True, "distance_km": round(est / 1000, 1),
                "eta": _fmt_dur(est / (WALK_SPEED_MPS if mode == "walking" else 8.0)),
                "steps": ["Routing service is busy; open the map link for turn-by-turn directions."],
                "note": "Estimate from straight-line distance."}
    return {"ok": True, **base, "distance_km": round(route["distance_m"] / 1000, 1),
            "eta": _fmt_dur(route["duration_s"]), "steps": simplify_steps(route["steps"]),
            "engine": engine,
            "note": "Free-flow estimate; on Kumbh snan days roads close and walking is required near ghats."}
