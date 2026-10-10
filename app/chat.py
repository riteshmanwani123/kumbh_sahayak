"""Text chat: real OpenAI tool-calling loop when a key exists, otherwise a rule-based mock LLM that
exercises the same tools so the whole pipeline can be demoed without a key."""
import json
import re

import asyncio

from . import config, memory
from .prompts import system_prompt
from .session_log import log_event
from .tools.geocode import GAZETTEER, _norm
from .tools.nearby import ALIASES as CAT_ALIASES, CATEGORIES
from .tools.registry import chat_tools, run_tool
from .tools.travel import match_city

# ---------------- language detection ----------------
MR_MARKERS = {"आहे", "आहेत", "कुठे", "मला", "कसे", "कसा", "काय", "कधी", "आम्ही", "माझा", "माझी", "माझे", "जायचे",
              "हरवला", "हरवली", "हरवले", "पाहिजे", "जवळ", "नाही", "होईल", "आणि", "करा", "सांगा", "किती", "मध्ये",
              "aahe", "kuthe", "mala", "kasa", "kase", "kadhi", "pahije", "javal", "javal", "sanga", "kiti", "harvla"}
HI_MARKERS = {"है", "हैं", "कहाँ", "कहां", "मुझे", "कैसे", "क्या", "कब", "मेरा", "मेरी", "जाना", "खो", "गया", "गई",
              "चाहिए", "पास", "नहीं", "और", "बताइए", "बताओ", "कितना", "में", "hai", "kahan", "kaha", "mujhe", "kaise",
              "kya", "kab", "mera", "meri", "jana", "chahiye", "paas", "nahi", "batao", "bataiye", "kitna", "hain",
              "hoon", "hun", "hu", "par", "pe", "aana", "jaana", "kaun", "kidhar", "abhi", "humko", "hume"}


def detect_language(text: str, previous: str | None = None) -> str:
    """Script + marker-word heuristic. With no signal at all, keep the caller's previous language."""
    words = set(re.findall(r"[\wऀ-ॿ]+", (text or "").lower()))
    mr, hi = len(words & MR_MARKERS), len(words & HI_MARKERS)
    has_deva = bool(re.search(r"[ऀ-ॿ]", text or ""))
    if mr > hi:
        return "mr"
    if hi > mr or (has_deva and hi == mr == 0):
        return "hi"
    if mr and mr == hi:
        return "mr"
    if previous and not re.search(r"\b(the|is|are|what|where|how|when|can|please|i|my|we)\b", (text or "").lower()):
        return previous
    return "en"


# ---------------- mock LLM ----------------
EMERGENCY_WORDS = ["emergency", "accident", "injured", "bleeding", "heart attack", "chest pain", "unconscious",
                   "fire", "stampede", "drowning", "drown", "help me", "theft", "stolen", "attack", "fainted",
                   "बचाओ", "मदद करो", "आग", "दुर्घटना", "बेहोश", "चोरी", "भगदड़", "डूब", "घायल", "हार्ट",
                   "अपघात", "वाचवा", "आग लागली", "बेशुद्ध", "बुडत", "जखमी", "चेंगराचेंगरी", "behosh", "aag", "bachao"]
LOST_WORDS = ["lost", "missing", "khoya", "kho gaya", "kho gayi", "gum", "खो गया", "खो गई", "खोया", "गुम",
              "लापता", "हरवला", "हरवली", "हरवले", "सापडत नाही", "harvla", "harvli"]
DIRECTION_WORDS = ["how to reach", "how do i get", "how to go", "route", "directions", "way to", "rasta", "raasta",
                   "kaise jaun", "kaise jaye", "kaise jayen", "kaise pahuche", "रास्ता", "कैसे जाऊं", "कैसे जाएं",
                   "कैसे पहुंच", "कसे जायचे", "कसे जाऊ", "रस्ता", "मार्ग", "kase jaycha", "kasa jaycha", "jana hai",
                   "जाना है", "जायचे आहे", "kitna door", "कितनी दूर", "किती दूर", "how far"]
WEATHER_WORDS = ["weather", "rain", "temperature", "mausam", "baarish", "मौसम", "बारिश", "हवामान", "पाऊस", "तापमान"]
TRAVEL_WORDS = ["coming from", "come from", "travel from", "train from", "bus from", "reach nashik", "get to nashik",
                "se nashik", "से नासिक", "से नाशिक", "पासून नाशिक", "nashik kaise", "नासिक कैसे", "नाशिकला कसे",
                "to nashik", "nashik aana", "nashik ana", "आना है", "यायचे"]
