"use strict";
const $ = id => document.getElementById(id);
let review = null, preview = null, busy = false;
const node = (tag, text, className = "") => { const el = document.createElement(tag); el.textContent = text; el.className = className; return el; };
const number = value => value == null ? "—" : Number(value).toLocaleString("it-IT", {maximumFractionDigits: 1});
const date = value => value ? new Date(value.length === 10 ? `${value}T12:00:00` : value).toLocaleDateString("it-IT", {timeZone:"Europe/Rome", day:"numeric", month:"short", year:"numeric"}) : "—";
const duration = value => value == null ? "—" : `${number(value / 60)} min`;
const pace = value => { if (!value) return "—"; const seconds = Math.round(value); return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2,"0")}/km`; };
function notice(message, error = false) { $("notice").hidden = false; $("notice").textContent = message; $("notice").className = error ? "error" : ""; }
async function api(path, method = "GET", body) {
  const response = await fetch(path, {method, headers:{"Content-Type":"application/json"}, ...(body ? {body:JSON.stringify(body)} : {})});
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : "Richiesta non valida: aggiorna i dati e riprova.");
  return value;
}
function setBusy(value) { busy = value; ["refresh-review", "adjust-program", "accept-adjustment", "dismiss-adjustment"].forEach(id => $(id).disabled = value); }
function selectTab(name, focus = false) {
  ["review", "advice"].forEach(key => { const selected = key === name; $( `tab-${key}`).setAttribute("aria-selected", String(selected)); $(`tab-${key}`).tabIndex = selected ? 0 : -1; $(`panel-${key}`).hidden = !selected; });
  history.replaceState(null, "", name === "advice" ? "#advice" : "#workout");
  if (focus) $(`tab-${name}`).focus();
}
["review", "advice"].forEach(name => {
  $(`tab-${name}`).onclick = () => selectTab(name);
  $(`tab-${name}`).onkeydown = event => { if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) { event.preventDefault(); selectTab(event.key === "Home" ? "review" : event.key === "End" ? "advice" : name === "review" ? "advice" : "review", true); } };
});
function render(value) {
  review = value;
  const a = value.last_workout, m = value.match, p = value.program;
  $("review-updated").textContent = a?.source === "manual" ? `Feedback dichiarato: ${date(a.date)}` : `Dati aggiornati: ${date(value.activities_refreshed_at)}`;
  $("workout-name").textContent = a?.name || "Nessun workout disponibile";
  $("workout-meta").textContent = a ? `${a.sport.toUpperCase()} · ${date(a.date)} · ${(a.source || "garmin").toUpperCase()}` : "SINCRONIZZA LE ATTIVITÀ PER INIZIARE";
  $("workout-verdict").textContent = value.verdict;
  $("workout-stats").replaceChildren();
  if (a) [["Distanza", a.distance_known === false ? "Non indicata" : `${number(a.distance_m / 1000)} km`], ["Durata", duration(a.duration_s)], ["Passo", pace(a.avg_pace_s_km)], ["FC media", a.avg_hr ? `${number(a.avg_hr)} bpm` : "—"], ["Dislivello", a.elevation_gain_m == null ? "—" : `+${number(a.elevation_gain_m)} m`]].forEach(([label, text]) => { const el = node("div", ""); el.append(node("small", label), node("strong", text)); $("workout-stats").append(el); });
  const statuses = {completed:"Durata compatibile", completed_modified:"Durata modificata", substituted:"Alternativa prevista"};
  $("workout-match").textContent = m ? `${m.planned_name} · previsti ${duration(m.planned_duration_s)} · svolti ${duration(a.duration_s)} · ${statuses[m.status] || m.status}.` : a ? "Nessuna associazione certa con una seduta del piano." : "Premi Aggiorna e valuta per leggere le attività.";
  $("workout-note").textContent = m?.note || (m ? "L'associazione non verifica ogni singolo step." : "");
  $("trend-title").textContent = p.eligible ? `${p.direction === "improving" ? "Passo in miglioramento" : "Passo in rallentamento"} · ${number(p.change_percent)}%` : "Continuità prima di tutto.";
  $("trend-reason").textContent = p.reason;
  $("trend-policy").textContent = p.policy;
  $("trend-evidence").replaceChildren();
  p.evidence.forEach(e => { const tr = node("tr", ""); [e.name, date(e.date), pace(e.avg_pace_s_km), e.avg_hr ? `${number(e.avg_hr)} bpm` : "—", duration(e.duration_s), e.elevation_gain_m == null ? "—" : `+${number(e.elevation_gain_m)} m`].forEach(text => tr.append(node("td", text))); $("trend-evidence").append(tr); });
  if (!p.evidence.length) { const tr = node("tr", ""), td = node("td", `Campione insufficiente o sport non confrontabile${p.sample_count != null ? ` · ${p.sample_count}/4 corse` : ""}.`); td.colSpan = 6; tr.append(td); $("trend-evidence").append(tr); }
  $("advice-list").replaceChildren(...(value.advice.length ? value.advice : ["Sincronizza le attività: i consigli saranno basati sull'ultima seduta registrata."]).map(text => node("li", text)));
  $("program-title").textContent = p.eligible ? "Valuta un piccolo adattamento." : "Mantieni il piano.";
  $("program-reason").textContent = p.reason;
  $("program-context").replaceChildren(...(p.context_reasons || []).filter(text => !p.reason.includes(text)).map(text => node("li", text)));
  $("adjust-program").hidden = !p.eligible;
  $("program-detail").textContent = p.eligible ? "Apri la proposta per vedere esattamente cosa cambierebbe. Puoi mantenere il piano." : "Il cambio verrà proposto solo con un trend persistente e dati sufficienti.";
  $("review-limitations").replaceChildren(...value.limitations.map(text => node("p", text)));
  if (typeof renderDetailedSummary === "function") renderDetailedSummary();
}
async function load() { render(await api("/api/review/workout")); }
$("refresh-review").onclick = async () => {
  if (busy) return; setBusy(true); notice("Lettura delle attività e valutazione…");
  try { if (typeof sessionDetail === "undefined" || sessionDetail?.activity?.source !== "manual") await api("/api/review/run", "POST"); await load(); if (typeof refreshDetailed === "function") await refreshDetailed(true); notice("Review e dettagli della seduta aggiornati."); } catch (error) { notice(error.message, true); } finally { setBusy(false); }
};
$("adjust-program").onclick = async () => {
  if (busy || !review?.program.eligible) return; setBusy(true);
  try {
    preview = await api("/api/review/adjustment/preview", "POST");
    $("adjustment-reason").textContent = preview.reason; $("adjustment-error").textContent = "";
    $("adjustment-changes").replaceChildren(...preview.changes.map(change => {
      const el = node("div", "", "proposal-change");
      el.append(node("strong", `${date(change.date)} · ${change.name}`), node("p", `${number(change.before_duration_min)} → ${number(change.after_duration_min)} min stimati · ${change.description}`));
      change.step_changes.forEach(step => el.append(node("p", `${step.iterations > 1 ? `${step.iterations}× ` : ""}${step.type === "interval" ? "Intervallo" : "Corsa"}: ${duration(step.before_duration_s)} → ${duration(step.after_duration_s)}`, "small")));
      return el;
    }));
    $("adjustment-dialog").showModal();
  } catch (error) { notice(error.message, true); await load().catch(() => {}); } finally { setBusy(false); }
};
$("dismiss-adjustment").onclick = () => { preview = null; $("adjustment-dialog").close(); };
$("adjustment-dialog").addEventListener("cancel", event => { if (busy) event.preventDefault(); else preview = null; });
$("accept-adjustment").onclick = async () => {
  if (busy || !preview) return; setBusy(true);
  try {
    await api("/api/review/adjustment/apply", "POST", {preview_id:preview.preview_id, confirmed:true});
    preview = null; $("adjustment-dialog").close(); await load();
    notice("Piano adattato e copia precedente conservata. Dalla dashboard: Test 1 workout, poi Sync Plan per aggiornare Garmin.");
    $("tab-advice").focus();
  } catch (error) { $("adjustment-error").textContent = error.message; } finally { setBusy(false); }
};
selectTab(location.hash === "#advice" ? "advice" : "review");
load().catch(error => { $("workout-name").textContent = "Review non disponibile"; notice(error.message, true); });
setInterval(() => { if (!busy && !$("adjustment-dialog").open) load().catch(error => notice(error.message, true)); }, 30000);
