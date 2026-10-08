"""Detailed local workout review and official user-owned ChatGPT connection."""

import logging

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import Field

from app.errors import CoachError
from app.models import StrictModel

router = APIRouter(tags=["session-review", "chatgpt-local"])


class DetailRequest(StrictModel):
    activity_id: str | None = Field(default=None, max_length=200)


class ConnectionRequest(StrictModel):
    profile_id: str | None = Field(default=None, max_length=32)
    fresh_registration: bool = Field(default=False, strict=True)


class BrainRequest(DetailRequest):
    model: str = Field(min_length=1, max_length=100)


class OAuthAccessFilter(logging.Filter):
    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) >= 3 and isinstance(record.args[2], str):
            if record.args[2].startswith("/auth/callback"):
                args = list(record.args)
                args[2] = "/auth/callback"
                record.args = tuple(args)
        return True


logging.getLogger("uvicorn.access").addFilter(OAuthAccessFilter())


def coach(request):
    return request.app.state.coach


@router.post("/api/session-review/refresh")
def refresh_details(body: DetailRequest, request: Request):
    current = coach(request)
    with current.lock:
        current.details.refresh(body.activity_id)
    return detailed_view(current, body.activity_id)


def detailed_view(current, activity_id=None):
    result = current.details.view(current.workout_review(), current.plan(), activity_id)
    status = current.chatgpt.status()
    result["chatgpt"] = status
    if result["status"] == "ready" and status["active"]:
        cached = current.db.get("chatgpt_review:" + result["activity"]["activity_id"])
        if cached and cached.get("context_hash") == result["context_hash"] and cached.get("profile") == status["active"]:
            result["brain"] = cached
    result.pop("context", None)
    return result


@router.get("/api/session-review")
def details(request: Request, activity_id: str | None = None):
    return detailed_view(coach(request), activity_id)


@router.post("/api/session-review/brain")
def brain_review(body: BrainRequest, request: Request):
    current = coach(request)
    result = current.details.view(current.workout_review(), current.plan(), body.activity_id)
    if result["status"] != "ready":
        raise CoachError("Leggi prima i dettagli Garmin di questa seduta.", "details_required", 409)
    answer = current.chatgpt.review(result["context"], body.model)
    answer["context_hash"] = result["context_hash"]
    # Account/plan/data changes during inference must not silently attach an old review.
    latest = current.details.view(current.workout_review(), current.plan(), body.activity_id)
    if latest.get("context_hash") != answer["context_hash"] or current.chatgpt.status()["active"] != answer["profile"]:
        raise CoachError("Contesto o account cambiato durante la review. Riprova.", "chatgpt_stale", 409)
    current.db.set("chatgpt_review:" + result["activity"]["activity_id"], answer)
    return answer


@router.get("/api/chatgpt/status")
def connection_status(request: Request):
    current = coach(request)
    return {**current.chatgpt.status(), "error": current.db.get("chatgpt_connection_error")}


@router.post("/api/chatgpt/connect")
def connect(body: ConnectionRequest, request: Request, response: Response):
    url, state = coach(request).chatgpt.start(body.profile_id, body.fresh_registration)
    response.set_cookie("chatgpt_attempt", state, max_age=600, httponly=True, samesite="lax", path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"authorization_url": url}


@router.get("/auth/callback")
def callback(request: Request):
    current = coach(request)
    try:
        current.chatgpt.callback(dict(request.query_params), request.cookies.get("chatgpt_attempt"))
        current.db.set("chatgpt_connection_error", None)
    except CoachError as error:
        current.db.set("chatgpt_connection_error", str(error))
    response = RedirectResponse("/review#chatgpt", status_code=303)
    response.delete_cookie("chatgpt_attempt", path="/")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/api/chatgpt/models")
def models(request: Request):
    return {"models": coach(request).chatgpt.models()}


@router.post("/api/chatgpt/select")
def select_profile(body: ConnectionRequest, request: Request):
    coach(request).chatgpt.select(body.profile_id)
    return coach(request).chatgpt.status()


@router.post("/api/chatgpt/welcome")
def welcome(request: Request):
    coach(request).chatgpt.welcome()
    return {"status": "acknowledged"}


@router.post("/api/chatgpt/disconnect")
def disconnect(request: Request):
    return coach(request).chatgpt.disconnect()