COMPLAINT_WORDS = ["complaint", "shikayat", "शिकायत", "तक्रार", "takrar", "dirty", "gande", "गंदे", "घाण", "ghaan"]
STATUS_WORDS = ["kya hua", "status", "what happened", "क्या हुआ", "काय झाले", "kay zala", "my ticket", "meri complaint",
                "मेरी शिकायत", "माझी तक्रार"]
NAME_RE = re.compile(r"(?:my name is|mera naam|मेरा नाम|माझे नाव|maza nav|majha nav)\s+([A-Za-z\u0900-\u097F]+)", re.I)
NEARBY_WORDS = ["nearest", "nearby", "near me", "close", "where is the", "paas", "najdik", "पास", "नजदीक",
                "जवळ", "jawal", "javal", "kahan hai", "कहाँ है", "कहां है", "कुठे आहे", "find"]

T = {  # reply templates
    "emergency": {
        "en": "Please dial 112 right now for emergency help (ambulance 108). I've logged ticket {tid}. What is the nearest landmark?",
        "hi": "कृपया अभी 112 पर कॉल करें (एम्बुलेंस 108)। मैंने टिकट {tid} दर्ज कर लिया है। आप किस जगह के पास हैं?",
        "mr": "कृपया आत्ताच 112 वर फोन करा (रुग्णवाहिका 108). मी तिकीट {tid} नोंदवले आहे. तुम्ही कोणत्या ठिकाणाजवळ आहात?"},
    "lost": {
        "en": "Please call 112 now and tell the nearest police officer; for a child also call 1098. I've logged ticket {tid}. What is the person wearing and where were they last seen?",
        "hi": "कृपया अभी 112 पर कॉल करें और पास के पुलिसकर्मी को बताएं; बच्चा हो तो 1098 पर भी। टिकट नंबर {tid} दर्ज है। उन्होंने क्या पहना था और आखिरी बार कहाँ देखा?",
        "mr": "कृपया आत्ता 112 वर फोन करा आणि जवळच्या पोलिसांना सांगा; लहान मूल असल्यास 1098 वरही. तिकीट क्रमांक {tid} नोंदवला आहे. त्यांनी काय कपडे घातले होते आणि शेवटचे कुठे दिसले?"},
    "ask_landmark": {
        "en": "Sure. Which landmark or area are you near right now?",
        "hi": "ज़रूर। आप अभी किस जगह या लैंडमार्क के पास हैं?",
        "mr": "नक्की. तुम्ही आत्ता कोणत्या ठिकाणाजवळ आहात?"},
    "directions": {
        "en": "From {frm} to {to} is about {km} km, roughly {eta} {mode}. {step} I've sent the map link to your screen.",
        "hi": "{frm} से {to} लगभग {km} किमी है, {mode} करीब {eta}। {step} मैप लिंक आपकी स्क्रीन पर भेज दिया है।",
        "mr": "{frm} पासून {to} सुमारे {km} किमी आहे, {mode} साधारण {eta}. {step} नकाशाची लिंक तुमच्या स्क्रीनवर पाठवली आहे."},
    "nearby": {
        "en": "The nearest {cat} is {name}, about {dist}. I've put {n} options with map links on your screen.",
        "hi": "सबसे नज़दीकी {cat} {name} है, लगभग {dist} दूर। {n} विकल्प मैप लिंक के साथ स्क्रीन पर हैं।",
        "mr": "सर्वात जवळचे {cat} {name} आहे, सुमारे {dist} अंतरावर. {n} पर्याय नकाशा लिंकसह स्क्रीनवर आहेत."},
    "nearby_none": {
        "en": "Sorry, I couldn't find that nearby right now. For emergencies dial 112.",
        "hi": "माफ़ कीजिए, अभी पास में यह नहीं मिला। आपात स्थिति में 112 डायल करें।",
        "mr": "माफ करा, आत्ता जवळ हे सापडले नाही. आपत्कालीन स्थितीत 112 डायल करा."},
    "travel": {
        "en": "From {city}, Nashik is about {km} km by road. {best} Trains come to Nashik Road station; MSRTC buses also run.",
        "hi": "{city} से नासिक सड़क से लगभग {km} किमी है। {best} ट्रेन नासिक रोड स्टेशन आती है, MSRTC बसें भी चलती हैं।",
        "mr": "{city} पासून नाशिक रस्त्याने सुमारे {km} किमी आहे. {best} रेल्वे नाशिक रोड स्टेशनला येते, एसटी बसेसही आहेत."},
    "weather": {
        "en": "In {place} it is {temp}°C with {summary} right now. Rain chance today is {rain}%.",
        "hi": "{place} में अभी {temp}°C है, {summary}। आज बारिश की संभावना {rain}% है।",
        "mr": "{place} मध्ये आत्ता {temp}°C आहे, {summary}. आज पावसाची शक्यता {rain}% आहे."},
    "not_found": {
        "en": "Sorry, I don't have verified information on that yet. For emergencies dial 112; official updates are on divcomnashik.maharashtra.gov.in.",
        "hi": "माफ़ कीजिए, इसकी पक्की जानकारी अभी मेरे पास नहीं है। आपात स्थिति में 112 डायल करें; आधिकारिक जानकारी divcomnashik.maharashtra.gov.in पर है।",
        "mr": "माफ करा, याची खात्रीशीर माहिती अजून माझ्याकडे नाही. आपत्कालीन स्थितीत 112 डायल करा; अधिकृत माहिती divcomnashik.maharashtra.gov.in वर आहे."},
    "remembered": {
        "en": "Namaste {name} ji, welcome. How can I help you today?",
        "hi": "नमस्ते {name} जी, आपका स्वागत है। बताइए, मैं क्या मदद करूँ?",
        "mr": "नमस्कार {name} जी, स्वागत आहे. सांगा, काय मदत करू?"},
    "complaint": {
        "en": "Your complaint is registered. Ticket ID: {tid}.",
        "hi": "आपकी शिकायत दर्ज हो गई है। टिकट नंबर: {tid}।",
        "mr": "तुमची तक्रार नोंदवली आहे. तिकीट क्रमांक: {tid}."},
    "status": {
        "en": "Your ticket {tid} is still {status}; no officer update yet. For urgent help dial 112.",
        "hi": "आपका टिकट {tid} अभी {status} है; अभी कोई अपडेट नहीं आया। ज़रूरी मदद के लिए 112 डायल करें।",
        "mr": "तुमचे तिकीट {tid} अजून {status} आहे; अजून अपडेट नाही. तातडीच्या मदतीसाठी 112 डायल करा."},
    "no_tickets": {
        "en": "I don't find any earlier ticket for you. Could you read out the ticket ID?",
        "hi": "आपका कोई पुराना टिकट नहीं मिला। क्या आप टिकट नंबर बता सकते हैं?",
        "mr": "तुमचे कोणतेही आधीचे तिकीट सापडले नाही. तिकीट क्रमांक सांगाल का?"},
    "fallback": {
        "en": "Sorry, that service is slow right now. For emergencies dial 112. Could you tell me a nearby landmark?",
        "hi": "माफ़ कीजिए, अभी सेवा धीमी है। आपात स्थिति में 112 डायल करें। कोई पास का लैंडमार्क बताइए?",
        "mr": "माफ करा, सेवा आत्ता संथ आहे. आपत्कालीन स्थितीत 112 डायल करा. जवळचे एखादे ठिकाण सांगाल का?"},
}
BEST = {
    "Road (MSRTC bus or car) or train — both practical.":
        {"hi": "सड़क (MSRTC बस या कार) या ट्रेन — दोनों ठीक हैं।", "mr": "रस्ता (एसटी बस किंवा कार) किंवा रेल्वे — दोन्ही सोयीचे."},
    "Overnight train or bus; driving is long.":
        {"hi": "रात की ट्रेन या बस बेहतर है; गाड़ी से सफर लंबा है।", "mr": "रात्रीची रेल्वे किंवा बस चांगली; गाडीने प्रवास लांब आहे."},
    "Train is usually most practical; book early.":
        {"hi": "ट्रेन सबसे सुविधाजनक है; जल्दी बुकिंग करें।", "mr": "रेल्वे सर्वात सोयीची; लवकर बुकिंग करा."},
}
SKY = {"clear sky": {"hi": "आसमान साफ़", "mr": "आकाश निरभ्र"}, "mainly clear": {"hi": "ज़्यादातर साफ़", "mr": "बहुतांश निरभ्र"},
       "partly cloudy": {"hi": "हल्के बादल", "mr": "अंशतः ढगाळ"}, "overcast": {"hi": "बादल छाए", "mr": "ढगाळ"},
       "light drizzle": {"hi": "हल्की बूंदाबांदी", "mr": "हलकी रिमझिम"}, "drizzle": {"hi": "बूंदाबांदी", "mr": "रिमझिम"},
       "light rain": {"hi": "हल्की बारिश", "mr": "हलका पाऊस"}, "rain": {"hi": "बारिश", "mr": "पाऊस"},
       "heavy rain": {"hi": "तेज़ बारिश", "mr": "मुसळधार पाऊस"}, "rain showers": {"hi": "बौछारें", "mr": "सरी"},
       "thunderstorm": {"hi": "आंधी-तूफ़ान", "mr": "वादळी पाऊस"}}


