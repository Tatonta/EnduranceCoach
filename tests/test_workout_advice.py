from copy import deepcopy
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.integrations.activities import ActivityRecord
from app.main import create_app
from app.services.coach import Coach
from app.services.planner import canonical_hash
from app.services.reviewer import match_score, review_latest_workouts
from app.services.workout_review import adjusted_plan, last_workout_review


def runs(now, paces=(360, 350, 340, 330)):
    result = []
    for i, pace in enumerate(paces):
        stamp = now - timedelta(days=10 - 3 * i)
        result.append(
            {
                "activity_id": str(i),
                "source": "garmin",
                "source_activity_id": str(i),
                "name": "Easy run",
                "sport": "running",
                "activity_type": "running",
                "start_time": stamp.isoformat(),
                "date": stamp.date().isoformat(),
                "distance_m": 2400 / pace * 1000,
                "duration_s": 2400,
                "elapsed_duration_s": 2400,
                "avg_pace_s_km": pace,
                "avg_hr": 140,
                "max_hr": 155,
                "elevation_gain_m": 10,
                "workout_id": "",
            }
        )
    return result


def evaluate(plan, activities, now, refreshed=True, accepted=None):
    snapshot = review_latest_workouts(
        plan, sorted(activities, key=lambda a: a["start_time"], reverse=True), now
    )
    return last_workout_review(
        plan, activities, now, snapshot, now.isoformat() if refreshed else None, accepted
    )


def test_latest_real_workout_and_no_invented_metrics(plan, settings):
    now = settings.now().replace(day=5)
    a = runs(now)
    future = deepcopy(a[-1])
    future.update(activity_id="future", start_time=(now + timedelta(days=1)).isoformat())
    review = evaluate(plan, [future, *reversed(a)], now)
    assert review["last_workout"]["activity_id"] == "3"
    assert review["advice"]
    assert evaluate(plan, [], now)["last_workout"] is None
    assert evaluate(plan, [], now)["program"]["eligible"] is False


@pytest.mark.parametrize(
    "paces,direction", [((360, 350, 340, 330), "improving"), ((330, 340, 350, 365), "declining")]
)
def test_sustained_meaningful_trend(plan, settings, paces, direction):
    now = settings.now().replace(day=5)
    result = evaluate(plan, runs(now, paces), now)["program"]
    assert result["eligible"] and result["direction"] == direction
    assert len(result["evidence"]) == 4


@pytest.mark.parametrize(
    "paces", [(360, 360, 360, 320), (360, 330, 350, 320), (360, 356, 352, 348)]
)
def test_one_off_inconsistent_or_small_change_never_prompts(plan, settings, paces):
    now = settings.now().replace(day=5)
    assert not evaluate(plan, runs(now, paces), now)["program"]["eligible"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("avg_hr", None),
        ("avg_hr", 165),
        ("elevation_gain_m", None),
        ("elevation_gain_m", 300),
        ("elapsed_duration_s", 3600),
        ("duration_s", 4800),
        ("source", "suunto"),
        ("name", "Easy intervals"),
        ("name", "Race"),
        ("sport", "cycling"),
        ("avg_pace_s_km", float("nan")),
    ],
)
def test_incomparable_or_missing_data_abstains(plan, settings, field, value):
    now = settings.now().replace(day=5)
    activities = runs(now)
    activities[-1][field] = value
    assert not evaluate(plan, activities, now)["program"]["eligible"]


def test_stale_data_sparse_history_and_accepted_evidence_abstain(plan, settings):
    now = settings.now().replace(day=5)
    a = runs(now)
    assert not evaluate(plan, a, now, refreshed=False)["program"]["eligible"]
    assert not evaluate(plan, a[:3], now)["program"]["eligible"]
    assert not evaluate(plan, a, now, accepted={"evidence_activity_ids": ["0"]})["program"][
        "eligible"
    ]
    short = runs(now)
    for i, item in enumerate(short):
        stamp = now - timedelta(days=4 - i)
        item.update(start_time=stamp.isoformat(), date=stamp.date().isoformat())
    assert not evaluate(plan, short, now)["program"]["eligible"]


