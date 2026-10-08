from app.garmin.calendar import calendar_workouts
from app.garmin.client import CoachError
from app.garmin.workouts import marker, upload_workout, validate_remote
from app.services.planner import atomic_json, canonical_hash, workout_hash


class SyncService:
    def __init__(self, settings, db, client):
        self.settings, self.db, self.client = settings, db, client

    def save(self, workout, wid, sid, status):
        self.db.save_workout(
            plan_workout_id=workout.key,
            garmin_workout_id=wid,
            scheduled_workout_id=sid,
            date=workout.date.isoformat(),
            status=status,
            json_hash=workout_hash(workout),
            last_sync=self.settings.now().isoformat(),
        )
        atomic_json(
            self.settings.data_dir / "state.json",
            {"user_id": self.settings.user_id, "workouts": self.db.rows()},
        )

    def library(self):
        result = []
        for page in range(100):
            batch = self.client.get_workouts(page * 100, 100)
            if not isinstance(batch, list):
                raise CoachError("Formato libreria Garmin sconosciuto", "workout_schema")
            result.extend(batch)
            if len(batch) < 100:
                return result
        raise CoachError("Libreria incompleta: sincronizzazione bloccata", "workouts_incomplete")

    def ensure_template(self, workout, library, calendar):
        row = self.db.row(workout.key)
        if (
            row
            and row["scheduled_workout_id"]
            and (
                row["json_hash"] != workout_hash(workout) or row["date"] != workout.date.isoformat()
            )
        ):
            journal_key = f"replacement:{workout.key}"
            if not self.db.get(journal_key):
                self.db.set(journal_key, row)
        candidate_ids = []
        if row and row["json_hash"] == workout_hash(workout) and row["garmin_workout_id"]:
            candidate_ids.append(row["garmin_workout_id"])
        # Recover uploads after a crash or missing SQLite state via full content hash.
        hashed_ids = [
            str(w["workoutId"])
            for w in library
            if marker(workout, self.settings.user_id) in (w.get("description") or "")
        ]
        candidate_ids.extend(hashed_ids)
        # Adopt existing legacy workouts only after reading their true structured steps.
        candidate_ids.extend(
            item["workout_id"]
            for item in calendar
            if item["date"] == workout.date.isoformat()
            and item["name"] == workout.name
            and item["workout_id"]
        )
        for wid in dict.fromkeys(candidate_ids):
            remote = self.client.get_workout_by_id(wid)
            check = validate_remote(workout, remote, self.settings.user_id)
            if check["valid"]:
                return wid, check
            if wid in hashed_ids or (
                row
                and wid == row["garmin_workout_id"]
                and row["json_hash"] == workout_hash(workout)
            ):
                raise CoachError(
                    "Template già caricato ma struttura non valida: correggi il piano o verifica Garmin prima di riprovare",
                    "validation_failed",
                )
        if (
            row
            and row["json_hash"] == workout_hash(workout)
            and row["status"] == "upload_uncertain"
        ):
            raise CoachError(
                "Upload precedente incerto e non visibile nella libreria: verifica Garmin prima di un nuovo invio",
                "upload_uncertain",
            )
        self.save(workout, None, None, "upload_uncertain")
        wid = upload_workout(self.client, workout, self.settings.user_id)
        # Persist immediately: failed validation/restart must not duplicate the upload.
        self.save(workout, wid, None, "uploaded")
        remote = self.client.get_workout_by_id(wid)
        check = validate_remote(workout, remote, self.settings.user_id)
        if not check["valid"]:
            self.save(workout, wid, None, "validation_failed")
            raise CoachError(check["message"], "validation_failed")
        library.append({"workoutId": wid, "description": marker(workout, self.settings.user_id)})
        return wid, check

    def test_workout(self, plan, workout_id=None):
        workout = next(
            (
                w
                for w in plan.workouts
                if w.sport in {"running", "cycling"}
                and w.date >= self.settings.now().date()
                and (not workout_id or w.key == workout_id)
            ),
            None,
        )
        if workout is None:
            raise CoachError("Nessun workout futuro disponibile per il test")
        calendar = calendar_workouts(self.client, plan.start, plan.end)
        wid, check = self.ensure_template(workout, self.library(), calendar)
        existing = next(
            (
                r
                for r in calendar
                if r["workout_id"] == wid and r["date"] == workout.date.isoformat()
            ),
            None,
        )
        current = self.db.row(workout.key)
        status = (
            "scheduled"
            if existing
            else "schedule_uncertain"
            if current and current["status"] == "schedule_uncertain"
            else "validated"
        )
        self.save(
            workout,
            wid,
            existing["scheduled_id"] if existing else None,
            status,
        )
        proof = {
            "plan_hash": canonical_hash(plan),
            "plan_workout_id": workout.key,
            "workout_id": wid,
            "workout_hash": workout_hash(workout),
            "verified_at": self.settings.now().isoformat(),
            **check,
        }
        self.db.set("test_proof", proof)
        atomic_json(self.settings.data_dir / "test_workout.json", proof)
        return proof

    def sync_plan(self, plan, confirmed=False):
        proof = self.db.get("test_proof")
        if not proof or not proof.get("valid") or proof["plan_hash"] != canonical_hash(plan):
            raise CoachError(
                "Esegui prima il test di un workout del piano corrente", "test_required"
            )
        if not confirmed:
            raise CoachError(
                "Conferma il test riuscito prima della sincronizzazione completa",
                "confirmation_required",
            )
        calendar = calendar_workouts(self.client, plan.start, plan.end)
        library = self.library()
        results = []
        for workout in sorted(plan.workouts, key=lambda w: w.date):
            if (
                workout.sport not in {"running", "cycling"}
                or workout.date < self.settings.now().date()
            ):
                results.append({"id": workout.key, "status": "skipped"})
                continue
            journal_key = f"replacement:{workout.key}"
            old = self.db.get(journal_key) or self.db.row(workout.key)
            if (
                old
                and old["scheduled_workout_id"]
                and (
                    old["json_hash"] != workout_hash(workout)
                    or old["date"] != workout.date.isoformat()
                )
            ):
                self.db.set(journal_key, old)
            try:
                # Validate replacement before removing the old schedule.
                wid, check = self.ensure_template(workout, library, calendar)
                if (
                    old
                    and old["scheduled_workout_id"]
                    and (
                        old["json_hash"] != workout_hash(workout)
                        or old["date"] != workout.date.isoformat()
                    )
                ):
                    stale = next(
                        (r for r in calendar if r["scheduled_id"] == old["scheduled_workout_id"]),
                        None,
                    )
                    if (
                        not stale
                        and old["date"] != workout.date.isoformat()
                        and old["date"] >= self.settings.now().date().isoformat()
                    ):
                        from datetime import date

                        prior_date = date.fromisoformat(old["date"])
                        stale = next(
                            (
                                r
                                for r in calendar_workouts(self.client, prior_date, prior_date)
                                if r["scheduled_id"] == old["scheduled_workout_id"]
                            ),
                            None,
                        )
                    if stale and stale["date"] >= self.settings.now().date().isoformat():
                        if stale["workout_id"] != old["garmin_workout_id"]:
                            raise CoachError(
                                "Identità vecchia schedulazione cambiata", "schedule_identity"
                            )
                        detail = self.client.get_scheduled_workout_by_id(stale["scheduled_id"])
                        if (
                            str(detail.get("workoutScheduleId")) != stale["scheduled_id"]
                            or str(detail.get("calendarDate") or detail.get("date") or "")[:10]
                            != stale["date"]
                        ):
                            raise CoachError(
                                "Vecchia schedulazione non verificabile", "schedule_identity"
                            )
                        self.client.unschedule_workout(stale["scheduled_id"])
                        if stale in calendar:
                            calendar.remove(stale)
                matches = [
                    r
                    for r in calendar
                    if r["workout_id"] == wid and r["date"] == workout.date.isoformat()
                ]
                if matches:
                    sid = matches[0]["scheduled_id"]
                    self.save(workout, wid, sid, "scheduled")
                    self.db.set(journal_key, None)
                    results.append(
                        {
                            "id": workout.key,
                            "status": "already_scheduled",
                            "workout_id": wid,
                            "duplicates": len(matches) - 1,
                        }
                    )
                    continue
                if old and old["status"] == "schedule_uncertain":
                    raise CoachError(
                        "Schedulazione precedente incerta e non visibile: verifica Garmin prima di un nuovo invio",
                        "schedule_uncertain",
                    )
                # Mark intent before the network request: a timeout may still mean success.
                self.save(workout, wid, None, "schedule_uncertain")
                self.client.schedule_workout(wid, workout.date.isoformat())
                # Calendar is the source of scheduled IDs, not the template ID.
                calendar = calendar_workouts(self.client, plan.start, plan.end)
                matches = [
                    r
                    for r in calendar
                    if r["workout_id"] == wid and r["date"] == workout.date.isoformat()
                ]
                if not matches:
                    self.save(workout, wid, None, "schedule_uncertain")
                    raise CoachError(
                        "Schedulazione inviata ma non ancora visibile: controlla il calendario prima di riprovare",
                        "schedule_uncertain",
                    )
                sid = matches[0]["scheduled_id"]
                self.save(workout, wid, sid, "scheduled")
                self.db.set(journal_key, None)
                results.append(
                    {
                        "id": workout.key,
                        "status": "scheduled",
                        "workout_id": wid,
                        "scheduled_id": sid,
                    }
                )
            except CoachError as exc:
                results.append(
                    {"id": workout.key, "status": "error", "code": exc.code, "message": str(exc)}
                )
                # Stop on uncertainty rather than risk more writes or duplicate schedules.
                return {"status": "partial", "results": results}
        return {
            "status": "complete",
            "results": results,
            "note": "Eventuali workout estranei/duplicati si rimuovono con preview e conferma cleanup",
        }