def _loc(table: dict, s: str, lang: str) -> str:
    return table.get(s, {}).get(lang, s) if lang != "en" else s


def _loc_eta(eta: str, lang: str) -> str:
    if lang == "en":
        return eta
    return eta.replace(" h ", {"hi": " घंटे ", "mr": " तास "}[lang]).replace("min", {"hi": "मिनट", "mr": "मिनिटे"}[lang])


MODE_WORD = {"walking": {"en": "on foot", "hi": "पैदल", "mr": "पायी"},
             "driving": {"en": "by road", "hi": "गाड़ी से", "mr": "गाडीने"}}
CAT_WORD = {"hospital": {"hi": "अस्पताल", "mr": "रुग्णालय"}, "toilets": {"hi": "शौचालय", "mr": "शौचालय"},
            "police": {"hi": "पुलिस स्टेशन", "mr": "पोलीस स्टेशन"}, "drinking_water": {"hi": "पीने का पानी", "mr": "पिण्याचे पाणी"},
            "food": {"hi": "खाने की जगह", "mr": "जेवणाचे ठिकाण"}, "parking": {"hi": "पार्किंग", "mr": "पार्किंग"},
            "atm": {"hi": "एटीएम", "mr": "एटीएम"}, "pharmacy": {"hi": "दवा की दुकान", "mr": "मेडिकल"}}


