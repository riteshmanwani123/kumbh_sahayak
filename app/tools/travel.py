"""travel_to_nashik: city-specific road distance + general rail/bus/air guidance grounded in the KB."""
import re

from .kb import search_kumbh_info

# OSRM road distance to Ramkund, computed 2026-10-10 (see knowledge/04_getting_there.md).
CITIES: dict[str, tuple[int, float, list[str]]] = {
    "Mumbai": (183, 2.3, ["mumbai", "bombay", "मुंबई", "मुम्बई", "csmt", "dadar"]),
    "Thane": (149, 1.8, ["thane", "ठाणे", "kalyan", "कल्याण"]),
    "Pune": (216, 2.8, ["pune", "poona", "पुणे"]),
    "Shirdi": (96, 1.1, ["shirdi", "शिर्डी"]),
    "Chhatrapati Sambhajinagar": (186, 2.1, ["aurangabad", "sambhajinagar", "औरंगाबाद", "संभाजीनगर"]),
    "Dhule": (156, 1.9, ["dhule", "धुळे", "धुले"]),
    "Surat": (229, 2.8, ["surat", "सूरत", "सुरत"]),
    "Vadodara": (352, 4.2, ["vadodara", "baroda", "वडोदरा"]),
    "Ahmedabad": (454, 5.4, ["ahmedabad", "amdavad", "अहमदाबाद"]),
    "Solapur": (389, 4.7, ["solapur", "sholapur", "सोलापूर", "सोलापुर"]),
    "Indore": (416, 5.0, ["indore", "इंदौर", "इंदूर"]),
    "Ujjain": (471, 5.9, ["ujjain", "उज्जैन"]),
    "Nagpur": (630, 6.9, ["nagpur", "नागपूर", "नागपुर"]),
    "Bhopal": (665, 8.2, ["bhopal", "भोपाल"]),
    "Hyderabad": (676, 8.4, ["hyderabad", "हैदराबाद"]),
    "Goa": (678, 8.3, ["goa", "panaji", "गोवा"]),
    "Raipur": (909, 10.4, ["raipur", "रायपुर"]),
    "Jaipur": (955, 11.5, ["jaipur", "जयपुर"]),
    "Bengaluru": (972, 11.8, ["bengaluru", "bangalore", "बेंगलुरु", "बंगलौर", "बंगळुरू"]),
    "Delhi": (1145, 13.5, ["delhi", "new delhi", "दिल्ली"]),
    "Chennai": (1217, 14.7, ["chennai", "madras", "चेन्नई"]),
    "Lucknow": (1273, 15.3, ["lucknow", "लखनऊ"]),
    "Varanasi": (1360, 15.7, ["varanasi", "banaras", "kashi", "वाराणसी", "बनारस"]),
    "Patna": (1590, 18.4, ["patna", "पटना"]),
    "Kolkata": (1738, 20.2, ["kolkata", "calcutta", "कोलकाता"]),
}
DIRECT_FLIGHT_CITIES = {"Delhi", "Ahmedabad", "Bengaluru", "Goa", "Hyderabad"}  # per Wikipedia, routes change


def match_city(text: str) -> str | None:
    t = (text or "").lower()
    for name, (_, _, aliases) in CITIES.items():
        if any(re.search(rf"(?<![\wऀ-ॿ]){re.escape(a)}(?![\wऀ-ॿ])", t) for a in aliases):
            return name
    return None


def travel_to_nashik(from_city: str) -> dict:
    city = match_city(from_city)
    rail = ("Train to Nashik Road station (about 12 km from Ramkund). Kumbh special trains will be announced "
            "by Central Railway; railway enquiry 139.")
    bus = "MSRTC (ST) buses run to Nashik bus stands (Mahamarg, Thakkar Bazar, CBS, Nimani). MSRTC helpline 1800-22-1250."
    air = ("Nashik airport is at Ozar (ISK), about 20 km from Ramkund; limited IndiGo routes. "
           "Otherwise fly to Mumbai (about 180 km) and continue by train or bus.")
    out: dict = {"ok": True, "from_city": city or from_city, "to": "Ramkund, Nashik"}
    if city:
        km, hrs, _ = CITIES[city]
        out["road_distance_km"] = km
        out["drive_time"] = f"about {hrs:.0f}–{hrs * 1.5:.0f} hours without Kumbh traffic" if hrs >= 2 else \
            f"about {int(hrs * 60)}–{int(hrs * 90)} minutes without Kumbh traffic"
        if km <= 250:
            out["best_option"] = "Road (MSRTC bus or car) or train — both practical."
        elif km <= 600:
            out["best_option"] = "Overnight train or bus; driving is long."
        else:
            out["best_option"] = "Train is usually most practical; book early."
        if city in DIRECT_FLIGHT_CITIES:
            out["flight"] = f"{city} has had direct IndiGo flights to Nashik (Ozar); check current schedules."
    else:
        out["note"] = "City not in distance table; giving general guidance."
    out.update({"rail": rail, "bus": bus, "air": air,
                "snan_day_tip": "On Amrut Snan days private vehicles must park outside the city and use MSRTC "
                                "shuttle buses; the last stretch to the ghat is on foot."})
    kb = search_kumbh_info(f"getting to Nashik from {city or from_city} train bus road", k=2)
    out["sources"] = sorted({u for p in kb.get("passages", []) for u in p["sources"]})[:4]
    return out
