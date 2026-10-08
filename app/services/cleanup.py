import uuid
from datetime import datetime, timedelta

from app.garmin.calendar import calendar_workouts
from app.garmin.client import CoachError
from app.garmin.workouts import validate_remote
from app.services.planner import atomic_json, canonical_hash


def compare_calendar(plan, items, resolve):
    """Keep one structurally verified schedule per current plan entry."""
    kept, rows = set(), []
    cache = {}
    for item in sorted(items, key=lambda r: (r["date"], r["scheduled_id"])):
        candidates = [
            w
            for w in plan.workouts
            if w.sport in {"running", "cycling"}
            and w.date.isoformat() == item["date"]
            and w.name == item["name"]
        ]
        match = None
        if candidates and item["workout_id"]:
            wid = item["workout_id"]
            if wid not in cache:
                cache[wid] = resolve(wid)
            match = next((w for w in candidates if validate_remote(w, cache[wid])["valid"]), None)
        if match and match.key not in kept:
            action, reason = "keep", "Piano corrente: struttura verificata"
            kept.add(match.key)
        elif match:
            action, reason = "unschedule", "Duplicato del piano corrente"
        else:
            action = "unschedule"
            reason = (
                "Garmin Coach / piano precedente"
                if item.get("source") == "Garmin Coach"
                else "Fuori dal piano corrente o struttura diversa"
            )
        rows.append({**item, "action": action, "reason": reason})
    return rows


class CleanupService:
    def __init__(self, settings, db, client):
        self.settings, self.db, self.client = settings, db, client

    def selection(self, plan):
        items = calendar_workouts(self.client, plan.start, plan.end)
        return compare_calendar(plan, items, self.client.get_workout_by_id)

    def preview_calendar_cleanup(self, plan):
        rows = self.selection(plan)
        now = self.settings.now()
        preview = {
            "preview_id": uuid.uuid4().hex,
            "generated_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=15)).isoformat(),
            "plan_hash": canonical_hash(plan),
            "start": plan.start.isoformat(),
            "end": plan.end.isoformat(),
            "rows": rows,
            "remove_count": sum(r["action"] == "unschedule" for r in rows),
        }
        preview["digest"] = canonical_hash(rows)
        self.db.set("cleanup_preview", preview)
        atomic_json(self.settings.data_dir / "cleanup_preview.json", preview)
        return preview

    def apply_calendar_cleanup(self, plan, preview_id, confirmed=False):
        if not confirmed:
            raise CoachError("Conferma esplicita necessaria", "confirmation_required")
        preview = self.db.get("cleanup_preview")
        if not preview or preview_id != preview["preview_id"]:
            raise CoachError("Prima genera e controlla una preview", "preview_required")
        if self.settings.now() > datetime.fromisoformat(preview["expires_at"]):
            raise CoachError("Preview scaduta: genera una nuova preview", "preview_expired")
        if (
            canonical_hash(plan) != preview["plan_hash"]
            or canonical_hash(self.selection(plan)) != preview["digest"]
        ):
            raise CoachError(
                "Piano o calendario cambiato: serve una nuova preview", "preview_changed"
            )
        # Consume once, even after a partial network failure; retry requires fresh preview.
        self.db.set("cleanup_preview", None)
        removed = []
        for row in preview["rows"]:
            if row["action"] != "unschedule":
                continue
            try:
                detail = self.client.get_scheduled_workout_by_id(row["scheduled_id"])
                if (
                    not isinstance(detail, dict)
                    or str(detail.get("workoutScheduleId") or detail.get("id"))
                    != row["scheduled_id"]
                ):
                    raise CoachError(
                        "Scheduled ID non verificabile: rimozione bloccata", "schedule_identity"
                    )
                if str(detail.get("calendarDate") or detail.get("date") or "")[:10] != row["date"]:
                    raise CoachError(
                        "Data scheduled workout cambiata: rimozione bloccata", "schedule_identity"
                    )
                detail_wid = str(
                    (detail.get("workout") or {}).get("workoutId") or detail.get("workoutId") or ""
                )
                if row["workout_id"] and detail_wid != row["workout_id"]:
                    raise CoachError(
                        "Template scheduled workout cambiato: rimozione bloccata",
                        "schedule_identity",
                    )
                self.client.unschedule_workout(row["scheduled_id"])
                removed.append(row["scheduled_id"])
                for state in self.db.rows():
                    if state["scheduled_workout_id"] == row["scheduled_id"]:
                        state.update(
                            scheduled_workout_id=None,
                            status="unscheduled",
                            last_sync=self.settings.now().isoformat(),
                        )
                        self.db.save_workout(**state)
                atomic_json(
                    self.settings.data_dir / "state.json",
                    {"user_id": self.settings.user_id, "workouts": self.db.rows()},
                )
            except CoachError as exc:
                return {
                    "status": "partial",
                    "removed": removed,
                    "error": str(exc),
                    "code": exc.code,
                    "message": "Operazione interrotta: genera una nuova preview prima di riprovare",
                }
        return {"status": "applied", "removed": removed}
