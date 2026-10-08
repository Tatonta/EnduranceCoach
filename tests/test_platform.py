from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("sqlalchemy", reason="Install .[platform] to test the multi-athlete API")
pytest.importorskip("argon2", reason="Install .[platform] to test account security")

from platform_database import isolated_database
from sqlalchemy import func, select
from test_intake import profile_fixture
from test_workout_advice import runs

from app.errors import CoachError
from app.platform.config import ROOT, PlatformSettings
from app.platform.main import create_platform_app
from app.platform.security import token_hash
from app.platform.service import AthleteService
from app.platform.store import PlatformStore
from app.platform.tables import (
    Activity,
    AdjustmentProposal,
    Athlete,
    AthleteProfile,
    AuditEvent,
    AuthSession,
    PlanVersion,
    SchemaRevision,
)
from scripts.create_initial_plan import initial_plan

PASSWORD = "test-only password with enough entropy"


@pytest.fixture
def platform(tmp_path):
    with isolated_database(tmp_path) as database_url:
        settings = PlatformSettings(
            database_url=database_url,
            registration_enabled=True,
            require_https=False,
        )
        settings.now = lambda: datetime(2026, 10, 5, 20, tzinfo=UTC)
        store = PlatformStore(settings)
        store.initialize()
        app = create_platform_app(settings, store)
        with TestClient(app) as client:
            users = []
            for name in ("alice", "bob"):
                credentials = {"email": f"{name}@example.test", "password": PASSWORD}
                result = client.post("/v1/auth/register", json=credentials)
                assert result.status_code == 201, result.text
                token = client.post("/v1/auth/login", json=credentials).json()["access_token"]
                users.append(
                    {**result.json(), "headers": {"Authorization": f"Bearer {token}"}, "token": token}
                )
            yield client, app, users, settings


def test_reader_keeps_plan_snapshot_while_another_worker_commits(platform):
    client, app, (alice, _), settings = platform
    assert save_plan(client, alice).status_code == 200
    second_store = PlatformStore(settings)
    try:
        with app.state.store.read_session() as reader:
            original = reader.get(Athlete, alice["id"])
            assert original.plan_version == 1
            updated = app.state.athletes.current_plan(reader, original).model_copy(deep=True)
            updated.plan_name = "Concurrent new plan"
            assert AthleteService(second_store).replace_plan(alice["id"], updated, 1)["version"] == 2
            reader.expire_all()
            assert reader.get(Athlete, alice["id"]).plan_version == 1
            assert reader.get(PlanVersion, (alice["id"], 2)) is None
        assert app.state.athletes.plan(alice["id"])["version"] == 2
    finally:
        second_store.close()


def save_plan(client, user, expected=0, name=None):
    plan = initial_plan()
    if name:
        plan["plan_name"] = name
    return client.put(
        "/v1/plan", headers=user["headers"], json={"plan": plan, "expected_version": expected}
    )


def records(now):
    return [{k: v for k, v in row.items() if k not in {"activity_id", "date"}} for row in runs(now)]


def seed_trend(client, user, settings):
    assert save_plan(client, user).status_code == 200
    result = client.post(
        "/v1/activities/import",
        headers=user["headers"],
        json={"activities": records(settings.now())},
    )
    assert result.status_code == 200, result.text
    assert client.get("/v1/review/workout", headers=user["headers"]).json()["program"]["eligible"]


@pytest.mark.parametrize(
    "path",
    [
        "/v1/me",
        "/v1/me/export",
        "/v1/plan",
        "/v1/plan/history",
        "/v1/activities",
        "/v1/review/workout",
        "/v1/integrations",
        "/v1/openapi.json",
        "/v1/profile",
    ],
)
def test_every_athlete_read_requires_auth(platform, path):
    client, _, _, _ = platform
    response = client.get(path)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["cache-control"] == "no-store"


def test_mutations_require_auth_and_owner_cannot_be_injected(platform):
    client, _, (alice, bob), settings = platform
    assert (
        client.put("/v1/plan", json={"expected_version": 0, "plan": initial_plan()}).status_code
        == 401
    )
    assert (
        client.post(
            "/v1/activities/import", json={"activities": records(settings.now())}
        ).status_code
        == 401
    )
    assert client.post("/v1/review/adjustments/preview").status_code == 401
    assert (
        client.request(
            "DELETE", "/v1/me", json={"confirmed": True, "password": PASSWORD}
        ).status_code
        == 401
    )
    spoofed = client.put(
        "/v1/plan",
        headers=alice["headers"],
        json={"expected_version": 0, "plan": initial_plan(), "athlete_id": bob["id"]},
    )
    assert spoofed.status_code == 422
    assert client.get("/v1/plan", headers=alice["headers"]).status_code == 404
    assert client.get("/v1/plan", headers=bob["headers"]).status_code == 404


