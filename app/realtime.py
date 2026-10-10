"""Mint short-lived OpenAI Realtime client secrets (ephemeral keys). The real API key never leaves the server."""
import os

import httpx

from . import config
from .prompts import system_prompt
from .tools.registry import realtime_tools

CLIENT_SECRETS_URL = "https://api.openai.com/v1/realtime/client_secrets"
TRANSCRIBE_PROMPT = ("Pilgrim helpline for Nashik Kumbh Mela. Speech may be Hindi, Marathi, English or mixed. "
                     "Place names: Nashik, Ramkund, Panchavati, Trimbakeshwar, Kushavarta, Tapovan, Sadhugram, "
                     "Kalaram, Nashik Road, Ozar, Godavari, Amrut Snan, akhada, MSRTC.")


def session_config(caller_context: str = "") -> dict:
    if os.getenv("TURN_DETECTION", "server_vad") == "semantic_vad":
        turn = {"type": "semantic_vad", "eagerness": "high"}
    else:
        turn = {"type": "server_vad", "threshold": 0.6, "prefix_padding_ms": 300, "silence_duration_ms": 550}
    transcription = {"model": config.TRANSCRIBE_MODEL}
    if "whisper" not in config.TRANSCRIBE_MODEL:
        transcription["prompt"] = TRANSCRIBE_PROMPT
    return {
        "type": "realtime",
        "model": config.REALTIME_MODEL,
        "instructions": system_prompt(caller_context),
        "output_modalities": ["audio"],
        "tools": realtime_tools(),
        "tool_choice": "auto",
        "audio": {
            "input": {"transcription": transcription, "turn_detection": turn,
                      "noise_reduction": {"type": "far_field"}},
            "output": {"voice": config.REALTIME_VOICE},
        },
    }


async def mint_client_secret(safety_id: str = "", caller_context: str = "") -> dict:
    """Returns {"value": "ek_...", "expires_at": int, "model": str}. Raises RuntimeError with a safe message."""
    if not config.has_key():
        raise RuntimeError("OPENAI_API_KEY not configured on the server")
    headers = {"Authorization": f"Bearer {config.openai_key()}", "Content-Type": "application/json"}
    if safety_id:
        headers["OpenAI-Safety-Identifier"] = safety_id
    body = {"expires_after": {"anchor": "created_at", "seconds": 600}, "session": session_config(caller_context)}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(CLIENT_SECRETS_URL, json=body, headers=headers)
    if r.status_code >= 400:
        try:
            msg = r.json().get("error", {}).get("message", "")
        except Exception:
            msg = ""
        raise RuntimeError(f"OpenAI returned {r.status_code}: {msg[:300]}")
    data = r.json()
    return {"value": data["value"], "expires_at": data.get("expires_at"), "model": config.REALTIME_MODEL}
