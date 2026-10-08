from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/activities", tags=["activities"])


@router.get("/recent")
def recent(request: Request, limit: int = 20):
    coach = request.app.state.coach
    return {
        "last_refresh": coach.db.get("last_refresh"),
        "activities": coach.db.activities()[: max(1, min(limit, 200))],
    }


@router.post("/refresh")
def refresh(request: Request):
    return request.app.state.coach.refresh()
