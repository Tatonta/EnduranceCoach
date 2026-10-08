from datetime import timedelta

from fastapi.testclient import TestClient

from app.garmin.activities import normalize_activity
from app.main import create_app
from app.services.reviewer import review_latest_workouts


def activity(day="2026-10-06", sport="running", name="Threshold 3x8", seconds=3300, id="a"):
    return {
        "activity_id": id,
        "date": day,
        "start_time": day + "T09:00:00+02:00",
        "sport": sport,
        "activity_type": sport,
        "name": name,
        "duration_s": seconds,
        "distance_m": 10000,
        "avg_pace_s_km": 300,
        "avg_hr": 150,
        "max_hr": 175,
        "workout_id": "",
    }


def test_review_conservative_sport_duration_and_identity(plan, settings):
    now = settings.now().replace(day=7)
    wrong = activity(sport="cycling")
    assert review_latest_workouts(plan, [wrong], now)["matches"][2]["status"] == "missed"
    wrong = activity(name="Easy run")
    assert review_latest_workouts(plan, [wrong], now)["matches"][2]["status"] == "missed"
    short = activity(seconds=500)
    assert review_latest_workouts(plan, [short], now)["matches"][2]["status"] == "missed"
    good = activity()
    match = review_latest_workouts(plan, [good], now)["matches"][2]
    assert match["status"] == "completed" and match["interval_compliance"] == "unverified"


def test_review_ambiguous_and_modified(plan, settings):
    now = settings.now().replace(day=7)
    a, b = activity(id="a"), activity(id="b")
    assert review_latest_workouts(plan, [a, b], now)["matches"][2]["activity_id"] is None
    a["duration_s"] = 2700
    assert review_latest_workouts(plan, [a], now)["matches"][2]["status"] == "completed_modified"


def test_review_substitution_and_pending(plan, settings):
    now = settings.now().replace(day=9)
    a = activity(day="2026-10-08", name="Easy", seconds=3600)
    snapshot = review_latest_workouts(plan, [a], now)
    assert snapshot["matches"][4]["status"] == "substituted"
    assert any(f["code"] == "SUBSTITUTED_SESSION" for f in snapshot["flags"])
    assert snapshot["matches"][6]["status"] == "pending"


def test_rolling_seven_days_and_fatigue(plan, settings):
    a = activity(day="2026-10-03", sport="cycling", seconds=12000)
    old = activity(day="2026-09-26", id="old")
    snapshot = review_latest_workouts(plan, [a, old], settings.now())
    assert snapshot["training_summary"]["running_distance_7d"] == 0
    assert snapshot["training_summary"]["cycling_duration_7d"] == 12000
    assert any(f["code"] == "HIGH_FATIGUE" for f in snapshot["flags"])


def test_utc_activity_day_boundary():
    a = normalize_activity(
        {
            "activityId": 1,
            "activityName": "Run",
            "startTimeGMT": "2026-10-02 23:30:00",
            "activityType": {"typeKey": "running"},
            "duration": 3600,
            "distance": 10000,
            "averageSpeed": 3,
        }
    )
    assert a["date"] == "2026-10-03"
    assert a["avg_pace_s_km"] == 1000 / 3
    assert "ownerId" not in a


def test_strength_session_review(plan, settings):
    a = activity(day="2026-10-05", sport="strength", name="Gym", seconds=2400)
    snapshot = review_latest_workouts(plan, [a], settings.now().replace(day=6))
    assert snapshot["matches"][1]["status"] == "completed"
    assert snapshot["matches"][1]["activity_id"] == "a"


def test_vo2_falls_back_to_last_run(coach, fake):
    fake.activity_data = [
        {
            "activityId": 1,
            "activityName": "Easy",
            "startTimeGMT": "2026-10-02 07:00:00",
            "activityType": {"typeKey": "running"},
            "duration": 3000,
            "distance": 10000,
        }
    ]
    calls = []

    def metrics(day):
        calls.append(day)
        return (
            []
            if day == "2026-10-03"
            else [{"generic": {"vo2MaxValue": 42, "vo2MaxPreciseValue": 41.6}}]
        )

    fake.get_max_metrics = metrics
    coach.refresh()
    assert calls == ["2026-10-03", "2026-10-02"]
    assert coach.db.get("vo2max")["value"] == 42
    assert coach.db.get("vo2max")["measured_date"] == "2026-10-02"


def test_review_writes_snapshot_and_database(coach, fake):
    fake.activity_data = [
        {
            "activityId": 1,
            "activityName": "Bike",
            "startTimeGMT": "2026-10-03 07:00:00",
            "activityType": {"typeKey": "road_biking"},
            "duration": 12000,
            "distance": 60000,
            "averageHR": 133,
        }
    ]
    snapshot = coach.review()
    assert (coach.settings.data_dir / "review_snapshot.json").exists()
    assert coach.db.get("latest_review")["generated_at"] == snapshot["generated_at"]
    assert len(coach.db.activities()) == 1
    assert coach.db.get("next_review").startswith("2026-10-05")


def test_api_health_dashboard_plan_and_guards(coach, fake):
    app = create_app(coach.settings, fake)
    with TestClient(app) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        assert "Partiamo da te" in client.get("/").text
        assert "GARMIN ADAPTIVE COACH" in client.get("/dashboard").text
        assert client.get("/static/dashboard.js").status_code == 200
        assert len(client.get("/api/plan").json()["workouts"]) == 22
        assert client.post("/api/plan/sync", json={"confirmed": True}).status_code == 409
        assert (
            client.post(
                "/api/calendar/cleanup/apply", json={"preview_id": "no", "confirmed": False}
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/activities/refresh", headers={"Origin": "https://example.com"}
            ).status_code
            == 403
        )
        assert client.get("/api/health", headers={"Host": "evil.test"}).status_code == 400
        assert client.post("/api/review/run").status_code == 200
        assert client.get("/api/review/latest").status_code == 200
        assert client.get("/api/dashboard/summary").status_code == 200
        p = client.post("/api/calendar/cleanup/preview").json()
        assert (
            client.post(
                "/api/calendar/cleanup/apply",
                json={"preview_id": p["preview_id"], "confirmed": True},
            ).json()["status"]
            == "applied"
        )


def test_scheduler_two_days_and_restart_persistence(coach):
    coach.settings.scheduler_enabled = True
    coach.start()
    job = coach.scheduler.get_job("review")
    assert job.trigger.interval == timedelta(days=2)
    next_review = coach.db.get("next_review")
    coach.stop()
    coach.start()
    assert coach.db.get("next_review") == next_review
    coach.stop()
