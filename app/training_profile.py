"""Athlete-owned coaching intake, shared by local, platform and native clients."""

from datetime import date as CalendarDate
from typing import Literal

from pydantic import Field, model_validator

from app.errors import CoachError
from app.models import StrictModel


class TrainingDay(StrictModel):
    weekday: int = Field(ge=0, le=6, strict=True)  # Monday = 0
    minutes: int = Field(ge=15, le=240, strict=True)


class BestPerformance(StrictModel):
    sport: Literal["running", "cycling"]
    distance_m: float = Field(ge=400, le=500_000)
    duration_s: float = Field(ge=30, le=172_800)
    date: CalendarDate | None = None
    note: str = Field(default="", max_length=300)


class TrainingProfile(StrictModel):
    schema_version: Literal[1] = 1
    primary_sport: Literal["running", "cycling", "both"]
    goal_type: Literal["fitness", "consistency", "event", "personal_best"]
    goal_description: str = Field(min_length=10, max_length=1500)
    target_date: CalendarDate | None = None
    deadline_flexible: bool = Field(default=True, strict=True)
    age_years: int | None = Field(default=None, ge=18, le=110, strict=True)
    weight_kg: float | None = Field(default=None, ge=30, le=350)
    height_cm: float | None = Field(default=None, ge=120, le=240)
    device_vendor: Literal[
        "none", "garmin", "coros", "suunto", "fitbit", "amazfit", "xiaomi", "apple", "other"
    ]
    device_model: str = Field(default="", max_length=120)
    heart_rate_sensor: bool = Field(default=False, strict=True)
    power_meter: bool = Field(default=False, strict=True)
    running_years: float = Field(ge=0, le=80)
    cycling_years: float = Field(ge=0, le=80)
    recent_running_km_week: float = Field(ge=0, le=500)
    recent_cycling_km_week: float = Field(ge=0, le=3000)
    experience_notes: str = Field(default="", max_length=2000)
    gym_sessions_week: int = Field(ge=0, le=7, strict=True)
    gym_notes: str = Field(default="", max_length=1000)
    availability: list[TrainingDay] = Field(min_length=1, max_length=7)
    best_performances: list[BestPerformance] = Field(default_factory=list, max_length=20)
    constraints: str = Field(default="", max_length=1500)
    coaching_consent: bool = Field(strict=True)

    @model_validator(mode="after")
    def meaningful_intake(self):
        self.goal_description = self.goal_description.strip()
        if len(self.goal_description) < 10:
            raise ValueError("Describe what you want to achieve")
        if not self.deadline_flexible and self.target_date is None:
            raise ValueError("A fixed deadline requires a target date")
        if len({day.weekday for day in self.availability}) != len(self.availability):
            raise ValueError("Availability days must be unique")
        if self.device_vendor == "none" and self.device_model.strip():
            raise ValueError("A device model requires a device")
        if not self.coaching_consent:
            raise ValueError("Confirm use of the answers for coaching")
        return self

    def validate_calendar(self, today):
        if self.target_date and self.target_date <= today:
            raise CoachError(
                "La scadenza deve essere futura; aggiorna il tuo obiettivo.", "profile_date", 422
            )
        if any(result.date and result.date > today for result in self.best_performances):
            raise CoachError(
                "Un miglior tempo deve riferirsi a una prestazione già svolta.", "profile_date", 422
            )


class ProfileWrite(StrictModel):
    expected_version: int = Field(ge=0, strict=True)
    profile: TrainingProfile


def profile_brief(profile):
    """An evidence summary, not a substitute for the AI coach or a training prescription."""
    days = sorted(profile.availability, key=lambda day: day.weekday)
    return {
        "days_per_week": len(days),
        "available_minutes_week": sum(day.minutes for day in days),
        "device_feedback": "subjective"
        if profile.device_vendor == "none"
        else "device_when_connected",
        "notes": [
            "Le risposte sono dichiarazioni dell'atleta; i migliori tempi non sono risultati verificati.",
            "Senza dispositivo il coach può usare durata, sensazioni e feedback manuali, senza inventare FC, split o GPS."
            if profile.device_vendor == "none"
            else "La scelta del produttore non collega automaticamente l'account né garantisce le metriche disponibili.",
            "Palestra e impegni vanno considerati nel carico totale e nel recupero.",
        ],
    }