def _has(text: str, words: list[str]) -> bool:
    """Latin keywords match on word boundaries (so 'train' != 'rain'); Devanagari ones as substrings."""
    t = (text or "").lower()
    for w in (w.strip() for w in words):
        if re.search(r"[a-z]", w):
            if re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", t):
                return True
        elif w in t:
            return True
    return False


def places_in_order(text: str) -> list[str]:
    """Gazetteer places mentioned in the text, in order of appearance (for from/to extraction)."""
    t = _norm(text)
    found = []
    for name, _, _, aliases in GAZETTEER:
        best = None
        for a in aliases:
            a_n = _norm(a)
            if a_n and (i := t.find(a_n)) >= 0 and (best is None or len(a_n) > best[1]):
                best = (i, len(a_n))
        if best:
            found.append((best[0], -best[1], name))
    found.sort()
    out, spans = [], []
    for i, neg_len, name in found:  # drop places nested inside a longer match (e.g. "trimbak" in "trimbakeshwar")
        if any(s <= i < e for s, e in spans):
            continue
        spans.append((i, i - neg_len))
        out.append(name)
    return out


def _category(text: str) -> str | None:
    t = (text or "").lower()
    for c in CATEGORIES:
        if c.replace("_", " ") in t or c.rstrip("s") in t:
            return c
    for k, v in sorted(CAT_ALIASES.items(), key=lambda kv: -len(kv[0])):
        if k in t:
            return v
    return None


def _fmt_dist(m: int | None) -> str:
    if m is None:
        return "?"
    return f"{m / 1000:.1f} km" if m >= 1000 else f"{int(round(m, -1))} m"


def _faq_answer(passages: list[dict], lang: str) -> str | None:
    tag = {"en": "(EN)", "hi": "(HI)", "mr": "(MR)"}[lang]
    for p in passages:
        if tag in p["text"].split("\n", 1)[0]:
            m = re.search(r"\nA:\s*(.+)", p["text"])
            if m:
                return m.group(1).strip()
    return None


