from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/climbs", tags=["climbs"])


@router.get("")
def latest(request: Request):
    return request.app.state.coach.climbs.latest()


@router.post("/refresh")
def refresh(request: Request):
    return request.app.state.coach.refresh_climbs()
