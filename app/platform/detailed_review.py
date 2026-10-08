"""Owner-scoped detailed evidence, separate from lightweight activity summaries."""

from datetime import datetime, timedelta

from sqlalchemy import select

from app.errors import CoachError
from app.integrations.session_details import SessionDetails, analyze_canonical
from app.models import Plan
from app.platform.tables import Activity, ActivityDetails, PlanVersion
from app.services.planner import canonical_hash
from app.services.session_analysis import step_structure


class ActivityDetailService:
    def __init__(self, store):
        self.store = store

    def source(self, session, athlete_id, provider, provider_id):
        source = session.get(Activity, (athlete_id, provider, provider_id))
        if not source:
            raise CoachError("Activity not found", "not_found", 404)
        return source

    def linked_workout(self, session, source, details):
        if details.plan_version is None:
            return None
        version = session.get(PlanVersion, (source.athlete_id, details.plan_version))
        if not version:
            raise CoachError("Referenced plan unavailable", "detail_plan_reference", 422)
        plan = Plan.model_validate(version.payload)
        workout = next((row for row in plan.workouts if row.key == details.plan_workout_id), None)
        if (
            not workout
            or workout.sport != source.payload["sport"]
            or workout.date.isoformat() != source.payload["date"]
        ):
            raise CoachError(
                "Plan reference does not match activity sport/date", "detail_plan_reference", 422
            )
        mapping, _ = step_structure(workout, fit_indices=False)
        if any(
            lap.step_index is not None and lap.step_index not in mapping for lap in details.laps
        ):
            raise CoachError("Unknown executable step index", "detail_plan_reference", 422)
        return workout

    def validate_extent(self, source, details):
        duration = source.payload["elapsed_duration_s"]
        distance = source.payload["distance_m"]
        if (
            datetime.fromisoformat(source.payload["start_time"]) + timedelta(seconds=duration)
            > self.store.settings.now()
        ):
            raise CoachError(
                "Detailed review requires a concluded activity", "activity_not_completed", 422
            )
        if (
            any(lap.start_elapsed_s + lap.elapsed_s > duration + 1 for lap in details.laps)
            or any(sample.elapsed_s > duration + 1 for sample in details.samples)
            or sum(lap.duration_s for lap in details.laps) > source.payload["duration_s"] + 1
            or sum(zone.time_s or 0 for zone in details.hr_zones) > duration + 5
        ):
            raise CoachError("Detailed times exceed the source activity", "detail_extent", 422)
        # Small rounding differences are allowed; this is an ingestion tolerance, not a fitness threshold.
        max_distance = distance + max(50, distance * 0.02)
        if sum(lap.distance_m or 0 for lap in details.laps) > max_distance or any(
            sample.distance_m is not None and sample.distance_m > max_distance
            for sample in details.samples
        ):
            raise CoachError("Detailed distances exceed the source activity", "detail_extent", 422)

    def write(self, athlete_id, provider, provider_id, body):
        with self.store.transaction() as session:
            self.store.lock_athlete(session, athlete_id)
            source = self.source(session, athlete_id, provider, provider_id)
            if provider == "manual":
                raise CoachError(
                    "Self-reported activities cannot receive device evidence", "detail_source", 409
                )
            summary_hash = canonical_hash(source.payload)
            if body.expected_activity_hash != summary_hash:
                raise CoachError(
                    "Activity changed; reload before writing details", "version_conflict", 409
                )
            row = session.get(ActivityDetails, (athlete_id, provider, provider_id))
            version = row.version if row else 0
            if body.expected_details_version != version:
                raise CoachError("Details changed; reload before writing", "version_conflict", 409)
            self.linked_workout(session, source, body.details)
            self.validate_extent(source, body.details)
            if row is None:
                row = ActivityDetails(
                    athlete_id=athlete_id, provider=provider, provider_id=provider_id
                )
                session.add(row)
            row.version = version + 1
            row.summary_hash = summary_hash
            row.payload = body.details.model_dump(mode="json")
            row.updated_at = self.store.settings.now().isoformat()
            return {"version": row.version, "activity_hash": summary_hash, "status": "saved"}

    def view_in_session(self, session, source, *, canonical_id=None, include_payload=False):
        fingerprint = canonical_hash(source.payload)
        row = session.get(ActivityDetails, (source.athlete_id, source.provider, source.provider_id))
        result = {
            "status": "not_loaded",
            "version": row.version if row else 0,
            "activity_hash": fingerprint,
            "source": source.provider,
            "source_activity_id": source.provider_id,
        }
        if source.provider == "manual":
            return {
                **result,
                "status": "unsupported",
                "reason": "Self-reported evidence has no device samples",
            }
        if not row:
            return result
        if include_payload:
            result["details"] = row.payload
        if row.summary_hash != fingerprint:
            return {
                **result,
                "status": "stale",
                "reason": "Source summary changed; refresh detailed evidence",
            }
        details = SessionDetails.model_validate(row.payload)
        workout = self.linked_workout(session, source, details)
        activity = {**source.payload, "activity_id": canonical_id or source.canonical_id}
        result.update(
            status="ready",
            updated_at=row.updated_at,
            plan_reference={
                "version": details.plan_version,
                "workout_id": details.plan_workout_id,
                "verification": "client_supplied",
            },
            analysis=analyze_canonical(activity, details, workout),
            limitations=[
                "Imported details and the plan link are supplied by the athlete/client; vendor access is not verified.",
                "Phase target comparison uses the referenced plan version, not a guessed match.",
                "Heart rate zones are configured references; averages and recovery differences are not clinical tests.",
            ],
        )
        return result

    def view(self, athlete_id, provider, provider_id):
        with self.store.read_session() as session:
            return self.view_in_session(
                session,
                self.source(session, athlete_id, provider, provider_id),
                include_payload=True,
            )

    def for_canonical(self, session, athlete_id, canonical_id):
        sources = session.scalars(
            select(Activity)
            .where(Activity.athlete_id == athlete_id, Activity.canonical_id == canonical_id)
            .order_by(Activity.provider != "garmin", Activity.provider, Activity.provider_id)
        ).all()
        fallback = None
        for source in sources:
            value = self.view_in_session(session, source, canonical_id=canonical_id)
            if value["status"] == "ready":
                return value
            if fallback is None or value["status"] == "stale":
                fallback = value
        return fallback