class MockLLM:
    """Deterministic intent router. Same tool calls as the real model would make."""

    def __init__(self):
        self.state: dict[str, dict] = {}

    @staticmethod
    async def _directions(call, st, lang, frm, to) -> str | None:
        st["last_place"] = frm
        far = any(k in (frm + to).lower() for k in ("trimbak", "kushavarta", "airport", "station", "igatpuri", "nashik city"))
        res = await call("get_directions", from_place=frm, to_place=to, mode="driving" if far else "walking")
        if not res.get("ok"):
            return None
        step = (res.get("steps") or [""])[0]
        return T["directions"][lang].format(
            frm=res["from"].split(",")[0], to=res["to"].split(",")[0], km=res["distance_km"], eta=_loc_eta(res["eta"], lang),
            mode=MODE_WORD[res["mode"]][lang], step=step + "." if lang == "en" else "")

    async def respond(self, session_id: str, text: str) -> dict:
        st = self.state.setdefault(session_id, {})
        lang = st["lang"] = detect_language(text, st.get("lang"))
        calls: list[dict] = []

        async def call(_tool, **args):
            res = await run_tool(_tool, args, session_id)  # caller resolved from the session in run_tool
            calls.append({"name": _tool, "args": args, "result": res})
            log_event(session_id, "tool", name=_tool, args=args, result=res)
            return res

        places = places_in_order(text)
        reply = None

        if (m := NAME_RE.search(text)) and not _has(text, EMERGENCY_WORDS + LOST_WORDS):
            city = match_city(text)
            await call("remember_caller_details", name=m.group(1).title(), preferred_language=lang,
                       **({"home_city": city} if city else {}))
            reply = T["remembered"][lang].format(name=m.group(1).title())
        elif _has(text, STATUS_WORDS):
            res = await call("get_my_tickets")
            t = (res.get("tickets") or [None])[0]
            reply = T["status"][lang].format(tid=t["ticket_id"], status=t["status"]) if t else T["no_tickets"][lang]
        elif _has(text, COMPLAINT_WORDS) and not _has(text, EMERGENCY_WORDS):
            res = await call("create_ticket", type="complaint", details=text, caller_language=lang)
            reply = T["complaint"][lang].format(tid=res.get("ticket_id", "—"))
        elif _has(text, EMERGENCY_WORDS):
            res = await call("create_ticket", type="emergency", details=text, caller_language=lang)
            reply = T["emergency"][lang].format(tid=res.get("ticket_id", "—"))
        elif _has(text, LOST_WORDS):
            res = await call("create_ticket", type="lost_found", details=text, caller_language=lang)
            reply = T["lost"][lang].format(tid=res.get("ticket_id", "—"))
        elif st.get("pending_to") and places:
            reply = await self._directions(call, st, lang, places[0], st.pop("pending_to"))
        elif _has(text, WEATHER_WORDS):
            res = await call("get_weather", place=places[0] if places else "Nashik")
            if res.get("ok"):
                today = (res.get("forecast") or [{}])[0]
                reply = T["weather"][lang].format(place=res["place"].split(",")[0], temp=res["now"]["temp_c"],
                                                  summary=_loc(SKY, res["now"]["summary"], lang), rain=today.get("rain_chance_pct", "?"))
        elif (city := match_city(text)) and (_has(text, TRAVEL_WORDS) or not places):
            res = await call("travel_to_nashik", from_city=city)
            reply = T["travel"][lang].format(city=city, km=res.get("road_distance_km", "?"),
                                             best=_loc(BEST, res.get("best_option", ""), lang))
        elif (cat := _category(text)) and (_has(text, NEARBY_WORDS) or places):
            place = places[0] if places else st.get("last_place", "Ramkund")
            res = await call("find_nearby", place=place, category=cat)
            if res.get("ok") and res.get("results"):
                top = res["results"][0]
                reply = T["nearby"][lang].format(cat=CAT_WORD.get(cat, {}).get(lang, cat.replace("_", " ")),
                                                 name=top["name"], dist=_fmt_dist(top.get("distance_m")),
                                                 n=len(res["results"]))
            elif res.get("ok"):
                reply = T["nearby_none"][lang]
        elif _has(text, DIRECTION_WORDS):
            if len(places) >= 2:
                reply = await self._directions(call, st, lang, places[0], places[1])
            elif len(places) == 1:
                st["pending_to"] = places[0]
                reply = T["ask_landmark"][lang]
            else:
                reply = T["ask_landmark"][lang]
        if reply is None and not calls:
            q = text
            res = await call("search_kumbh_info", query=q)
            if res.get("found"):
                reply = _faq_answer(res["passages"], lang)
                if reply and _has(text, ["and", "aur", "और", "आणि", "ani"]):
                    # Two questions in one turn: also answer the second via a narrower search.
                    second = re.split(r"\band\b|\baur\b|और|आणि|\bani\b", text, maxsplit=1)[0]
                    res2 = await call("search_kumbh_info", query=second)
                    extra = _faq_answer(res2.get("passages", []), lang) if res2.get("found") else None
                    if extra and extra != reply:
                        reply = extra + " " + reply
                if not reply:
                    body = res["passages"][0]["text"].split("\n", 1)[-1]
                    lines = [l.strip("-* |") for l in body.splitlines() if len(l.strip()) > 25]
                    reply = (" ".join(lines[:2]) or body)[:350]
            else:
                reply = T["not_found"][lang]
        if reply is None:
            reply = T["fallback"][lang]
        if places:
            st["last_place"] = places[0]
        return {"reply": reply, "language": lang, "tool_calls": calls}


