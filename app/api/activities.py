from fastapi import APIRouter, Request

from app.errors import CoachError
from app.session_feedback import ManualSession, canonical_manual_id

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


@router.post("/manual")
def manual(body: ManualSession, request: Request):
    coach = request.app.state.coach
    body.validate_completion(coach.settings.now())
    with coach.lock:
        if not coach.db.get("training_profile"):
            raise CoachError("Completa prima il questionario.", "profile_required", 409)
        row = body.record().payload(coach.settings.timezone)
        coach.db.save_activities([row])
        coach.db.set("assistant_draft", None)
    return {"status": "saved", "activity": row}


@router.delete("/manual/{request_id}", status_code=204)
def delete_manual(request_id: str, request: Request):
    coach = request.app.state.coach
    with coach.lock:
        if not coach.db.delete_manual_activity("manual:" + canonical_manual_id(request_id)):
            raise CoachError("Seduta non trovata.", "not_found", 404)
        coach.db.set("assistant_draft", None)
