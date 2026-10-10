// Renders tool results as cards in the side panel (replaces SMS for the demo).
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const km = (m) => (m == null ? "" : m >= 1000 ? (m / 1000).toFixed(1) + " km" : Math.round(m / 10) * 10 + " m");
const safeUrl = (u) => (/^(https?:|tel:)/.test(u || "") ? u : "#");

export function renderCard(name, args, res) {
  const el = document.createElement("div");
  el.className = "card";
  if (!res || res.ok === false) {
    el.classList.add("warn");
    el.innerHTML = `<h3>⚠️ ${esc(name)} unavailable</h3><div class="sub">${esc(res?.error || "error")}</div>`;
    return el;
  }
  switch (name) {
    case "get_directions": {
      const l = res.map_links || {};
      el.innerHTML = `<h3>🧭 ${esc(res.from)} → ${esc(res.to)}</h3>
        <div class="big">${esc(res.distance_km)} km · ${esc(res.eta)}</div>
        <div class="sub">${res.mode === "walking" ? "Walking" : "By road"}${res.approximate ? " (approximate)" : ""}</div>
        <ol>${(res.steps || []).map((s) => `<li>${esc(s)}</li>`).join("")}</ol>
        <div class="btns"><a target="_blank" rel="noopener" href="${esc(safeUrl(l.google_maps))}">Open in Google Maps</a>
        <a class="alt" target="_blank" rel="noopener" href="${esc(safeUrl(l.openstreetmap))}">OpenStreetMap</a></div>
        <div class="sub">${esc(res.note || "")}</div>`;
      break;
    }
    case "find_nearby": {
      el.innerHTML = `<h3>📍 ${esc(res.category.replace("_", " "))} near ${esc(res.place)}</h3>
        <ul>${(res.results || []).map((r) => `<li><b>${esc(r.name)}</b> ${r.distance_m != null ? "· " + km(r.distance_m) : ""}
          ${r.phone ? ` · <a href="tel:${esc(r.phone)}">${esc(r.phone)}</a>` : ""}
          ${r.map_link ? ` · <a target="_blank" rel="noopener" href="${esc(safeUrl(r.map_link))}">map</a>` : ""}</li>`).join("") || "<li>No results</li>"}</ul>
        <div class="sub">${esc(res.note || "")}</div>`;
      break;
    }
    case "search_kumbh_info": {
      const p = res.passages || [];
      const srcs = [...new Set(p.flatMap((x) => x.sources || []))].slice(0, 4);
      el.innerHTML = `<h3>📚 Knowledge base: “${esc(args?.query)}”</h3>
        ${res.found ? `<div class="sub">${p.length} passage(s) · ${esc(res.method)} · as of ${esc(p[0]?.as_of)}</div>
        <ul>${srcs.map((u) => `<li><a target="_blank" rel="noopener" href="${esc(safeUrl(u))}">${esc(u.replace(/^https?:\/\/(www\.)?/, "").slice(0, 60))}</a></li>`).join("")}</ul>`
        : `<div class="sub">Not found in verified knowledge base.</div>`}`;
      break;
    }
    case "travel_to_nashik": {
      el.innerHTML = `<h3>🚆 ${esc(res.from_city)} → Nashik</h3>
        ${res.road_distance_km ? `<div class="big">~${esc(res.road_distance_km)} km by road</div><div class="sub">${esc(res.drive_time)}</div>` : ""}
        <ul><li><b>Best:</b> ${esc(res.best_option || "—")}</li><li><b>Train:</b> ${esc(res.rail)}</li>
        <li><b>Bus:</b> ${esc(res.bus)}</li><li><b>Air:</b> ${esc(res.flight || res.air)}</li><li>${esc(res.snan_day_tip)}</li></ul>`;
      break;
    }
    case "create_ticket": {
      if (res.type !== "complaint") el.classList.add("danger");
      el.innerHTML = `<h3>${res.type === "emergency" ? "🚨 Emergency" : res.type === "lost_found" ? "🔎 Lost & found" : "📝 Complaint"} ticket</h3>
        <div class="big">${esc(res.ticket_id)}</div>
        <div class="btns">${(res.call_now || []).map((c) => `<a href="tel:${esc(c.number)}">${esc(c.name)}: ${esc(c.number)}</a>`).join("")}</div>
        <div class="sub">${esc(res.note)}</div>`;
      break;
    }
    case "get_weather": {
      const n = res.now || {};
      el.innerHTML = `<h3>🌦️ Weather · ${esc(res.place)}</h3>
        <div class="big">${esc(n.temp_c)}°C · ${esc(n.summary)}</div>
        <ul>${(res.forecast || []).map((d) => `<li>${esc(d.date)}: ${esc(d.summary)}, ${esc(d.min_c)}–${esc(d.max_c)}°C, rain ${esc(d.rain_chance_pct)}%</li>`).join("")}</ul>
        <div class="sub">Source: Open-Meteo</div>`;
      break;
    }
    case "remember_caller_details": {
      el.innerHTML = `<h3>🧠 Remembered</h3><div class="sub">${esc(Object.entries(args || {}).map(([k, v]) => k.replace("_", " ") + ": " + v).join(" · "))}</div>`;
      break;
    }
    case "get_my_tickets": {
      el.innerHTML = `<h3>🗂️ Your tickets</h3><ul>${(res.tickets || []).map((t) => `<li><b>${esc(t.ticket_id)}</b> · ${esc(t.type)} · ${esc(t.status)} · ${esc(t.created_at?.slice(0, 16).replace("T", " "))}</li>`).join("") || "<li>No tickets found</li>"}</ul><div class="sub">${esc(res.note || "")}</div>`;
      break;
    }
    default:
      el.innerHTML = `<h3>${esc(name)}</h3><pre>${esc(JSON.stringify(res, null, 2)).slice(0, 800)}</pre>`;
  }
  return el;
}

