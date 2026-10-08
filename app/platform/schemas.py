import json
import re
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator

from app.integrations.activities import ActivityRecord
from app.models import Plan, StrictModel


class Credentials(StrictModel):
    email: str = Field(min_length=3, max_length=254)
    password: SecretStr = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        value = value.strip().casefold()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address")
        return value


class Registration(Credentials):
    timezone: str = Field(default="Europe/Rome", max_length=64)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown timezone") from None
        return value


class PlanWrite(StrictModel):
    expected_version: int = Field(ge=0, strict=True)
    plan: Plan

    @model_validator(mode="after")
    def finite_plan_metadata(self):
        # Athlete metadata is a flexible dict; PostgreSQL JSON rejects NaN/Infinity.
        # Reject it at the boundary instead of failing after a partial database write.
        try:
            json.dumps(self.plan.athlete, allow_nan=False)
        except (ValueError, TypeError):
            raise ValueError("Plan metadata must contain finite JSON values") from None
        return self


class ActivityImport(StrictModel):
    ingestion_method: Literal["client_import"] = "client_import"
    activities: list[ActivityRecord] = Field(min_length=1, max_length=500)


class ProposalAcceptance(StrictModel):
    expected_version: int = Field(ge=1, strict=True)
    confirmed: bool = Field(default=False, strict=True)


class AccountDeletion(StrictModel):
    password: SecretStr = Field(min_length=12, max_length=128)
    confirmed: bool = Field(default=False, strict=True)
