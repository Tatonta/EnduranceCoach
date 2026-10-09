"""Owner-bound evidence preparation; AI transport is a separate integration."""

from datetime import timedelta
from zoneinfo import ZoneInfo

from app.coaching_context import build_coaching_context, completed_history
from app.errors import CoachError
from app.platform.detailed_review import ActivityDetailService
from app.platform.tables import Athlete, AthleteProfile
from app.training_profile import TrainingProfile


class CoachingContextService:
    def __init__(self, store, athletes):
        self.store, self.athletes = store, athletes

    def context(self, athlete_id):
        with self.store.read_session() as session:
            athlete = session.get(Athlete, athlete_id)
            profile = session.get(AthleteProfile, athlete_id)
            if not athlete or not profile:
                raise CoachError(
                    "Completa il questionario prima del coaching.", "profile_required", 409
                )
            now = self.store.settings.now().astimezone(ZoneInfo(athlete.timezone))
            since = now - timedelta(days=42)
            activities = self.athletes.activity_payloads(
                session, athlete_id, limit=2001, earliest=since.timestamp()
            )
            if len(activities) > 2000:
                raise CoachError(
                    "Storico oltre il limite del contesto: nessuna analisi AI preparata.",
                    "activities_incomplete",
                    409,
                )
            plan = self.athletes.current_plan(session, athlete) if athlete.plan_version else None
            details = ActivityDetailService(self.store)
            recent = completed_history(activities, now)
            evidence = {
                row["activity_id"]: details.for_canonical(session, athlete_id, row["activity_id"])
                or {"status": "not_loaded"}
                for row in recent[:2]
            }
            prepared = build_coaching_context(
                TrainingProfile.model_validate(profile.payload),
                profile.version,
                plan,
                athlete.plan_version,
                activities,
                evidence,
                now,
            )
            return {**prepared, "ai_status": "not_connected", "inference_performed": False}
