"""Detailed vendor-neutral evidence. Adapters convert vendor units before this boundary."""

from itertools import pairwise
from typing import Literal

from pydantic import Field, model_validator

from app.models import StrictModel


class Dynamics(StrictModel):
    cadence_spm: float | None = Field(default=None, ge=0, le=300)
    cadence_rpm: float | None = Field(default=None, ge=0, le=250)
    stride_m: float | None = Field(default=None, gt=0, le=5)
    ground_contact_s: float | None = Field(default=None, gt=0, le=2)
    vertical_oscillation_m: float | None = Field(default=None, ge=0, le=0.5)
    vertical_ratio_percent: float | None = Field(default=None, ge=0, le=100)
    power_w: float | None = Field(default=None, ge=0, le=4000)


class DetailedLap(Dynamics):
    lap: int = Field(ge=1, strict=True)
    phase_type: Literal["warmup", "run", "interval", "recovery", "cooldown", "unknown"] = "unknown"
    # Zero-based executable template leaves; repeat children counted once, no FIT repeat marker.
    step_index: int | None = Field(default=None, ge=0, le=1000, strict=True)
    start_elapsed_s: float = Field(ge=0)
    duration_s: float = Field(gt=0)
    elapsed_s: float = Field(gt=0)
    distance_m: float | None = Field(default=None, ge=0)
    avg_hr: float | None = Field(default=None, gt=0, le=250)
    max_hr: float | None = Field(default=None, gt=0, le=250)

    @model_validator(mode="after")
    def valid_lap(self):
        if self.elapsed_s < self.duration_s:
            raise ValueError("Elapsed duration cannot be shorter than active duration")
        if self.avg_hr and self.max_hr and self.avg_hr > self.max_hr:
            raise ValueError("Mean heart rate cannot exceed maximum")
        return self


class DetailedSample(Dynamics):
    elapsed_s: float = Field(ge=0)
    distance_m: float | None = Field(default=None, ge=0)
    speed_m_s: float | None = Field(default=None, ge=0, le=40)
    hr: float | None = Field(default=None, gt=0, le=250)
    segment: int = Field(default=0, ge=0, strict=True)


class HRZone(StrictModel):
    zone: int = Field(ge=1, le=5, strict=True)
    low_bpm: float = Field(gt=0, le=250)
    high_bpm: float | None = Field(default=None, gt=0, le=250)
    time_s: float | None = Field(default=None, ge=0)


class RoutePoint(StrictModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class SessionDetails(StrictModel):
    schema_version: Literal[1] = 1
    laps: list[DetailedLap] = Field(default_factory=list, max_length=500)
    samples: list[DetailedSample] = Field(default_factory=list, max_length=4000)
    route_segments: list[list[RoutePoint]] = Field(default_factory=list, max_length=100)
    hr_zones: list[HRZone] = Field(default_factory=list, max_length=5)
    dynamics: Dynamics = Field(default_factory=Dynamics)
    reported_sample_count: int | None = Field(default=None, ge=0, le=10_000_000, strict=True)
    coverage_note: str = Field(default="", max_length=500)
    plan_version: int | None = Field(default=None, ge=1, strict=True)
    plan_workout_id: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def coherent_evidence(self):
        if (self.plan_version is None) != (self.plan_workout_id is None):
            raise ValueError("A planned step link requires both plan version and workout identity")
        if self.plan_version is None and any(lap.step_index is not None for lap in self.laps):
            raise ValueError("Step indices require an explicit plan reference")
        for a, b in pairwise(self.laps):
            if b.lap <= a.lap or b.start_elapsed_s < a.start_elapsed_s + a.elapsed_s - 1:
                raise ValueError("Laps must be ordered and not overlap")
        for a, b in pairwise(self.samples):
            if b.elapsed_s <= a.elapsed_s or b.segment < a.segment:
                raise ValueError("Samples require increasing elapsed time and ordered segments")
            if (
                a.segment == b.segment
                and a.distance_m is not None
                and b.distance_m is not None
                and b.distance_m < a.distance_m
            ):
                raise ValueError("Accumulated distance must not decrease within a segment")
        if self.reported_sample_count is not None and self.reported_sample_count < len(
            self.samples
        ):
            raise ValueError("Reported coverage cannot be smaller than supplied samples")
        if (
            any(len(segment) < 2 for segment in self.route_segments)
            or sum(map(len, self.route_segments)) > 2000
        ):
            raise ValueError("Route segments need two points each and at most 2000 points total")
        zones = sorted(self.hr_zones, key=lambda z: z.zone)
        if len({z.zone for z in zones}) != len(zones) or any(
            a.low_bpm >= b.low_bpm for a, b in pairwise(zones)
        ):
            raise ValueError("Zone numbers must be unique and boundaries increasing")
        if any(z.high_bpm is not None and z.high_bpm < z.low_bpm for z in zones):
            raise ValueError("Zone upper boundary cannot be below its lower boundary")
        if any(a.high_bpm is not None and a.high_bpm >= b.low_bpm for a, b in pairwise(zones)):
            raise ValueError("Heart rate zone ranges must not overlap")
        if not (self.laps or self.samples or self.route_segments):
            raise ValueError("Detailed evidence requires laps, samples or a route")
        return self


class DetailWrite(StrictModel):
    expected_details_version: int = Field(ge=0, strict=True)
    expected_activity_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    details: SessionDetails


def analyze_canonical(activity, details, workout=None):
    from app.services.session_analysis import evaluate_measured_session

    def normalized(value):
        result = value.model_dump()
        result["gct_ms"] = (
            value.ground_contact_s * 1000 if value.ground_contact_s is not None else None
        )
        result["vertical_cm"] = (
            value.vertical_oscillation_m * 100 if value.vertical_oscillation_m is not None else None
        )
        return result

    laps = [normalized(lap) for lap in details.laps]
    for lap in laps:
        lap["pace_s_km"] = (
            lap["duration_s"] / lap["distance_m"] * 1000
            if lap["distance_m"] is not None and lap["distance_m"] > 0
            else None
        )
        lap["quality_flags"] = []
    samples = [normalized(sample) for sample in details.samples]
    for sample in samples:
        sample["pace_s_km"] = (
            1000 / sample["speed_m_s"]
            if sample["speed_m_s"] and activity["sport"] == "running"
            else None
        )
    route_segments = [
        [[point.lat, point.lon] for point in segment] for segment in details.route_segments
    ]
    evidence = {
        "laps": laps,
        "samples": samples,
        "route": [],
        "dynamics": normalized(details.dynamics),
        "zones": [
            {
                "zoneNumber": z.zone,
                "zoneLowBoundary": z.low_bpm,
                "zoneHighBoundary": z.high_bpm,
                "secsInZone": z.time_s,
            }
            for z in sorted(details.hr_zones, key=lambda z: z.zone)
        ],
        "locomotion_s": {},
        "reported_sample_count": details.reported_sample_count,
    }
    result = evaluate_measured_session(activity, evidence, workout, source_label=activity["source"])
    result["route_segments"] = route_segments
    result["coverage"]["gps_points"] = sum(map(len, route_segments))
    result["coverage_note"] = details.coverage_note
    result["method"] = (
        "Lap e campioni normalizzati; fasi per indici dichiarati e tipo di fase, FC ponderata per durata. Indici di step eseguibili senza marcatori repeat FIT."
    )
    return result
