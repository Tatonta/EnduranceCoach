import json
from copy import deepcopy
from datetime import timedelta

import pytest
from test_intake import profile_fixture
from test_workout_advice import runs

from app.coaching_context import build_coaching_context
from app.errors import CoachError
from app.training_profile import TrainingProfile


def test_context_is_bounded_and_keeps_observed_detail_without_location_or_legacy_secrets(
    plan, settings
):
    now = settings.now().replace(day=5)
    profile = TrainingProfile.model_validate(profile_fixture())
    plan.athlete = {"password": "synthetic-private-marker", "lat": 45.123456}
    activities = runs(now)
    activities[-1]["route"] = [{"lat": 45.123456, "lon": 9.987654}]
    details = {
        "3": {
            "status": "ready",
            "version": 1,
            "analysis": {
                "verdict": "Seduta da correggere",
                "issues": ["FC alta nel secondo lap"],
                "route": [{"lat": 45.123456, "lon": 9.987654}],
                "route_segments": [[{"lat": 45.123456, "lon": 9.987654}]],
                "series": [
                    {"elapsed_s": i * 10, "hr": 140, "lat": 45.123456, "lon": 9.987654}
                    for i in range(500)
                ],
                "phases": [{"number": 1, "name": "Corsa", "duration_s": 2400}],
                "laps": [{"lap": 1, "avg_hr": 160, "stride_m": 1.2}],
                "access_token": "synthetic-private-marker",
            },
        }
    }
    prepared = build_coaching_context(profile, 1, plan, 1, activities, details, now)
    encoded = json.dumps(prepared)
    assert "synthetic-private-marker" not in encoded
    assert "45.123456" not in encoded and "9.987654" not in encoded
    evidence = prepared["context"]["recent_session_evidence"][0]
    assert evidence["analysis"]["laps"][0]["avg_hr"] == 160
    assert evidence["analysis"]["laps"][0]["stride_m"] == 1.2
    assert evidence["context_coverage"]["series"] == {
        "available": 500,
        "included": 120,
        "representative_sample": True,
    }
    assert evidence["analysis"]["series"][0]["elapsed_s"] == 0
    assert evidence["analysis"]["series"][-1]["elapsed_s"] == 4990
    updated = deepcopy(details)
    updated["3"]["version"] = 2
    assert (
        build_coaching_context(profile, 1, plan, 1, activities, updated, now)["context_hash"]
        != prepared["context_hash"]
    )
    assert (
        build_coaching_context(
            profile, 1, plan, 1, activities, details, now + timedelta(minutes=1)
        )["context_hash"]
        == prepared["context_hash"]
    )


def test_context_reports_history_coverage_and_excludes_unfinished_sessions(plan, settings):
    now = settings.now().replace(day=5)
    profile = TrainingProfile.model_validate(profile_fixture())
    activities = []
    for index in range(25):
        row = deepcopy(runs(now)[0])
        start = now - timedelta(days=index + 1)
        row.update(
            activity_id=str(index), start_time=start.isoformat(), date=start.date().isoformat()
        )
        activities.append(row)
    unfinished = {**activities[0], "activity_id": "ongoing", "start_time": now.isoformat()}
    prepared = build_coaching_context(profile, 1, None, 0, [unfinished, *activities], {}, now)
    assert prepared["context"]["current_plan"] is None
    assert prepared["context"]["context_coverage"]["history_truncated"]
    assert prepared["context"]["context_coverage"]["history_available"] == 25
    assert len(prepared["context"]["recent_activity_summaries"]) == 20
    assert "ongoing" not in json.dumps(prepared)


def test_oversized_context_is_refused_without_silent_cutting(plan, settings):
    now = settings.now().replace(day=5)
    plan.notes = ["synthetic text " * 30000]
    with pytest.raises(CoachError) as error:
        build_coaching_context(profile_fixture(), 1, plan, 1, [], {}, now)
    assert error.value.code == "context_too_large"
