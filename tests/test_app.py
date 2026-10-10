import json

import pytest
from fastapi.testclient import TestClient

from app import config, session_log
from app.chat import detect_language, places_in_order
from app.main import app
from app.realtime import session_config

client = TestClient(app)


@pytest.mark.parametrize("text,lang", [
    ("Where is Ramkund?", "en"), ("रामकुंड कहाँ है?", "hi"), ("रामकुंड कुठे आहे?", "mr"),
    ("Mujhe Ramkund jana hai", "hi"), ("mala Ramkund la jayche aahe", "mr"),
])
def test_detect_language(text, lang):
    assert detect_language(text) == lang


def test_language_is_sticky_for_bare_place_names():
    assert detect_language("Nashik Road station", previous="hi") == "hi"


def test_places_in_order():
    assert places_in_order("from Nashik Road station to Ramkund") == ["Nashik Road Railway Station", "Ramkund, Panchavati"]
    assert places_in_order("Trimbakeshwar mandir") == ["Trimbakeshwar Temple"]


def test_status_without_key():
    r = client.get("/api/status").json()
    assert r["key_configured"] is False and r["text_mode"] == "mock"


def test_token_without_key_is_503():
    r = client.post("/api/realtime/token", json={"session_id": "t"})
    assert r.status_code == 503


def test_pages_served():
    assert "Call Kumbh Sahayak" in client.get("/").text
    assert "Text mode" in client.get("/chat").text
    demos = client.get("/static/demo_conversations.json").json()
    assert len(demos) == 11


def test_chat_mock_emergency_and_log(fake_http):
    r = client.post("/api/chat", json={"session_id": "abc123", "message": "मदद करो! आग लगी है रामकुंड के पास"}).json()
    assert r["mode"] == "mock" and "112" in r["reply"] and r["tool_calls"][0]["name"] == "create_ticket"
    logs = list(config.LOG_DIR.glob("*_abc123.jsonl"))
    kinds = [json.loads(l)["kind"] for l in logs[0].read_text().splitlines()]
    assert kinds[:3] == ["user", "tool", "assistant"]


def test_tool_relay(fake_http):
    r = client.post("/api/tools", json={"session_id": "s", "name": "travel_to_nashik", "args": {"from_city": "Pune"}})
    assert r.json()["road_distance_km"] == 216
    assert client.post("/api/tools", json={"name": "rm_rf", "args": {}}).status_code == 404


def test_logs_scrub_secrets():
    session_log.log_event("scrub", "x", text="my key is sk-proj-ABCDEFGHIJKLMNOP and ek_123456789")
    content = next(config.LOG_DIR.glob("*_scrub.jsonl")).read_text()
    assert "sk-proj" not in content and "ek_123" not in content and "[REDACTED]" in content


def test_realtime_session_config_shape():
    s = session_config()
    assert s["type"] == "realtime" and s["model"] == config.REALTIME_MODEL
    assert s["audio"]["output"]["voice"] == config.REALTIME_VOICE
    assert len(s["tools"]) == 8 and "Kumbh Sahayak" in s["instructions"]
    assert "2 August 2027" in s["instructions"]  # verified core facts are pinned in the prompt
    assert "112" in s["instructions"]