def test_auth_tokens_passwords_and_expiry(platform):
    client, app, (alice, _), settings = platform
    with app.state.store.sessions() as session:
        athlete = session.get(Athlete, alice["id"])
        assert (
            athlete.password_hash.startswith("$argon2id$") and PASSWORD not in athlete.password_hash
        )
        stored = session.get(AuthSession, token_hash(alice["token"]))
        assert stored and stored.token_hash != alice["token"]
    response = client.post(
        "/v1/auth/login",
        json={"email": alice["email"], "password": "wrong password with enough length"},
    )
    assert response.status_code == 401 and PASSWORD not in response.text
    now = settings.now()
    settings.now = lambda: now + timedelta(hours=25)
    assert client.get("/v1/me", headers=alice["headers"]).status_code == 401


def test_logout_revokes_session(platform):
    client, _, (alice, bob), _ = platform
    assert client.post("/v1/auth/logout", headers=alice["headers"]).status_code == 204
    assert client.get("/v1/me", headers=alice["headers"]).status_code == 401
    assert client.get("/v1/me", headers=bob["headers"]).status_code == 200


def test_request_validation_never_echoes_password(platform):
    client, _, _, _ = platform
    secret = "short-secret"
    result = client.post("/v1/auth/login", json={"email": "not-email", "password": secret})
    assert result.status_code == 422 and secret not in result.text
    result = client.post(
        "/v1/auth/register",
        json={"email": "c@example.test", "password": PASSWORD, "timezone": "invalid/zone"},
    )
    assert result.status_code == 422 and PASSWORD not in result.text


def test_explicit_signup_gate_and_login_throttle(platform):
    client, _, (alice, _), settings = platform
    settings.registration_enabled = False
    assert (
        client.post(
            "/v1/auth/register", json={"email": "new@example.test", "password": PASSWORD}
        ).status_code
        == 403
    )
    for _ in range(11):
        assert (
            client.post(
                "/v1/auth/login", json={"email": alice["email"], "password": PASSWORD + "wrong"}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/v1/auth/login", json={"email": alice["email"], "password": PASSWORD}
        ).status_code
        == 429
    )
    now = settings.now()
    settings.now = lambda: now + timedelta(minutes=16)
    assert (
        client.post(
            "/v1/auth/login", json={"email": alice["email"], "password": PASSWORD}
        ).status_code
        == 200
    )


def test_plan_isolation_and_optimistic_versions(platform):
    client, _, (alice, bob), _ = platform
    assert save_plan(client, alice, name="Alice private plan").json()["version"] == 1
    assert client.get("/v1/plan", headers=bob["headers"]).status_code == 404
    assert save_plan(client, bob, name="Bob plan").status_code == 200
    assert save_plan(client, alice, expected=0).status_code == 409
    assert (
        client.get("/v1/plan", headers=alice["headers"]).json()["plan"]["plan_name"]
        == "Alice private plan"
    )
    assert "Alice private plan" not in client.get("/v1/me/export", headers=bob["headers"]).text
    assert save_plan(client, alice, expected=1, name="Alice second plan").json()["version"] == 2
    history = client.get("/v1/plan/history", headers=alice["headers"]).json()["versions"]
    assert [entry["version"] for entry in history] == [2, 1]


def test_nonfinite_flexible_plan_metadata_is_rejected_before_writing(platform):
    import json

    client, _, (alice, _), _ = platform
    plan = initial_plan()
    plan["athlete"]["bad_metric"] = float("nan")
    response = client.put(
        "/v1/plan",
        headers={**alice["headers"], "Content-Type": "application/json"},
        content=json.dumps({"expected_version": 0, "plan": plan}),
    )
    assert response.status_code == 422
    assert client.get("/v1/plan", headers=alice["headers"]).status_code == 404