export function addCard(container, name, args, res) {
  container.querySelector(".empty")?.remove();
  container.prepend(renderCard(name, args, res));
}

const MR = /(आहे|आहेत|कुठे|मला|कसे|कसा|काय|कधी|पाहिजे|जवळ|नाही|सांगा|किती|\b(aahe|kuthe|mala|kasa|pahije|sanga)\b)/i;
const HI = /(है|हैं|कहाँ|कहां|मुझे|कैसे|क्या|कब|चाहिए|नहीं|बताइए|\b(hai|kahan|mujhe|kaise|kya|kab|chahiye|nahi|batao)\b)/i;
export function detectLang(text) {
  const mr = (text.match(new RegExp(MR, "gi")) || []).length, hi = (text.match(new RegExp(HI, "gi")) || []).length;
  if (mr > hi) return "mr";
  if (hi > mr || /[ऀ-ॿ]/.test(text)) return "hi";
  return "en";
}
export const LANG_LABEL = { en: "English", hi: "हिंदी", mr: "मराठी" };

// ---- caller memory (anonymous ID kept in this browser) ----
export function getCallerId() {
  let id = null;
  try { id = localStorage.getItem("kumbh_caller_id"); } catch {}
  if (!id || !/^[A-Za-z0-9_-]{6,64}$/.test(id)) {
    id = "c_" + (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, "") : Date.now().toString(36) + Math.random().toString(36).slice(2));
    try { localStorage.setItem("kumbh_caller_id", id); } catch {}
  }
  return id;
}
export function resetCallerId() { try { localStorage.removeItem("kumbh_caller_id"); } catch {} return getCallerId(); }
export function endSession(sessionId) {
  if (!sessionId) return;
  const body = JSON.stringify({ session_id: sessionId });
  if (!(navigator.sendBeacon && navigator.sendBeacon("/api/session/end", new Blob([body], { type: "application/json" }))))
    fetch("/api/session/end", { method: "POST", headers: { "Content-Type": "application/json" }, body, keepalive: true }).catch(() => {});
}
export async function renderMemory(el, callerId, onForget) {
  let d = { known: false };
  try { d = await (await fetch("/api/caller/" + callerId)).json(); } catch {}
  if (!d.known || (!d.sessions?.length && !d.profile?.name)) {
    el.innerHTML = `<div class="sub">New caller — nothing remembered yet. Share your name or city and I'll remember it next time.</div>`;
    return d;
  }
  const p = d.profile, last = (d.sessions || []).filter((s) => s.summary)[0];
  el.innerHTML = `<div><b>${esc(p.name || "Returning caller")}</b> · visit ${esc(p.visit_count)}
      ${p.home_city ? " · from " + esc(p.home_city) : ""}${p.preferred_language ? " · " + esc(LANG_LABEL[p.preferred_language] || p.preferred_language) : ""}</div>
    ${p.group_info || p.stay_location ? `<div class="sub">${esc([p.group_info, p.stay_location].filter(Boolean).join(" · "))}</div>` : ""}
    ${last ? `<div class="sub">Last time: ${esc(last.summary)}</div>` : ""}
    ${(d.tickets || []).length ? `<div class="sub">Tickets: ${d.tickets.map((t) => esc(t.ticket_id) + " (" + esc(t.status) + ")").join(", ")}</div>` : ""}
    <div class="btns"><button class="ghost" id="forget">Forget me</button></div>`;
  el.querySelector("#forget").onclick = async () => {
    if (!confirm("Delete everything remembered about you on this device?")) return;
    await fetch("/api/caller/" + callerId, { method: "DELETE" });
    onForget?.();
  };
  return d;
}
