from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.models import Plan

router = APIRouter(prefix="/api/plan", tags=["plan"])


class Confirmation(BaseModel):
    confirmed: bool = Field(default=False, strict=True)


class TestRequest(BaseModel):
    workout_id: str | None = None


@router.get("")
def get_plan(request: Request):
    return request.app.state.coach.plan()


@router.put("")
def put_plan(plan: Plan, request: Request):
    return request.app.state.coach.replace_plan(plan)


@router.post("/test")
def test_workout(body: TestRequest, request: Request):
    return request.app.state.coach.test_workout(body.workout_id)


@router.post("/sync")
def sync(body: Confirmation, request: Request):
    return request.app.state.coach.sync_plan(body.confirmed)
