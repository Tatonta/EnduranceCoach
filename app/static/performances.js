"use strict";
const $ = id => document.getElementById(id);
let busy = false;
const date = value => value ? new Date(`${value.slice(0,10)}T12:00:00`).toLocaleDateString("it-IT",{day:"2-digit",month:"short",year:"numeric"}) : "—";
const time = seconds => { if (!seconds) return "—"; let n=Math.round(seconds); return n>=3600 ? `${Math.floor(n/3600)}:${String(Math.floor(n%3600/60)).padStart(2,"0")}:${String(n%60).padStart(2,"0")}` : `${Math.floor(n/60)}:${String(n%60).padStart(2,"0")}`; };
function el(tag,text="",className="") { const e=document.createElement(tag); e.textContent=text; e.className=className; return e; }
function notice(text,error=false) { $("notice").hidden=false; $("notice").textContent=text; $("notice").className=error?"error":""; }
async function api(path,method="GET",body) { const r=await fetch(path,{method,headers:{"Content-Type":"application/json"},...(body!==undefined?{body:JSON.stringify(body)}:{})}); const data=await r.json(); if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Dati non validi. Controlla i valori inseriti."); return data; }
async function action(text,fn) { if(busy)return; busy=true; document.querySelectorAll("button").forEach(b=>b.disabled=true); notice(text); try { await fn(); await load(); }catch(e){notice(e.message,true);} finally{busy=false;document.querySelectorAll("button").forEach(b=>b.disabled=false);} }
function render(data) {
  $("bests-updated").textContent=`Aggiornato: ${date(data.generated_at)}`;
  ["5k","10k","half","marathon"].forEach(key=>{const row=data.rows.find(r=>r.distance_key===key);$("best-"+key).textContent=time(row?.duration_s);$("date-"+key).textContent=row?.available?date(row.date):"Nessun dato disponibile";});
  const coverage=data.coverage;
  $("coverage").textContent=coverage?`${coverage.running_activities} corse nello storico Garmin · dal ${date(coverage.oldest_date)}. ${coverage.details_missing ? `${coverage.details_missing} attività senza campioni utilizzabili: copertura parziale per le distanze calcolate.` : "Campioni disponibili per tutte le corse."}${coverage.activities_with_sample_breaks ? ` In ${coverage.activities_with_sample_breaks} attività sono esclusi tratti con campioni incoerenti.` : ""}`:"Premi Aggiorna migliori tempi per leggere lo storico Garmin.";
  if(data.note)$("bests-note").textContent=data.note;
  $("bests-body").replaceChildren(...data.rows.map(row=>{
    const tr=el("tr"), distance=el("td",row.distance_label); tr.append(distance,el("td",time(row.duration_s),"best-time"),el("td",row.avg_pace_s_km?`${time(row.avg_pace_s_km)}/km`:"—"),el("td",date(row.date)));
    const activity=el("td"); if(row.garmin_url){const a=el("a",row.activity_name);a.href=row.garmin_url;a.target="_blank";a.rel="noopener";activity.append(a,el("small",row.source,"sport-sub"));}else activity.textContent="Nessun tratto disponibile";tr.append(activity);
    return tr;
  }));
}
async function load(){const data=await api("/api/performances");render(data);if(data.progress)notice(`Analisi storico in corso · ${data.progress.current}/${data.progress.total} corse.`);}
$("refresh-bests").onclick=()=>action("Analisi dei migliori tempi su tutte le corse Garmin…",async()=>{const r=await api("/api/performances/refresh","POST");notice(`Migliori tempi aggiornati · ${r.coverage.running_activities} corse analizzate.`);});
load().catch(e=>notice(e.message,true));
setInterval(()=>{if(!busy)load().catch(e=>notice(e.message,true));},15000);
