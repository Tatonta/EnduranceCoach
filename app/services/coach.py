import secrets
import threading
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from filelock import FileLock, Timeout

from app.db import Database
from app.errors import CoachError
from app.garmin.client import GarminClient
from app.integrations.activities import GarminActivitySource, integration_catalog
from app.services.adjustment_context import contextualize_adjustment
from app.services.chatgpt import ChatGPTService
from app.services.cleanup import CleanupService
from app.services.climbs import ClimbService
from app.services.performances import PerformanceService
from app.services.planner import atomic_json, canonical_hash, load_plan, replace_plan
from app.services.reviewer import review_latest_workouts
from app.services.sync import SyncService
from app.services.workout_details import WorkoutDetailsService
from app.services.workout_review import adjusted_plan, last_workout_review


class OperationLock:
    """Serialize CLI, API and scheduled jobs, including across local processes."""

    def __init__(self, path):
        self.thread_lock = threading.RLock()
        self.file_lock = FileLock(path)

    def __enter__(self):
        self.thread_lock.acquire()
        try:
            self.file_lock.acquire(timeout=1)
        except Timeout:
            self.thread_lock.release()
            raise CoachError(
                "Un'altra operazione è in corso: attendi e riprova", "operation_busy"
            ) from None
        return self

    def __exit__(self, *args):
        self.file_lock.release()
        self.thread_lock.release()


