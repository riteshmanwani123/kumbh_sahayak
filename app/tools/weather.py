"""get_weather: Open-Meteo current + 3-day forecast (free, no key)."""
from .. import net
from .geocode import geocode

WMO = {0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "fog",
       51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
       80: "rain showers", 81: "heavy showers", 82: "violent showers", 95: "thunderstorm",
       96: "thunderstorm with hail", 99: "thunderstorm with hail"}


async def get_weather(place: str = "Nashik") -> dict:
    loc = await geocode(place or "Ramkund")
    if not loc:
        return {"ok": False, "error": f"Could not find '{place}'."}
    key = (round(loc["lat"], 2), round(loc["lon"], 2))
    data, stale = net.cache_get("weather", key), False
    if data is None:
        for _attempt in range(2):  # one retry: Open-Meteo occasionally returns a transient 5xx/timeout
            try:
                r = await net.client().get("https://api.open-meteo.com/v1/forecast", timeout=4, params={
                    "latitude": key[0], "longitude": key[1], "timezone": "Asia/Kolkata", "forecast_days": 3,
                    "current": "temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m",
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"})
                r.raise_for_status()
                data = r.json()
                break
            except Exception:
                data = None
        if data is None:
            data, stale = net.cache_get("weather_stale", key), True
            if data is None:
                return {"ok": False, "error": "Weather service unavailable right now."}
        else:
            net.cache_set("weather", key, data, ttl=900)
            net.cache_set("weather_stale", key, data, ttl=6 * 3600)
    cur, daily = data.get("current", {}), data.get("daily", {})
    days = [{"date": d, "summary": WMO.get(c, "mixed"), "min_c": lo, "max_c": hi, "rain_chance_pct": p}
            for d, c, hi, lo, p in zip(daily.get("time", []), daily.get("weather_code", []),
                                       daily.get("temperature_2m_max", []), daily.get("temperature_2m_min", []),
                                       daily.get("precipitation_probability_max", []))]
    return {"ok": True, "place": loc["name"],
            "now": {"temp_c": cur.get("temperature_2m"), "humidity_pct": cur.get("relative_humidity_2m"),
                    "rain_mm": cur.get("precipitation"), "summary": WMO.get(cur.get("weather_code"), "mixed"),
                    "wind_kmh": cur.get("wind_speed_10m")},
            "forecast": days, "source": "Open-Meteo",
            **({"note": "Live service busy; this is the last reading from the past few hours."} if stale else {})}
