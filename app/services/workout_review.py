"""Explainable coaching heuristics using normalized activities, without vendor API calls."""

import math
import re
from datetime import datetime, timedelta
from itertools import pairwise

from app.models import HRTarget, Plan, flatten
from app.services.planner import canonical_hash
from app.session_feedback import manual_findings


def positive(value):
    return isinstance(value, (int, float)) and math.isfinite(value) and value > 0


def completed_activities(activities, now):
    result = []
    seen = set()
    for activity in activities:
        try:
            stamp = datetime.fromisoformat(activity["start_time"])
            identity = (activity.get("source", "garmin"), activity["activity_id"])
            if stamp.tzinfo and stamp <= now and identity not in seen:
                result.append(activity)
                seen.add(identity)
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(result, key=lambda a: datetime.fromisoformat(a["start_time"]))


def easy_name(name):
    name = name.lower()
    if re.search(
        r"\b(race|gara|marathon|maratona|intervals?|ripetute|threshold|tempo|soglia|fartlek)\b",
        name,
    ):
        return False
    return bool(re.search(r"\b(easy|recovery|facile|lenta|lento|recupero)\b", name))


def easy_run(activity, matched_workouts):
    if activity.get("source") == "manual":
        return False
    workout = matched_workouts.get(activity["activity_id"])
    if workout:
        steps = list(flatten(workout.steps))
        return (
            not workout.quality
            and not any(s.type in {"interval", "repeat"} for s in workout.steps)
            and (
                easy_name(workout.name)
                or any(isinstance(s.target, HRTarget) and s.target.zone <= 2 for s in steps)
            )
            and all(
                not s.target or isinstance(s.target, HRTarget) and s.target.zone <= 2 for s in steps
            )
        )
    return easy_name(activity.get("name", ""))


def performance_trend(activities, now, matched_workouts, flags):
    result = {
        "decision": "keep",
        "eligible": False,
        "direction": None,
        "reason": "Mantieni il piano: servono almeno quattro corse facili comparabili, distribuite su almeno sette giorni.",
        "evidence": [],
        "change_percent": None,
        "policy": "Ultime 4 corse facili: ogni passaggio ≥1%, miglioramento complessivo ≥6% o rallentamento ≥8%; FC entro 6 bpm, durata entro 25%, terreno pianeggiante simile. Soglie euristiche.",
    }
    if activities and activities[-1].get("source") == "manual":
        result["reason"] = "Mantieni il piano: una seduta dichiarata e le sensazioni aiutano il coaching, ma non dimostrano un trend misurato di prestazione."
        return result
    if not activities or activities[-1]["sport"] != "running":
        result["reason"] = (
            "Mantieni il piano: l'ultima attività non offre un confronto di corsa affidabile. Bici e forza non vengono confrontate con il passo di corsa."
        )
        return result
    if not easy_run(activities[-1], matched_workouts):
        result["reason"] = (
            "Mantieni il piano: l'ultima corsa è di qualità, una gara o ha intensità non verificabile. Per un trend affidabile si confrontano le corse facili."
        )
        return result
    cutoff = now - timedelta(days=42)
    runs = [
        a
        for a in activities
        if a["sport"] == "running"
        and datetime.fromisoformat(a["start_time"]) >= cutoff
        and easy_run(a, matched_workouts)
    ][-4:]
    result["sample_count"] = len(runs)
    if len(runs) < 4:
        return result
    result["evidence"] = [
        {
            k: a.get(k)
            for k in (
                "activity_id",
                "name",
                "date",
                "avg_pace_s_km",
                "avg_hr",
                "duration_s",
                "elevation_gain_m",
            )
        }
        for a in runs
    ]
    stamps = [datetime.fromisoformat(a["start_time"]) for a in runs]
    if (
        now - stamps[-1] > timedelta(days=7)
        or stamps[-1] - stamps[0] < timedelta(days=7)
        or len({a["date"] for a in runs}) < 4
    ):
        result["reason"] = (
            "Mantieni il piano: le corse devono coprire almeno sette giorni, in quattro giornate distinte, con l'ultima entro sette giorni."
        )
        return result
    if len({(a.get("source", "garmin"), a.get("activity_type")) for a in runs}) != 1:
        result["reason"] = "Mantieni il piano: fonte o tipo di corsa differiscono tra le sessioni."
        return result
    if not all(
        positive(a.get("avg_pace_s_km"))
        and 150 <= a["avg_pace_s_km"] <= 600
        and positive(a.get("avg_hr"))
        and 90 <= a["avg_hr"] <= 200
        and positive(a.get("duration_s"))
        and 1200 <= a["duration_s"] <= 5400
        and positive(a.get("distance_m"))
        and a["distance_m"] >= 3000
        and isinstance(a.get("elevation_gain_m"), (int, float))
        and math.isfinite(a["elevation_gain_m"])
        and a["elevation_gain_m"] >= 0
        and positive(a.get("elapsed_duration_s"))
        and 1 <= a["elapsed_duration_s"] / a["duration_s"] <= 1.1
        for a in runs
    ):
        result["reason"] = (
            "Mantieni il piano: mancano FC, dislivello o tempi affidabili, oppure le corse hanno durata, passo o pause non comparabili."
        )
        return result
    paces = [a["avg_pace_s_km"] for a in runs]
    hearts = [a["avg_hr"] for a in runs]
    durations = [a["duration_s"] for a in runs]
    hills = [a["elevation_gain_m"] / (a["distance_m"] / 1000) for a in runs]
    if (
        max(hearts) - min(hearts) > 6
        or max(durations) / min(durations) > 1.25
        or max(hills) > 10
        or max(hills) - min(hills) > 3
    ):
        result["reason"] = (
            "Mantieni il piano: sforzo cardiaco, durata o dislivello cambiano troppo per attribuire il passo alla forma."
        )
        return result
    improvement = all(b <= a * 0.99 for a, b in pairwise(paces)) and paces[0] / paces[-1] >= 1.06
    deterioration = all(b >= a * 1.01 for a, b in pairwise(paces)) and paces[-1] / paces[0] >= 1.08
    if not improvement and not deterioration:
        result["reason"] = (
            "Mantieni il piano: nessun miglioramento o peggioramento abbastanza grande e continuo nelle ultime quattro corse comparabili."
        )
        return result
    if improvement and any(
        f["code"] in {"HIGH_FATIGUE", "HIGH_VOLUME", "LOW_RECOVERY"} for f in flags
    ):
        result["reason"] = (
            "Il passo migliora, ma i segnali di carico o recupero sconsigliano una progressione adesso. Mantieni il piano."
        )
        return result
    result.update(
        eligible=True,
        decision="consider_adjustment",
        direction="improving" if improvement else "declining",
        change_percent=round(
            (paces[0] / paces[-1] - 1 if improvement else paces[-1] / paces[0] - 1) * 100, 1
        ),
        reason="Quattro corse facili migliorano a FC simile: valuta una piccola progressione del volume facile."
        if improvement
        else "Quattro corse facili rallentano sensibilmente a FC simile: valuta una settimana con meno carico.",
    )
    return result


