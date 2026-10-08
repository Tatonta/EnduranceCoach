"""Self-reported session evidence, usable with no watch or vendor account."""

from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import UUID4, Field, model_validator

from app.errors import CoachError
from app.models import StrictModel


class SessionFeedback(StrictModel):
    perceived_exertion: int | None = Field(default=None, ge=1, le=10, strict=True)
    feeling: Literal["good", "normal", "fatigued", "very_fatigued"] = "normal"
    discomfort: Literal["none", "present", "prefer_not_to_say"] = "prefer_not_to_say"
    completed_as_planned: bool | None = Field(default=None, strict=True)
    notes: str = Field(default="", max_length=1500)
    distance_reported: bool = Field(default=False, strict=True)


class ManualSession(StrictModel):
    request_id: UUID4
    name: str = Field(min_length=1, max_length=100)
    sport: Literal["running", "cycling", "strength", "other"]
    start_time: datetime
    duration_min: float = Field(ge=1, le=1440)
    distance_km: float | None = Field(default=None, ge=0, le=1500)
    perceived_exertion: int | None = Field(default=None, ge=1, le=10, strict=True)
    feeling: Literal["good", "normal", "fatigued", "very_fatigued"] = "normal"
    discomfort: Literal["none", "present", "prefer_not_to_say"] = "prefer_not_to_say"
    completed_as_planned: bool | None = Field(default=None, strict=True)
    notes: str = Field(default="", max_length=1500)

    @model_validator(mode="after")
    def meaningful_record(self):
        self.name = self.name.strip()
        if not self.name or self.start_time.tzinfo is None:
            raise ValueError("Name and timezone-aware start time are required")
        return self

    def validate_completion(self, now):
        if self.start_time + timedelta(minutes=self.duration_min) > now:
            raise CoachError(
                "Registra una seduta conclusa: controlla inizio e durata.",
                "session_not_completed",
                422,
            )

    def record(self):
        from app.integrations.activities import ActivityRecord

        distance = self.distance_km * 1000 if self.distance_km is not None else 0
        seconds = self.duration_min * 60
        return ActivityRecord(
            source="manual",
            source_activity_id=str(self.request_id),
            name=self.name,
            sport=self.sport,
            activity_type=self.sport,
            start_time=self.start_time,
            distance_m=distance,
            duration_s=seconds,
            elapsed_duration_s=seconds,
            avg_pace_s_km=seconds / distance * 1000
            if self.sport == "running" and distance > 0
            else None,
            feedback=SessionFeedback(
                perceived_exertion=self.perceived_exertion,
                feeling=self.feeling,
                discomfort=self.discomfort,
                completed_as_planned=self.completed_as_planned,
                notes=self.notes,
                distance_reported=self.distance_km is not None,
            ),
        )


def manual_findings(activity):
    feedback = activity.get("feedback") or {}
    positives, issues, actions = [], [], []
    if feedback.get("completed_as_planned") is True:
        positives.append(
            "Hai dichiarato di aver completato la seduta prevista: continuità rispettata."
        )
    elif feedback.get("completed_as_planned") is False:
        issues.append(
            "Hai dichiarato una seduta diversa dal previsto: il motivo annotato va considerato nel coaching."
            if feedback.get("notes", "").strip()
            else "Hai dichiarato una seduta diversa dal previsto: usa le note per spiegare che cosa è cambiato."
        )
        actions.append("Non aggiungere automaticamente il lavoro non svolto alla prossima seduta.")
    if feedback.get("feeling") == "good":
        positives.append("Sensazioni buone dichiarate al termine della seduta.")
    elif feedback.get("feeling") in {"fatigued", "very_fatigued"}:
        issues.append(
            "Hai segnalato stanchezza: il coach deve considerarla insieme al carico recente."
        )
        actions.append(
            "Aggiorna il coach su come ti senti prima della prossima seduta impegnativa."
        )
    if feedback.get("discomfort") == "present":
        issues.append(
            "Hai segnalato fastidi o dolore. Non è possibile dedurne la causa dal registro."
        )
        actions.append(
            "Descrivi il fastidio al coach; non considerare il programma una valutazione del dolore."
        )
    rpe = feedback.get("perceived_exertion")
    if rpe is not None:
        positives.append(
            f"Sforzo percepito registrato: {rpe}/10, dato dichiarato utile per contestualizzare il lavoro."
        )
    if not actions:
        actions.append(
            "Confronta le sensazioni di questa seduta con quelle della prossima; aggiorna durata e sforzo effettivi."
        )
    return {
        "verdict": "Seduta dichiarata: aspetti da chiarire"
        if issues
        else "Seduta dichiarata: feedback registrato",
        "positive": positives,
        "issues": issues,
        "actions": actions,
    }


def canonical_manual_id(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise CoachError("Seduta non trovata.", "not_found", 404) from None