def test_client_import_is_idempotent_scoped_and_reports_provenance(platform):
    client, _, (alice, bob), settings = platform
    payload = {"activities": records(settings.now())}
    for _ in range(2):
        result = client.post("/v1/activities/import", headers=alice["headers"], json=payload)
        assert result.status_code == 200 and result.json()["unique_workouts"] == 4
    activities = client.get("/v1/activities", headers=alice["headers"]).json()["activities"]
    assert (
        len(activities) == 4
        and activities[0]["source_references"][0]["ingestion_method"] == "client_import"
    )
    assert client.get("/v1/activities", headers=bob["headers"]).json()["activities"] == []
    integrations = client.get("/v1/integrations", headers=alice["headers"]).json()
    assert integrations["live_vendor_connections"] == 0
    assert all(not v["activity_import"] for v in integrations["vendors"])


def test_cross_vendor_exact_duplicate_counts_once(platform):
    client, _, (alice, _), settings = platform
    original = records(settings.now())[0]
    copy = {**original, "source": "apple_health", "source_activity_id": "healthkit-uuid"}
    for record in (original, copy):
        assert (
            client.post(
                "/v1/activities/import", headers=alice["headers"], json={"activities": [record]}
            ).status_code
            == 200
        )
    result = client.get("/v1/activities", headers=alice["headers"]).json()["activities"]
    assert len(result) == 1 and len(result[0]["source_references"]) == 2
    assert result[0]["source"] == "garmin"
    copy["duration_s"] += 120
    copy["elapsed_duration_s"] += 120
    assert (
        client.post(
            "/v1/activities/import", headers=alice["headers"], json={"activities": [copy]}
        ).status_code
        == 200
    )
    assert len(client.get("/v1/activities", headers=alice["headers"]).json()["activities"]) == 2


def test_ambiguous_duplicate_and_transitive_time_chain_are_not_merged(platform):
    client, _, (alice, _), settings = platform
    a = records(settings.now())[0]
    b = {**a, "source_activity_id": "another-garmin-id"}
    imported = {**a, "source": "apple_health", "source_activity_id": "healthkit-id"}
    response = client.post(
        "/v1/activities/import", headers=alice["headers"], json={"activities": [a, b, imported]}
    )
    assert response.json()["unique_workouts"] == 3
    later = records(settings.now())[1]
    middle = {
        **later,
        "source": "coros",
        "start_time": (
            datetime.fromisoformat(later["start_time"]) + timedelta(seconds=1.5)
        ).isoformat(),
    }
    end = {
        **later,
        "source": "suunto",
        "start_time": (
            datetime.fromisoformat(later["start_time"]) + timedelta(seconds=3)
        ).isoformat(),
    }
    response = client.post(
        "/v1/activities/import", headers=alice["headers"], json={"activities": [later, middle, end]}
    )
    assert response.json()["unique_workouts"] >= 5


def test_duplicate_import_preserves_canonical_identity_and_pagination(platform):
    client, _, (alice, _), settings = platform
    values = records(settings.now())
    client.post("/v1/activities/import", headers=alice["headers"], json={"activities": values})
    first_page = client.get("/v1/activities?limit=2", headers=alice["headers"]).json()
    assert first_page["total"] == 4 and first_page["next_offset"] == 2
    second_page = client.get("/v1/activities?limit=2&offset=2", headers=alice["headers"]).json()
    assert second_page["next_offset"] is None
    ids = {entry["activity_id"] for entry in first_page["activities"] + second_page["activities"]}
    assert len(ids) == 4
    copies = [
        {
            **entry,
            "source": "apple_health",
            "source_activity_id": "apple-" + entry["source_activity_id"],
        }
        for entry in values
    ]
    client.post("/v1/activities/import", headers=alice["headers"], json={"activities": copies})
    actual = client.get("/v1/activities", headers=alice["headers"]).json()
    assert actual["total"] == 4
    assert {entry["activity_id"] for entry in actual["activities"]} == ids
    assert all(len(entry["source_references"]) == 2 for entry in actual["activities"])
    assert client.get("/v1/activities?limit=1000", headers=alice["headers"]).status_code == 422


def test_invalid_batches_cannot_partially_import(platform):
    client, _, (alice, _), settings = platform
    a = records(settings.now())[0]
    assert (
        client.post(
            "/v1/activities/import", headers=alice["headers"], json={"activities": [a, a]}
        ).status_code
        == 422
    )
    future = {**a, "start_time": (settings.now() + timedelta(days=1)).isoformat()}
    assert (
        client.post(
            "/v1/activities/import", headers=alice["headers"], json={"activities": [a, future]}
        ).status_code
        == 422
    )
    malformed = {**a, "source": "suunto", "avg_hr": -1}
    assert (
        client.post(
            "/v1/activities/import", headers=alice["headers"], json={"activities": [a, malformed]}
        ).status_code
        == 422
    )
    assert client.get("/v1/activities", headers=alice["headers"]).json()["activities"] == []


