import re
from datetime import date, timedelta
from itertools import pairwise

from app.models import flatten


def tokens(name):
    return set(re.findall(r"[a-z0-9]+", name.lower())) - {
        "run",
        "running",
        "corsa",
        "min",
        "easy",
        "workout",
    }


def planned_targets(workout):
    return [s.target.model_dump() for s in flatten(workout.steps) if s.target]


def match_score(workout, activity, template_id=None):
    if activity["date"] != workout.date.isoformat():
        return None
    compatible = activity["sport"] == workout.sport
    alternative = (
        workout.sport == "cycling"
        and activity["sport"] == "running"
        and "oppure" in workout.description.lower()
    )
    if not compatible and not alternative:
        return None
    planned_seconds = (workout.estimated_duration_min or 0) * 60
    if planned_seconds <= 0:
        return None
    ratio = activity["duration_s"] / planned_seconds
    if not 0.55 <= ratio <= 1.65:
        return None
    overlap = len(tokens(workout.name) & tokens(activity["name"]))
    linked = bool(
        activity.get("source", "garmin") == "garmin"
        and template_id and activity.get("workout_id") == template_id
    )
    # Aggregate pace does not prove completion of prescribed intervals.
    if workout.quality and not overlap and not linked:
        return None
    if any(t in activity["name"].lower() for t in ("race", "gara", "marathon")) and not linked:
        return None
    return 10 * linked + 2 * overlap + (2 if compatible else 0) + (1 - abs(1 - ratio))


