"""Fetch real Garmin detail explicitly, cache privately, and prepare the coach's evidence."""

from datetime import timedelta

from app.errors import CoachError
from app.services.planner import canonical_hash
from app.services.session_analysis import analyze_session


class WorkoutDetailsService:
    def __init__(self, settings, db, client):
        self.settings, self.db, self.client = settings, db, client

    def activity(self, activity_id=None):
        from app.services.workout_review import completed_activities

        completed = list(reversed(completed_activities(self.db.activities(), self.settings.now())))
        result = next((a for a in completed if a["activity_id"] == activity_id), None) if activity_id else next(iter(completed), None)
        if not result:
            raise CoachError("Attività non trovata nello storico sincronizzato.", "activity_not_found", 404)
        return result

    def refresh(self, activity_id=None):
        activity = self.activity(activity_id)
        if activity.get("source", "garmin") != "garmin":
            raise CoachError("Dettagli Garmin disponibili solo per attività Garmin.", "details_source", 409)
        raw, errors = {}, []
        for name, method, parameters in (
            ("summary", "get_activity", {}), ("details", "get_activity_details", {"maxchart": 100000, "maxpoly": 4000}),
            ("splits", "get_activity_splits", {}), ("typed_splits", "get_activity_typed_splits", {}),
            ("hr_zones", "get_activity_hr_in_timezones", {}),
        ):
            try:
                raw[name] = getattr(self.client, method)(activity["activity_id"], **parameters)
            except (CoachError, AttributeError):
                errors.append(name)
        if not raw.get("splits") and not raw.get("details"):
            raise CoachError("Garmin non ha restituito lap o campioni. Riprova la lettura dettagliata.", "details_unavailable", 502)
        self.db.set("workout_detail:" + activity["activity_id"], {"raw": raw, "fetched_at": self.settings.now().isoformat(), "errors": errors})
        return activity["activity_id"]

    def view(self, base, plan, activity_id=None):
        activity = self.activity(activity_id)
        stored = self.db.get("workout_detail:" + activity["activity_id"])
        if not stored:
            return {"status": "not_loaded", "activity": activity, "message": "Leggi i lap e i campioni Garmin per questa seduta."}
        # The reviewed activity may be an older session selected in the UI.
        from app.services.reviewer import review_latest_workouts

        snapshot = review_latest_workouts(plan, [activity], self.settings.now(), self.db.rows())
        match = next((m for m in snapshot["matches"] if m.get("activity_id") == activity["activity_id"]), None)
        workout = next((w for w in plan.workouts if match and w.key == match["plan_workout_id"]), None)
        analysis = analyze_session(activity, stored["raw"], workout)
        since = (self.settings.now() - timedelta(days=42)).date().isoformat()
        from app.services.session_analysis import timestamp

        history = sorted([a for a in self.db.activities() if since <= a["date"] and timestamp(a["start_time"]) < timestamp(activity["start_time"])], key=lambda a: timestamp(a["start_time"]), reverse=True)[:30]
        historical_matches = review_latest_workouts(plan, history, self.settings.now())["matches"]
        kinds = {m["activity_id"]: "quality" if m.get("quality") else "planned_non_quality" for m in historical_matches if m.get("activity_id")}
        history_context = []
        for previous in history:
            row = {k: previous.get(k) for k in ("date", "sport", "activity_type", "duration_s", "distance_m", "avg_pace_s_km", "avg_hr", "elevation_gain_m", "training_load")}
            name = previous.get("name", "").lower()
            row["session_kind"] = kinds.get(previous["activity_id"], "quality_named" if any(t in name for t in ("threshold", "tempo", "interval", "ripetut", "vo2")) else "easy_named" if any(t in name for t in ("easy", "facile", "recovery", "recupero")) else "unspecified")
            history_context.append(row)
        evidence = {"activity": {k: activity.get(k) for k in ("date", "sport", "duration_s", "distance_m", "avg_pace_s_km", "avg_hr", "max_hr", "elevation_gain_m", "training_load")},
                    "planned_workout": workout.model_dump(mode="json") if workout else None,
                    "analysis": {k: v for k, v in analysis.items() if k not in {"route", "series", "activity_id"}},
                    "history": history_context,
                    "athlete_context": {k: plan.athlete[k] for k in ("vo2max", "running_days_per_week", "strength_days_per_week", "stress_fracture_history") if k in plan.athlete},
                    "training_profile": (self.db.get("training_profile") or {}).get("profile"),
                    "program_decision": base["program"],
                    "limitations": ["Contesto del piano corrente; versione originale del workout non verificata.", "Il riferimento Z2 per easy senza target HR esplicito è indicativo; confermare zone individuali.", "Meteo, sensazioni, RPE, sonno e dolore non sono misurati da questi dati."]}
        # Strip names/IDs from program evidence; neither GPS nor account identity goes to ChatGPT.
        evidence["program_decision"] = {k: v for k, v in base["program"].items() if k != "evidence"}
        return {"status": "ready", "activity": activity, "analysis": analysis, "match": match,
                "fetched_at": stored["fetched_at"], "fetch_errors": stored["errors"],
                "history": history, "context": evidence, "context_hash": canonical_hash(evidence)}
