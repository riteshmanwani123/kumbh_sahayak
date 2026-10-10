"""Pre-fetch map data for key landmarks so the live demo is instant even if free map servers are slow.

Usage:  .venv/bin/python -m scripts.warm_cache   (takes a few minutes; respects rate limits)
"""
import asyncio

from app.tools.directions import get_directions
from app.tools.nearby import find_nearby
from app.tools.weather import get_weather

PLACES = ["Ramkund", "Trimbakeshwar Temple", "Nashik Road Railway Station", "Tapovan", "Kushavarta"]
CATS = ["hospital", "police", "toilets", "drinking_water", "food", "parking", "bus_station", "atm", "pharmacy", "lodging"]
ROUTES = [("Nashik Road station", "Ramkund", "driving"), ("Ramkund", "Tapovan", "walking"),
          ("Ramkund", "Trimbakeshwar", "driving"), ("Nashik Airport", "Ramkund", "driving"),
          ("Mahamarg Bus Stand", "Ramkund", "driving"), ("Kalaram Mandir", "Ramkund", "walking"),
          ("Trimbakeshwar Temple", "Kushavarta", "walking")]


async def main():
    for a, b, m in ROUTES:
        r = await get_directions(a, b, m)
        print(f"route {a} -> {b}: {r.get('distance_km')} km {r.get('eta')}")
    for p in PLACES:
        for c in CATS:
            r = await find_nearby(p, c)
            print(f"nearby {c:15s} @ {p}: {len(r.get('results', []))} ({r.get('source')})")
            await asyncio.sleep(1)
    for p in ("Nashik", "Trimbakeshwar"):
        await get_weather(p)
    print("Cache warm.")


if __name__ == "__main__":
    asyncio.run(main())
