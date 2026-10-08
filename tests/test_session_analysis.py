from datetime import UTC, datetime

import pytest

from app.models import Plan
from app.services.session_analysis import analyze_session, timestamp


def fixture_plan():
    return Plan.model_validate({"plan_name": "Synthetic", "workouts": [{"id": "quality", "date": "2026-10-06", "name": "Threshold", "sport": "running", "quality": True,
        "estimated_duration_min": 25, "steps": [{"type": "warmup", "duration_min": 5}, {"type": "repeat", "iterations": 2, "steps": [
            {"type": "interval", "duration_min": 5, "target": {"type": "pace", "fast": "5:00", "slow": "5:10"}},
            {"type": "recovery", "duration_min": 1}]}, {"type": "cooldown", "duration_min": 5}]}]})


def lap(index, duration, distance, kind, number, hr=150):
    return {"wktStepIndex": index, "duration": duration, "elapsedDuration": duration, "distance": distance,
            "intensityType": kind, "lapIndex": number, "averageHR": hr, "strideLength": 120, "averageRunCadence": 170}


def test_auto_laps_group_into_repeats_with_their_actual_targets():
    rows = [lap(0, 300, 800, "WARMUP", 1), lap(1, 150, 600, "ACTIVE", 2), lap(1, 150, 600, "ACTIVE", 3),
            lap(2, 60, 100, "RECOVERY", 4), lap(1, 300, 1000, "ACTIVE", 5), lap(2, 60, 100, "RECOVERY", 6), lap(4, 300, 700, "COOLDOWN", 7)]
    result = analyze_session({"activity_id": "synthetic"}, {"splits": {"lapDTOs": rows}}, fixture_plan().workouts[0])
    assert len(result["phases"]) == 6
    assert result["phases"][1]["lap_numbers"] == [2, 3]
    assert result["phases"][1]["verdict"] == "troppo veloce"
    assert result["phases"][3]["verdict"] == "in target"
    assert result["missing_phases"] == []


def test_unrecorded_intervals_are_not_assumed_completed_from_the_title():
    result = analyze_session({"activity_id": "synthetic"}, {"splits": {"lapDTOs": [lap(0, 300, 800, "WARMUP", 1)]}}, fixture_plan().workouts[0])
    assert result["missing_phases"].count("Lavoro") == 2
    assert any("non registrate" in issue for issue in result["issues"])
    assert result["positive"]


def test_descriptor_units_and_full_cadence_are_preserved():
    raw = {"summary": {"summaryDTO": {"strideLength": 123, "averageRunCadence": 170}}, "details": {
        "metricDescriptors": [{"key": key, "metricsIndex": index} for index, key in enumerate(["sumElapsedDuration", "sumDistance", "directRunCadence", "directDoubleCadence", "directStrideLength", "directSpeed", "directHeartRate"])],
        "activityDetailMetrics": [{"metrics": [10, 30, 85, 171, 123, 3, 140]}]}}
    result = analyze_session({"activity_id": "synthetic"}, raw)
    assert result["series"][0]["cadence_spm"] == 171
    assert result["series"][0]["stride_m"] == pytest.approx(1.23)
    assert result["dynamics"]["stride_m"] == pytest.approx(1.23)
    assert result["series"][0]["pace_s_km"] == pytest.approx(1000 / 3)


def test_timestamp_preserves_an_existing_timezone():
    assert timestamp("2026-10-06T18:00:00+02:00") == datetime(2026, 10, 6, 16, tzinfo=UTC).timestamp()
