from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_intake import profile_fixture
from test_workout_advice import runs

from app.api.assistant import context
from app.integrations.activities import ActivityRecord
from app.main import create_app
from app.session_feedback import ManualSession


def manual_body(now, **changes):
    return {
        "request_id": str(uuid4()),
        "name": "Seduta sintetica",
        "sport": "running",
        "start_time": (now - timedelta(hours=1)).isoformat(),
        "duration_min": 30,
        "perceived_exertion": 7,
        "feeling": "fatigued",
        "discomfort": "none",
        "completed_as_planned": False,
        "notes": "Feedback sintetico, nessun dato personale",
        **changes,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"perceived_exertion": 11},
        {"perceived_exertion": True},
        {"duration_min": 0},
        {"distance_km": -1},
        {"avg_hr": 130},
        {"athlete_id": "other"},
        {"start_time": "2026-10-03T10:00:00"},
        {"name": " "},
    ],
)
def test_manual_boundary_rejects_invalid_or_invented_metrics(settings, changes):
    with pytest.raises(ValidationError):
        ManualSession.model_validate(manual_body(settings.now(), **changes))


def test_manual_record_preserves_unknown_distance_and_never_claims_device_metrics(settings):
    record = ManualSession.model_validate(manual_body(settings.now())).record()
    payload = record.payload(settings.timezone)
    assert payload["source"] == "manual" and payload["evidence_kind"] == "self_reported"
    assert payload["distance_known"] is False and payload["avg_pace_s_km"] is None
    assert payload["avg_hr"] is payload["elevation_gain_m"] is None
    with pytest.raises(ValidationError):
        ActivityRecord.model_validate({**record.model_dump(), "distance_m": 1000, "avg_pace_s_km": 300})
    for field in ("avg_hr", "max_hr", "training_load"):
        with pytest.raises(ValidationError):
            ActivityRecord.model_validate({**record.model_dump(), field: 100})


def test_local_manual_flow_is_idempotent_owned_and_usable_without_plan(settings, fake):
    app = create_app(settings, fake)
    body = manual_body(settings.now())
    with TestClient(app) as client:
        assert client.post("/api/activities/manual", json=body).status_code == 409
        client.put("/api/profile", json={"expected_version": 0, "profile": profile_fixture()})
        for _ in range(2):
            result = client.post("/api/activities/manual", json=body)
            assert result.status_code == 200, result.text
        rows = client.get("/api/activities/recent").json()["activities"]
        assert len(rows) == 1
        assert rows[0]["feedback"]["perceived_exertion"] == 7
        evidence, before_hash, _ = context(app.state.coach)
        assert evidence["recent_activity_summaries"][0]["feedback"]["feeling"] == "fatigued"
        assert len(client.get("/api/assistant").json()["manual_sessions"]) == 1
        future = manual_body(settings.now(), duration_min=120)
        assert client.post("/api/activities/manual", json=future).status_code == 422
        assert not settings.plan_path.exists()
        changed = {**body, "notes": "Changed synthetic feedback"}
        assert client.post("/api/activities/manual", json=changed).status_code == 200
        assert context(app.state.coach)[1] != before_hash
        assert client.delete("/api/activities/manual/garmin-private-id").status_code == 404
        assert client.delete("/api/activities/manual/" + body["request_id"]).status_code == 204
        assert client.get("/api/activities/recent").json()["activities"] == []
        assert fake.uploads == fake.schedules == 0


def test_manual_review_requires_no_garmin_calls_and_never_offers_adjustment(coach, fake):
    app = create_app(coach.settings, fake)
    with TestClient(app) as client:
        client.put("/api/profile", json={"expected_version": 0, "profile": profile_fixture()})
        saved = client.post(
            "/api/activities/manual", json=manual_body(coach.settings.now())
        ).json()["activity"]
        review = client.get("/api/review/workout").json()
        assert not review["program"]["eligible"]
        assert "dichiarata" in review["verdict"]
        assert any("Non aggiungere" in item for item in review["advice"])
        details = client.post(
            "/api/session-review/refresh", json={"activity_id": saved["activity_id"]}
        )
        assert details.status_code == 200, details.text
        assert details.json()["analysis"]["evidence_kind"] == "self_reported"
        assert details.json()["analysis"]["route"] == []
        assert details.json()["analysis"]["phases"] == []
        assert details.json()["analysis"]["coverage"]["sample_count"] == 0


def test_four_manual_easy_runs_cannot_fake_a_performance_trend(coach):
    from app.services.reviewer import review_latest_workouts
    from app.services.workout_review import last_workout_review

    now = coach.settings.now()
    rows = [
        {
            **row,
            "source": "manual",
            "evidence_kind": "self_reported",
            "feedback": {"perceived_exertion": 2},
        }
        for row in runs(now)
    ]
    plan = coach.plan()
    result = last_workout_review(
        plan, rows, now, review_latest_workouts(plan, rows, now), now.isoformat()
    )
    assert not result["program"]["eligible"]
    assert "dichiarata" in result["program"]["reason"]