def adjusted_plan(plan, now, direction):
    """Small, local proposal; dates, identities and pace targets remain stable."""
    candidate = plan.model_copy(deep=True)
    changes = []
    for workout in candidate.workouts:
        if (
            not now.date() < workout.date <= now.date() + timedelta(days=7)
            or workout.sport != "running"
        ):
            continue
        if direction == "improving" and (
            workout.quality or any(s.type == "repeat" for s in workout.steps)
        ):
            continue
        before = workout.estimated_duration_min
        delta = 0
        step_changes = []
        for step in flatten(workout.steps):
            if step.type not in {"run", "interval"} or step.seconds is None:
                continue
            # Progress only explicitly easy timed running. Do not invent distance durations.
            if direction == "improving" and not (
                isinstance(step.target, HRTarget)
                and step.target.zone <= 2
                or step.target is None
                and easy_name(workout.name)
            ):
                continue
            multiplier = 1.05 if direction == "improving" else 0.85
            old = step.seconds
            new = round(old * multiplier)
            if new < 60:
                continue
            repeats = next(
                (s.iterations for s in workout.steps if any(child is step for child in s.steps)),
                1,
            )
            delta += (new - old) * repeats
            step_changes.append(
                {
                    "type": step.type,
                    "iterations": repeats,
                    "before_duration_s": old,
                    "after_duration_s": new,
                }
            )
            if step.duration_min is not None:
                step.duration_min = new / 60
            else:
                step.duration_s = new
        if delta:
            workout.estimated_duration_min = round(before + delta / 60, 2)
            changes.append(
                {
                    "workout_id": workout.key,
                    "date": workout.date.isoformat(),
                    "name": workout.name,
                    "before_duration_min": before,
                    "after_duration_min": workout.estimated_duration_min,
                    "step_changes": step_changes,
                    "description": "+5% sui soli tratti facili a tempo"
                    if direction == "improving"
                    else "−15% sui tratti di lavoro a tempo",
                }
            )
    return Plan.model_validate(candidate.model_dump(mode="json")), changes


