"use strict";
const $=id=>document.getElementById(id), days=["Lunedì","Martedì","Mercoledì","Giovedì","Venerdì","Sabato","Domenica"];
let state=null, modelAccount=null, draft=null, busy=false;
function el(tag,text,cls){const node=document.createElement(tag);node.textContent=text || "";if(cls)node.className=cls;return node;}
async function api(path,options={}){const response=await fetch(path,{headers:{"Content-Type":"application/json"},...options});const data=await response.json();if(!response.ok)throw new Error(data.detail || "Operazione non completata.");return data;}
function error(text){$("coach-error").textContent=text;$("coach-error").hidden=!text;}
function controls(){const connected=!!state?.chatgpt.profiles.find(p=>p.id===state.chatgpt.active)?.plan_enabled;
  $("send-message").disabled=busy || !connected || !$("model").value;$("create-plan").disabled=busy || !connected || !$("model").value || state?.has_plan;
  for(const id of ["connect","disconnect","account","model"])$(id).disabled=busy;
}
async function load(){state=await api("/api/assistant");if(!state.intake.profile){window.location.assign("/onboarding");return;}
  const p=state.intake.profile;$("coach-goal").textContent=p.goal_description;$("coach-timeline").textContent=p.target_date?`Obiettivo entro ${p.target_date}${p.deadline_flexible?" · scadenza flessibile":""}`:"Scadenza da definire con il coach";
  $("week-summary").replaceChildren(...[...p.availability].sort((a,b)=>a.weekday-b.weekday).map(day=>el("div",`${days[day.weekday]} · fino a ${day.minutes} min`,"weekly-day")));
  $("gym-summary").textContent=`Palestra/forza: ${p.gym_sessions_week} sedute/settimana${p.gym_notes?` · ${p.gym_notes}`:""}. Il tempo disponibile include tutte le sedute.`;
  $("device-summary").textContent=p.device_vendor==="none"?"Nessun dispositivo: il coach userà il contesto e i tuoi feedback, con meno dettagli tecnici.":`${p.device_vendor.toUpperCase()} ${p.device_model} · scelta registrata; le connessioni e i dati disponibili sono verificati separatamente.`;
  $("existing-plan").textContent=state.has_plan?"Il tuo programma esiste già. Le proposte di adattamento si trovano nella review, quando il trend le giustifica.":"Il coach può preparare una bozza iniziale dopo il collegamento ChatGPT.";
  $("review-link").hidden=!state.has_plan;
  $("conversation").replaceChildren(...state.conversation.flatMap(item=>[el("div",item.question,"coach-message question"),el("div",item.answer,"coach-message")]));
  const s=state.chatgpt,active=s.profiles.find(p=>p.id===s.active),connected=!!active?.plan_enabled;
  $("coach-connection").textContent=connected?"ChatGPT collegato · scegli il modello e invia una domanda.":active?.connected?"Account collegato; autorizza anche l'uso del piano ChatGPT.":"Collega il tuo account ChatGPT per parlare con il coach.";
  $("connect").hidden=connected;$("disconnect").hidden=!active?.connected;$("account").hidden=!s.profiles.length;
  $("account").replaceChildren(new Option("Collega un altro account…",""),...s.profiles.map(p=>new Option(p.label+(p.email?` · ${p.email}`:""),p.id)));$("account").value=s.active || "";
  $("model").hidden=!connected;
  if(connected && modelAccount!==s.active){const result=await api("/api/chatgpt/models");$("model").replaceChildren(...result.models.map(m=>new Option(m.name,m.id)));modelAccount=s.active;}
  if(!connected){modelAccount=null;$("model").replaceChildren();}
  if(s.welcome_required && !$("welcome").open)$("welcome").showModal();controls();
}
async function operation(task){if(busy)return;busy=true;error("");controls();try{await task();}catch(failure){error(failure.message);}finally{busy=false;controls();}}
async function connect(fresh=false){if(location.hostname==="localhost"){location.replace(`http://127.0.0.1:${location.port}/coach`);return;}
  const reply=await api("/api/chatgpt/connect",{method:"POST",body:JSON.stringify({profile_id:state.chatgpt.active || null,fresh_registration:fresh,return_to:"coach"})});location.assign(reply.authorization_url);
}
$("connect").addEventListener("click",()=>operation(()=>connect()));
$("account").addEventListener("change",()=>operation(async()=>{if(!$("account").value){await connect(true);return;}await api("/api/chatgpt/select",{method:"POST",body:JSON.stringify({profile_id:$("account").value})});$("conversation").replaceChildren();await load();}));
$("model").addEventListener("change",controls);
$("disconnect").addEventListener("click",()=>operation(async()=>{const reply=await api("/api/chatgpt/disconnect",{method:"POST"});$("conversation").replaceChildren();await load();if(!reply.remote_revoked)error("Sessione rimossa localmente; la revoca remota non è stata confermata. Controlla gli accessi in ChatGPT.");}));
$("ack-welcome").addEventListener("click",()=>operation(async()=>{await api("/api/chatgpt/welcome",{method:"POST"});$("welcome").close();}));
async function send(purpose){const question=$("question").value.trim() || (purpose==="initial_plan"?"Prepara una bozza iniziale coerente con il mio obiettivo e la mia disponibilità.":"");if(question.length<5){error("Scrivi una domanda per il coach.");return;}
  $("coach-status").textContent=purpose==="initial_plan"?"ChatGPT sta preparando una bozza…":"Il coach sta considerando il profilo e lo storico…";
  try{const answer=await api("/api/assistant/message",{method:"POST",body:JSON.stringify({model:$("model").value,question,expected_profile_version:state.intake.version,purpose})});
    $("conversation").append(el("div",question,"coach-message question"),el("div",answer.text,"coach-message"));$("question").value="";$("coach-status").textContent=`Risposta ChatGPT · ${answer.model}`;
    if(answer.draft){draft=answer.draft;$("draft-explanation").textContent=draft.explanation;const list=el("ol",null,"draft-list");for(const workout of draft.plan.workouts)list.append(el("li",`${workout.date} · ${workout.name} · ${workout.estimated_duration_min ?? "—"} min · ${workout.description}`));$("draft-workouts").replaceChildren(list);$("draft-error").textContent="";$("draft-dialog").showModal();}
  }catch(failure){$("coach-status").textContent="Risposta non completata. Nessun programma è stato cambiato.";throw failure;}
}
$("coach-form").addEventListener("submit",event=>{event.preventDefault();operation(()=>send("advice"));});
$("create-plan").addEventListener("click",()=>operation(()=>send("initial_plan")));
$("dismiss-draft").addEventListener("click",()=>{$("draft-dialog").close();draft=null;});
$("accept-draft").addEventListener("click",()=>operation(async()=>{if(!draft)return;$("accept-draft").disabled=true;try{await api("/api/assistant/plan/apply",{method:"POST",body:JSON.stringify({draft_id:draft.draft_id,confirmed:true})});$("draft-dialog").close();draft=null;await load();$("coach-status").textContent="Programma salvato. Puoi controllarlo in Piano e calendario.";}catch(failure){$("draft-error").textContent=failure.message;}finally{$("accept-draft").disabled=false;}}));
operation(load);