def test_activity_delete_uses_authenticated_owner(platform):
    client, _, (alice, bob), settings = platform
    a = records(settings.now())[0]
    client.post("/v1/activities/import", headers=alice["headers"], json={"activities": [a]})
    route = f"/v1/activities/{a['source']}/{a['source_activity_id']}"
    assert client.delete(route, headers=bob["headers"]).status_code == 404
    assert len(client.get("/v1/activities", headers=alice["headers"]).json()["activities"]) == 1
    assert client.delete(route, headers=alice["headers"]).status_code == 204


def test_adjustment_confirmation_owner_atomic_apply_and_replay(platform):
    client, app, (alice, bob), settings = platform
    seed_trend(client, alice, settings)
    proposal = client.post("/v1/review/adjustments/preview", headers=alice["headers"]).json()
    route = f"/v1/review/adjustments/{proposal['proposal_id']}/apply"
    body = {"expected_version": 1, "confirmed": True}
    assert client.post(route, headers=bob["headers"], json=body).status_code == 404
    assert (
        client.post(route, headers=alice["headers"], json={**body, "confirmed": False}).status_code
        == 409
    )
    assert client.post(route, headers=alice["headers"], json=body).json()["version"] == 2
    assert not client.get("/v1/review/workout", headers=alice["headers"]).json()["program"][
        "eligible"
    ]
    assert client.post(route, headers=alice["headers"], json=body).status_code == 409
    with app.state.store.sessions() as session:
        assert session.get(AdjustmentProposal, proposal["proposal_id"]).status == "applied"
        assert session.get(Athlete, alice["id"]).last_adjustment
        assert (
            len(
                session.scalars(
                    select(PlanVersion).where(PlanVersion.athlete_id == alice["id"])
                ).all()
            )
            == 2
        )


@pytest.mark.parametrize("change", ["plan", "activity", "expiry"])
def test_proposal_revalidates_every_dependency(platform, change):
    client, _, (alice, _), settings = platform
    seed_trend(client, alice, settings)
    proposal = client.post("/v1/review/adjustments/preview", headers=alice["headers"]).json()
    if change == "plan":
        assert save_plan(client, alice, expected=1).status_code == 200
    elif change == "activity":
        changed = records(settings.now())[-1]
        changed["avg_hr"] = 175
        client.post(
            "/v1/activities/import", headers=alice["headers"], json={"activities": [changed]}
        )
    else:
        now = settings.now()
        settings.now = lambda: now + timedelta(minutes=11)
    response = client.post(
        f"/v1/review/adjustments/{proposal['proposal_id']}/apply",
        headers=alice["headers"],
        json={"expected_version": 1, "confirmed": True},
    )
    assert response.status_code in {404, 409}


def test_transaction_rolls_back_plan_and_evidence_on_failure(platform, monkeypatch):
    client, app, (alice, _), settings = platform
    seed_trend(client, alice, settings)
    service = app.state.athletes
    proposal = service.preview(alice["id"])
    real_audit = service.audit

    def fail_commit(session, athlete_id, event, payload):
        if event == "adjustment_applied":
            raise RuntimeError("Simulated write failure")
        real_audit(session, athlete_id, event, payload)

    monkeypatch.setattr(service, "audit", fail_commit)
    with pytest.raises(RuntimeError):
        service.apply(alice["id"], proposal["proposal_id"], 1, True)
    with app.state.store.sessions() as session:
        assert session.get(Athlete, alice["id"]).plan_version == 1
        assert session.get(Athlete, alice["id"]).last_adjustment is None
        assert session.get(PlanVersion, (alice["id"], 2)) is None
        assert session.get(AdjustmentProposal, proposal["proposal_id"]).status == "pending"


def test_concurrent_workers_cannot_both_apply_one_proposal(platform):
    client, app, (alice, _), settings = platform
    seed_trend(client, alice, settings)
    proposal = app.state.athletes.preview(alice["id"])

    second_store = PlatformStore(settings)
    second_worker = AthleteService(second_store)

    def apply_once(worker):
        try:
            return worker.apply(alice["id"], proposal["proposal_id"], 1, True)["status"]
        except CoachError as error:
            return error.status

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(apply_once, [app.state.athletes, second_worker]))
    second_store.close()
    assert sorted(map(str, outcomes)) == ["409", "applied"]
    assert app.state.athletes.plan(alice["id"])["version"] == 2


