import pytest
from fastapi.testclient import TestClient

from app import memory
from app.main import app
from app.tools.registry import run_tool

client = TestClient(app)
CID = "c_testcaller0001"


def test_session_profile_context_and_forget():
    assert memory.start_session(CID, "s_one", "text") is False          # first visit
    memory.add_message("s_one", "user", "Mera naam Sunita hai, Pune se aayi hoon", "hi")
    memory.add_message("s_one", "assistant", "Namaste Sunita ji")
    assert memory.update_profile(CID, name="Sunita", home_city="Pune", notes="with elderly mother")["ok"]
    memory.update_profile(CID, notes="staying in Panchavati")
    p = memory.get_profile(CID)
    assert p["name"] == "Sunita" and p["preferred_language"] == "hi" and "elderly" in p["notes"] and "Panchavati" in p["notes"]
    memory.end_session("s_one")
    summary = memory.summarize_session("s_one")                       # no key in tests → extractive fallback
    assert "Sunita" in summary

    assert memory.start_session(CID, "s_two", "voice") is True          # returning
    ctx = memory.build_context(CID, "s_two")
    assert "Returning caller" in ctx and "Sunita" in ctx and "Pune" in ctx

    out = memory.forget(CID)
    assert out["deleted_sessions"] == 2 and memory.get_profile(CID) is None


def test_update_profile_rejects_unknown_fields_and_ids():
    assert not memory.update_profile("bad id!", name="x")["ok"]
    memory.start_session("c_testcaller0002", "s_x", "text")
    r = memory.update_profile("c_testcaller0002", aadhaar="1234", name="Ravi")
    assert r["saved"] == ["name"]


@pytest.mark.asyncio
async def test_tools_link_tickets_to_caller():
    memory.start_session("c_testcaller0003", "s_t", "voice")
    t = await run_tool("create_ticket", {"type": "complaint", "details": "dirty toilets at ghat 3", "caller_language": "en"}, "s_t")
    r = await run_tool("get_my_tickets", {}, "s_t")
    assert r["tickets"][0]["ticket_id"] == t["ticket_id"]
    saved = await run_tool("remember_caller_details", {"name": "Asha", "home_city": "Nagpur"}, "s_t")
    assert saved["ok"] and memory.get_profile("c_testcaller0003")["home_city"] == "Nagpur"
    assert "Their tickets" in memory.build_context("c_testcaller0003", "other")


def test_api_caller_endpoints_and_chat_memory(fake_http):
    cid = "c_testcaller0004"
    r = client.post("/api/chat", json={"session_id": "s_api1", "caller_id": cid, "message": "Ramkund kahan hai?"})
    assert r.status_code == 200
    assert [m["role"] for m in memory.session_messages("s_api1")] == ["user", "assistant"]
    assert client.post("/api/session/end", json={"session_id": "s_api1"}).json()["ok"]
    info = client.get(f"/api/caller/{cid}").json()
    assert info["known"] and info["sessions"][0]["session_id"] == "s_api1"
    assert client.delete(f"/api/caller/{cid}").json()["ok"]
    assert client.get(f"/api/caller/{cid}").json() == {"known": False}
    assert client.get("/api/caller/bad!id").status_code in (400, 404)