class Coach:
    """API, CLI and future MCP share the same validated service operations."""

    def __init__(self, settings, client=None, activity_sources=None):
        self.settings = settings
        self.db = Database(settings.data_dir / "coach.sqlite3", settings.user_id)
        self.client = client or GarminClient(settings.token_dir)
        self.activity_sources = (
            activity_sources
            if activity_sources is not None
            else [GarminActivitySource(self.client)]
        )
        self.lock = OperationLock(str(settings.data_dir / ".operation.lock"))
        self.syncer = SyncService(settings, self.db, self.client)
        self.cleaner = CleanupService(settings, self.db, self.client)
        self.performances = PerformanceService(settings, self.db, self.client)
        self.climbs = ClimbService(settings, self.db, self.client)
        self.details = WorkoutDetailsService(settings, self.db, self.client)
        self.chatgpt = ChatGPTService(settings)
        self.scheduler = None

    def plan(self):
        return load_plan(self.settings.plan_path)

    def replace_plan(self, plan):
        with self.lock:
            replace_plan(self.settings.plan_path, plan)
            self.db.set("cleanup_preview", None)
            self.db.set("test_proof", None)
            self.db.set("adjustment_preview", None)
            return plan.model_dump(mode="json")

    def refresh(self):
        with self.lock:
            now = self.settings.now()
            plan = self.plan()
            earliest = min(plan.start, now.date() - timedelta(days=42))
            activities = []
            for source in self.activity_sources:
                records = source.fetch(now, earliest)
                if any(record.source != source.source for record in records):
                    raise CoachError(
                        "Fonte attività non coerente con l'adapter", "activities_source"
                    )
                activities.extend(
                    record.payload(self.settings.timezone)
                    for record in records
                    if earliest <= record.start_time.astimezone(now.tzinfo).date() <= now.date()
                )
            activities.sort(key=lambda a: a["start_time"], reverse=True)
            self.db.save_activities(activities)
            self.db.set("last_refresh", now.isoformat())
            garmin_active = any(source.source == "garmin" for source in self.activity_sources)
            self.db.set(
                "garmin_status",
                {
                    "connected": garmin_active,
                    "message": "Garmin connesso" if garmin_active else "Garmin non configurato",
                },
            )
            refresh_result = {
                "status": "refreshed",
                "count": len(activities),
                "last_refresh": now.isoformat(),
            }
            if not garmin_active:
                return refresh_result
            # VO2 is optional; failure does not discard successfully refreshed activities.
            try:
                metric_days = list(
                    dict.fromkeys(
                        [now.date().isoformat()]
                        + [a["date"] for a in activities if a["sport"] == "running"]
                    )
                )[:4]
                values = []

                def visit(obj):
                    if isinstance(obj, dict):
                        value = (
                            obj.get("vo2MaxValue")
                            or obj.get("vo2MaxPreciseValue")
                            or obj.get("vo2Max")
                        )
                        if isinstance(value, (int, float)) and value > 0:
                            values.append(value)
                        else:
                            for key, value in obj.items():
                                if key == "cycling":
                                    continue
                                visit(value)
                    elif isinstance(obj, list):
                        for value in obj:
                            visit(value)

                for metric_day in metric_days:
                    visit(self.client.get_max_metrics(metric_day))
                    if values:
                        self.db.set(
                            "vo2max",
                            {
                                "value": values[0],
                                "source": "Garmin",
                                "measured_date": metric_day,
                                "updated_at": now.isoformat(),
                            },
                        )
                        break
            except CoachError:
                pass
            return refresh_result

    def review(self, refresh=True):
        with self.lock:
            if refresh:
                self.refresh()
            if not self.db.get("last_refresh"):
                raise CoachError(
                    "Aggiorna Garmin prima della review: nessun dato disponibile",
                    "activities_required",
                )
            snapshot = review_latest_workouts(
                self.plan(), self.db.activities(), self.settings.now(), self.db.rows()
            )
            snapshot["activities_refreshed_at"] = self.db.get("last_refresh")
            snapshot["workout_review"] = self.workout_review(snapshot)
            self.db.set("latest_review", snapshot)
            self.db.set("last_review", snapshot["generated_at"])
            self.db.set("next_review", (self.settings.now() + timedelta(days=2)).isoformat())
            atomic_json(self.settings.data_dir / "review_snapshot.json", snapshot)
            if self.scheduler and self.scheduler.get_job("review"):
                self.scheduler.reschedule_job(
                    "review",
                    trigger="interval",
                    days=2,
                    start_date=datetime.fromisoformat(self.db.get("next_review")),
                )
            return snapshot

    def integrations(self):
        return integration_catalog(
            {source.source for source in self.activity_sources}, workout_export_sources={"garmin"}
        )

    def workout_review(self, snapshot=None):
        # Read cached data while a slow remote refresh holds the mutation lock.
        # Preview/application callers hold that lock and revalidate before writing.
        plan, activities, now = self.plan(), self.db.activities(), self.settings.now()
        snapshot = snapshot or review_latest_workouts(plan, activities, now, self.db.rows())
        result = last_workout_review(
            plan,
            activities,
            now,
            snapshot,
            self.db.get("last_refresh"),
            self.db.get("last_adjustment"),
        )
        context = {}
        if result["program"]["eligible"]:
            evidence_ids = {row["activity_id"] for row in result["program"]["evidence"]}
            context = {
                row["activity_id"]: self.details.comparison_evidence(row, plan)
                for row in activities
                if row["activity_id"] in evidence_ids
            }
        return contextualize_adjustment(result, context, activities, now)

    def preview_adjustment(self):
        with self.lock:
            review = self.workout_review()
            if not review["program"]["eligible"]:
                raise CoachError(review["program"]["reason"], "adjustment_not_recommended")
            plan = self.plan()
            proposed, changes = adjusted_plan(
                plan, self.settings.now(), review["program"]["direction"]
            )
            preview = {
                "preview_id": secrets.token_urlsafe(24),
                "plan_hash": canonical_hash(plan),
                "evidence_hash": review["evidence_hash"],
                "expires_at": (self.settings.now() + timedelta(minutes=10)).isoformat(),
                "direction": review["program"]["direction"],
                "reason": review["program"]["reason"],
                "evidence_activity_ids": [a["activity_id"] for a in review["program"]["evidence"]],
                "changes": changes,
                "proposed_plan": proposed.model_dump(mode="json"),
            }
            self.db.set("adjustment_preview", preview)
            return preview

    def apply_adjustment(self, preview_id, confirmed=False):
        with self.lock:
            preview = self.db.get("adjustment_preview")
            if not confirmed:
                raise CoachError("Conferma la preview prima di applicarla", "confirmation_required")
            review = self.workout_review()
            if (
                not preview
                or preview["preview_id"] != preview_id
                or datetime.fromisoformat(preview["expires_at"]) <= self.settings.now()
                or preview["plan_hash"] != canonical_hash(self.plan())
                or preview["evidence_hash"] != review["evidence_hash"]
                or not review["program"]["eligible"]
            ):
                raise CoachError(
                    "Preview scaduta o dati cambiati: rivaluta la proposta", "adjustment_stale"
                )
            from app.models import Plan

            plan = Plan.model_validate(preview["proposed_plan"])
            self.replace_plan(plan)
            self.db.set(
                "last_adjustment",
                {
                    "applied_at": self.settings.now().isoformat(),
                    "direction": preview["direction"],
                    "evidence_activity_ids": preview["evidence_activity_ids"],
                    "changes": preview["changes"],
                },
            )
            self.review(refresh=False)
            return {"status": "applied", "changes": preview["changes"], "requires_sync": True}

    def test_workout(self, workout_id=None):
        with self.lock:
            return self.syncer.test_workout(self.plan(), workout_id)

    def sync_plan(self, confirmed=False):
        with self.lock:
            return self.syncer.sync_plan(self.plan(), confirmed)

    def preview_calendar_cleanup(self):
        with self.lock:
            return self.cleaner.preview_calendar_cleanup(self.plan())

    def refresh_performances(self):
        with self.lock:
            try:
                result = self.performances.refresh(deep=True)
                self.db.set("performance_error", None)
                return result
            except CoachError as exc:
                self.db.set("performance_error", str(exc))
                self.db.set("performance_progress", None)
                raise

    def apply_calendar_cleanup(self, preview_id, confirmed=False):
        with self.lock:
            return self.cleaner.apply_calendar_cleanup(self.plan(), preview_id, confirmed)

    def refresh_climbs(self):
        with self.lock:
            try:
                result = self.climbs.refresh()
                self.db.set("climb_error", None)
                return result
            except CoachError as exc:
                self.db.set("climb_error", str(exc))
                self.db.set("climb_progress", None)
                raise

    def summary(self):
        plan, now = self.plan(), self.settings.now()
        snapshot = review_latest_workouts(plan, self.db.activities(), now, self.db.rows())
        vo2 = self.db.get("vo2max") or {
            "value": plan.athlete.get("vo2max"),
            "source": "Dato iniziale fornito",
            "updated_at": None,
        }
        activities = self.db.activities()
        proof = self.db.get("test_proof")
        if proof and proof["plan_hash"] != canonical_hash(plan):
            proof = None
        future = sorted((w for w in plan.workouts if w.date >= now.date()), key=lambda w: w.date)
        return {
            "plan_name": plan.plan_name,
            "today": now.date().isoformat(),
            "vo2max": vo2,
            "garmin": self.db.get(
                "garmin_status", {"connected": False, "message": "Garmin da aggiornare"}
            ),
            "last_refresh": self.db.get("last_refresh"),
            "last_review": self.db.get("last_review"),
            "next_review": self.db.get("next_review"),
            "scheduler_enabled": self.settings.scheduler_enabled,
            "activities": activities[:12],
            "last_workout": activities[0] if activities else None,
            "today_workouts": [
                w.model_dump(mode="json") for w in plan.workouts if w.date == now.date()
            ],
            "next_workout": future[0].model_dump(mode="json") if future else None,
            "next_quality": next((w.model_dump(mode="json") for w in future if w.quality), None),
            "training_summary": snapshot["training_summary"],
            "flags": snapshot["flags"],
            "notes": plan.notes,
            "test_proof": proof,
            "sync_state": self.db.rows(),
        }

    def background_refresh(self):
        if not self.settings.plan_path.exists():
            return
        try:
            self.review(refresh=True)
            self.refresh_performances()
            self.refresh_climbs()
            self.db.set("scheduler_error", None)
        except CoachError as exc:
            self.db.set(
                "garmin_status", {"connected": False, "message": str(exc), "code": exc.code}
            )
            self.db.set(
                "scheduler_error", {"message": str(exc), "at": self.settings.now().isoformat()}
            )
        except Exception:
            self.db.set(
                "scheduler_error",
                {
                    "message": "Errore locale nella review: controllare piano e configurazione",
                    "at": self.settings.now().isoformat(),
                },
            )

    def start(self):
        if self.settings.scheduler_enabled:
            self.scheduler = BackgroundScheduler(timezone=self.settings.timezone)
            next_review = self.db.get("next_review")
            start = (
                datetime.fromisoformat(next_review)
                if next_review
                else self.settings.now() + timedelta(days=2)
            )
            if start < self.settings.now():
                start = self.settings.now() + timedelta(seconds=5)
            self.db.set("next_review", start.isoformat())
            self.scheduler.add_job(
                self.background_refresh,
                "interval",
                days=2,
                start_date=start,
                id="review",
                max_instances=1,
                coalesce=True,
                misfire_grace_time=3600,
            )
            self.scheduler.start()
        if self.settings.startup_refresh:
            threading.Thread(
                target=self.background_refresh, daemon=True, name="garmin-startup"
            ).start()

    def stop(self):
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
