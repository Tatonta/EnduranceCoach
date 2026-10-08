"use strict";
const $ = id => document.getElementById(id);
const weekdays = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"];
let currentStep = 0, version = 0, loaded = false;
function el(tag, text, cls) { const node = document.createElement(tag); if (text) node.textContent = text; if (cls) node.className = cls; return node; }
function error(text) { $("intake-error").textContent = text; $("intake-error").hidden = !text; }
async function api(path, options = {}) { const response = await fetch(path, {headers: {"Content-Type": "application/json"}, ...options}); const data = await response.json(); if (!response.ok) throw new Error(data.detail || "Operazione non completata."); return data; }
const today = new Date().toLocaleDateString("en-CA");
const tomorrow = new Date(); tomorrow.setDate(tomorrow.getDate() + 1);
$("target-date").min = tomorrow.toLocaleDateString("en-CA");
weekdays.forEach((day, weekday) => {
  const box = el("div", null, "availability-day"), check = el("input"), minutes = el("input");
  check.type = "checkbox"; check.id = `day-${weekday}`;
  minutes.type = "number"; minutes.min = 15; minutes.max = 240; minutes.step = 1; minutes.value = 45; minutes.disabled = true; minutes.id = `minutes-${weekday}`;
  const label = el("label", null, "check-label"); label.append(check, document.createTextNode(day));
  const timeLabel = el("label", "Minuti disponibili"); timeLabel.append(minutes);
  box.append(label, timeLabel); $("availability").append(box);
  check.addEventListener("change", () => { minutes.disabled = !check.checked; minutes.required = check.checked; });
});
function timeText(seconds) { const value = Math.round(seconds); return `${Math.floor(value / 3600)}:${String(Math.floor(value / 60) % 60).padStart(2,"0")}:${String(value % 60).padStart(2,"0")}`; }
function addPerformance(value = null) {
  if ($("best-performances").children.length >= 20) { error("Puoi inserire fino a 20 prestazioni."); return; }
  const row = el("div", null, "performance-row"), fields = el("div", null, "intake-fields");
  const sport = el("select"); sport.dataset.field = "sport";
  sport.append(new Option("Corsa", "running"), new Option("Ciclismo", "cycling"));
  const distance = el("input"), duration = el("input"), date = el("input"), note = el("input");
  Object.assign(distance,{type:"number",min:"0.4",max:"500",step:"0.001",required:true}); distance.dataset.field = "distance";
  Object.assign(duration,{type:"text",placeholder:"0:45:00",required:true,pattern:"[0-9]{1,2}:[0-5][0-9]:[0-5][0-9]"}); duration.dataset.field = "duration";
  date.type = "date"; date.max = today; date.dataset.field = "date";
  note.maxLength = 300; note.dataset.field = "note";
  [["Sport",sport],["Distanza, km",distance],["Tempo totale, h:mm:ss",duration],["Data (facoltativa)",date],["Contesto (facoltativo)",note]].forEach(([text,input])=>{const label=el("label",text);label.append(input);fields.append(label);});
  const remove = el("button", "Rimuovi prestazione"); remove.type = "button"; remove.addEventListener("click",()=>row.remove());
  row.append(fields,remove); $("best-performances").append(row);
  if (value) { sport.value=value.sport; distance.value=value.distance_m / 1000; duration.value=timeText(value.duration_s); date.value=value.date || ""; note.value=value.note || ""; }
}
$("add-performance").addEventListener("click",()=>addPerformance());
function deviceChanged() { const none=$("device-vendor").value==="none"; $("device-model").disabled=none; if(none) $("device-model").value=""; $("device-note").textContent=none ? "Senza dispositivo puoi comunque ricevere coaching e riportare durata, sensazioni e progressi. FC, split e percorso saranno disponibili solo se misurati." : "La scelta del dispositivo prepara il profilo. Il collegamento dell'account e la disponibilità delle metriche sono passaggi separati."; }
$("device-vendor").addEventListener("change",deviceChanged);
$("deadline-flexible").addEventListener("change",()=>{$("target-date").required=!$("deadline-flexible").checked;});
function collect() {
  const numeric = id => $(id).value === "" ? null : Number($(id).value);
  const performances=Array.from($("best-performances").children).map(row=>{ const input=field=>row.querySelector(`[data-field="${field}"]`).value; const parts=input("duration").split(":").map(Number); return {sport:input("sport"),distance_m:Number(input("distance"))*1000,duration_s:parts[0]*3600+parts[1]*60+parts[2],date:input("date") || null,note:input("note")}; });
  return {schema_version:1,primary_sport:$("primary-sport").value,goal_type:$("goal-type").value,goal_description:$("goal-description").value.trim(),target_date:$("target-date").value || null,deadline_flexible:$("deadline-flexible").checked,
    age_years:numeric("age-years"),weight_kg:numeric("weight-kg"),height_cm:numeric("height-cm"),device_vendor:$("device-vendor").value,device_model:$("device-model").value,
    heart_rate_sensor:$("heart-rate-sensor").checked,power_meter:$("power-meter").checked,running_years:numeric("running-years"),cycling_years:numeric("cycling-years"),recent_running_km_week:numeric("running-km"),recent_cycling_km_week:numeric("cycling-km"),experience_notes:$("experience-notes").value,
    gym_sessions_week:Number($("gym-sessions").value),gym_notes:$("gym-notes").value,availability:weekdays.flatMap((_,i)=>$("day-"+i).checked?[{weekday:i,minutes:Number($("minutes-"+i).value)}]:[]),best_performances:performances,constraints:$("constraints").value,coaching_consent:$("coaching-consent").checked};
}
function fill(profile) {
  const mapping={"primary-sport":"primary_sport","goal-type":"goal_type","goal-description":"goal_description","target-date":"target_date","age-years":"age_years","weight-kg":"weight_kg","height-cm":"height_cm","device-vendor":"device_vendor","device-model":"device_model","running-years":"running_years","cycling-years":"cycling_years","running-km":"recent_running_km_week","cycling-km":"recent_cycling_km_week","experience-notes":"experience_notes","gym-sessions":"gym_sessions_week","gym-notes":"gym_notes","constraints":"constraints"};
  for(const [id,key] of Object.entries(mapping)) $(id).value=profile[key] ?? "";
  for(const [id,key] of Object.entries({"deadline-flexible":"deadline_flexible","heart-rate-sensor":"heart_rate_sensor","power-meter":"power_meter","coaching-consent":"coaching_consent"})) $(id).checked=profile[key];
  for(const day of profile.availability){$("day-"+day.weekday).checked=true;$("minutes-"+day.weekday).disabled=false;$("minutes-"+day.weekday).required=true;$("minutes-"+day.weekday).value=day.minutes;}
  profile.best_performances.forEach(addPerformance); deviceChanged(); $("target-date").required=!profile.deadline_flexible;
}
function summary() {
  const p=collect(), list=el("dl",null,"profile-summary");
  const items=[["Obiettivo",p.goal_description],["Scadenza",p.target_date ? `${p.target_date}${p.deadline_flexible?" · flessibile":""}` : "Da definire con il coach"],["Sport",$("primary-sport").selectedOptions[0].text],["Profilo",`${p.age_years ?? "—"} anni · ${p.weight_kg ?? "—"} kg · ${p.height_cm ?? "—"} cm`],["Dispositivo",$("device-vendor").selectedOptions[0].text+(p.device_model?` · ${p.device_model}`:"")],["Base recente",`Corsa ${p.recent_running_km_week} km/sett. · bici ${p.recent_cycling_km_week} km/sett.`],["Disponibilità",p.availability.map(d=>`${weekdays[d.weekday]} ${d.minutes} min`).join(" · ")],["Palestra",`${p.gym_sessions_week} sedute/sett. ${p.gym_notes}`],["Migliori tempi",p.best_performances.map(b=>`${b.sport==="running"?"Corsa":"Bici"} ${b.distance_m/1000} km in ${timeText(b.duration_s)}`).join(" · ") || "Non inseriti"],["Vincoli",p.constraints || "Non indicati"]];
  items.forEach(([key,value])=>{const row=el("div");row.append(el("dt",key),el("dd",value));list.append(row);});$("profile-summary").replaceChildren(list);
}
function showStep(step) {
  currentStep=step; document.querySelectorAll(".intake-step").forEach((section,i)=>{section.hidden=i!==step;});
  document.querySelectorAll(".intake-progress span").forEach((node,i)=>{if(i===step) node.setAttribute("aria-current","step");else node.removeAttribute("aria-current");});
  $("previous-step").hidden=step===0; $("next-step").hidden=step===4; $("save-intake").hidden=step!==4; $("step-count").textContent=`Passaggio ${step+1} di 5`;
  if(step===4) summary(); error(""); window.scrollTo({top:0});
}
function validateStep(step) {
  const section=document.querySelector(`[data-step="${step}"]`);
  for(const field of section.querySelectorAll("input,select,textarea")) if(!field.checkValidity()){showStep(step);field.reportValidity();return false;}
  if(step===0 && $("goal-description").value.trim().length<10){error("Descrivi l'obiettivo con almeno 10 caratteri.");return false;}
  if(step===3 && !weekdays.some((_,i)=>$("day-"+i).checked)){error("Seleziona almeno un giorno disponibile.");return false;}
  return true;
}
$("next-step").addEventListener("click",()=>{if(validateStep(currentStep)) showStep(currentStep+1);});
$("previous-step").addEventListener("click",()=>showStep(currentStep-1));
$("intake-form").addEventListener("submit",async event=>{event.preventDefault();if(!loaded)return;for(let step=0;step<5;step++)if(!validateStep(step)){return;}
  $("save-intake").disabled=true; try{await api("/api/profile",{method:"PUT",body:JSON.stringify({expected_version:version,profile:collect()})});window.location.assign("/coach");}catch(failure){error(failure.message);}finally{$("save-intake").disabled=false;}
});
showStep(0);
(async()=>{ $("next-step").disabled=true; try{const state=await api("/api/profile");version=state.version;if(state.profile){fill(state.profile);$("back-coach").hidden=false;}loaded=true;}catch(failure){error(failure.message);}finally{$("next-step").disabled=!loaded;}})();