def review_latest_workouts(plan, activities, now, state=None):
    state = state or []
    rows = {r["plan_workout_id"]: r for r in state}
    used, matches, flags = set(), [], []
    today = now.date()
    for workout in sorted(plan.workouts, key=lambda w: w.date):
        match = {
            "plan_workout_id": workout.key,
            "planned_date": workout.date.isoformat(),
            "planned_name": workout.name,
            "planned_type": workout.sport,
            "quality": workout.quality,
            "planned_duration_s": (workout.estimated_duration_min or 0) * 60,
            "planned_target": planned_targets(workout),
            "activity_id": None,
            "actual_date": None,
            "actual_distance_m": None,
            "actual_duration_s": None,
            "actual_avg_pace_s_km": None,
            "actual_avg_hr": None,
            "actual_max_hr": None,
            "status": "pending",
        }
        if workout.date > today:
            matches.append(match)
            continue
        if workout.sport in {"rest", "manual"}:
            strength = [
                a
                for a in activities
                if a["date"] == workout.date.isoformat()
                and a["sport"] == "strength"
                and a["activity_id"] not in used
            ]
            if workout.sport == "manual" and len(strength) == 1:
                a = strength[0]
                used.add(a["activity_id"])
                match.update(
                    status="completed",
                    activity_id=a["activity_id"],
                    actual_date=a["date"],
                    actual_duration_s=a["duration_s"],
                    actual_avg_hr=a["avg_hr"],
                    actual_max_hr=a["max_hr"],
                    note="Attività di forza associata; esercizi e intensità non verificati",
                )
                matches.append(match)
                continue
            if workout.date < today:
                match["status"] = "completed" if workout.sport == "rest" else "missed"
                match["note"] = (
                    "Riposo previsto, non misurabile tramite attività"
                    if workout.sport == "rest"
                    else "Sessione manuale non verificata"
                )
            matches.append(match)
            continue
        ranked = []
        for activity in activities:
            if activity["activity_id"] in used:
                continue
            score = match_score(
                workout, activity, rows.get(workout.key, {}).get("garmin_workout_id")
            )
            if score is not None:
                ranked.append((score, activity))
        ranked.sort(key=lambda x: x[0], reverse=True)
        if ranked and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] > 0.5):
            activity = ranked[0][1]
            used.add(activity["activity_id"])
            ratio = activity["duration_s"] / match["planned_duration_s"]
            match.update(
                activity_id=activity["activity_id"],
                actual_date=activity["date"],
                actual_distance_m=activity["distance_m"],
                actual_duration_s=activity["duration_s"],
                actual_avg_pace_s_km=activity["avg_pace_s_km"],
                actual_avg_hr=activity["avg_hr"],
                actual_max_hr=activity["max_hr"],
                status="substituted"
                if activity["sport"] != workout.sport
                else "completed"
                if 0.85 <= ratio <= 1.15
                else "completed_modified",
                match_confidence="workout_link"
                if activity.get("source", "garmin") == "garmin"
                and activity.get("workout_id")
                and activity["workout_id"] == rows.get(workout.key, {}).get("garmin_workout_id")
                else "sport_duration_name",
                interval_compliance="unverified" if workout.quality else "not_applicable",
            )
            if workout.quality:
                match["note"] = (
                    "Sessione associata; fasi/ritmi degli intervalli non verificati con i dati aggregati"
                )
            if match["status"] == "substituted":
                flags.append(
                    {
                        "code": "SUBSTITUTED_SESSION",
                        "workout": workout.key,
                        "message": "Eseguita alternativa prevista",
                    }
                )
        elif workout.date < today:
            match["status"] = "missed"
            if ranked:
                match["note"] = "Più attività plausibili: nessuna associazione automatica"
            if workout.quality:
                flags.append(
                    {
                        "code": "MISSED_QUALITY",
                        "workout": workout.key,
                        "message": "Qualità senza esecuzione associabile; verificare manualmente",
                    }
                )
        matches.append(match)
    week_start = today - timedelta(days=6)
    recent = [a for a in activities if week_start.isoformat() <= a["date"] <= today.isoformat()]
    previous = [
        a
        for a in activities
        if (week_start - timedelta(days=7)).isoformat() <= a["date"] < week_start.isoformat()
    ]
    run_m = sum(a["distance_m"] for a in recent if a["sport"] == "running")
    previous_m = sum(a["distance_m"] for a in previous if a["sport"] == "running")
    if previous_m > 15000 and run_m > previous_m * 1.15:
        flags.append(
            {
                "code": "HIGH_VOLUME",
                "message": "Distanza corsa 7 giorni oltre +15% rispetto ai 7 precedenti (soglia euristica)",
            }
        )
    demanding = [
        a
        for a in recent
        if a["date"] >= (today - timedelta(days=1)).isoformat()
        and (a["duration_s"] >= 10800 or (a.get("training_load") or 0) >= 250)
    ]
    if demanding:
        flags.append(
            {
                "code": "HIGH_FATIGUE",
                "message": "Attività recente impegnativa: carico/durata suggeriscono di controllare recupero e sensazioni",
                "evidence_activity_ids": [a["activity_id"] for a in demanding],
                "basis": "proxy, non misura clinica",
            }
        )
    quality_days = sorted(
        date.fromisoformat(m["planned_date"]) for m in matches if m["quality"] and m["activity_id"]
    )
    if any((b - a).days < 2 for a, b in pairwise(quality_days)):
        flags.append(
            {
                "code": "LOW_RECOVERY",
                "message": "Meno di 48 ore tra due giornate di qualità associate",
            }
        )
    return {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "timezone": str(now.tzinfo),
        "units": {"distance": "m", "duration": "s", "pace": "s/km", "heart_rate": "bpm"},
        "recent_activities": activities[:100],
        "planned_workouts": plan.model_dump(mode="json")["workouts"],
        "matches": matches,
        "unmatched_activity_ids": [
            a["activity_id"] for a in activities if a["activity_id"] not in used
        ],
        "training_summary": {
            "running_distance_7d": run_m,
            "cycling_duration_7d": sum(a["duration_s"] for a in recent if a["sport"] == "cycling"),
            "quality_sessions_completed": sum(
                m["quality"] and m["status"] in {"completed", "completed_modified"} for m in matches
            ),
            "quality_sessions_missed": sum(
                m["quality"] and m["status"] == "missed" for m in matches
            ),
        },
        "flags": flags,
        "recommendations": [
            "Controllare gambe e recupero prima della prossima qualità; ridurre il carico se non recuperato."
        ]
        if demanding
        else [],
        "limitations": [
            "Associazioni conservative basate su sport, durata, nome/ID. I dati aggregati non verificano i singoli intervalli.",
            "OVERPERFORMED_INTERVALS/UNDERPERFORMED_INTERVALS richiedono analisi lap, non vengono dedotti dal passo medio.",
        ],
    }
