from datetime import date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from pydantic import Field, ValidationError, model_validator

from app.errors import CoachError
from app.models import StrictModel


class ActivityRecord(StrictModel):
    """Canonical SI-unit activity, independent of any vendor's response schema."""

    source: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    source_activity_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=300)
    sport: str = Field(pattern=r"^(running|cycling|strength|other)$")
    activity_type: str
    start_time: datetime
    distance_m: float = Field(ge=0)
    duration_s: float = Field(gt=0)
    elapsed_duration_s: float = Field(gt=0)
    avg_pace_s_km: float | None = Field(default=None, gt=0)
    avg_hr: float | None = Field(default=None, gt=0, le=250)
    max_hr: float | None = Field(default=None, gt=0, le=250)
    elevation_gain_m: float | None = Field(default=None, ge=0)
    training_load: float | None = Field(default=None, ge=0)
    aerobic_training_effect: float | None = Field(default=None, ge=0, le=5)
    workout_id: str = ""

    @model_validator(mode="after")
    def valid_time(self):
        if self.start_time.tzinfo is None:
            raise ValueError("Activity timestamps require a timezone")
        if self.elapsed_duration_s < self.duration_s:
            raise ValueError("Elapsed duration cannot be less than active duration")
        return self

    def payload(self, timezone):
        result = self.model_dump(mode="json")
        stamp = self.start_time.astimezone(ZoneInfo(timezone))
        # Preserve existing Garmin database IDs; all other providers are namespaced.
        result.update(
            activity_id=self.source_activity_id
            if self.source == "garmin"
            else f"{self.source}:{self.source_activity_id}",
            start_time=stamp.isoformat(),
            date=stamp.date().isoformat(),
        )
        return result


class ActivitySource(Protocol):
    source: str

    def fetch(self, now: datetime, earliest: date) -> list[ActivityRecord]: ...


class GarminActivitySource:
    source = "garmin"

    def __init__(self, client):
        self.client = client

    def fetch(self, now, earliest):
        from app.garmin.activities import fetch_recent_activities

        records = []
        for activity in fetch_recent_activities(self.client, now, earliest):
            values = {
                k: v
                for k, v in activity.items()
                if k not in {"activity_id", "date", "source", "source_activity_id"}
            }
            # Empty records cannot provide a meaningful workout review.
            if values["duration_s"] <= 0:
                continue
            try:
                records.append(
                    ActivityRecord(
                        source=self.source, source_activity_id=activity["activity_id"], **values
                    )
                )
            except ValidationError:
                raise CoachError(
                    "Metriche Garmin non valide: review non aggiornata", "activities_schema"
                ) from None
        return records


def integration_catalog(active_sources):
    vendors = [
        (
            "garmin",
            "Garmin",
            "Local Garmin adapter; production requires official Connect Developer Program access.",
        ),
        ("coros", "COROS", "Developer onboarding and OAuth credentials required."),
        ("suunto", "Suunto", "Partner approval and OAuth credentials required."),
        (
            "fitbit",
            "Fitbit / Google Health",
            "Google Health API access required; legacy Fitbit API shuts down October 30, 2026. Google currently states new project onboarding is closed.",
        ),
        (
            "amazfit",
            "Amazfit / Zepp",
            "Confirm approved cloud API access or an Apple Health bridge; Zepp OS device APIs are a separate route.",
        ),
        (
            "xiaomi",
            "Xiaomi",
            "Confirm supported devices, region and authorized data access; no cloud adapter implemented.",
        ),
        (
            "apple_health",
            "Apple Health",
            "Requires an iOS HealthKit client and explicit user permissions.",
        ),
    ]
    return [
        {
            "id": key,
            "name": name,
            "activity_import": key in active_sources,
            "status": "local_adapter" if key in active_sources else "planned",
            "notes": notes,
            "workout_export": key == "garmin",
        }
        for key, name, notes in vendors
    ]
