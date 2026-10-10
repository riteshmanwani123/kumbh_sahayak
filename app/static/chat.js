import { addCard, LANG_LABEL, getCallerId, resetCallerId, endSession, renderMemory } from "/static/cards.js";

const $ = (id) => document.getElementById(id);
const transcript = $("transcript"), cards = $("cards"), input = $("input"), langEl = $("lang"), banner = $("banner");
let sessionId = newId(), busy = false, used = false;
let callerId = getCallerId();
const memoryEl = $("memory");
const refreshMemory = () => renderMemory(memoryEl, callerId, () => { callerId = resetCallerId(); refreshMemory(); });
function rotateSession() { if (used) endSession(sessionId); sessionId = newId(); used = false; setTimeout(refreshMemory, 4000); }

function newId() { return "t" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }
function addMsg(role, text, meta = "") {
  transcript.querySelector(".msg.system:only-child")?.remove();
  const el = document.createElement("div");
  el.className = "msg " + role;
  el.textContent = text;
  if (meta) { const m = document.createElement("span"); m.className = "meta"; m.textContent = meta; el.appendChild(m); }
  transcript.appendChild(el);
  transcript.scrollTop = transcript.scrollHeight;
  return el;
}

async function send(text) {
  if (!text.trim() || busy) return;
  busy = true;
  addMsg("user", text);
  const wait = addMsg("system", "…");
  const t0 = performance.now();
  try {
    const r = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, caller_id: callerId, message: text, mock: $("mock").checked }) });
    used = true;
    const d = await r.json();
    wait.remove();
    (d.tool_calls || []).forEach((c) => {
      addMsg("system", `🔧 ${c.name} · ${c.result?._ms ?? "?"} ms`);
      addCard(cards, c.name, c.args, c.result);
    });
    addMsg("assistant", d.reply || d.detail || "(no reply)", `${d.mode || ""} · ${Math.round(performance.now() - t0)} ms`);
    if (d.language) langEl.textContent = "Language: " + LANG_LABEL[d.language];
    if ((d.tool_calls || []).some((c) => ["remember_caller_details", "create_ticket"].includes(c.name))) refreshMemory();
  } catch (e) {
    wait.textContent = "⚠️ " + e.message;
  }
  busy = false;
}

$("form").onsubmit = (e) => { e.preventDefault(); const t = input.value; input.value = ""; send(t); };
$("reset").onclick = () => { rotateSession(); transcript.innerHTML = ""; addMsg("system", "New session (memory kept)"); };
window.addEventListener("pagehide", () => used && endSession(sessionId));
refreshMemory();

(async () => {
  try {
    const s = await (await fetch("/api/status")).json();
    banner.textContent = s.key_configured
      ? `OpenAI key configured · text model replies (${s.realtime_model} for voice) · KB index: ${s.kb_index}`
      : "No OpenAI key yet · running the mock LLM (rule-based) with the real tools: maps, weather, tickets, KB keyword search.";
  } catch {}
  const demos = await (await fetch("/static/demo_conversations.json")).json();
  for (const d of demos) {
    const b = document.createElement("button");
    const sessions = d.sessions || [d.turns];
    b.className = "chip"; b.textContent = d.title; b.title = sessions.map((t) => t.join(" → ")).join("  ||  ");
    b.onclick = async () => {
      addMsg("system", `Demo ${d.id}: ${d.title}`);
      for (const [n, turns] of sessions.entries()) {
        rotateSession();
        if (n) { addMsg("system", "— caller hangs up and calls again —"); await new Promise((r) => setTimeout(r, 2500)); }
        for (const t of turns) await send(t);
      }
    };
    $("chips").appendChild(b);
  }
})();
