// Voice client: OpenAI Realtime over WebRTC using an ephemeral key minted by our backend.
// Tool calls arrive on the data channel; we relay them to /api/tools and return the results.
import { addCard, detectLang, LANG_LABEL, getCallerId, resetCallerId, endSession, renderMemory } from "/static/cards.js";

const $ = (id) => document.getElementById(id);
const callBtn = $("call"), statusEl = $("status"), langEl = $("lang"), dot = $("dot"), who = $("who");
const transcript = $("transcript"), cards = $("cards"), muteBtn = $("mute"), banner = $("banner"), codeEl = $("code");

let pc, dc, mic, audioEl, sessionId, live = false;
let callerId = getCallerId();
const memoryEl = $("memory");
const refreshMemory = () => renderMemory(memoryEl, callerId, () => { callerId = resetCallerId(); refreshMemory(); });
const bubbles = new Map(); // item_id -> element for streaming assistant transcript
const handledCalls = new Set();

function setStatus(t, on = false) { statusEl.textContent = t; statusEl.classList.toggle("on", on); }
function setLang(text) { const l = detectLang(text || ""); langEl.textContent = "Language: " + LANG_LABEL[l]; }
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
const log = (role, text, extra) =>
  fetch("/api/log", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, role, text, extra }) }).catch(() => {});
const send = (ev) => dc?.readyState === "open" && dc.send(JSON.stringify(ev));

async function init() {
  try {
    const s = await (await fetch("/api/status")).json();
    if (!s.voice_ready) {
      banner.innerHTML = "Voice mode needs an OpenAI API key on the server. <a href='/chat'>Text mode</a> works now (mock or real LLM).";
      banner.classList.remove("hidden");
      callBtn.disabled = true;
    }
    if (s.access_code_required) codeEl.style.display = "block";
  } catch { /* server offline */ }
}

async function start() {
  callBtn.disabled = true;
  setStatus("Connecting…");
  sessionId = "v" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  try {
    const tr = await fetch("/api/realtime/token", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, caller_id: callerId, access_code: codeEl.value || "" }) });
    if (!tr.ok) throw new Error((await tr.json()).detail || "Token request failed");
    const tok = await tr.json();

    pc = new RTCPeerConnection();
    audioEl = new Audio(); audioEl.autoplay = true;
    pc.ontrack = (e) => { audioEl.srcObject = e.streams[0]; };
    mic = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    mic.getTracks().forEach((t) => pc.addTrack(t, mic));

    dc = pc.createDataChannel("oai-events");
    dc.onopen = () => {
      setStatus("Live", true);
      send({ type: "response.create", response: { instructions: tok.greeting } });
    };
    dc.onmessage = (e) => onEvent(JSON.parse(e.data));
    dc.onclose = () => live && stop("Disconnected");

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    const sdpRes = await fetch("https://api.openai.com/v1/realtime/calls", {
      method: "POST", body: offer.sdp,
      headers: { Authorization: `Bearer ${tok.value}`, "Content-Type": "application/sdp" },
    });
    if (!sdpRes.ok) throw new Error("Realtime connect failed: " + sdpRes.status + " " + (await sdpRes.text()).slice(0, 200));
    await pc.setRemoteDescription({ type: "answer", sdp: await sdpRes.text() });

    live = true;
    callBtn.textContent = "⏹ Hang up"; callBtn.classList.add("live"); callBtn.disabled = false;
    muteBtn.disabled = false;
    addMsg("system", "Connected · " + tok.model + (tok.returning ? " · returning caller" + (tok.caller_name ? " (" + tok.caller_name + ")" : "") : ""));
  } catch (err) {
    addMsg("system", "⚠️ " + (err.message || err));
    stop("Error");
  }
}

function stop(reason = "Ended") {
  live = false;
  try { dc?.close(); pc?.getSenders().forEach((s) => s.track?.stop()); pc?.close(); } catch {}
  mic?.getTracks().forEach((t) => t.stop());
  pc = dc = mic = null;
  callBtn.textContent = "📞 Call Kumbh Sahayak"; callBtn.classList.remove("live"); callBtn.disabled = false;
  muteBtn.disabled = true; muteBtn.textContent = "🎙️ Mute";
  dot.classList.remove("speaking"); who.textContent = "—";
  setStatus(reason);
  if (sessionId) { log("session_end", reason); endSession(sessionId); sessionId = null; setTimeout(refreshMemory, 4000); }
}

async function runToolCalls(calls) {
  const fresh = calls.filter((c) => !handledCalls.has(c.call_id));
  if (!fresh.length) return;
  fresh.forEach((c) => handledCalls.add(c.call_id));
  await Promise.all(fresh.map(async (c) => {
    const chip = addMsg("system", `🔧 ${c.name}…`);
    let res;
    try {
      res = await (await fetch("/api/tools", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, name: c.name, args: c.arguments }) })).json();
    } catch { res = { ok: false, error: "network", spoken_fallback: "Sorry, the service is slow. For emergencies dial 112." }; }
    chip.textContent = `🔧 ${c.name} · ${res._ms ?? "?"} ms`;
    let args = {}; try { args = JSON.parse(c.arguments || "{}"); } catch {}
    addCard(cards, c.name, args, res);
    send({ type: "conversation.item.create", item: { type: "function_call_output", call_id: c.call_id, output: JSON.stringify(res) } });
  }));
  send({ type: "response.create" });
}

function onEvent(ev) {
  switch (ev.type) {
    case "input_audio_buffer.speech_started":
      dot.classList.add("speaking"); who.textContent = "You";
      break;
    case "input_audio_buffer.speech_stopped":
      dot.classList.remove("speaking"); who.textContent = "Thinking…";
      break;
    case "conversation.item.input_audio_transcription.completed": {
      const t = (ev.transcript || "").trim();
      if (t) { addMsg("user", t); setLang(t); log("user", t); }
      break;
    }
    case "response.output_audio_transcript.delta": {
      dot.classList.add("speaking"); who.textContent = "Sahayak";
      let b = bubbles.get(ev.item_id);
      if (!b) { b = addMsg("assistant", ""); bubbles.set(ev.item_id, b); }
      b.textContent += ev.delta || "";
      transcript.scrollTop = transcript.scrollHeight;
      break;
    }
    case "response.output_audio_transcript.done": {
      const t = ev.transcript || bubbles.get(ev.item_id)?.textContent || "";
      if (bubbles.get(ev.item_id)) bubbles.get(ev.item_id).textContent = t;
      setLang(t); log("assistant", t);
      break;
    }
    case "output_audio_buffer.stopped":
      dot.classList.remove("speaking"); who.textContent = "Listening";
      break;
    case "response.done": {
      const calls = (ev.response?.output || []).filter((o) => o.type === "function_call");
      if (calls.length) runToolCalls(calls);
      else { dot.classList.remove("speaking"); who.textContent = "Listening"; }
      if (ev.response?.status === "failed") addMsg("system", "⚠️ " + JSON.stringify(ev.response.status_details).slice(0, 200));
      break;
    }
    case "error":
      addMsg("system", "⚠️ " + (ev.error?.message || "error"));
      log("error", ev.error?.message || "error");
      break;
  }
}

callBtn.onclick = () => (live ? stop() : start());
muteBtn.onclick = () => {
  const t = mic?.getAudioTracks()[0]; if (!t) return;
  t.enabled = !t.enabled; muteBtn.textContent = t.enabled ? "🎙️ Mute" : "🔇 Unmute";
};
window.addEventListener("pagehide", () => live && endSession(sessionId));
init();
refreshMemory();
