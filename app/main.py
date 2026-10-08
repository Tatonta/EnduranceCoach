from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api import activities, calendar, climbs, performances, plan, review, session_review
from app.config import ROOT, Settings
from app.garmin.client import CoachError
from app.services.coach import Coach


def create_app(settings=None, client=None):
    settings = settings or Settings()
    coach = Coach(settings, client)

    @asynccontextmanager
    async def lifespan(app):
        coach.plan()  # Fail clearly on invalid source-of-truth JSON before starting jobs.
        coach.start()
        yield
        coach.stop()

    app = FastAPI(title="Garmin Adaptive Coach", version="0.1.0", lifespan=lifespan)
    app.state.coach = coach
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )

    @app.middleware("http")
    async def same_origin(request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if request.headers.get("sec-fetch-site") == "cross-site" or (
                origin and urlsplit(origin).netloc != request.headers.get("host")
            ):
                return JSONResponse(
                    {"detail": "Richiesta da origine esterna bloccata"}, status_code=403
                )
        response = await call_next(request)
        if request.url.path.startswith(("/api/session-review", "/api/chatgpt", "/auth/callback")):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data: https://tile.openstreetmap.org; frame-ancestors 'none'; base-uri 'self'"
        )
        return response

    @app.exception_handler(CoachError)
    async def coach_error(request, exc):
        return JSONResponse({"detail": str(exc), "code": exc.code}, status_code=exc.status)

    @app.exception_handler(ValidationError)
    async def invalid_plan(request, exc):
        return JSONResponse(
            {
                "detail": "workouts.json non valido: controlla schema, durate, target e ID duplicati",
                "code": "invalid_plan",
            },
            status_code=422,
        )

    for router in (
        activities.router,
        plan.router,
        calendar.router,
        review.router,
        performances.router,
        climbs.router,
        session_review.router,
    ):
        app.include_router(router)
    app.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")
    templates = Jinja2Templates(directory=ROOT / "app" / "templates")

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "version": "0.1.0",
            "timezone": settings.timezone,
            "garmin": coach.db.get("garmin_status"),
            "scheduler_enabled": settings.scheduler_enabled,
            "next_review": coach.db.get("next_review"),
            "scheduler_error": coach.db.get("scheduler_error"),
        }

    @app.get("/api/dashboard/summary")
    def summary():
        return coach.summary()

    @app.get("/api/integrations")
    def integrations():
        return {"vendors": coach.integrations(), "deployment": "single_user_local"}

    @app.get("/review")
    def workout_review_page(request: Request):
        return templates.TemplateResponse(request=request, name="review.html", context={})

    @app.get("/")
    def dashboard(request: Request):
        return templates.TemplateResponse(request=request, name="dashboard.html", context={})

    @app.get("/performances")
    def best_performances(request: Request):
        return templates.TemplateResponse(request=request, name="performances.html", context={})

    @app.get("/climbs")
    def cycling_climbs(request: Request):
        return templates.TemplateResponse(request=request, name="climbs.html", context={})

    return app


app = create_app()
