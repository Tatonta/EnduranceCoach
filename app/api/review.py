from fastapi import APIRouter, Request
from pydantic import Field

from app.errors import CoachError
from app.models import StrictModel

router = APIRouter(prefix="/api/review", tags=["review"])


class AdjustmentConfirmation(StrictModel):
    preview_id: str = Field(min_length=1)
    confirmed: bool = Field(default=False, strict=True)


@router.get("/workout")
def workout(request: Request):
    return request.app.state.coach.workout_review()


@router.post("/adjustment/preview")
def preview_adjustment(request: Request):
    return request.app.state.coach.preview_adjustment()


@router.post("/adjustment/apply")
def apply_adjustment(body: AdjustmentConfirmation, request: Request):
    return request.app.state.coach.apply_adjustment(body.preview_id, body.confirmed)


@router.get("/latest")
def latest(request: Request):
    snapshot = request.app.state.coach.db.get("latest_review")
    if snapshot is None:
        raise CoachError("Nessuna review disponibile: esegui Run Review", "review_required", 404)
    return snapshot


@router.post("/run")
def run_review(request: Request):
    return request.app.state.coach.review()
