# Kumbh Sahayak — AI voice assistant for the Nashik–Trimbakeshwar Simhastha Kumbh Mela (demo)

A browser-based voice helpline for pilgrims that **remembers returning callers**. Callers speak in Hindi, Marathi or English (including mixed speech) and get event info, directions, nearby facilities, travel guidance, weather and emergency help. Map links and tickets appear on screen; for this demo they replace SMS.

**Only paid API: OpenAI.** Maps, routing, places and weather all use free, keyless services (OpenStreetMap Nominatim / Photon / Overpass, OSRM, Open-Meteo).

## Architecture

```
                          Browser (index.html + app.js)
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  🎙 mic ──WebRTC audio──►┐                    ┌──► 🔊 speaker               │
  │                          │   OpenAI Realtime  │                           │
  │  data channel "oai-events" ◄──── events ──────┘  (gpt-realtime-2.1,       │
  │     • transcripts → live transcript + language pill   voice "marin")       │
  │     • response.done{function_call} ─┐                                      │
  │  side panel ◄── cards ──────────────┤                                      │
  └─────────────────────────────────────┼──────────────────────────────────────┘
        ① POST /api/realtime/token      │ ③ POST /api/tools {name,args}
           (ephemeral ek_… key, 10 min) │    → function_call_output → response.create
                                        ▼
  ┌──────────────────────── FastAPI backend (app/) ──────────────────────────┐
  │  realtime.py  mints client secret with the system prompt + 6 tool schemas │
  │               (the real OPENAI_API_KEY never leaves the server)           │
  │  tools/registry.py ── timeouts, never-raise, spoken fallback ──┐          │
  │    search_kumbh_info ── kb.py: Markdown chunks → embeddings (numpy)       │
  │                          └ BM25 keyword fallback (no key / stale index)   │
  │    get_directions ──── geocode.py (curated gazetteer → Nominatim)         │
  │                        + OSRM car / FOSSGIS foot routing                  │
  │    find_nearby ─────── Photon ∥ Overpass (mirrors) → Nominatim → verified │
  │    travel_to_nashik ── city distance table (OSRM-computed) + KB           │
  │    create_ticket ───── SQLite data/tickets.sqlite                         │
  │    get_weather ─────── Open-Meteo                                         │
  │  net.py: shared HTTP client, SQLite TTL cache, per-host rate limiting     │
  │    remember_caller_details / get_my_tickets ── memory.py                 │
  │  memory.py: data/kumbh.sqlite — callers, sessions (+AI summary), messages │
  │             → "returning caller" brief injected into the next session    │
  │  session_log.py: data/logs/<date>_<session>.jsonl (secrets scrubbed)      │
  │  chat.py: text mode → OpenAI tool loop (key) or rule-based Mock LLM       │
  └───────────────────────────────────────────────────────────────────────────┘
        ② browser POSTs its SDP offer to https://api.openai.com/v1/realtime/calls
           with the ephemeral key and gets the SDP answer
```

## Caller memory (recognises prior context)
- Each browser gets an anonymous caller ID (kept in `localStorage`). There's no phone number in a browser demo, so this stands in for caller ID.
- `data/kumbh.sqlite` stores, per caller, a **profile** (name, language, home city, group, where staying, notes), every **session** with a 2-sentence AI summary written at hang-up, every **message**, and linked **tickets**.
- When a call or chat starts, a short "returning caller" brief (profile, last 3 session summaries, open tickets) is added to the model's instructions. It greets them by name and follows up on anything unresolved. If they ask "what happened to my complaint?", it calls `get_my_tickets`.
- The model saves details with `remember_caller_details` when a caller shares them. It never stores phone, ID or payment numbers.
- The "Sahayak remembers" panel shows what is stored, and **Forget me** deletes it all (`DELETE /api/caller/{id}`).
- Event facts never come from memory. They always come from the knowledge base, and the core dates are pinned in the system prompt.

## Setup

```bash
cd ai-voice-assistant
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env        # then put your key in .env (see below)
```

## Run

```bash
./run.sh
```

- Voice: **http://localhost:8000** (needs `OPENAI_API_KEY`; the browser asks for microphone access)
- Text: **http://localhost:8000/chat** (works without a key using the Mock LLM, which calls the real tools)
- Terminal chat: `.venv/bin/python -m scripts.chat_cli`

### Without a key ("no-key mode")
Everything except voice works: the text page and CLI use a rule-based mock LLM that detects language and intent and calls the real tools (maps, weather, tickets, KB keyword search). The voice page shows a banner pointing to text mode.

### When you have the key
```bash
# 1. put OPENAI_API_KEY=sk-... in .env   (never commit .env — it's in .gitignore)
.venv/bin/python -m scripts.build_index              # 2. embeddings for the knowledge base
.venv/bin/python -m scripts.run_demo_conversations   # 3. 10 demos through the real model
./run.sh                                             # 4. open http://localhost:8000 and press Call
```
Re-run `build_index` after editing anything in `knowledge/`. Until you do, the app uses keyword search, which still works.

## Tests

```bash
.venv/bin/python -m pytest              # 59 offline unit tests (HTTP mocked)
.venv/bin/python -m pytest -m live      # hits the real free map/weather APIs
.venv/bin/python -m scripts.run_demo_conversations --mock
.venv/bin/python -m scripts.warm_cache  # pre-fetch map data for demo landmarks (recommended before a live demo)
```

## Demo script — 11 test conversations
Last real-model run (Oct 2026): **11/11 pass** with `gpt-5.4-mini` text, and live voice was verified end to end with `gpt-realtime-2.1`.

