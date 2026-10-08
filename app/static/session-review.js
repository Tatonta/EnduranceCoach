"use strict";
// Official loopback OAuth callback uses 127.0.0.1; keep the browser cookie on that host.
if (location.hostname === "localhost") location.replace(`http://127.0.0.1:${location.port || "8000"}/review${location.hash}`);
let sessionDetail = null, sessionMap = null, routeLayer = null, hoverMarker = null;
let sessionBusy = false, chatStatus = null, catalogAccount = null;
const strideValue = value => value == null ? "—" : Number(value).toLocaleString("it-IT", {minimumFractionDigits:2, maximumFractionDigits:2});
function detailBusy(value) {
  sessionBusy = value;
  ["read-session", "session-activity", "generate-brain", "connect-chatgpt", "disconnect-chatgpt", "chatgpt-accounts", "chatgpt-model"].forEach(id => $(id).disabled = value);
}
function metricTile(label, value) { const el = node("div", ""); el.append(node("small", label), node("strong", value)); return el; }
function renderDetailedSummary() {
  if (!sessionDetail || sessionDetail.status !== "ready") return;
  const a = sessionDetail.activity, d = sessionDetail.analysis, m = sessionDetail.match;
  $("workout-name").textContent = a.name;
  $("workout-meta").textContent = `${a.sport.toUpperCase()} · ${date(a.date)} · LAP E CAMPIONI GARMIN`;
  $("workout-verdict").textContent = d.verdict;
  $("workout-stats").replaceChildren(...[["Distanza", `${number(a.distance_m / 1000)} km`], ["Durata attiva", duration(a.duration_s)], ["Passo medio", pace(a.avg_pace_s_km)], ["FC media/max", `${number(a.avg_hr)} / ${number(a.max_hr)} bpm`], ["Dislivello", `${number(a.elevation_gain_m)} m`]].map(v => metricTile(...v)));
  $("workout-match").textContent = m ? `${m.planned_name} · previsti ${duration(m.planned_duration_s)} · registrati ${duration(a.duration_s)}` : "Sessione senza associazione certa: i dati reali sono mostrati, senza imporre target di un'altra seduta.";
  $("workout-note").textContent = "Le fasi qui sotto sono ricostruite dai lap e dagli indici degli step Garmin. Il confronto usa il piano corrente.";
  $("advice-list").replaceChildren(...d.actions.map(text => node("li", text)));
}
function evidenceList(id, title, items, className) {
  const root = $(id); root.replaceChildren();
  if (!items.length) return;
  const list = node("ul", "", "session-findings");
  items.forEach(item => list.append(node("li", item)));
  root.append(node("h3", title, className), list);
}
function renderSession(value) {
  sessionDetail = value;
  if (value.status !== "ready") { $("detail-status").textContent = value.message; return; }
  const d = value.analysis;
  renderDetailedSummary();
  $("detail-status").textContent = `${d.coverage.lap_count} lap · ${d.coverage.sample_count} campioni · dettagli letti ${date(value.fetched_at)}`;
  $("session-judgement").textContent = d.verdict;
  evidenceList("session-positive", "Cosa è riuscito", d.positive, "finding-positive");
  evidenceList("session-issues", "Cosa correggere o chiarire", d.issues, "finding-warning");
  evidenceList("session-actions", "Per la prossima seduta", d.actions, "finding-action");
  const mechanics = d.dynamics;
  $("session-dynamics").replaceChildren(...[["Cadenza", `${number(mechanics.cadence_spm)} passi/min`], ["Stride length", `${strideValue(mechanics.stride_m)} m`], ["Contatto a terra", `${number(mechanics.gct_ms)} ms`], ["Oscillazione verticale", `${number(mechanics.vertical_cm)} cm`], ["Rapporto verticale", `${number(mechanics.vertical_ratio_percent)}%`], ["Potenza", `${number(mechanics.power_w)} W`]].map(v => metricTile(...v)));
  $("session-locomotion").textContent = `Garmin distingue: corsa ${duration(d.locomotion_s.RWD_RUN)} · cammino ${duration(d.locomotion_s.RWD_WALK)} · soste ${duration(d.locomotion_s.RWD_STAND)}.`;
  $("phase-list").replaceChildren(...d.phases.map(phase => {
    const el = node("article", "", "session-phase");
    const heading = node("div", "", "section-heading"); heading.append(node("h3", `${phase.number}. ${phase.name}`), node("span", phase.verdict, `badge ${phase.verdict.includes("troppo") ? "phase-warning" : ""}`));
    el.append(heading, node("p", `${duration(phase.duration_s)} · ${number(phase.distance_m / 1000)} km · ${pace(phase.pace_s_km)} · FC media ${number(phase.avg_hr)} bpm`));
    if (phase.target?.type === "pace") el.append(node("p", `Target: ${phase.target.fast}–${phase.target.slow}/km · scostamento ${number(phase.pace_delta_s)} s/km`, "small"));
    if (phase.hr_reference) el.append(node("p", `FC di riferimento: Z${phase.hr_reference.zone} · ${phase.hr_reference.low}–${phase.hr_reference.high ?? "oltre"} bpm · ${phase.hr_reference.explicit ? "target del piano" : "riferimento easy indicativo"}`, "small"));
    if (phase.planned_duration_s) el.append(node("p", `Durata prevista ${duration(phase.planned_duration_s)} · ${phase.duration_compliance} · lap ${phase.lap_numbers.join(", ")}`, "small"));
    if (phase.hr_mean_difference_bpm != null) el.append(node("p", `Differenza fra FC media del lavoro precedente e recupero: ${number(phase.hr_mean_difference_bpm)} bpm`, "small"));
    return el;
  }));
  $("session-laps").replaceChildren(...d.laps.map(lap => {
    const tr = node("tr", "");
    [lap.lap, lap.phase, number(lap.distance_m / 1000), duration(lap.duration_s), pace(lap.pace_s_km), `${number(lap.avg_hr)} / ${number(lap.max_hr)}`, lap.hr_zone ? `Z${lap.hr_zone}` : "—", `${number(lap.cadence_spm)} spm`, `${strideValue(lap.stride_m)} m`].forEach(text => tr.append(node("td", String(text))));
    if(lap.quality_flags?.length) {tr.className="lap-quality-warning";tr.children[1].append(node("small"," · Dinamiche parziali"));}
    return tr;
  }));
  $("session-coverage").textContent = `${d.method} ${value.fetch_errors.length ? `Letture non riuscite: ${value.fetch_errors.join(", ")}.` : ""}`;
  if (value.brain) showBrain(value.brain);
  else { $("brain-text").hidden = true; $("brain-text").textContent = ""; }
  drawSessionMap(); drawSessionChart();
}
function drawSessionMap() {
  if (!sessionDetail?.analysis || typeof L === "undefined") return;
  if (!sessionMap) {
    sessionMap = L.map("session-map", {zoomAnimation:false,fadeAnimation:false,markerZoomAnimation:false});
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {maxZoom:19, attribution:"© OpenStreetMap contributors"}).addTo(sessionMap);
  }
  if (routeLayer) sessionMap.removeLayer(routeLayer);
  if (hoverMarker) {sessionMap.removeLayer(hoverMarker);hoverMarker=null;}
  const points = sessionDetail.analysis.route;
  if (points.length > 1) { routeLayer = L.featureGroup([L.polyline(points,{color:"#163b43",weight:8}),L.polyline(points,{color:"#79e4c2",weight:4})]).addTo(sessionMap); sessionMap.fitBounds(routeLayer.getBounds(), {padding:[28,28],animate:false}); }
  else { sessionMap.setView([45,10], 4); $("session-coverage").textContent += " Percorso GPS non disponibile per questa seduta."; }
  setTimeout(() => {sessionMap.invalidateSize({pan:false});if(routeLayer){const bounds=routeLayer.getBounds();sessionMap.setView(bounds.getCenter(),Math.min(17,sessionMap.getBoundsZoom(bounds,false,L.point(48,48))),{animate:false,reset:true});}}, 120);
}
function drawSessionChart() {
  const chart = $("session-chart"), samples = sessionDetail?.analysis?.series || [];
  chart.replaceChildren();
  const width = Math.max(chart.parentElement.clientWidth, 280), height = 330, left = 50, right = width - 48, top = 24, bottom = 285;
  chart.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const usable = samples.filter(p => p.pace_s_km != null || p.hr != null);
  if (!usable.length) return;
  const xmax = samples.at(-1).elapsed_s || 1;
  const paces = samples.map(p => p.pace_s_km).filter(p => p != null && p < 1000), hrs = samples.map(p => p.hr).filter(p => p != null);
  const pmin = Math.min(...paces, 240), pmax = Math.max(...paces, 600), hmin = Math.min(...hrs, 100), hmax = Math.max(...hrs, 180);
  const ns = "http://www.w3.org/2000/svg";
  function svg(tag, attrs) { const el = document.createElementNS(ns, tag); Object.entries(attrs).forEach(([k,v]) => el.setAttribute(k,String(v))); chart.append(el); return el; }
  function label(x,y,text,anchor="start",color="#94a4b7") { const el=svg("text",{x,y,"text-anchor":anchor,fill:color,"font-size":12}); el.textContent=text; }
  const x = t => left + t / xmax * (right-left), yp = p => top+(p-pmin)/(pmax-pmin)*(bottom-top), yh = h => bottom-(h-hmin)/(hmax-hmin)*(bottom-top);
  for(let i=0;i<5;i++) { const y=top+i/4*(bottom-top); svg("line",{x1:left,y1:y,x2:right,y2:y,stroke:"#253140"}); label(left-7,y+4,pace(pmin+i/4*(pmax-pmin)).replace("/km",""),"end","#79e4c2"); label(right+7,y+4,Math.round(hmax-i/4*(hmax-hmin))+"", "start", "#efc17a"); }
  for(let i=0;i<5;i++) label(x(i/4*xmax),310,Math.round(i/4*xmax/60)+"′","middle");
  label(left,14,"Passo/km","start","#79e4c2"); label(right,14,"FC bpm","end","#efc17a");
  for(const [key,scale,color] of [["pace_s_km",yp,"#79e4c2"],["hr",yh,"#efc17a"]]) {
    let path="", open=false;
    samples.forEach(point => { const value=point[key]; if(value==null || (key==="pace_s_km"&&value>1000)) {open=false;return;} path+=`${open?"L":"M"}${x(point.elapsed_s).toFixed(1)},${scale(value).toFixed(1)} `;open=true; });
    svg("path",{d:path,fill:"none",stroke:color,"stroke-width":1.7});
  }
  chart.onpointerdown = event => {
    const bounds=chart.getBoundingClientRect(), elapsed=Math.max(0,Math.min(xmax,((event.clientX-bounds.left)/bounds.width*width-left)/(right-left)*xmax));
    const point=samples.reduce((best,p)=>Math.abs(p.elapsed_s-elapsed)<Math.abs(best.elapsed_s-elapsed)?p:best,samples[0]);
    $("chart-hover").textContent = `${duration(point.elapsed_s)} · km ${number(point.distance_m/1000)} · ${pace(point.pace_s_km)} · FC ${number(point.hr)} bpm · cadenza ${number(point.cadence_spm)} spm · stride ${number(point.stride_m)} m`;
    if(point.lat!=null&&sessionMap) {if(hoverMarker)sessionMap.removeLayer(hoverMarker);hoverMarker=L.circleMarker([point.lat,point.lon],{radius:7,color:"#efc17a"}).addTo(sessionMap);sessionMap.panTo([point.lat,point.lon]);}
  };
}
async function refreshDetailed(force=false) {
  detailBusy(true); $("detail-status").textContent="Lettura di lap, fasi, dinamiche e percorso…";
  try {
    const activity_id=$("session-activity").value||null;
    let value=force ? await api("/api/session-review/refresh","POST",{activity_id}) : await api(`/api/session-review${activity_id ? "?activity_id="+encodeURIComponent(activity_id) : ""}`);
    if(value.status==="not_loaded") value=await api("/api/session-review/refresh","POST",{activity_id});
    renderSession(value);
  } catch(error) { $("detail-status").textContent=error.message; }
  finally { detailBusy(false); }
}
function showBrain(answer) { $("brain-text").hidden=false; $("brain-text").textContent=answer.text; $("brain-status").textContent=`Review ChatGPT · ${answer.model} · ${new Date(answer.generated_at*1000).toLocaleString("it-IT")}`; }
async function syncChatGPT() {
  chatStatus=await api("/api/chatgpt/status");
  $("chatgpt-state").textContent=chatStatus.plan_enabled ? "Using ChatGPT plan" : chatStatus.connected ? "Consenso al piano da completare" : "Account da collegare";
  $("disconnect-chatgpt").hidden=!chatStatus.connected;
  $("generate-brain").hidden=!chatStatus.plan_enabled;
  $("chatgpt-accounts").hidden=!chatStatus.profiles.length;
  $("chatgpt-accounts").replaceChildren(...chatStatus.profiles.map(p=>{const op=node("option",`${p.label} · ${p.id.slice(0,6)}`);op.value=p.id;return op;}));
  if(chatStatus.retry_registration){const retry=node("option","Riprova il collegamento precedente");retry.value="retry";$("chatgpt-accounts").append(retry);$("chatgpt-accounts").hidden=false;}
  const extra=node("option","Aggiungi altro account / workspace");extra.value="new";$("chatgpt-accounts").append(extra);$("chatgpt-accounts").value=chatStatus.active||(chatStatus.retry_registration?"retry":"new");
  if(chatStatus.error) $("brain-status").textContent=chatStatus.error;
  if(chatStatus.plan_enabled && catalogAccount!==chatStatus.active) {
    const result=await api("/api/chatgpt/models");
    $("chatgpt-model").replaceChildren(...result.models.map(m=>{const op=node("option",m.name);op.value=m.id;return op;}));
    $("chatgpt-model").hidden=false;catalogAccount=chatStatus.active;
  } else if(!chatStatus.plan_enabled) {$("chatgpt-model").hidden=true;catalogAccount=null;}
  if(chatStatus.welcome_required&&!$("chatgpt-welcome").open) $("chatgpt-welcome").showModal();
}
$("read-session").onclick=()=>refreshDetailed(true);
$("session-activity").onchange=()=>refreshDetailed();
$("connect-chatgpt").onclick=async()=>{detailBusy(true);try{const intake=await api("/api/profile");if(!intake.profile){location.assign("/onboarding");return;}const selected=$("chatgpt-accounts").value;const result=await api("/api/chatgpt/connect","POST",{profile_id:selected&&!['new','retry'].includes(selected)?selected:null,fresh_registration:selected==='new'});location.assign(result.authorization_url);}catch(e){$("brain-status").textContent=e.message;detailBusy(false);}};
$("chatgpt-accounts").onchange=async()=>{if(['new','retry'].includes($("chatgpt-accounts").value))return;try{await api("/api/chatgpt/select","POST",{profile_id:$("chatgpt-accounts").value});await syncChatGPT();await refreshDetailed();}catch(e){$("brain-status").textContent=e.message;}};
$("disconnect-chatgpt").onclick=async()=>{try{const result=await api("/api/chatgpt/disconnect","POST");$("brain-status").textContent=result.remote_revoked?"Account scollegato.":"Sessione locale rimossa; revoca remota non confermata. Gestisci il collegamento in ChatGPT.";await syncChatGPT();$("brain-text").hidden=true;}catch(e){$("brain-status").textContent=e.message;}};
$("ack-chatgpt").onclick=async()=>{await api("/api/chatgpt/welcome","POST");$("chatgpt-welcome").close();};
$("generate-brain").onclick=async()=>{if(sessionBusy||sessionDetail?.status!=="ready")return;detailBusy(true);$("brain-status").textContent="ChatGPT sta valutando fasi, intensità e storico…";try{showBrain(await api("/api/session-review/brain","POST",{activity_id:sessionDetail.activity.activity_id,model:$("chatgpt-model").value}));}catch(e){$("brain-status").textContent=e.message;}finally{detailBusy(false);}};
new ResizeObserver(()=>{if(sessionDetail?.status==="ready")drawSessionChart();}).observe($("session-chart").parentElement);
["tab-review","tab-advice"].forEach(id=>$(id).addEventListener("click",()=>setTimeout(()=>{sessionMap?.invalidateSize({pan:false});if(routeLayer&&sessionMap)sessionMap.fitBounds(routeLayer.getBounds(),{padding:[24,24],maxZoom:17,animate:false});drawSessionChart();},80)));
api("/api/activities/recent?limit=40").then(value=>{value.activities.forEach(a=>{const op=node("option",`${date(a.date)} · ${a.name}`);op.value=a.activity_id;$("session-activity").append(op);});}).catch(()=>{});
syncChatGPT().catch(error=>{$("brain-status").textContent=error.message;});
refreshDetailed();