def test_export_and_account_deletion_remove_only_owner_data(platform):
    client, app, (alice, bob), settings = platform
    seed_trend(client, alice, settings)
    save_plan(client, bob)
    exported = client.get("/v1/me/export", headers=alice["headers"])
    assert exported.status_code == 200
    assert (
        PASSWORD not in exported.text
        and "password_hash" not in exported.text
        and "token_hash" not in exported.text
    )
    assert (
        exported.json()["plans"]
        and exported.json()["activity_sources"]
        and exported.json()["audit"]
    )
    assert (
        client.request(
            "DELETE",
            "/v1/me",
            headers=alice["headers"],
            json={"confirmed": False, "password": PASSWORD},
        ).status_code
        == 409
    )
    assert (
        client.request(
            "DELETE",
            "/v1/me",
            headers=alice["headers"],
            json={"confirmed": True, "password": PASSWORD},
        ).status_code
        == 204
    )
    assert client.get("/v1/me", headers=alice["headers"]).status_code == 401
    assert client.get("/v1/plan", headers=bob["headers"]).status_code == 200
    with app.state.store.sessions() as session:
        for table in (Activity, AuthSession, AuditEvent, PlanVersion, AdjustmentProposal):
            assert (
                session.scalar(
                    select(func.count()).select_from(table).where(table.athlete_id == alice["id"])
                )
                == 0
            )


def test_host_origin_body_and_https_boundaries(platform):
    client, _, _, settings = platform
    assert client.get("/health", headers={"Host": "evil.test"}).status_code == 400
    assert (
        client.post("/v1/auth/login", headers={"Origin": "https://evil.test"}, json={}).status_code
        == 403
    )
    assert client.post("/v1/auth/login", content=b"x" * 2_000_001).status_code == 413
    settings.require_https = True
    assert client.get("/health").status_code == 400


def test_schema_migration_is_explicit_and_does_not_touch_personal_store(tmp_path):
    path = tmp_path / "isolated" / "platform.sqlite3"
    store = PlatformStore(PlatformSettings(database_url=f"sqlite:///{path.as_posix()}"))
    assert not path.exists()
    store.initialize()
    store.check_schema()
    store.initialize()
    with pytest.raises(ValueError, match="personal"):
        PlatformSettings(database_url=f"sqlite:///{(ROOT / 'data/coach.sqlite3').as_posix()}")
    store.close()


def test_profile_is_owner_bound_versioned_exported_and_deleted(platform):
    client, app, (alice, bob), _ = platform
    assert client.get("/v1/profile", headers=alice["headers"]).json()["code"] == "profile_required"
    payload = {"expected_version": 0, "profile": profile_fixture()}
    assert client.put("/v1/profile", json=payload).status_code == 401
    reply = client.put("/v1/profile", headers=alice["headers"], json=payload)
    assert reply.status_code == 200 and reply.json()["version"] == 1
    assert client.get("/v1/profile", headers=bob["headers"]).status_code == 404
    assert client.put("/v1/profile", headers=alice["headers"], json=payload).status_code == 409
    assert client.get("/v1/me/export", headers=alice["headers"]).json()["training_profile"]["profile"] == payload["profile"]
    assert client.get("/v1/me/export", headers=bob["headers"]).json()["training_profile"] is None
    assert client.put("/v1/profile", headers=alice["headers"], json={**payload, "athlete_id": bob["id"]}).status_code == 422
    assert client.request("DELETE", "/v1/me", headers=alice["headers"], json={"password": PASSWORD, "confirmed": True}).status_code == 204
    with app.state.store.read_session() as session:
        assert session.get(AthleteProfile, alice["id"]) is None


def test_revision_one_migration_preserves_data_and_requires_explicit_initializer(platform):
    _, app, (alice, _), _ = platform
    store = app.state.store
    # Build the previous revision from disposable test data, never a real database.
    AthleteProfile.__table__.drop(store.engine)
    with store.transaction() as session:
        session.get(SchemaRevision, 1).version = 1
    with pytest.raises(RuntimeError, match="version"):
        store.check_schema()
    store.initialize()
    store.initialize()
    store.check_schema()
    with store.read_session() as session:
        assert session.get(SchemaRevision, 1).version == 2
        assert session.get(Athlete, alice["id"]).email == alice["email"]
        assert session.get(AthleteProfile, alice["id"]) is None
