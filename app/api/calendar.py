from fastapi import APIRouter, Request

from app.api.plan import Confirmation

router = APIRouter(prefix="/api/calendar/cleanup", tags=["calendar"])


class ApplyRequest(Confirmation):
    preview_id: str


@router.post("/preview")
def preview(request: Request):
    return request.app.state.coach.preview_calendar_cleanup()


@router.post("/apply")
def apply(body: ApplyRequest, request: Request):
    return request.app.state.coach.apply_calendar_cleanup(body.preview_id, body.confirmed)