def test_fatigue_blocks_progression(plan, settings):
    now = settings.now().replace(day=5)
    a = runs(now)
    a[-1]["training_load"] = 300
    assert not evaluate(plan, a, now)["program"]["eligible"]


def test_intervening_quality_is_not_compared_to_easy_run_pace(plan, settings):
    now = settings.now().replace(day=5)
    a = runs(now)
    quality = deepcopy(a[1])
    stamp = now - timedelta(days=5)
    quality.update(
        activity_id="quality",
        name="Threshold intervals",
        start_time=stamp.isoformat(),
        date=stamp.date().isoformat(),
        avg_pace_s_km=260,
    )
    assert evaluate(plan, [*a, quality], now)["program"]["eligible"]
    a[1]["avg_hr"] = None
    assert not evaluate(plan, [*a, quality], now)["program"]["eligible"]


def test_proposal_bounded_future_preserves_plan_identity_and_targets(plan, settings):
    now = settings.now().replace(day=5)
    original_hash = canonical_hash(plan)
    for direction in ("improving", "declining"):
        proposed, changes = adjusted_plan(plan, now, direction)
        assert changes
        assert canonical_hash(plan) == original_hash
        for old, new in zip(plan.workouts, proposed.workouts, strict=True):
            assert old.key == new.key and old.date == new.date
            if old.date <= now.date() or old.date > now.date() + timedelta(days=7):
                assert old == new
            if direction == "improving" and old.quality:
                assert old == new


def test_repeated_work_blocks_update_estimated_duration_with_multiplicity(plan, settings):
    now = settings.now().replace(day=5)
    proposed, changes = adjusted_plan(plan, now, "declining")
    old = next(w for w in plan.workouts if w.key == "oct-06")
    new = next(w for w in proposed.workouts if w.key == "oct-06")
    change = next(c for c in changes if c["workout_id"] == "oct-06")
    assert change["step_changes"][0]["iterations"] == 3
    assert new.estimated_duration_min == old.estimated_duration_min - 3 * 8 * 0.15


def test_date_boundary_invalidates_pending_preview(coach):
    from app.errors import CoachError

    now = coach.settings.now().replace(day=5, hour=23, minute=58)
    coach.settings.now = lambda: now
    coach.db.save_activities(runs(now))
    coach.db.set("last_refresh", now.isoformat())
    preview = coach.preview_adjustment()
    coach.settings.now = lambda: now + timedelta(minutes=3)
    with pytest.raises(CoachError, match="Preview"):
        coach.apply_adjustment(preview["preview_id"], True)


def test_quality_review_does_not_infer_interval_success(plan, settings):
    now = settings.now().replace(day=7)
    a = runs(now)[-1]
    a.update(
        date="2026-10-06",
        start_time="2026-10-06T09:00:00+02:00",
        name="Threshold 3x8",
        duration_s=3300,
        elapsed_duration_s=3300,
    )
    review = evaluate(plan, [a], now)
    assert review["match"]["interval_compliance"] == "unverified"
    assert any("lap" in advice for advice in review["advice"])


def test_api_confirmation_stale_preview_apply_backup_and_no_vendor_mutation(coach, fake):
    now = coach.settings.now().replace(day=5)
    coach.settings.now = lambda: now
    app = create_app(coach.settings, fake)
    service = app.state.coach
    service.db.save_activities(runs(now))
    service.db.set("last_refresh", now.isoformat())
    with TestClient(app) as client:
        assert client.get("/review").status_code == 200
        assert "Consigli pratici" in client.get("/review").text
        assert client.get("/static/review.js").status_code == 200
        assert client.get("/api/review/workout").json()["program"]["eligible"]
        preview = client.post("/api/review/adjustment/preview").json()
        before = canonical_hash(service.plan())
        assert (
            client.post(
                "/api/review/adjustment/apply",
                json={"preview_id": preview["preview_id"], "confirmed": False},
            ).status_code
            == 409
        )
        assert canonical_hash(service.plan()) == before
        result = client.post(
            "/api/review/adjustment/apply",
            json={"preview_id": preview["preview_id"], "confirmed": True},
        )
        assert result.status_code == 200 and result.json()["requires_sync"]
        assert canonical_hash(service.plan()) != before
        assert list((service.settings.data_dir / "backups").glob("plan-*.json"))
        assert service.db.get("test_proof") is None and service.db.get("cleanup_preview") is None
        assert not client.get("/api/review/workout").json()["program"]["eligible"]
        assert (
            client.post(
                "/api/review/adjustment/apply",
                json={"preview_id": preview["preview_id"], "confirmed": True},
            ).status_code
            == 409
        )
        assert fake.uploads == fake.schedules == 0 and fake.unscheduled == []


