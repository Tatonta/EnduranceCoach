"""Dry-run validation and atomic first-plan creation from client-supplied drafts."""

import json
from datetime import date, timedelta

from pydantic import AwareDatetime, Field

from app.errors import CoachError
from app.initial_plan import validate_draft
from app.models import Plan, StrictModel
from app.platform.coaching import CoachingContextService
from app.platform.tables import Athlete
from app.services.planner import canonical_hash
from app.training_profile import TrainingProfile


class InitialPlanPreview(StrictModel):
    expected_context_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    plan: Plan
    explanation: str = Field(min_length=1, max_length=8000)


class InitialPlanAcceptance(InitialPlanPreview):
    draft_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    expires_at: AwareDatetime
    confirmed: bool = Field(strict=True)


class InitialPlanService:
    def __init__(self, store, athletes):
        self.store, self.athletes = store, athletes
        self.contexts = CoachingContextService(store, athletes)

    def prepare(self, session, athlete, body):
        if not athlete:
            raise CoachError("Account unavailable", "unauthorized", 401)
        if athlete.plan_version:
            raise CoachError("Un programma esiste già. Usa review e proposte per adattarlo.", "plan_exists", 409)
        evidence = self.contexts.in_session(session, athlete)
        if body.expected_context_hash != evidence["context_hash"]:
            raise CoachError("Profilo o storico cambiati: prepara una nuova bozza.", "draft_stale", 409)
        explanation = body.explanation.strip()
        try:
            if not explanation:
                raise ValueError("Explanation required")
            validate_draft(body.plan, TrainingProfile.model_validate(evidence["context"]["training_profile"]),
                           date.fromisoformat(evidence["context"]["today"]))
            plan = body.plan.model_dump(mode="json")
            if len(json.dumps(plan, ensure_ascii=False).encode("utf-8")) > 100_000:
                raise ValueError("Draft too large")
        except ValueError:
            raise CoachError("La bozza non rispetta struttura, disponibilità o limiti iniziali. Nessun piano salvato.",
                             "draft_invalid", 422) from None
        fingerprint = canonical_hash({"athlete_id": athlete.id, "context_hash": evidence["context_hash"],
                                      "plan": plan, "explanation": explanation})
        return {"plan": plan, "explanation": explanation, "context_hash": evidence["context_hash"],
                "draft_hash": fingerprint}

    def preview(self, athlete_id, body):
        with self.store.read_session() as session:
            result = self.prepare(session, session.get(Athlete, athlete_id), body)
            return {**result, "expires_at": (self.store.settings.now() + timedelta(minutes=15)).isoformat(),
                    "status": "validated", "inference_performed": False, "vendor_sync": "not_sent"}

    def apply(self, athlete_id, body):
        if not body.confirmed:
            raise CoachError("Conferma le sedute prima di salvare il programma.", "confirmation_required", 409)
        with self.store.transaction() as session:
            athlete = self.store.lock_athlete(session, athlete_id)
            now = self.store.settings.now()
            if not now < body.expires_at <= now + timedelta(minutes=15):
                raise CoachError("Anteprima scaduta o non valida: preparane una nuova.", "draft_stale", 409)
            prepared = self.prepare(session, athlete, body)
            if body.draft_hash != prepared["draft_hash"]:
                raise CoachError("Le sedute o l'atleta non corrispondono all'anteprima.", "draft_stale", 409)
            version = self.athletes.write_plan(session, athlete, body.plan, "accepted_initial_draft")
        return {"status": "applied", "version": version, "plan": prepared["plan"], "vendor_sync": "not_sent"}
