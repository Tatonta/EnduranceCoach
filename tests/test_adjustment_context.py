from copy import deepcopy
from datetime import timedelta

import pytest
from test_workout_advice import evaluate, runs

from app.errors import CoachError
from app.services.adjustment_context import contextualize_adjustment
from app.services.planner import canonical_hash


def test_detail_intensity_or_staleness_hides_proposal_without_faking_another_trend(plan, settings):
    now = settings.now().replace(day=5)
    activity = runs(now)
    base = evaluate(plan, activity, now)
    assert base["program"]["eligible"]
    for evidence in [
        {"status": "stale"},
        {"status": "unverified"},
        {
            "status": "ready",
            "version": 1,
            "analysis": {
                "comparison_blockers": [
                    {"code": "HR_REFERENCE_EXCEEDED", "note": "FC sopra il riferimento configurato"}
                ]
            },
        },
    ]:
        result = contextualize_adjustment(base, {"3": evidence}, activity, now)
        assert not result["program"]["eligible"]
        assert result["program"]["direction"] == "improving"
        assert result["program"]["context_reasons"]
        assert base["program"]["eligible"]


def test_missing_detail_keeps_existing_average_policy_and_version_changes_invalidate_hash(
    plan, settings
):
    now = settings.now().replace(day=5)
    activity = runs(now)
    base = evaluate(plan, activity, now)
    none = contextualize_adjustment(base, {}, activity, now)
    assert none["program"]["eligible"]
    first = {"3": {"status": "ready", "version": 1, "analysis": {"comparison_blockers": []}}}
    second = deepcopy(first)
    second["3"]["version"] = 2
    assert (
        contextualize_adjustment(base, first, activity, now)["evidence_hash"]
        != contextualize_adjustment(base, second, activity, now)["evidence_hash"]
    )


def test_recent_declared_discomfort_or_severe_fatigue_requires_context_before_adjustment(
    plan, settings
):
    now = settings.now().replace(day=5)
    activity = runs(now)
    for feedback in [{"discomfort": "present"}, {"feeling": "very_fatigued"}]:
        manual = {
            "activity_id": "manual-context",
            "source": "manual",
            "start_time": (now - timedelta(hours=30)).isoformat(),
            "feedback": feedback,
        }
        base = evaluate(plan, activity, now)
        result = contextualize_adjustment(base, {}, [manual, *activity], now)
        assert not result["program"]["eligible"]
        assert result["program"]["recent_feedback_checks"][0]["activity_id"] == "manual-context"
        manual["start_time"] = (now - timedelta(days=5)).isoformat()
        assert contextualize_adjustment(base, {}, [manual, *activity], now)["program"]["eligible"]


def test_local_preview_cannot_apply_after_new_detail_context(coach):
    now = coach.settings.now().replace(day=5)
    coach.settings.now = lambda: now
    rows = runs(now)
    coach.db.save_activities(rows)
    coach.db.set("last_refresh", now.isoformat())
    preview = coach.preview_adjustment()
    raw = {
        "splits": {
            "lapDTOs": [
                {
                    "lapIndex": 1,
                    "duration": 2400,
                    "elapsedDuration": 2400,
                    "distance": rows[-1]["distance_m"],
                    "intensityType": "ACTIVE",
                    "averageHR": 140,
                }
            ]
        }
    }
    coach.db.set(
        "workout_detail:3",
        {
            "raw": raw,
            "activity_hash": canonical_hash(rows[-1]),
            "fetched_at": now.isoformat(),
            "errors": [],
        },
    )
    with pytest.raises(CoachError):
        coach.apply_adjustment(preview["preview_id"], True)