def last_workout_review(plan, activities, now, snapshot, last_refresh=None, accepted=None):
    activities = completed_activities(activities, now)
    last = activities[-1] if activities else None
    workouts = {w.key: w for w in plan.workouts}
    matched = {
        m["activity_id"]: workouts[m["plan_workout_id"]]
        for m in snapshot["matches"]
        if m.get("activity_id")
    }
    match = next(
        (m for m in snapshot["matches"] if last and m.get("activity_id") == last["activity_id"]),
        None,
    )
    trend = performance_trend(activities, now, matched, snapshot["flags"])
    try:
        refreshed = datetime.fromisoformat(last_refresh) if last_refresh else None
        fresh = (
            refreshed and refreshed.tzinfo and timedelta(0) <= now - refreshed <= timedelta(days=3)
        )
    except (TypeError, ValueError):
        fresh = False
    evidence_ids = [e["activity_id"] for e in trend["evidence"]]
    if trend["eligible"] and not fresh:
        trend.update(
            eligible=False,
            decision="keep",
            reason="Aggiorna le attività prima di valutare un cambio: i dati sincronizzati risalgono a oltre tre giorni fa o non sono disponibili.",
        )
    if (
        trend["eligible"]
        and accepted
        and set(evidence_ids) & set(accepted.get("evidence_activity_ids", []))
    ):
        trend.update(
            eligible=False,
            decision="keep",
            reason="Piano già adattato su queste corse. Servono quattro nuove corse comparabili prima di proporre un altro cambio.",
        )
    if trend["eligible"]:
        _, changes = adjusted_plan(plan, now, trend["direction"])
        if not changes:
            trend.update(
                eligible=False,
                decision="keep",
                reason="Il trend merita attenzione, ma non ci sono sessioni future a tempo adattabili nei prossimi sette giorni. Mantieni il piano e rivaluta il prossimo blocco.",
            )
    advice = []
    if last:
        if match:
            if match["status"] == "completed_modified":
                advice.append(
                    "La durata differisce dal previsto: controlla il motivo. Non recuperare i minuti mancanti aggiungendoli alla prossima seduta."
                )
            elif match["status"] == "substituted":
                advice.append(
                    "Hai svolto l'alternativa prevista: conta come lavoro fatto. Evita di sommare anche la seduta originale."
                )
            else:
                advice.append(
                    "Sessione associata al piano. Prosegui con la prossima seduta se le sensazioni di recupero sono buone."
                )
            if match.get("quality"):
                advice.append(
                    "Per valutare i ritmi della qualità servono i singoli lap: il passo medio di tutta la seduta include riscaldamento e recuperi."
                )
        else:
            advice.append(
                "Attività registrata, senza associazione certa al piano. Verifica sport, data e durata prima di considerare una seduta saltata."
            )
        if last["duration_s"] >= 10800 or (last.get("training_load") or 0) >= 250:
            advice.append(
                "Uscita lunga o carico elevato: prima della qualità, controlla se le gambe sono recuperate. Se sono ancora pesanti, scegli una seduta facile."
            )
        elif last["sport"] == "cycling":
            advice.append(
                "La bici aggiunge carico aerobico: considera la sua durata nel recupero prima della prossima corsa impegnativa."
            )
        elif last["sport"] == "strength":
            advice.append(
                "Dopo la forza, considera l'affaticamento delle gambe prima della corsa di qualità; durata e FC non verificano gli esercizi svolti."
            )
        if any(f["code"] == "HIGH_VOLUME" for f in snapshot["flags"]):
            advice.append(
                "Il volume recente è già cresciuto: consolida questa settimana prima di aggiungere altro lavoro."
            )
        advice.append(
            "Annota quanto è stata impegnativa la seduta e come ti senti il giorno dopo: questi dati aiutano a distinguere progresso e stanchezza."
        )
    manual = manual_findings(last) if last and last.get("source") == "manual" else None
    if manual:
        advice = manual["actions"]
    return {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "activities_refreshed_at": last_refresh,
        "last_workout": last,
        "match": match,
        "verdict": manual["verdict"] if manual else "Nessuna attività disponibile"
        if not last
        else "Lavoro registrato, recupero da valutare"
        if not match
        else "Seduta associata al piano",
        "advice": advice,
        "feedback_findings": manual,
        "program": trend,
        "evidence_hash": canonical_hash(
            {
                "decision_date": now.date().isoformat(),
                "plan": plan.model_dump(mode="json"),
                "activities": activities,
                "last_refresh": last_refresh,
            }
        ),
        "limitations": [
            "Durata, eventuale distanza, sforzo e sensazioni sono dichiarati dall'atleta.",
            "Senza campioni misurati non si verificano FC, fasi delle ripetute, dinamiche o GPS.",
            "Il feedback aiuta il coaching, ma non dimostra da solo una variazione misurata di prestazione.",
        ] if manual else [
            "Le soglie sono euristiche, non una misura clinica di forma o fatica.",
            "FC e terreno simili riducono gli errori, ma caldo, vento, sonno e sensazioni non sono verificati. Conferma il contesto prima di accettare.",
            "Non vengono dedotte prestazioni degli intervalli dal passo medio, né confrontati corsa e ciclismo.",
        ],
    }