# ---------------- real OpenAI ----------------
class OpenAIChat:
    def __init__(self):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=config.openai_key())
        self.history: dict[str, list] = {}

    async def respond(self, session_id: str, text: str, caller_id: str = "") -> dict:
        msgs = self.history.get(session_id)
        if msgs is None:
            ctx = await asyncio.to_thread(memory.build_context, caller_id, session_id) if caller_id else ""
            msgs = [{"role": "system", "content": system_prompt(ctx, channel="text")}]
            # After a server restart, rebuild this session's turns from the database.
            for m in (await asyncio.to_thread(memory.session_messages, session_id))[-12:-1]:
                msgs.append({"role": m["role"], "content": m["text"]})
            self.history[session_id] = msgs
        msgs.append({"role": "user", "content": text})
        calls = []
        for _ in range(5):
            resp = await self.client.chat.completions.create(model=config.TEXT_MODEL, messages=msgs,
                                                             tools=chat_tools())
            m = resp.choices[0].message
            msgs.append(m.model_dump(exclude_none=True))
            if not m.tool_calls:
                if len(msgs) > 30:  # keep context small, but never split a tool call from its result
                    cut = len(msgs) - 20
                    while cut < len(msgs) and msgs[cut]["role"] != "user":
                        cut += 1
                    del msgs[1:cut]
                return {"reply": m.content or "", "language": detect_language(m.content or text),
                        "tool_calls": calls}
            for tc in m.tool_calls:
                res = await run_tool(tc.function.name, tc.function.arguments, session_id, caller_id or None)
                args = json.loads(tc.function.arguments or "{}")
                calls.append({"name": tc.function.name, "args": args, "result": res})
                log_event(session_id, "tool", name=tc.function.name, args=args, result=res)
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(res, ensure_ascii=False)})
        return {"reply": T["fallback"]["en"], "language": "en", "tool_calls": calls}


_mock, _real = MockLLM(), None


async def _safe_mock(session_id: str, text: str) -> dict:
    try:
        return await _mock.respond(session_id, text)
    except Exception as e:  # noqa: BLE001 — a demo must never crash mid-call
        log_event(session_id, "error", where="mock", error=f"{type(e).__name__}: {str(e)[:200]}")
        lang = detect_language(text)
        return {"reply": T["fallback"][lang], "language": lang, "tool_calls": []}


async def chat(session_id: str, text: str, force_mock: bool = False, caller_id: str = "") -> dict:
    global _real
    log_event(session_id, "user", text=text)
    if caller_id:
        await asyncio.to_thread(memory.start_session, caller_id, session_id, "text")
    await asyncio.to_thread(memory.add_message, session_id, "user", text, detect_language(text))
    if config.has_key() and not force_mock:
        if _real is None:
            _real = OpenAIChat()
        try:
            out = await _real.respond(session_id, text, caller_id)
            out["mode"] = "openai"
        except Exception as e:  # noqa: BLE001
            log_event(session_id, "error", where="openai_chat", error=f"{type(e).__name__}: {str(e)[:200]}")
            out = await _safe_mock(session_id, text)
            out["mode"] = "mock (OpenAI error fallback)"
    else:
        out = await _safe_mock(session_id, text)
        out["mode"] = "mock"
    out["reply"] = re.sub(r"\*\*|__|^#+\s*", "", out["reply"], flags=re.M).strip()  # spoken/plain text only
    log_event(session_id, "assistant", text=out["reply"], language=out["language"], mode=out["mode"])
    await asyncio.to_thread(memory.add_message, session_id, "assistant", out["reply"])
    return out
