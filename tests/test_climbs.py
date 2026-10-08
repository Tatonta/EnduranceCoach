import copy
import json
import math
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.climb_catalog import load_catalog
from app.services.climbs import TraceIndex, catalog_attempts, cycling_traces, haversine
from app.services.geography import Geography, inside_polygon


def ride_detail(time_factor=1):
    points = []
    for d in range(0, 2001, 25):
        z = 100 + max(0, min(d - 200, 1000)) / 10
        points.append([d, d / 5 * time_factor, z, 45 + d / 111195, 9])
    keys = [
        "sumDistance",
        "sumElapsedDuration",
        "directElevation",
        "directLatitude",
        "directLongitude",
    ]
    return {
        "metricDescriptors": [{"key": k, "metricsIndex": i} for i, k in enumerate(keys)],
        "activityDetailMetrics": [{"metrics": p} for p in points],
    }


def reference():
    trace = cycling_traces(ride_detail())[0]
    return {
        "id": "cf-1",
        "name": "Passo di prova da Valle",
        "source_url": "https://climbfinder.com/it/salite/prova",
        "distance_m": 1000,
        "gain_m": 100,
        "summit_m": 200,
        "path": [p[3:5] for p in trace if 200 <= p[0] <= 1200],
    }


def write_catalog(settings, rows=None):
    path = settings.data_dir / "climbfinder-catalog.json"
    path.write_text(
        json.dumps(
            {
                "source": "Climbfinder",
                "regions": ["Lombardia"],
                "rows": rows if rows is not None else [reference()],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_full_catalog_route_has_exact_boundaries_and_direction():
    trace = cycling_traces(ride_detail())[0]
    matches = catalog_attempts(reference(), TraceIndex(trace))
    assert len(matches) == 1
    assert matches[0]["duration_s"] == pytest.approx(200, abs=0.01)
    assert matches[0]["start_elapsed_s"] == pytest.approx(40, abs=0.01)
    assert matches[0]["end_elapsed_s"] == pytest.approx(240, abs=0.01)
    assert matches[0]["distance_m"] == pytest.approx(1000, abs=0.01)
    assert matches[0]["avg_speed_kmh"] == pytest.approx(18, abs=0.01)
    assert catalog_attempts(reference(), TraceIndex(trace[25:])) == []  # Partial ascent.
    reverse = copy.deepcopy(reference())
    reverse["path"].reverse()
    assert catalog_attempts(reverse, TraceIndex(trace)) == []
    flat = [p[:2] + [100] + p[3:] for p in trace]
    assert catalog_attempts(reference(), TraceIndex(flat)) == []


def test_repeat_time_includes_long_stop():
    trace = cycling_traces(ride_detail(0.8))[0]
    point = trace[30][:]
    stopped = (
        trace[:31]
        + [[point[0], point[1] + 90, *point[2:]]]
        + [[p[0], p[1] + 90, *p[2:]] for p in trace[31:]]
    )
    matches = catalog_attempts(reference(), TraceIndex(stopped))
    assert len(matches) == 1
    assert matches[0]["duration_s"] == pytest.approx(250, abs=0.01)
    assert matches[0]["avg_speed_kmh"] == pytest.approx(14.4, abs=0.01)


def test_parallel_road_and_wrong_middle_are_not_matched():
    trace = cycling_traces(ride_detail())[0]
    parallel = [p[:4] + [p[4] + 0.001] for p in trace]
    assert catalog_attempts(reference(), TraceIndex(parallel)) == []
    other = [p[:4] + [p[4] + (0.002 if 500 < p[0] < 1000 else 0)] for p in trace]
    assert catalog_attempts(reference(), TraceIndex(other)) == []


def test_multiple_passages_in_one_ride_are_kept():
    first = cycling_traces(ride_detail())[0]
    # Ride back along the road, then climb again faster.
    back = [[2000 + 2000 - p[0], 400 + (2000 - p[0]) / 5, *p[2:]] for p in reversed(first[:-1])]
    second = [[4000 + p[0], 800 + p[1] * 0.8, *p[2:]] for p in first[1:]]
    matches = catalog_attempts(reference(), TraceIndex(first + back + second))
    assert len(matches) == 2
    assert sorted(m["duration_s"] for m in matches) == pytest.approx([160, 200], abs=0.01)


def test_large_gps_gap_cannot_be_timed_as_complete():
    trace = cycling_traces(ride_detail())[0]
    assert catalog_attempts(reference(), TraceIndex(trace[:20] + trace[40:])) == []


def test_short_gps_dropout_is_recovered_but_long_dropout_and_teleport_split():
    detail = ride_detail()
    detail["activityDetailMetrics"][30]["metrics"][3] = None
    traces = cycling_traces(detail)
    assert len(traces) == 1
    assert len(catalog_attempts(reference(), TraceIndex(traces[0]))) == 1
    detail = ride_detail()
    for row in detail["activityDetailMetrics"][25:45]:
        row["metrics"][3] = None
    traces = cycling_traces(detail)
    assert len(traces) == 2
    assert not any(catalog_attempts(reference(), TraceIndex(t)) for t in traces)
    detail = ride_detail()
    detail["activityDetailMetrics"][30]["metrics"][3] += 10
    traces = cycling_traces(detail)
    assert len(traces) >= 2
    assert not any(p[3] > 50 for trace in traces for p in trace)


def test_long_stop_with_gps_drift_keeps_elapsed_time_without_interpolating_jump():
    trace = cycling_traces(ride_detail())[0]
    p = trace[30]
    drifted = [p[0], p[1] + 1200, p[2], p[3], p[4] + 0.002]
    stopped = trace[:31] + [drifted] + [[q[0], q[1] + 1200, *q[2:]] for q in trace[31:]]
    index = TraceIndex(stopped)
    assert 30 not in {i for indices in index.grid.values() for i in indices}
    matches = catalog_attempts(reference(), index)
    assert len(matches) == 1
    assert matches[0]["duration_s"] == pytest.approx(1400, abs=0.01)


def test_length_uses_official_catalog_distance_when_geometry_is_simplified():
    trace = cycling_traces(ride_detail())[0]
    trace = [[p[0] * 1.1, *p[1:]] for p in trace]
    climb = {**reference(), "distance_m": 1100}
    matches = catalog_attempts(climb, TraceIndex(trace))
    assert len(matches) == 1
    assert matches[0]["distance_m"] == pytest.approx(1100, abs=0.01)


def test_dead_reckoned_gps_is_flagged_and_a_real_detour_is_rejected():
    trace = [[d, d / 5, 100 + d / 10, 45 + d / 111195, 9] for d in range(0, 6501, 25)]
    climb = {
        **reference(),
        "distance_m": 6000,
        "gain_m": 600,
        "path": [p[3:5] for p in trace if 200 <= p[0] <= 6200],
    }
    reconstructed = [p[:4] + [p[4] + (0.002 if 2500 <= p[0] <= 3100 else 0)] for p in trace]
    matches = catalog_attempts(climb, TraceIndex(reconstructed))
    assert len(matches) == 1
    assert matches[0]["gps_tolerance_used"]
    assert 85 <= matches[0]["gps_coverage_pct"] < 100
    detour = [
        p[:4]
        + [p[4] + (0.004 * math.sin(math.pi * (p[0] - 2300) / 1200) if 2300 < p[0] < 3500 else 0)]
        for p in trace
    ]
    assert catalog_attempts(climb, TraceIndex(detour)) == []


def test_polygon_holes_and_offline_italian_region():
    shape = SimpleNamespace(
        parts=[0, 4], points=[(0, 0), (4, 0), (4, 4), (0, 4), (1, 1), (3, 1), (3, 3), (1, 3)]
    )
    assert inside_polygon(0.5, 0.5, shape)
    assert not inside_polygon(2, 2, shape)
    assert Geography().lookup(45.695, 9.67) == {
        "country": "Italia",
        "region": "Lombardia",
        "zone": "Bergamo",
    }
    assert haversine((45, 9), (45, 9)) == 0


def test_history_keeps_catalog_name_and_best_time_and_reuses_trace_cache(coach, fake):
    write_catalog(coach.settings)
    fake.activity_data = [
        {
            "activityId": aid,
            "activityName": "Road bike",
            "startTimeGMT": f"2026-09-{day:02} 08:00:00",
            "activityType": {"typeKey": "road_biking"},
            "distance": 2000,
            "duration": 400,
        }
        for aid, day in [(10, 27), (11, 28)]
    ]
    calls = []

    def details(aid, **kwargs):
        calls.append(aid)
        return ride_detail(1 if aid == "10" else 0.8)

    fake.get_activity_details = details
    coach.climbs.geography = SimpleNamespace(
        lookup=lambda *p: {"country": "Italia", "region": "Lombardia", "zone": "Bergamo"}
    )
    result = coach.refresh_climbs()
    assert len(result["rows"]) == 1
    row = result["rows"][0]
    assert row["name"] == reference()["name"]
    assert row["attempt_count"] == 2
    assert row["best"]["activity_id"] == "11"
    assert row["best"]["avg_speed_kmh"] == pytest.approx(22.5, abs=0.01)
    assert row["attempts"][1]["avg_speed_kmh"] == pytest.approx(18, abs=0.01)
    assert row["best"]["date"] == "2026-09-28"
    assert row["best"]["garmin_url"].endswith("/11")
    assert row["path"] == reference()["path"]
    assert row["source_url"] == reference()["source_url"]
    assert row["profile"][0] == pytest.approx([0, 100], abs=0.01)
    assert row["profile"][-1] == pytest.approx([1000, 200], abs=0.01)
    coach.db.set("climb_names", {"cf-1": "Generic custom name"})
    coach.refresh_climbs()
    assert calls == ["10", "11"]
    assert coach.climbs.latest()["rows"][0]["name"] == reference()["name"]
    write_catalog(coach.settings, [])
    assert coach.refresh_climbs()["rows"] == []  # Catalog changes rematch cached rides.
    assert calls == ["10", "11"]
    assert not fake.uploads and not fake.schedules


def test_missing_catalog_excludes_generic_slopes_and_old_snapshot(coach, fake):
    coach.db.set("climbs", {"rows": [{"name": "Salita 01"}]})
    assert coach.climbs.latest()["rows"] == []
    fake.activity_data = [
        {
            "activityId": 10,
            "startTimeGMT": "2026-09-27 08:00:00",
            "activityType": {"typeKey": "cycling"},
            "duration": 100,
        }
    ]
    fake.get_activity_details = lambda *a, **k: ride_detail()
    result = coach.refresh_climbs()
    assert result["coverage"]["rides_without_catalog_match"] == 1
    assert result["rows"] == []


def test_missing_details_are_visible(coach, fake):
    write_catalog(coach.settings)
    fake.activity_data = [
        {
            "activityId": 10,
            "startTimeGMT": "2026-09-27 08:00:00",
            "activityType": {"typeKey": "cycling"},
            "duration": 100,
        }
    ]
    result = coach.refresh_climbs()
    assert result["coverage"]["details_missing"] == 1
    assert result["rows"] == []


def test_catalog_validation_rejects_external_links_and_duplicate_ids(coach):
    path = write_catalog(coach.settings)
    assert len(load_catalog(path)["rows"]) == 1
    wrong = {**reference(), "source_url": "javascript:alert(1)"}
    with pytest.raises(ValueError):
        load_catalog(write_catalog(coach.settings, [wrong]))
    with pytest.raises(ValueError):
        load_catalog(write_catalog(coach.settings, [reference(), reference()]))


def test_climb_page_and_removed_rename_endpoint(coach, fake):
    with TestClient(create_app(coach.settings, fake)) as client:
        page = client.get("/climbs")
        assert page.status_code == 200
        assert 'id="climb-map"' in page.text and "HEATMAP" in page.text
        assert "Climbfinder" in page.text and "rename-dialog" not in page.text
        assert client.get("/api/climbs").json()["rows"] == []
        assert client.post("/api/climbs/refresh").status_code == 200
        assert client.put("/api/climbs/missing/name", json={"name": "New"}).status_code == 404
        assert client.get("/static/vendor/leaflet/leaflet.js").status_code == 200
