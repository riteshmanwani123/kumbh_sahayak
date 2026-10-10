"""Tool schemas (Realtime + Chat Completions formats) and a safe async dispatcher."""
import asyncio
import json
import time

from .directions import get_directions
from .kb import search_kumbh_info
from .nearby import CATEGORIES, find_nearby
from .. import memory
from .tickets import create_ticket, lookup_tickets
from .travel import travel_to_nashik
from .weather import get_weather

TOOLS = [
    {"name": "search_kumbh_info",
     "description": "Search the verified Kumbh Mela knowledge base (dates, Amrut Snan, ghats, akhadas, parking, "
                    "helplines, rules, safety, accommodation, FAQ). ALWAYS call before stating any event fact, "
                    "date, timing, rule or phone number. Query in English works best.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "get_directions",
     "description": "Route between two places in Nashik/Trimbakeshwar. Returns distance, ETA, 3-5 steps and a map "
                    "link shown on the caller's screen. Use landmark names (e.g. 'Nashik Road station', 'Ramkund').",
     "parameters": {"type": "object", "properties": {
         "from_place": {"type": "string", "description": "A named landmark/area the caller actually said "
                        "(e.g. 'Nashik Road station'). Never 'current location' — if unknown, ask the caller first."},
         "to_place": {"type": "string", "description": "Destination landmark"},
         "mode": {"type": "string", "enum": ["walking", "driving"], "description": "Default walking near ghats"}},
         "required": ["from_place", "to_place"]}},
    {"name": "find_nearby",
     "description": "Find the nearest facilities around a landmark, with distance and map links.",
     "parameters": {"type": "object", "properties": {
         "place": {"type": "string", "description": "Landmark or area"},
         "category": {"type": "string", "enum": list(CATEGORIES)}}, "required": ["place", "category"]}},
    {"name": "travel_to_nashik",
     "description": "How to reach Nashik from another city: road distance, train, MSRTC bus, flights, snan-day tips.",
     "parameters": {"type": "object", "properties": {"from_city": {"type": "string"}}, "required": ["from_city"]}},
    {"name": "create_ticket",
     "description": "Log a ticket: lost_found (missing person/item), complaint, or emergency. For emergencies, "
                    "tell the caller to dial 112 FIRST, then call this. Returns a ticket ID to read out.",
     "parameters": {"type": "object", "properties": {
         "type": {"type": "string", "enum": ["lost_found", "complaint", "emergency"]},
         "details": {"type": "string", "description": "Who/what, description, last seen location, contact"},
         "caller_language": {"type": "string", "enum": ["en", "hi", "mr"]}},
         "required": ["type", "details", "caller_language"]}},
    {"name": "remember_caller_details",
     "description": "Save details the caller shares about themselves so you remember them next time: first name, "
                    "preferred language, home city, who they travel with, where they are staying, special needs. "
                    "Call it as soon as they share any of these. Never store phone, ID or payment numbers.",
     "parameters": {"type": "object", "properties": {
         "name": {"type": "string"}, "preferred_language": {"type": "string", "enum": ["en", "hi", "mr"]},
         "home_city": {"type": "string"}, "group_info": {"type": "string", "description": "e.g. with elderly parents"},
         "stay_location": {"type": "string"}, "notes": {"type": "string", "description": "other useful context"}},
         "required": []}},
    {"name": "get_my_tickets",
     "description": "Look up this caller's earlier tickets (lost & found, complaints, emergencies) and their status, "
                    "e.g. when they ask 'what happened to my complaint?'. Optional ticket_id narrows it.",
     "parameters": {"type": "object", "properties": {"ticket_id": {"type": "string"}}, "required": []}},
    {"name": "get_weather",
     "description": "Current weather and 3-day forecast for a place (default Nashik).",
     "parameters": {"type": "object", "properties": {"place": {"type": "string"}}, "required": ["place"]}},
]

TOOL_NAMES = {t["name"] for t in TOOLS}
TIMEOUTS = {"search_kumbh_info": 6, "get_directions": 12, "find_nearby": 20, "travel_to_nashik": 6,
            "create_ticket": 3, "get_weather": 8, "remember_caller_details": 3, "get_my_tickets": 3}
FALLBACK_SPEECH = ("Sorry, that service is slow right now. For any emergency please dial 112. "
                   "Could you tell me a nearby landmark?")


async def _const(v):
    return v


def realtime_tools() -> list[dict]:
    return [{"type": "function", **t} for t in TOOLS]


def chat_tools() -> list[dict]:
    return [{"type": "function", "function": t} for t in TOOLS]


async def run_tool(name: str, args: dict | str | None, session_id: str = "", caller_id: str | None = None) -> dict:
    """Never raises: returns {"ok": False, "error", "spoken_fallback"} on failure."""
    t0 = time.perf_counter()
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except json.JSONDecodeError:
            args = {}
    args = args or {}
    if name not in TOOL_NAMES:
        return {"ok": False, "error": f"Unknown tool {name}", "spoken_fallback": FALLBACK_SPEECH}
    if caller_id is None and session_id:
        caller_id = await asyncio.to_thread(memory.caller_for_session, session_id)
    try:
        if name == "search_kumbh_info":
            coro = asyncio.to_thread(search_kumbh_info, args.get("query", ""))
        elif name == "get_directions":
            coro = get_directions(args.get("from_place", ""), args.get("to_place", ""), args.get("mode", "walking"))
        elif name == "find_nearby":
            coro = find_nearby(args.get("place", ""), args.get("category", ""))
        elif name == "travel_to_nashik":
            coro = asyncio.to_thread(travel_to_nashik, args.get("from_city", ""))
        elif name == "create_ticket":
            coro = asyncio.to_thread(create_ticket, args.get("type", ""), args.get("details", ""),
                                     args.get("caller_language", "en"), session_id, None, caller_id)
        elif name == "remember_caller_details":
            coro = (asyncio.to_thread(memory.update_profile, caller_id, **args) if caller_id
                    else _const({"ok": False, "error": "caller not identified"}))
        elif name == "get_my_tickets":
            coro = asyncio.to_thread(lookup_tickets, caller_id, args.get("ticket_id", ""))
        else:
            coro = get_weather(args.get("place", "Nashik"))
        result = await asyncio.wait_for(coro, TIMEOUTS[name])
    except asyncio.TimeoutError:
        result = {"ok": False, "error": "timeout"}
    except Exception as e:  # noqa: BLE001 — tool failures must never crash a call
        result = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    if not result.get("ok"):
        result.setdefault("spoken_fallback", FALLBACK_SPEECH)
    result["_ms"] = int((time.perf_counter() - t0) * 1000)
    return result