@pytest.mark.parametrize("mutation", ["plan", "activity", "expiry"])
def test_preview_revalidates_current_evidence(coach, mutation):
    from app.garmin.client import CoachError

    now = coach.settings.now().replace(day=5)
    coach.settings.now = lambda: now
    coach.db.save_activities(runs(now))
    coach.db.set("last_refresh", now.isoformat())
    p = coach.preview_adjustment()
    if mutation == "plan":
        plan = coach.plan()
        plan.plan_name += " revised"
        coach.replace_plan(plan)
    elif mutation == "activity":
        changed = runs(now)[-1]
        changed["avg_hr"] = 160
        coach.db.save_activities([changed])
    else:
        p["expires_at"] = (now - timedelta(seconds=1)).isoformat()
        coach.db.set("adjustment_preview", p)
    with pytest.raises(CoachError):
        coach.apply_adjustment(p["preview_id"], True)


def test_unknown_trend_cannot_generate_proposal(coach):
    from app.garmin.client import CoachError

    with pytest.raises(CoachError, match="Mantieni"):
        coach.preview_adjustment()


def test_source_contract_namespace_timezone_and_validation(coach, settings, plan, fake):
    now = settings.now()
    values = runs(now)[0]
    record = ActivityRecord.model_validate(
        {k: v for k, v in values.items() if k not in {"activity_id", "date"}}
    )
    other = record.model_copy(update={"source": "suunto"})
    assert record.payload(settings.timezone)["activity_id"] == "0"
    assert other.payload(settings.timezone)["activity_id"] == "suunto:0"
    with pytest.raises(ValidationError):
        ActivityRecord.model_validate(
            {**record.model_dump(), "start_time": now.replace(tzinfo=None)}
        )
    with pytest.raises(ValidationError):
        ActivityRecord.model_validate({**record.model_dump(), "avg_hr": float("nan")})

    class Source:
        source = "suunto"

        def fetch(self, now, earliest):
            return [other]

    service = Coach(settings, fake, activity_sources=[Source()])
    assert service.refresh()["count"] == 1
    assert service.db.activities()[0]["source"] == "suunto"
    assert service.db.get("garmin_status")["connected"] is False


def test_foreign_vendor_id_cannot_prove_garmin_workout_link(plan, settings):
    workout = next(w for w in plan.workouts if w.quality)
    a = runs(settings.now())[-1]
    a.update(
        source="suunto",
        date=workout.date.isoformat(),
        name="Unknown",
        workout_id="123",
        duration_s=workout.estimated_duration_min * 60,
    )
    assert match_score(workout, a, "123") is None


def test_vendor_zero_heart_rate_is_missing_not_invalid(coach, fake):
    fake.activity_data = [
        {
            "activityId": 1,
            "startTimeGMT": "2026-10-02 07:00:00",
            "activityType": {"typeKey": "running"},
            "duration": 2400,
            "distance": 6000,
            "averageHR": 0,
            "maxHR": 0,
        }
    ]
    coach.refresh()
    assert coach.db.activities()[0]["avg_hr"] is None
    assert coach.db.activities()[0]["max_hr"] is None


def test_cached_review_remains_readable_during_a_mutating_operation(coach):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    holding, release = threading.Event(), threading.Event()

    def hold_lock():
        with coach.lock:
            holding.set()
            release.wait(timeout=5)

    with ThreadPoolExecutor() as executor:
        future = executor.submit(hold_lock)
        assert holding.wait(timeout=2)
        try:
            assert coach.workout_review()["last_workout"] is None
        finally:
            release.set()
        future.result(timeout=2)
