from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/performances", tags=["performances"])


@router.get("")
def latest(request: Request):
    return request.app.state.coach.performances.latest()


@router.post("/refresh")
def refresh(request: Request):
    return request.app.state.coach.refresh_performances()
