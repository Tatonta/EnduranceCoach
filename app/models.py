from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def pace_seconds(value: str) -> int:
    import re

    if not re.fullmatch(r"\d{1,2}:[0-5]\d", value):
        raise ValueError("Passo richiesto nel formato m:ss/km")
    minutes, seconds = map(int, value.split(":"))
    total = minutes * 60 + seconds
    if total <= 0:
        raise ValueError("Passo deve essere positivo")
    return total


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PaceTarget(StrictModel):
    type: Literal["pace"]
    slow: str
    fast: str

    @model_validator(mode="after")
    def valid_range(self):
        if pace_seconds(self.slow) < pace_seconds(self.fast):
            raise ValueError("slow deve essere più lento o uguale a fast")
        return self


class HRTarget(StrictModel):
    type: Literal["hr_zone"]
    zone: int = Field(ge=1, le=5, strict=True)


Target = Annotated[PaceTarget | HRTarget, Field(discriminator="type")]


class Step(StrictModel):
    type: Literal["warmup", "run", "interval", "recovery", "cooldown", "repeat"]
    duration_s: float | None = Field(default=None, gt=0)
    duration_min: float | None = Field(default=None, gt=0)
    distance_m: float | None = Field(default=None, gt=0)
    target: Target | None = None
    iterations: int | None = Field(default=None, ge=1, le=100, strict=True)
    steps: list[Step] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_step(self):
        measures = sum(x is not None for x in (self.duration_s, self.duration_min, self.distance_m))
        if self.type == "repeat":
            if not self.steps or self.iterations is None or measures or self.target:
                raise ValueError("Repeat richiede iterations e steps, senza durata o target")
            if any(s.type == "repeat" for s in self.steps):
                raise ValueError("Repeat annidati non supportati nella v1")
        elif measures != 1 or self.steps or self.iterations is not None:
            raise ValueError("Uno step richiede una sola durata/distanza e nessun sotto-step")
        return self

    @property
    def seconds(self):
        return (
            self.duration_s
            if self.duration_s is not None
            else (self.duration_min * 60 if self.duration_min is not None else None)
        )


class Workout(StrictModel):
    id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    date: date
    name: str = Field(min_length=1, max_length=100)
    sport: Literal["running", "cycling", "rest", "manual"]
    estimated_duration_min: float | None = Field(default=None, gt=0)
    description: str = Field(default="", max_length=2000)
    quality: bool = False
    steps: list[Step] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_workout(self):
        if self.sport in {"running", "cycling"}:
            if not self.steps or self.estimated_duration_min is None:
                raise ValueError("Workout sportivo richiede steps ed estimated_duration_min")
        elif self.steps:
            raise ValueError("Rest/manual non possono avere step Garmin")
        if self.sport == "cycling" and any(
            s.target and s.target.type == "pace" for s in flatten(self.steps)
        ):
            raise ValueError("Target pace/km non valido per cycling: usare hr_zone")
        return self

    @property
    def key(self):
        return self.id or f"{self.date.isoformat()}-{self.sport}"


def flatten(steps: list[Step]):
    for step in steps:
        if step.type == "repeat":
            yield from flatten(step.steps)
        else:
            yield step


class Plan(StrictModel):
    plan_name: str = Field(min_length=1)
    goal: str = ""
    athlete: dict = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    workouts: list[Workout] = Field(min_length=1, max_length=366)

    @model_validator(mode="after")
    def unique_workouts(self):
        keys = [w.key for w in self.workouts]
        if len(set(keys)) != len(keys):
            raise ValueError("ID workout duplicati: assegnare id distinti alle doppie sessioni")
        sessions = [(w.date, w.name, w.sport) for w in self.workouts]
        if len(set(sessions)) != len(sessions):
            raise ValueError(
                "Le doppie sessioni nello stesso sport/giorno richiedono nomi distinti"
            )
        return self

    @property
    def start(self):
        return min(w.date for w in self.workouts)

    @property
    def end(self):
        return max(w.date for w in self.workouts)