These are also clickable chips on `/chat` and are run by `scripts/run_demo_conversations.py`.

| # | Lang | Caller says | Expected |
|---|---|---|---|
| 1 | EN | "When is the first Amrut Snan, and where is the main ghat?" | 2 Aug 2027; Ramkund (Nashik) / Kushavarta (Trimbak) — `search_kumbh_info` |
| 2 | HI | "शाही स्नान की तारीखें क्या हैं?" | 2 Aug, 31 Aug, 11/12 Sep 2027 in Hindi |
| 3 | MR | "रामकुंड जवळ हॉस्पिटल कुठे आहे?" | nearest hospitals, distances, map links — `find_nearby` |
| 4 | Hinglish, **directions** | "Mujhe Ramkund jana hai, rasta batao" → "Main Nashik Road station par hoon" | asks for landmark, then ~12 km route + map card — `get_directions` |
| 5 | HI, **EMERGENCY** | "मदद करो! मेरी माँ बेहोश हो गई है, हम रामकुंड के पास हैं" | **112 first**, ambulance 108, ticket ID — `create_ticket` |
| 6 | MR, lost child | "माझा मुलगा हरवला आहे, तो 8 वर्षांचा आहे, लाल शर्ट…" | 112 + 1098, lost & found ticket |
| 7 | EN | "I am coming from Indore with my parents. How do we reach Nashik?" | ~416 km, overnight train/bus — `travel_to_nashik` |
| 8 | Hinglish | "Delhi se Nashik kaise aana hai? Train best hai kya?" | ~1,145 km, train recommended |
| 9 | MR | "त्र्यंबकेश्वरला आज हवामान कसे आहे?" | live temperature + rain chance — `get_weather` |
| 10 | EN | "Is there a special Kumbh helpline number?" → "Can I drive my car to Ramkund on snan day?" | "not announced yet, dial 112"; outer parking + shuttle |
| 11 | Hinglish, **memory** | Call 1: "Mera naam Sunita hai, Pune se maa ke saath…" → "Ramkund ke toilets gande hain, complaint likhiye". Call 2: "Meri complaint ka kya hua?" | remembers Sunita, complaint ticket, then on the next call looks up the same ticket ID |

Things to try live in voice: interrupt it mid-sentence, switch language mid-call, ask for something not in the KB (e.g. "VIP darshan ticket price?"). It should say it has no verified info.

## Knowledge base (`knowledge/`)
- `01_event_overview.md`, `02_dates_calendar.md`, `03_key_sites.md` (with coordinates), `04_getting_there.md` (rail, bus, air, road; distances from 25 cities), `05_parking_traffic.md`, `06_emergency_helplines.md`, `07_safety_dos_donts.md`, `08_accommodation.md`, `faq.md` (42 Q&A: 14 topics × EN/HI/MR), `SOURCES.md`
- Every fact has a source URL and an "as of" date. Anything not from an official or news source is marked **[UNVERIFIED]**, and unannounced items are marked **to be announced**.
- **Dates check:** the official schedule (PTI, 1 Jun 2025, reconfirmed Sep 2026) is: flag hoisting 31 Oct 2026, 12:02 pm; Amrut Snans on 2 Aug, 31 Aug and 11 Sep 2027 (Nashik) / 12 Sep 2027 (Trimbakeshwar); close 24 Jul 2028. Two of the provided links (trimbakeshwartemplepujari.com, trimbakeshwardoshnivarankendra.com) list outdated dates (26 Aug, 13/18/25 Sep 2027) and are excluded.

## Configuration (`.env`)
| Var | Default | Notes |
|---|---|---|
| `OPENAI_API_KEY` | — | required for voice, embeddings and real text mode |
| `REALTIME_MODEL` | `gpt-realtime-2.1` | current per OpenAI docs (Oct 2026); `gpt-realtime-2.1-mini` is cheaper |
| `REALTIME_VOICE` | `marin` | OpenAI recommends `marin` or `cedar` |
| `TRANSCRIBE_MODEL` | `gpt-4o-mini-transcribe` | used for the on-screen user transcript |
| `TEXT_MODEL` | `gpt-5.4-mini` | text mode |
| `TURN_DETECTION` | `server_vad` | `semantic_vad` waits longer for pauses |
| `DEMO_ACCESS_CODE` | empty | **set this before deploying publicly**; the voice token endpoint then requires it |
| `HTTP_USER_AGENT` | generic | put a contact email in it (Nominatim usage policy) |

## Deploying
The app is a single container (`Dockerfile`), so any host with HTTPS works, for example Render, Railway, Fly.io or a VPS behind Caddy. Browsers only allow the microphone on **HTTPS** (or localhost).
```bash
docker build -t kumbh-sahayak .
docker run -p 8000:8000 --env-file .env kumbh-sahayak
```
On a PaaS: set `OPENAI_API_KEY`, `DEMO_ACCESS_CODE` and `HTTP_USER_AGENT` as environment variables. The platform's `PORT` is honoured. Mount a volume at `/app/data` if you want tickets and logs to survive restarts.

## Known limits (demo)
- No phone number: this is a browser call. For a real phone line, the next step is SIP → OpenAI Realtime (or Exotel/Plivo), which needs KYC.
- Free OSM services have rate limits and occasional outages: Overpass was down during development. Tools time out quickly and fall back to other sources, and responses are cached. Run `scripts.warm_cache` before demos. For production, self-host OSRM / Nominatim / Overpass with an India extract.
- Kumbh-specific facilities (medical camps, khoya-paya centres, final parking lots) aren't published yet, so the assistant says "to be announced".
- Tickets are local demo records, not official complaints.
