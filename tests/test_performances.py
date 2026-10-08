from fastapi.testclient import TestClient

from app.main import create_app
from app.services.performances import (
    fastest_recorded_effort,
    recorded_points,
    recorded_segments,
)


def sample_detail():
    return {
        "metricDescriptors": [
            {"key": "sumDistance", "metricsIndex": 0},
            {"key": "sumElapsedDuration", "metricsIndex": 1},
        ],
        "activityDetailMetrics": [
            {"metrics": [d, t]}
            for d, t in [(0, 0), (400, 100), (800, 210), (1000, 300), (1500, 440), (2000, 600)]
        ],
        "measurementCount": 6,
    }


def test_best_effort_uses_distance_and_elapsed_not_whole_activity():
    points = recorded_points(sample_detail())
    assert fastest_recorded_effort(points, 400) == 100
    assert fastest_recorded_effort(points, 800) == 210
    assert fastest_recorded_effort(points, 1000) == 300
    assert fastest_recorded_effort(points, 5000) is None


def test_fastest_window_checks_finish_breakpoints():
    # The minimum starts at 500 m inside a segment, and ends at the 1500 m vertex.
    points = [(0, 0), (800, 160), (1500, 230), (2000, 450)]
    assert fastest_recorded_effort(points, 1000) == 130


def test_pause_inside_effort_counts_but_pause_before_start_does_not():
    points = [(0, 0), (400, 100), (400, 200), (800, 300)]
    assert fastest_recorded_effort(points, 400) == 100
    assert fastest_recorded_effort(points, 800) == 300


def test_broken_or_impossible_samples_do_not_make_false_pb():
    detail = sample_detail()
    detail["activityDetailMetrics"][2]["metrics"] = [200, 210]
    assert recorded_points(detail) == []


def test_broken_sample_splits_trace_instead_of_discarding_valid_sections():
    detail = sample_detail()
    detail["activityDetailMetrics"] = [
        {"metrics": [d, t]}
        for d, t in [(0, 0), (400, 100), (800, 200), (2000, 201), (2400, 301), (2800, 401)]
    ]
    groups = recorded_segments(detail)
    assert len(groups) == 2
    assert min(fastest_recorded_effort(g, 800) for g in groups) == 200
    assert all(fastest_recorded_effort(g, 1000) is None for g in groups)
    detail = sample_detail()
    detail["activityDetailMetrics"][1]["metrics"] = [400, 1]
    assert min(fastest_recorded_effort(group, 400) for group in recorded_segments(detail)) >= 100


def test_history_records_provenance_and_cache(coach, fake):
    fake.activity_data = [
        {
            "activityId": 10,
            "activityName": "Running",
            "startTimeGMT": "2026-09-27 08:00:00",
            "activityType": {"typeKey": "running"},
            "distance": 2000,
            "duration": 600,
            "fastestSplit_1000": 295,
        }
    ]
    calls = []

    def details(aid, **kwargs):
        calls.append(aid)
        return sample_detail()

    fake.get_activity_details = details
    result = coach.refresh_performances()
    rows = {r["distance_key"]: r for r in result["rows"]}
    assert rows["1k"]["duration_s"] == 295
    assert rows["400m"]["duration_s"] == 100
    assert rows["400m"]["source"].startswith("Campioni Garmin")
    assert rows["marathon"]["available"] is False
    assert rows["1k"]["date"] == "2026-09-27"
    assert result["coverage"]["history_complete"]
    coach.refresh_performances()
    assert calls == ["10"]
    assert rows["1k"]["garmin_url"] == "https://connect.garmin.com/modern/activity/10"
    assert (coach.settings.data_dir / "best_performances.json").exists()


def test_performance_routes_use_only_garmin(coach, fake):
    # An old cache may contain links: the API never returns external associations.
    coach.db.set("strava_links", {"10": "https://www.strava.com/activities/123"})
    app = create_app(coach.settings, fake)
    with TestClient(app) as client:
        page = client.get("/performances")
        assert page.status_code == 200 and "Strava" not in page.text
        data = client.get("/api/performances").json()
        assert len(data["rows"]) == 16
        assert all("strava_url" not in row for row in data["rows"])
        assert client.post("/api/performances/refresh").status_code == 200
        assert not any("strava" in path for path in client.get("/openapi.json").json()["paths"])
        assert client.get("/api/strava/status").status_code == 404
        assert client.post("/api/strava/authorize").status_code == 404
        assert client.put("/api/performances/strava-link", json={}).status_code == 404
