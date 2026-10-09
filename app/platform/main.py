from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.errors import CoachError
from app.integrations.activities import integration_catalog
from app.integrations.session_details import DetailWrite
from app.platform.coaching import CoachingContextService
from app.platform.config import PlatformSettings
from app.platform.detailed_review import ActivityDetailService
from app.platform.initial_plan import InitialPlanAcceptance, InitialPlanPreview, InitialPlanService
from app.platform.schemas import (
    AccountDeletion,
    ActivityImport,
    Credentials,
    PlanWrite,
    ProposalAcceptance,
    Registration,
)
from app.platform.security import AccountService
from app.platform.service import AthleteService
from app.platform.store import PlatformStore
from app.session_feedback import ManualSession
from app.training_profile import ProfileWrite

bearer = HTTPBearer(auto_error=False)


def create_platform_app(settings=None, store=None):
    settings = settings or PlatformSettings()
    store = store or PlatformStore(settings)
    accounts, athletes = AccountService(store), AthleteService(store)

    @asynccontextmanager
    async def lifespan(app):
        store.check_schema()
        yield
        store.close()

    app = FastAPI(
        title="Adaptive Coach Platform",
        version="0.2.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.store = store
    app.state.accounts = accounts
    app.state.athletes = athletes
    detailed = ActivityDetailService(store)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))

    @app.middleware("http")
    async def boundaries(request, call_next):
        if settings.require_https and request.url.scheme != "https":
            return JSONResponse(
                {"detail": "HTTPS is required", "code": "https_required"}, status_code=400
            )
        if request.headers.get("origin"):
            # Native bearer clients send no Origin. Browser support will require
            # a deliberately configured frontend rather than permissive CORS.
            from urllib.parse import urlsplit

            if urlsplit(request.headers["origin"]).netloc != request.headers.get("host"):
                return JSONResponse(
                    {"detail": "Cross-origin request denied", "code": "origin_denied"},
                    status_code=403,
                )
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 2_000_000:
                return JSONResponse(
                    {"detail": "Request too large", "code": "body_limit"}, status_code=413
                )
            body.extend(chunk)
        request._body = bytes(body)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        if settings.require_https:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.exception_handler(CoachError)
    async def public_error(request, exc):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status == 401 else {}
        if exc.status == 429:
            headers["Retry-After"] = "900"
        return JSONResponse(
            {"detail": str(exc), "code": exc.code}, status_code=exc.status, headers=headers
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Default validation error payloads can echo passwords and health data.
        return JSONResponse(
            {
                "detail": "Invalid request fields",
                "code": "validation_failed",
                "fields": [".".join(map(str, error["loc"])) for error in exc.errors()],
            },
            status_code=422,
        )

    @app.exception_handler(SQLAlchemyError)
    async def storage_error(request, exc):
        return JSONResponse(
            {"detail": "Storage temporarily unavailable", "code": "storage_unavailable"},
            status_code=503,
        )

    def identity(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        return accounts.authenticate(credentials.credentials if credentials else None)

    authenticated = Annotated[dict, Depends(identity)]

    def client_ip(request):
        # Ignore untrusted X-Forwarded-For; proxy trust belongs in deployment configuration.
        return request.client.host if request.client else "unknown"

    @app.get("/health")
    def health():
        store.check_schema()
        return {"status": "ok", "service": "adaptive-coach-platform", "version": "0.2.0"}

    @app.post("/v1/auth/register", status_code=201)
    def register(body: Registration, request: Request):
        return accounts.register(
            body.email, body.password.get_secret_value(), body.timezone, client_ip(request)
        )

    @app.post("/v1/auth/login")
    def login(body: Credentials, request: Request):
        return accounts.login(body.email, body.password.get_secret_value(), client_ip(request))

    @app.post("/v1/auth/logout", status_code=204)
    def logout(user: authenticated):
        accounts.logout(user)
        return Response(status_code=204)

    @app.get("/v1/me")
    def me(user: authenticated):
        return {key: user[key] for key in ("id", "email", "timezone")}

    @app.delete("/v1/me", status_code=204)
    def delete_account(body: AccountDeletion, user: authenticated):
        if not body.confirmed:
            raise CoachError("Confirm account deletion", "confirmation_required", 409)
        accounts.delete_account(user, body.password.get_secret_value())
        return Response(status_code=204)

    @app.get("/v1/me/export")
    def export(user: authenticated):
        return athletes.export(user["id"])

    @app.get("/v1/plan")
    def get_plan(user: authenticated):
        return athletes.plan(user["id"])

    @app.get("/v1/profile")
    def get_profile(user: authenticated):
        return athletes.profile(user["id"])

    @app.put("/v1/profile")
    def put_profile(body: ProfileWrite, user: authenticated):
        return athletes.save_profile(user["id"], body.profile, body.expected_version)

    @app.put("/v1/plan")
    def put_plan(body: PlanWrite, user: authenticated):
        return athletes.replace_plan(user["id"], body.plan, body.expected_version)

    @app.get("/v1/plan/history")
    def history(user: authenticated):
        return {"versions": athletes.history(user["id"])}

    @app.get("/v1/activities")
    def activities(
        user: authenticated,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ):
        return athletes.activities(user["id"], limit, offset)

    @app.post("/v1/activities/import")
    def import_activities(body: ActivityImport, user: authenticated):
        return athletes.ingest(user["id"], body.activities)

    @app.post("/v1/activities/manual")
    def manual_session(body: ManualSession, user: authenticated):
        athletes.profile(user["id"])
        body.validate_completion(settings.now())
        return athletes.ingest(user["id"], [body.record()])

    @app.delete("/v1/activities/{provider}/{provider_id}", status_code=204)
    def remove_activity(provider: str, provider_id: str, user: authenticated):
        athletes.delete_activity(user["id"], provider, provider_id)
        return Response(status_code=204)

    @app.get("/v1/review/workout")
    def workout_review(user: authenticated):
        return athletes.review(user["id"])

    @app.get("/v1/coach/context")
    def coach_context(user: authenticated):
        return CoachingContextService(store, athletes).context(user["id"])

    @app.post("/v1/coach/initial-plan/preview")
    def initial_plan_preview(body: InitialPlanPreview, user: authenticated):
        return InitialPlanService(store, athletes).preview(user["id"], body)

    @app.post("/v1/coach/initial-plan/apply")
    def initial_plan_apply(body: InitialPlanAcceptance, user: authenticated):
        return InitialPlanService(store, athletes).apply(user["id"], body)

    @app.get("/v1/activities/{provider}/{provider_id}/details")
    def get_details(provider: str, provider_id: str, user: authenticated):
        return detailed.view(user["id"], provider, provider_id)

    @app.put("/v1/activities/{provider}/{provider_id}/details")
    def put_details(provider: str, provider_id: str, body: DetailWrite, user: authenticated):
        return detailed.write(user["id"], provider, provider_id, body)

    @app.post("/v1/review/adjustments/preview")
    def preview(user: authenticated):
        return athletes.preview(user["id"])

    @app.post("/v1/review/adjustments/{proposal_id}/apply")
    def apply(proposal_id: str, body: ProposalAcceptance, user: authenticated):
        return athletes.apply(user["id"], proposal_id, body.expected_version, body.confirmed)

    @app.get("/v1/integrations")
    def integrations(user: authenticated):
        return {
            "vendors": integration_catalog(set()),
            "live_vendor_connections": 0,
            "client_import_available": True,
        }

    @app.get("/v1/openapi.json")
    def schema(user: authenticated):
        return app.openapi()

    return app
