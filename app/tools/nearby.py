"""find_nearby: OSM POIs around a place. Photon (fast) and Overpass (complete) run in parallel; Nominatim
category search and a short verified list are fallbacks. Results are cached for 7 days."""
import asyncio

from .. import net
from .geocode import geocode

OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

CATEGORIES: dict[str, list[str]] = {
    "hospital": ['nwr["amenity"~"^(hospital|clinic)$"]'],
    "police": ['nwr["amenity"="police"]'],
    "toilets": ['nwr["amenity"="toilets"]'],
    "drinking_water": ['nwr["amenity"="drinking_water"]'],
    "food": ['nwr["amenity"~"^(restaurant|fast_food|cafe|food_court)$"]'],
    "parking": ['nwr["amenity"="parking"]'],
    "bus_station": ['nwr["amenity"="bus_station"]', 'node["highway"="bus_stop"]'],
    "railway_station": ['nwr["railway"~"^(station|halt)$"]'],
    "atm": ['nwr["amenity"~"^(atm|bank)$"]'],
    "lodging": ['nwr["tourism"~"^(hotel|guest_house|hostel|motel)$"]'],
    "pharmacy": ['nwr["amenity"="pharmacy"]'],
}
ALIASES = {
    "hospitals": "hospital", "clinic": "hospital", "doctor": "hospital", "medical": "hospital",
    "अस्पताल": "hospital", "हॉस्पिटल": "hospital", "दवाखाना": "hospital", "रुग्णालय": "hospital",
    "toilet": "toilets", "washroom": "toilets", "restroom": "toilets", "शौचालय": "toilets", "टॉयलेट": "toilets",
    "water": "drinking_water", "पानी": "drinking_water", "पाणी": "drinking_water",
    "restaurant": "food", "khana": "food", "खाना": "food", "जेवण": "food", "bhojan": "food",
    "bus": "bus_station", "bus stand": "bus_station", "railway": "railway_station", "station": "railway_station",
    "hotel": "lodging", "stay": "lodging", "dharamshala": "lodging", "lodge": "lodging",
    "medicine": "pharmacy", "chemist": "pharmacy", "bank": "atm", "पोलीस": "police", "पुलिस": "police",
}

# Photon search word + OSM tag filters per category.
PHOTON = {
    "hospital": ("hospital", ["amenity:hospital", "amenity:clinic"]),
    "police": ("police", ["amenity:police"]),
    "toilets": ("toilets", ["amenity:toilets"]),
    "drinking_water": ("water", ["amenity:drinking_water"]),
    "food": ("restaurant", ["amenity:restaurant", "amenity:fast_food", "amenity:cafe"]),
    "parking": ("parking", ["amenity:parking"]),
    "bus_station": ("bus", ["amenity:bus_station", "highway:bus_stop"]),
    "railway_station": ("station", ["railway:station", "railway:halt"]),
    "atm": ("atm", ["amenity:atm", "amenity:bank"]),
    "lodging": ("hotel", ["tourism:hotel", "tourism:guest_house", "tourism:hostel"]),
    "pharmacy": ("pharmacy", ["amenity:pharmacy"]),
}
NOMINATIM_PHRASE = {"hospital": "hospital", "police": "police", "toilets": "toilets", "food": "restaurant",
                    "parking": "parking", "bus_station": "bus station", "railway_station": "railway station",
                    "atm": "atm", "lodging": "hotel", "pharmacy": "pharmacy", "drinking_water": "drinking water"}
MAX_DIST_M = 6000

# Last-resort fallback when Overpass is down (official / verified entries only).
FALLBACK = {
    "hospital": [{"name": "Civil Hospital Nashik", "lat": 19.9974592, "lon": 73.7783439, "phone": "0253-2572038"}],
    "railway_station": [{"name": "Nashik Road Railway Station", "lat": 19.9481228, "lon": 73.8412959}],
    "bus_station": [{"name": "Nimani Bus Station", "lat": 20.0117604, "lon": 73.7968414},
                    {"name": "Thakkar Bazar Bus Stand", "lat": 19.9983644, "lon": 73.7808471},
                    {"name": "Mahamarg Bus Stand", "lat": 19.9888004, "lon": 73.7829469}],
}


def normalize_category(cat: str) -> str | None:
    c = (cat or "").strip().lower().replace("-", "_")
    if c in CATEGORIES:
        return c
    if c.rstrip("s") in CATEGORIES:
        return c.rstrip("s")
    return ALIASES.get(c)


