"""FastAPI app: voice page, text-chat page, realtime token minting, tool relay, chat, logs."""
import asyncio
import hashlib
import secrets

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, memory
from .chat import chat, detect_language
from .prompts import greeting_instruction
from .realtime import mint_client_secret
from .session_log import log_event
from .tools.kb import index_status
from .tools.registry import TOOL_NAMES, run_tool
from .tools.tickets import list_tickets

app = FastAPI(title="Kumbh Sahayak")
STATIC = config.ROOT / "app" / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def voice_page():
    return FileResponse(STATIC / "index.html")


@app.get("/chat")
def chat_page():
    return FileResponse(STATIC / "chat.html")


@app.get("/api/status")
def status():
    from .db import backend_name
    return {"key_configured": config.has_key(), "kb_index": index_status(), "storage": backend_name(),
            "voice_ready": config.has_key(), "realtime_model": config.REALTIME_MODEL,
            "text_mode": "openai" if config.has_key() else "mock", "access_code_required": bool(config.DEMO_ACCESS_CODE)}


class TokenReq(BaseModel):
    session_id: str = ""
    caller_id: str = ""
    access_code: str = ""


@app.post("/api/realtime/token")
async def realtime_token(req: TokenReq, request: Request):
    _check_code(req.access_code)
    if not config.has_key():
        raise HTTPException(503, "Voice mode needs OPENAI_API_KEY in .env. Text mode works at /chat.")
    ip = request.client.host if request.client else ""
    caller_id = req.caller_id if memory.valid_id(req.caller_id) else ""
    safety_id = hashlib.sha256(f"kumbh:{caller_id or ip}".encode()).hexdigest()[:32]
    returning, context, name = False, "", None
    if caller_id and req.session_id:
        returning = await asyncio.to_thread(memory.start_session, caller_id, req.session_id, "voice")
        context = await asyncio.to_thread(memory.build_context, caller_id, req.session_id)
        name = (await asyncio.to_thread(memory.get_profile, caller_id) or {}).get("name")
    try:
        tok = await mint_client_secret(safety_id, context)
    except RuntimeError as e:
        log_event(req.session_id, "error", where="token", error=str(e))
        raise HTTPException(502, str(e))
    log_event(req.session_id, "session_start", model=tok["model"], returning=returning, has_memory=bool(context))
    return {**tok, "greeting": greeting_instruction(name, returning and bool(context)), "returning": returning,
            "caller_name": name}


class ToolReq(BaseModel):
    session_id: str = ""
    name: str
    args: dict | str | None = None


@app.post("/api/tools")
async def tool_relay(req: ToolReq):
    if req.name not in TOOL_NAMES:
        raise HTTPException(404, "unknown tool")
    res = await run_tool(req.name, req.args, req.session_id)
    log_event(req.session_id, "tool", name=req.name, args=req.args, result=res)
    return res


def _check_code(code: str) -> None:
    """When DEMO_ACCESS_CODE is set (public deployment), every endpoint that spends OpenAI credit requires it."""
    if config.DEMO_ACCESS_CODE and not secrets.compare_digest(code or "", config.DEMO_ACCESS_CODE):
        raise HTTPException(401, "Wrong or missing access code")


class ChatReq(BaseModel):
    session_id: str = Field(default_factory=lambda: secrets.token_hex(6))
    caller_id: str = ""
    message: str
    mock: bool = False
    access_code: str = ""


@app.post("/api/chat")
async def chat_api(req: ChatReq):
    if not req.mock:
        _check_code(req.access_code)
    if not req.message.strip():
        raise HTTPException(400, "empty message")
    caller_id = req.caller_id if memory.valid_id(req.caller_id) else ""
    return {"session_id": req.session_id,
            **await chat(req.session_id, req.message[:2000], force_mock=req.mock, caller_id=caller_id)}


class EndReq(BaseModel):
    session_id: str


@app.post("/api/session/end")
async def session_end(req: EndReq):
    """Called on hang-up / page close (sendBeacon, so the caller never waits): mark the session ended and
    summarise it for next time. Done before responding because serverless platforms may freeze the function
    right after the response is sent."""
    await asyncio.to_thread(memory.end_session, req.session_id)
    try:
        await asyncio.wait_for(asyncio.to_thread(memory.summarize_session, req.session_id), 25)
    except Exception:
        pass  # build_context falls back to recent raw lines if no summary exists
    log_event(req.session_id, "session_end")
    return {"ok": True}


@app.get("/api/caller/{caller_id}")
def caller_info(caller_id: str):
    if not memory.valid_id(caller_id):
        raise HTTPException(400, "bad id")
    p = memory.get_profile(caller_id)
    if not p:
        return {"known": False}
    with memory.db() as con:
        sessions = [dict(r) for r in con.execute(
            "SELECT session_id, mode, started_at, summary FROM sessions WHERE caller_id=? ORDER BY started_at DESC "
            "LIMIT 5", (caller_id,))]
    return {"known": True, "profile": {k: p[k] for k in (*memory.PROFILE_FIELDS, "visit_count", "created_at")},
            "sessions": sessions, "tickets": memory.caller_tickets(caller_id)}


@app.delete("/api/caller/{caller_id}")
def caller_forget(caller_id: str):
    if not memory.valid_id(caller_id):
        raise HTTPException(400, "bad id")
    return memory.forget(caller_id)


class LogReq(BaseModel):
    session_id: str
    role: str
    text: str = ""
    extra: dict | None = None


@app.post("/api/log")
def log_api(req: LogReq):
    extra = {k: v for k, v in (req.extra or {}).items() if k not in ("session_id", "kind", "text")}
    log_event(req.session_id, req.role[:20], text=req.text[:4000], **extra)
    lang = detect_language(req.text)
    memory.add_message(req.session_id, req.role, req.text, lang if req.role == "user" else None)
    return {"ok": True, "language": lang}


@app.get("/api/tickets")
def tickets(code: str = ""):
    if config.DEMO_ACCESS_CODE and not secrets.compare_digest(code, config.DEMO_ACCESS_CODE):
        raise HTTPException(401, "Add ?code=<DEMO_ACCESS_CODE>")
    return list_tickets()


@app.exception_handler(Exception)
async def unhandled(_, exc: Exception):
    return JSONResponse({"error": f"{type(exc).__name__}"}, status_code=500)
