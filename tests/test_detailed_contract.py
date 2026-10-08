import copy

import pytest
from pydantic import ValidationError
from test_session_analysis import fixture_plan, lap

from app.garmin.session_details import normalize_garmin_details, route_segments
from app.integrations.session_details import SessionDetails, analyze_canonical
from app.services.session_analysis import analyze_session


def detail_fixture():
    return {
        "plan_version": 1,
        "plan_workout_id": "quality",
        "laps": [
            {
                "lap": 1,
                "phase_type": "warmup",
                "step_index": 0,
                "start_elapsed_s": 0,
                "duration_s": 300,
                "elapsed_s": 300,
                "distance_m": 800,
                "avg_hr": 120,
            },
            {
                "lap": 2,
                "phase_type": "interval",
                "step_index": 1,
                "start_elapsed_s": 300,
                "duration_s": 300,
                "elapsed_s": 300,
                "distance_m": 1200,
                "avg_hr": 170,
            },
            {
                "lap": 3,
                "phase_type": "recovery",
                "step_index": 2,
                "start_elapsed_s": 600,
                "duration_s": 60,
                "elapsed_s": 60,
                "distance_m": 100,
                "avg_hr": 150,
            },
            {
                "lap": 4,
                "phase_type": "interval",
                "step_index": 1,
                "start_elapsed_s": 660,
                "duration_s": 300,
                "elapsed_s": 300,
                "distance_m": 1000,
                "avg_hr": 175,
            },
            {
                "lap": 5,
                "phase_type": "recovery",
                "step_index": 2,
                "start_elapsed_s": 960,
                "duration_s": 60,
                "elapsed_s": 60,
                "distance_m": 100,
                "avg_hr": 153,
            },
            {
                "lap": 6,
                "phase_type": "cooldown",
                "step_index": 3,
                "start_elapsed_s": 1020,
                "duration_s": 300,
                "elapsed_s": 300,
                "distance_m": 700,
                "avg_hr": 125,
            },
        ],
        "samples": [
            {"elapsed_s": 10, "distance_m": 30, "speed_m_s": 3, "hr": 130, "segment": 0},
            {"elapsed_s": 20, "distance_m": 60, "speed_m_s": 3, "hr": 132, "segment": 0},
        ],
        "route_segments": [[{"lat": 45, "lon": 9}, {"lat": 45.001, "lon": 9.001}]],
        "dynamics": {
            "cadence_spm": 170,
            "stride_m": 1.23,
            "ground_contact_s": 0.279,
            "vertical_oscillation_m": 0.0849,
        },
        "reported_sample_count": 1320,
        "coverage_note": "Synthetic evidence",
    }


def test_canonical_and_garmin_phases_use_the_same_targets_and_units():
    workout = fixture_plan().workouts[0]
    activity = {"activity_id": "synthetic", "source": "coros", "sport": "running"}
    canonical = analyze_canonical(
        activity, SessionDetails.model_validate(detail_fixture()), workout
    )
    raw = {
        "splits": {
            "lapDTOs": [
                lap(0, 300, 800, "WARMUP", 1, 120),
                lap(1, 300, 1200, "ACTIVE", 2, 170),
                lap(2, 60, 100, "RECOVERY", 3, 150),
                lap(1, 300, 1000, "ACTIVE", 4, 175),
                lap(2, 60, 100, "RECOVERY", 5, 153),
                lap(4, 300, 700, "COOLDOWN", 6, 125),
            ]
        },
        "summary": {
            "summaryDTO": {
                "strideLength": 123,
                "groundContactTime": 279,
                "verticalOscillation": 8.49,
            }
        },
    }
    garmin = analyze_session(activity, raw, workout)
    assert [row["verdict"] for row in canonical["phases"]] == [
        row["verdict"] for row in garmin["phases"]
    ]
    assert canonical["phases"][1]["verdict"] == "troppo veloce"
    assert canonical["phases"][3]["verdict"] == "in target"
    assert canonical["dynamics"]["stride_m"] == pytest.approx(garmin["dynamics"]["stride_m"])
    assert canonical["dynamics"]["gct_ms"] == pytest.approx(279)
    normalized = normalize_garmin_details(activity, raw, workout, plan_version=1)
    assert normalized.laps[-1].step_index == 3
    assert normalized.dynamics.ground_contact_s == pytest.approx(0.279)
    assert analyze_canonical(activity, normalized, workout)["missing_phases"] == []


@pytest.mark.parametrize(
    "kind",
    [
        "no_plan_link",
        "overlap",
        "decreasing_time",
        "bad_stride_units",
        "wrong_coverage",
        "nonfinite_gps",
    ],
)
def test_detail_boundary_rejects_inconsistent_evidence(kind):
    body = copy.deepcopy(detail_fixture())
    if kind == "no_plan_link":
        body["plan_version"] = None
        body["plan_workout_id"] = None
    if kind == "overlap":
        body["laps"][1]["start_elapsed_s"] = 200
    if kind == "decreasing_time":
        body["samples"][1]["elapsed_s"] = 5
    if kind == "bad_stride_units":
        body["dynamics"]["stride_m"] = 123
    if kind == "wrong_coverage":
        body["reported_sample_count"] = 1
    if kind == "nonfinite_gps":
        body["route_segments"][0][0]["lat"] = float("nan")
    with pytest.raises(ValidationError):
        SessionDetails.model_validate(body)


def test_gps_holes_remain_separate_segments():
    raw = {
        "details": {
            "metricDescriptors": [
                {"key": "directLatitude", "metricsIndex": 0},
                {"key": "directLongitude", "metricsIndex": 1},
            ],
            "activityDetailMetrics": [
                {"metrics": row}
                for row in [[45, 9], [45.001, 9.001], [None, None], [45.01, 9.01], [45.011, 9.011]]
            ],
        }
    }
    segments = route_segments(raw)
    assert len(segments) == 2 and all(len(segment) == 2 for segment in segments)


def test_unknown_distance_preserves_hr_without_inventing_pace():
    body = {
        "laps": [
            {"lap": 1, "start_elapsed_s": 0, "duration_s": 300, "elapsed_s": 300, "avg_hr": 140}
        ],
        "samples": [{"elapsed_s": 10, "hr": 140}],
    }
    result = analyze_canonical(
        {"activity_id": "synthetic", "source": "apple_health", "sport": "running"},
        SessionDetails.model_validate(body),
    )
    assert result["laps"][0]["pace_s_km"] is None
    assert result["phases"][0]["distance_m"] is None
    assert result["series"][0]["hr"] == 140


def test_partial_zone_boundaries_do_not_invent_a_zone_classification():
    body = {
        "laps": [
            {"lap": 1, "start_elapsed_s": 0, "duration_s": 300, "elapsed_s": 300, "avg_hr": 120}
        ],
        "hr_zones": [{"zone": 2, "low_bpm": 113}],
    }
    activity = {"activity_id": "synthetic", "source": "suunto", "sport": "running"}
    result = analyze_canonical(activity, SessionDetails.model_validate(body))
    assert result["laps"][0]["hr_zone"] is None
    body["hr_zones"][0]["high_bpm"] = 131
    assert (
        analyze_canonical(activity, SessionDetails.model_validate(body))["laps"][0]["hr_zone"] == 2
    )