async def _overpass(cat: str, center) -> list[dict] | None:
    body = "".join(f"{sel}(around:3000,{center[0]},{center[1]});" for sel in CATEGORIES[cat])
    query = f"[out:json][timeout:8];({body});out center 60;"
    for url in OVERPASS_MIRRORS:
        try:
            r = await net.client().post(url, data={"data": query}, timeout=6)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
                out = []
                for e in r.json().get("elements", []):
                    tags = e.get("tags", {})
                    lat = e.get("lat") or e.get("center", {}).get("lat")
                    lon = e.get("lon") or e.get("center", {}).get("lon")
                    if lat is not None:
                        out.append({"name": tags.get("name:en") or tags.get("name"), "lat": lat, "lon": lon,
                                    "phone": tags.get("phone") or tags.get("contact:phone")})
                return out
        except Exception:
            continue
    return None


async def _overpass_budgeted(cat: str, center, budget: float = 4.5):
    try:
        return await asyncio.wait_for(_overpass(cat, center), budget)
    except asyncio.TimeoutError:
        return None


async def _photon(cat: str, center) -> list[dict] | None:
    word, tags = PHOTON[cat]
    d = 0.06
    params = [("q", word), ("lat", center[0]), ("lon", center[1]), ("limit", 20),
              ("bbox", f"{center[1] - d},{center[0] - d},{center[1] + d},{center[0] + d}")]
    params += [("osm_tag", t) for t in tags]
    try:
        await net.polite("photon", 0.5)
        r = await net.client().get("https://photon.komoot.io/api/", params=params, timeout=5)
        if r.status_code != 200:
            return None
        return [{"name": f["properties"].get("name"), "lat": f["geometry"]["coordinates"][1],
                 "lon": f["geometry"]["coordinates"][0]} for f in r.json().get("features", [])]
    except Exception:
        return None


async def _nominatim(cat: str, center) -> list[dict] | None:
    d = 0.03
    try:
        await net.polite("nominatim", 1.05)
        r = await net.client().get("https://nominatim.openstreetmap.org/search", timeout=6, params={
            "q": f"[{NOMINATIM_PHRASE[cat]}]", "format": "jsonv2", "limit": 15, "bounded": 1,
            "viewbox": f"{center[1] - d},{center[0] + d},{center[1] + d},{center[0] - d}"})
        r.raise_for_status()
        return [{"name": x.get("name"), "lat": float(x["lat"]), "lon": float(x["lon"])} for x in r.json()]
    except Exception:
        return None


def _merge(*lists) -> list[dict]:
    seen, out = [], []
    for lst in lists:
        for p in lst or []:
            if any(net.haversine_m((p["lat"], p["lon"]), (q["lat"], q["lon"])) < 40 for q in seen):
                continue
            seen.append(p)
            out.append(p)
    return out


async def find_nearby(place: str, category: str, limit: int = 5) -> dict:
    cat = normalize_category(category)
    if not cat:
        return {"ok": False, "error": f"Unknown category '{category}'. Use one of: {', '.join(CATEGORIES)}."}
    loc = await geocode(place)
    if not loc:
        return {"ok": False, "error": f"Could not find '{place}'. Ask for a nearby landmark."}
    center = (loc["lat"], loc["lon"])

    key = (cat, round(center[0], 4), round(center[1], 4))
    results = net.cache_get("nearby", key)
    source = "openstreetmap"
    if results is None:
        photon, overpass = await asyncio.gather(_photon(cat, center), _overpass_budgeted(cat, center))
        results = _merge(photon, overpass)
        if len([r for r in results if r.get("name")]) < 2:
            results = _merge(results, await _nominatim(cat, center))
        results = [r for r in results if net.haversine_m(center, (r["lat"], r["lon"])) <= MAX_DIST_M]
        if results:
            net.cache_set("nearby", key, results, ttl=7 * 86400)
        else:
            results, source = [dict(x) for x in FALLBACK.get(cat, [])], "fallback"

    for r_ in results:
        r_["name"] = r_.get("name") or cat.replace("_", " ").title() + " (unnamed)"
        if r_.get("lat") is not None:
            r_["distance_m"] = int(net.haversine_m(center, (r_["lat"], r_["lon"])))
            r_["map_link"] = net.gmaps_dir_link((r_["lat"], r_["lon"]), center, "walking")
    results.sort(key=lambda x: (x.get("distance_m") is None, x.get("distance_m", 0)))
    named = [r_ for r_ in results if "(unnamed)" not in r_["name"]]
    # Unnamed toilets/water points are still useful; otherwise prefer named places.
    pool = results if cat in ("toilets", "drinking_water", "parking") else named + [r_ for r_ in results if r_ not in named]
    picked = pool[:limit]
    for r_ in picked:
        if not r_.get("phone"):
            r_.pop("phone", None)
    return {"ok": True, "place": loc["name"], "category": cat, "results": picked, "source": source,
            "note": "From OpenStreetMap; temporary Kumbh facilities (medical camps, mobile toilets) are not listed yet."
            if source == "openstreetmap" else "Live map data unavailable or nothing mapped here; showing a short verified list."
            + (" For police dial 112 or 100." if cat == "police" else "")}
