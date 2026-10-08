import copy
import json
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.training_profile import TrainingProfile


def profile_fixture():
    path = Path(__file__).resolve().parents[1] / "ios/AdaptiveCoachTests/Fixtures/profile.json"
    return json.loads(path.read_text(encoding="utf-8"))["profile"]


@pytest.mark.parametrize(
    "change",
    [
        {"coaching_consent": False},
        {"goal_description": "          "},
        {"weight_kg": float("nan")},
        {"availability": [{"weekday": 0, "minutes": 45}] * 2},
        {"availability": []},
        {"deadline_flexible": False, "target_date": None},
        {"device_vendor": "none", "device_model": "invented"},
        {"athlete_id": "someone-else"},
    ],
)
def test_profile_rejects_ambiguous_or_invalid_answers(change):
    with pytest.raises(ValidationError):
        TrainingProfile.model_validate({**profile_fixture(), **change})


def test_first_visit_works_without_a_plan_or_watch(settings, fake):
    app = create_app(settings, fake)
    with TestClient(app) as client:
        assert client.get("/", follow_redirects=False).headers["location"] == "/onboarding"
        assert client.get("/api/profile").json()["onboarding_required"]
        assert client.post("/api/chatgpt/connect", json={}).status_code == 409
        saved = client.put(
            "/api/profile", json={"expected_version": 0, "profile": profile_fixture()}
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["brief"]["device_feedback"] == "subjective"
        assert client.get("/", follow_redirects=False).headers["location"] == "/coach"
        assert "Il tuo prossimo passo" in client.get("/coach").text
        assert not settings.plan_path.exists()
        assert fake.uploads == fake.schedules == 0
        stale = client.put(
            "/api/profile", json={"expected_version": 0, "profile": profile_fixture()}
        )
        assert stale.status_code == 409
        bad = {
            **profile_fixture(),
            "constraints": "synthetic private limitation",
            "availability": [],
        }
        response = client.put("/api/profile", json={"expected_version": 1, "profile": bad})
        assert response.status_code == 422 and "synthetic private limitation" not in response.text


def test_profile_does_not_rewrite_an_existing_program(coach, fake):
    original = coach.settings.plan_path.read_bytes()
    with TestClient(create_app(coach.settings, fake)) as client:
        assert (
            client.put(
                "/api/profile", json={"expected_version": 0, "profile": profile_fixture()}
            ).status_code
            == 200
        )
    assert coach.settings.plan_path.read_bytes() == original
    assert fake.uploads == fake.schedules == 0


def test_assistant_context_uses_intake_instead_of_arbitrary_legacy_metadata(coach, fake):
    from app.api.assistant import context

    plan = coach.plan()
    plan.athlete["unrelated_private_metadata"] = "synthetic-only-value"
    coach.replace_plan(plan)
    app = create_app(coach.settings, fake)
    with TestClient(app) as client:
        client.put("/api/profile", json={"expected_version": 0, "profile": profile_fixture()})
        evidence, _, _ = context(app.state.coach)
        assert "athlete" not in evidence["current_plan"]
        assert "synthetic-only-value" not in json.dumps(evidence)
        assert evidence["training_profile"]["goal_type"] == "event"


def test_ai_dialogue_uses_intake_and_bounded_account_owned_memory(settings, fake, monkeypatch):
    app = create_app(settings, fake)
    coach = app.state.coach
    calls = []
    active = "synthetic-profile"
    monkeypatch.setattr(coach.chatgpt, "status", lambda: {"active": active, "profiles": []})

    def respond(context, model, instructions):
        calls.append(copy.deepcopy(context))
        assert "Non interpretare l'assenza" in instructions
        return {
            "text": "Consiglio sintetico",
            "model": model,
            "profile": active,
            "generated_at": 1000,
        }

    monkeypatch.setattr(coach.chatgpt, "respond", respond)
    with TestClient(app) as client:
        client.put("/api/profile", json={"expected_version": 0, "profile": profile_fixture()})
        body = {
            "model": "synthetic-model",
            "question": "Come organizziamo la settimana?",
            "expected_profile_version": 1,
        }
        for _ in range(8):
            assert client.post("/api/assistant/message", json=body).status_code == 200
        assert calls[0]["training_profile"]["device_vendor"] == "none"
        assert len(calls[-1]["recent_conversation"]) == 6
        assert "route" not in calls[-1] and "access_token" not in str(calls[-1])
        active = "other-synthetic-profile"
        assert client.get("/api/assistant").json()["conversation"] == []
        assert client.post("/api/assistant/message", json=body).status_code == 200
        assert calls[-1]["recent_conversation"] == []
        changed = {
            **profile_fixture(),
            "goal_description": "Migliorare la continuità degli allenamenti.",
        }
        client.put("/api/profile", json={"expected_version": 1, "profile": changed})
        assert client.post("/api/assistant/message", json=body).status_code == 409
        assert len(calls) == 9


def test_initial_ai_draft_needs_confirmation_and_stale_context_cannot_apply(
    settings, fake, monkeypatch
):
    app = create_app(settings, fake)
    coach = app.state.coach
    profile = profile_fixture()
    day = settings.now().date() + timedelta(days=1)
    profile["availability"] = [{"weekday": day.weekday(), "minutes": 45}]
    plan = {
        "plan_name": "Synthetic initial plan",
        "workouts": [
            {
                "id": "initial-1",
                "date": day.isoformat(),
                "name": "Facile",
                "sport": "running",
                "estimated_duration_min": 30,
                "steps": [{"type": "run", "duration_min": 30}],
            }
        ],
    }
    monkeypatch.setattr(
        coach.chatgpt, "status", lambda: {"active": "synthetic-profile", "profiles": []}
    )
    monkeypatch.setattr(
        coach.chatgpt,
        "respond",
        lambda *args: {
            "text": json.dumps({"explanation": "Bozza sintetica", "plan": plan}),
            "model": "synthetic",
            "profile": "synthetic-profile",
            "generated_at": 1,
        },
    )
    with TestClient(app) as client:
        client.put("/api/profile", json={"expected_version": 0, "profile": profile})
        body = {
            "model": "synthetic",
            "question": "Prepara una bozza iniziale.",
            "expected_profile_version": 1,
            "purpose": "initial_plan",
        }
        reply = client.post("/api/assistant/message", json=body)
        assert reply.status_code == 200, reply.text
        draft = reply.json()["draft"]
        assert not settings.plan_path.exists()
        accept = {"draft_id": draft["draft_id"], "confirmed": False}
        assert client.post("/api/assistant/plan/apply", json=accept).status_code == 409
        client.put("/api/profile", json={"expected_version": 1, "profile": profile})
        assert (
            client.post("/api/assistant/plan/apply", json={**accept, "confirmed": True}).status_code
            == 409
        )
        assert not settings.plan_path.exists()
        body["expected_profile_version"] = 2
        second = client.post("/api/assistant/message", json=body).json()["draft"]
        assert (
            client.post(
                "/api/assistant/plan/apply",
                json={"draft_id": second["draft_id"], "confirmed": True},
            ).status_code
            == 200
        )
        assert settings.plan_path.exists()
        assert client.post("/api/assistant/message", json=body).json()["code"] == "plan_exists"
        assert fake.uploads == fake.schedules == 0


def test_invalid_ai_program_never_becomes_a_draft(settings, fake, monkeypatch):
    app = create_app(settings, fake)
    coach = app.state.coach
    day = settings.now().date() + timedelta(days=1)
    plan = {
        "plan_name": "Too long",
        "workouts": [
            {
                "date": day.isoformat(),
                "name": "Long",
                "sport": "running",
                "estimated_duration_min": 200,
                "steps": [{"type": "run", "duration_min": 200}],
            }
        ],
    }
    monkeypatch.setattr(coach.chatgpt, "status", lambda: {"active": "synthetic", "profiles": []})
    monkeypatch.setattr(
        coach.chatgpt,
        "respond",
        lambda *args: {
            "text": json.dumps({"explanation": "Invalid", "plan": plan}),
            "profile": "synthetic",
            "model": "synthetic",
            "generated_at": 1,
        },
    )
    with TestClient(app) as client:
        client.put("/api/profile", json={"expected_version": 0, "profile": profile_fixture()})
        result = client.post(
            "/api/assistant/message",
            json={
                "model": "synthetic",
                "question": "Crea il programma.",
                "purpose": "initial_plan",
                "expected_profile_version": 1,
            },
        )
        assert result.status_code == 422
        assert coach.db.get("assistant_draft") is None
        assert not settings.plan_path.exists()
