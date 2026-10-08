"use strict";
const $ = id => document.getElementById(id);
let currentPlan = null, currentSummary = null, preview = null, busy = false;
const dateLabel = value => value ? new Date(value.length === 10 ? `${value}T12:00:00` : value).toLocaleDateString("it-IT", {day:"2-digit", month:"short"}) : "—";
const dateTime = value => value ? new Date(value).toLocaleString("it-IT", {timeZone:"Europe/Rome",day:"2-digit",month:"short",hour:"2-digit",minute:"2-digit"}) : "—";
const number = (value, decimals = 1) => Number(value || 0).toLocaleString("it-IT", {maximumFractionDigits: decimals});
const duration = seconds => { const minutes = Math.round((seconds || 0) / 60); return minutes >= 60 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : `${minutes} min`; };
const pace = seconds => { if (!seconds) return "—"; const rounded = Math.round(seconds); return `${Math.floor(rounded / 60)}:${String(rounded % 60).padStart(2,"0")}/km`; };
function element(tag, text = "", className = "") { const node = document.createElement(tag); node.textContent = text; node.className = className; return node; }
function notice(message, error = false) { $("notice").hidden = false; $("notice").textContent = message; $("notice").className = error ? "error" : ""; }
async function api(path, method = "GET", body) {
  const response = await fetch(path, {method, headers: {"Content-Type":"application/json"}, ...(body !== undefined ? {body:JSON.stringify(body)} : {})});
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Dati non validi: controlla il formato JSON, le durate, i target e gli ID.");
  return result;
}
function setBusy(value) { busy = value; document.querySelectorAll("button").forEach(b => b.disabled = value); if (!value) $("apply").disabled = !preview || !preview.remove_count; }
async function operation(message, fn) {
  if (busy) return;
  setBusy(true); notice(message);
  try { await fn(); await load(); } catch (error) { notice(error.message, true); }
  finally { setBusy(false); }
}
function confirmAction(title, description) {
  $("confirm-title").textContent = title; $("confirm-description").textContent = description;
  const dialog = $("confirm-dialog"); dialog.returnValue = ""; dialog.showModal();
  return new Promise(resolve => dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), {once:true}));
}
function stepText(step) {
  const target = step.target?.type === "pace" ? ` @ ${step.target.fast}–${step.target.slow}/km` : step.target?.type === "hr_zone" ? ` · FC Z${step.target.zone}` : "";
  if (step.type === "repeat") return `${step.iterations}× (${step.steps.map(stepText).join(" + ")})`;
  const labels = {warmup:"Warmup",run:"Easy",interval:"Intervallo",recovery:"Recupero",cooldown:"Cooldown"};
  const amount = step.distance_m ? `${number(step.distance_m,0)} m` : step.duration_min ? `${step.duration_min}′` : `${step.duration_s}″`;
  return `${labels[step.type]} ${amount}${target}`;
}
function renderActivities(activities) {
  const tbody = $("activities-body"); tbody.replaceChildren();
  if (!activities.length) { const row = element("tr"), td = element("td", "Nessuna attività caricata. Premi Refresh Garmin."); td.colSpan = 6; row.append(td); tbody.append(row); }
  activities.forEach(a => {
    const tr = element("tr"), td = element("td"), wrap = element("div", "", "activity-cell");
    wrap.append(element("span", a.sport === "cycling" ? "◇" : "↗", `sport-icon ${a.sport}`));
    const title = element("div", a.name); title.append(element("small", a.sport === "cycling" ? `Bici · +${number(a.elevation_gain_m,0)} m` : a.activity_type, "sport-sub")); wrap.append(title); td.append(wrap); tr.append(td);
    [dateLabel(a.date), `${number(a.distance_m/1000)} km`, duration(a.duration_s), pace(a.avg_pace_s_km), a.avg_hr ? `${Math.round(a.avg_hr)} bpm` : "—"].forEach(v => tr.append(element("td",v)));
    tbody.append(tr);
  });
}
function renderPlan(plan, summary) {
  $("plan-name").textContent = plan.plan_name;
  $("plan-notes").replaceChildren(...plan.notes.map(n => element("div",n)));
  const tbody = $("plan-body"); tbody.replaceChildren();
  [...plan.workouts].sort((a,b) => a.date.localeCompare(b.date)).forEach(w => {
    const row = element("tr"); row.append(element("td",dateLabel(w.date)));
    const title = element("td",w.name); if (w.quality) title.append(element("small"," · qualità", "sport-sub")); row.append(title);
    row.append(element("td",w.sport), element("td",w.estimated_duration_min ? `~${number(w.estimated_duration_min)} min` : "Riposo / manuale"));
    const key = w.id || `${w.date}-${w.sport}`, state = summary.sync_state.find(s => s.plan_workout_id === key);
    const td = element("td"); td.append(element("span",state?.status || (w.sport === "rest" || w.sport === "manual" ? "Locale" : "Da sincronizzare"), `badge ${state?.status === "scheduled" ? "" : "pending"}`)); row.append(td); tbody.append(row);
  });
}
function renderSummary(s) {
  $("connection").textContent = s.garmin.message;
  $("status-dot").className = `dot ${s.garmin.connected ? "online" : ""}`;
  $("last-refresh").textContent = `Ultimo aggiornamento: ${dateTime(s.last_refresh)}`;
  $("today-date").textContent = new Date(`${s.today}T12:00:00`).toLocaleDateString("it-IT",{weekday:"long",day:"numeric",month:"long",year:"numeric"});
  $("vo2").textContent = s.vo2max.value ? number(s.vo2max.value) : "—";
  $("vo2-source").textContent = `${s.vo2max.source}${s.vo2max.measured_date ? ` · ${dateLabel(s.vo2max.measured_date)}` : ""}`;
  $("run-km").textContent = s.last_refresh ? number(s.training_summary.running_distance_7d/1000) : "—";
  $("bike-hours").textContent = s.last_refresh ? number(s.training_summary.cycling_duration_7d/3600) : "—";
  $("last-title").textContent = s.last_workout?.name || "—";
  $("last-detail").textContent = s.last_workout ? `${dateLabel(s.last_workout.date)} · ${number(s.last_workout.distance_m/1000)} km · ${duration(s.last_workout.duration_s)}` : "Aggiorna Garmin per iniziare";
  const today = s.today_workouts[0], done = s.activities.find(a => a.date === s.today);
  $("today-name").textContent = today?.name || (done ? "Oggi: lavoro fatto." : "Nessuna sessione prevista");
  $("today-description").textContent = today?.description || (done ? `${done.name} · ${number(done.distance_m/1000)} km. Ora spazio al recupero.` : "Controlla il prossimo allenamento nel piano.");
  $("today-meta").textContent = today ? `${today.sport.toUpperCase()}${today.estimated_duration_min ? ` · ~${today.estimated_duration_min} min` : ""}` : done ? `${duration(done.duration_s)} · FC media ${done.avg_hr || "—"}` : "";
  $("tomorrow").textContent = s.next_workout ? `${dateLabel(s.next_workout.date)} · ${s.next_workout.name} — ${s.next_workout.description}` : "Piano completato.";
  $("quality-name").textContent = s.next_quality?.name || "Nessuna qualità prevista";
  $("quality-steps").replaceChildren(...(s.next_quality?.steps || []).map(step => element("div",stepText(step))));
  $("quality-meta").textContent = s.next_quality ? `${dateLabel(s.next_quality.date)} · ~${number(s.next_quality.estimated_duration_min)} min · ${s.next_quality.sport}` : "";
  $("flags").replaceChildren();
  if (!s.flags.length) $("flags").append(element("p", s.last_review ? "Nessun flag nella review attuale." : "Esegui una review per valutare i dati."));
  s.flags.forEach(f => { const node = element("div","","flag"); node.append(element("strong",f.code),element("p",f.message)); $("flags").append(node); });
  $("scheduler").textContent = s.scheduler_enabled ? `Prossima review: ${dateTime(s.next_review)}. Funziona mentre il server è acceso; recupera le scadenze al riavvio.` : "Scheduler disattivato.";
  $("proof").textContent = s.test_proof?.valid ? `Test verificato · Garmin workout ID ${s.test_proof.workout_id} · ${dateTime(s.test_proof.verified_at)}. Nessuna sync completa eseguita dal test.` : "Prima della sync, verifica un singolo workout Garmin.";
  renderActivities(s.activities);
}
async function load() { const [s,p] = await Promise.all([api("/api/dashboard/summary"),api("/api/plan")]); currentPlan=p; currentSummary=s; renderSummary(s); renderPlan(p,s); }
$("refresh").onclick = () => operation("Aggiornamento Garmin…", async () => { const r=await api("/api/activities/refresh","POST"); notice(`${r.count} attività lette. Metriche aggiornate.`); });
$("review").onclick = () => operation("Lettura Garmin e review…", async () => { const r=await api("/api/review/run","POST"); notice(`Review salvata · ${r.matches.length} sessioni · ${r.flags.length} flag.`); });
$("preview").onclick = () => operation("Confronto del calendario con il piano…", async () => {
  preview = null; $("preview-wrap").hidden=true;
  preview = await api("/api/calendar/cleanup/preview","POST");
  $("preview-summary").textContent = `${preview.start} → ${preview.end} · ${preview.remove_count} schedulazioni da rimuovere. Preview valida per 15 minuti.`;
  $("preview-body").replaceChildren(...preview.rows.map(r => { const tr=element("tr"); [dateLabel(r.date),r.name,r.scheduled_id,r.action === "keep" ? "MANTIENI" : "RIMUOVI DAL CALENDARIO",r.reason].forEach(v=>tr.append(element("td",v))); return tr; }));
  $("preview-wrap").hidden=false; notice("Preview pronta. Controlla tutte le righe prima di applicare la pulizia.");
});
$("apply").onclick = async () => {
  if (!preview || busy) return;
  if (!await confirmAction("Applicare questa pulizia?", `Rimuoverai ${preview.remove_count} schedulazioni mostrate nella preview (${preview.start} → ${preview.end}). Attività registrate e template nella libreria saranno conservati.`)) return;
  operation("Rimozione delle sole schedulazioni confermate…", async () => {
    const r = await api("/api/calendar/cleanup/apply","POST",{preview_id:preview.preview_id,confirmed:true}); preview=null;
    $("preview-wrap").hidden=true; notice(r.status === "partial" ? `Pulizia interrotta: ${r.removed.length} rimozioni. ${r.error}` : `Pulizia completata: ${r.removed.length} schedulazioni rimosse.`,r.status === "partial");
  });
};
$("test").onclick = () => operation("Test di un singolo workout: upload/riuso e rilettura delle fasi…", async () => {
  const r=await api("/api/plan/test","POST",{}); notice(`Struttura verificata su Garmin · ID ${r.workout_id}. Warmup, repeat, intervalli, target e cooldown verificati. Il test non schedula.`);
});
$("sync").onclick = async () => {
  if (busy) return;
  if (!currentSummary?.test_proof?.valid) { notice("Premi prima Test 1 workout e controlla il risultato.",true); return; }
  if (!await confirmAction("Confermi il test e il piano?", "La sync creerà, verificherà e schedulerà le sessioni future. Le versioni precedenti gestite da questo coach saranno sostituite. Per workout estranei usa la pulizia con preview.")) return;
  operation("Sincronizzazione del piano Garmin…",async () => { const r=await api("/api/plan/sync","POST",{confirmed:true}); preview=null; $("preview-wrap").hidden=true; notice(r.status === "complete" ? "Piano sincronizzato. Tutti i workout schedulati hanno superato la verifica." : `Sync interrotta: ${r.results.at(-1)?.message || "Controlla lo stato."}`,r.status !== "complete"); });
};
$("edit-plan").onclick = () => { $("plan-json").value=JSON.stringify(currentPlan,null,2); $("editor-error").textContent=""; $("editor").showModal(); };
$("close-editor").onclick = () => $("editor").close();
$("save-plan").onclick = async () => {
  try { const value=JSON.parse($("plan-json").value); await api("/api/plan","PUT",value); $("editor").close(); preview=null; $("apply").disabled=true; $("preview-wrap").hidden=true; await load(); notice("Piano validato e salvato. Esegui di nuovo il test prima della sync."); }
  catch(e) { $("editor-error").textContent=e.message; }
};
load().catch(e => notice(e.message,true));
setInterval(() => { if (!busy && !$("editor").open) load().catch(e => notice(e.message,true)); },30000);
