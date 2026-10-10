"""Place resolution: curated Kumbh gazetteer first (instant, multilingual), then Nominatim biased to Nashik."""
import re
import unicodedata

from .. import config, net

# name, lat, lon, aliases (EN transliterations + Hindi + Marathi). Coordinates from OSM, 2026-10-10.
GAZETTEER: list[tuple[str, float, float, list[str]]] = [
    ("Nashik city", 20.0112475, 73.7902364, ["nashik", "nasik", "नाशिक", "नासिक", "nashik city"]),
    ("Ramkund, Panchavati", 20.0072639, 73.7924901,
     ["ramkund", "ram kund", "ramkunda", "रामकुंड", "राम कुंड", "रामकुंडा", "godaghat", "goda ghat"]),
    ("Panchavati, Nashik", 20.0066847, 73.7935717, ["panchavati", "panchvati", "panchwati", "पंचवटी"]),
    ("Kalaram Mandir", 20.0069500, 73.7952193, ["kalaram", "kala ram", "काळाराम", "कालाराम"]),
    ("Sita Gufa", 20.0077229, 73.7961612, ["sita gufa", "sitagufa", "सीता गुफा", "सीतागुंफा", "सीता गुंफा"]),
    ("Tapovan, Nashik", 20.0007797, 73.8125840, ["tapovan", "tapoban", "तपोवन"]),
    ("Sadhugram (Tapovan area, approx.)", 20.0007797, 73.8125840, ["sadhugram", "sadhu gram", "साधुग्राम"]),
    ("Kapila–Godavari Sangam", 19.9996771, 73.8154918, ["kapila sangam", "kapila", "कपिला संगम"]),
    ("Kushavarta Kund, Trimbakeshwar", 19.9327411, 73.5276142,
     ["kushavarta", "kushavart", "kushawart", "kusavarta", "कुशावर्त", "कुशावर्त कुंड"]),
    ("Trimbakeshwar Temple", 19.9321202, 73.5307549,
     ["trimbakeshwar", "trimbakeshwar temple", "tryambakeshwar", "trimbak", "त्र्यंबकेश्वर", "त्रिंबकेश्वर",
      "त्र्यंबक", "त्रिंबक", "त्रयंबकेश्वर"]),
    ("Brahmagiri, Trimbak", 19.9151855, 73.5236017, ["brahmagiri", "ब्रह्मगिरी", "ब्रह्मगिरि"]),
    ("Anjaneri", 19.9460158, 73.5868474, ["anjaneri", "अंजनेरी"]),
    ("Nashik Road Railway Station", 19.9481228, 73.8412959,
     ["nashik road station", "nashik road railway", "nasik road", "nashik road", "railway station",
      "नाशिक रोड", "नासिक रोड", "रेलवे स्टेशन", "रेल्वे स्टेशन"]),
    ("Mahamarg Bus Stand", 19.9888004, 73.7829469, ["mahamarg", "महामार्ग बस"]),
    ("Thakkar Bazar Bus Stand", 19.9983644, 73.7808471, ["thakkar bazar", "thakkar bazaar", "ठक्कर बाजार"]),
    ("Nimani Bus Station, Panchavati", 20.0117604, 73.7968414, ["nimani", "निमाणी", "निमानी"]),
    ("Nashik Airport (Ozar)", 20.1134525, 73.8963999,
     ["ozar", "ojhar", "nashik airport", "airport", "ओझर", "एयरपोर्ट", "विमानतळ"]),
    ("Civil Hospital Nashik", 19.9974592, 73.7783439, ["civil hospital", "सिविल हॉस्पिटल", "सिव्हिल हॉस्पिटल"]),
    ("Dwarka Circle", 19.9942732, 73.7970546, ["dwarka", "द्वारका"]),
    ("Someshwar", 20.0291990, 73.7234030, ["someshwar", "सोमेश्वर"]),
    ("Gangapur Dam", 20.0355393, 73.6802997, ["gangapur dam", "गंगापूर धरण"]),
    ("Deolali", 19.9183943, 73.8319469, ["deolali", "devlali", "देवळाली", "देवलाली"]),
    ("Igatpuri", 19.6944394, 73.5638878, ["igatpuri", "इगतपुरी"]),
]

_LATLON = re.compile(r"^\s*(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)\s*$")
_FILLER = re.compile(
    r"(?<!\S)(near|nearby|the|to|from|at|in|area|ke|paas|pass|najdik|jawal|javal|chowk|"
    r"के|पास|नजदीक|जवळ|जवळचा|जवळची|पासून|से|तक|मध्ये|में)(?!\S)", re.I)
# Generic aliases only win when nothing more specific matches.
_GENERIC = {"railway station", "रेलवे स्टेशन", "रेल्वे स्टेशन", "airport", "एयरपोर्ट", "विमानतळ", "civil hospital"}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "").lower()
    s = _FILLER.sub(" ", s)
    s = re.sub(r"[^\w\sऀ-ॿ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def gazetteer_lookup(query: str) -> dict | None:
    q = _norm(query)
    if not q:
        return None
    best, best_score = None, 0
    for name, lat, lon, aliases in GAZETTEER:
        if q == _norm(name):  # canonical name round-trips exactly (e.g. "Ramkund, Panchavati")
            return {"name": name, "lat": lat, "lon": lon, "source": "gazetteer"}
        for a in aliases:
            a_n = _norm(a)
            if not a_n:
                continue
            if q == a_n:
                score = 1000 + len(a_n)
            elif a_n in q:
                score = 1 if a in _GENERIC else len(a_n)
            elif len(q) >= 4 and q in a_n:
                score = len(q) - 0.5  # partial query (e.g. "kushav") — weaker than a full alias hit
            else:
                continue
            if score > best_score:
                best, best_score = {"name": name, "lat": lat, "lon": lon, "source": "gazetteer"}, score
    return best


async def geocode(query: str) -> dict | None:
    """Return {name, lat, lon, source} or None."""
    if not query or not query.strip():
        return None
    m = _LATLON.match(query)
    if m:
        return {"name": query.strip(), "lat": float(m.group(1)), "lon": float(m.group(2)), "source": "coords"}
    hit = gazetteer_lookup(query)
    if hit:
        return hit
    cached = net.cache_get("geocode", query.strip().lower())
    if cached is not None:
        return cached or None

    result = None
    vb = ",".join(map(str, config.VIEWBOX))
    for bounded, q in ((1, query), (1, f"{query}, Nashik"), (0, f"{query}, Maharashtra")):
        await net.polite("nominatim", 1.05)
        try:
            r = await net.client().get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": q, "format": "jsonv2", "limit": 1, "countrycodes": "in",
                        "viewbox": vb, "bounded": bounded},
            )
            r.raise_for_status()
            data = r.json()
        except Exception:
            data = []
        if data:
            d = data[0]
            result = {"name": d.get("display_name", query).split(",")[0] + ", " +
                      ", ".join(d.get("display_name", "").split(",")[1:3]).strip(),
                      "lat": float(d["lat"]), "lon": float(d["lon"]), "source": "nominatim"}
            break
    net.cache_set("geocode", query.strip().lower(), result or {}, ttl=7 * 86400 if result else 3600)
    return result
