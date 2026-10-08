import copy
from datetime import date, timedelta

import pytest

from app.garmin.calendar import months_between
from app.garmin.client import CoachError
from app.garmin.workouts import build_workout
from app.services.planner import atomic_json


def one_plan(coach):
    plan = coach.plan()
    plan.workouts = [plan.workouts[2]]
    atomic_json(coach.settings.plan_path, plan.model_dump(mode="json", exclude_none=True))
    return plan


def test_cross_year_months():
    assert list(months_between(date(2026, 12, 20), date(2027, 2, 1))) == [
        (2026, 12),
        (2027, 1),
        (2027, 2),
    ]


def test_calendar_bounds_and_activity_protection(coach, fake):
    fake.calendar = [
        {"id": 1, "date": "2026-10-04", "title": "old", "itemType": "workout"},
        {"id": 2, "date": "2026-10-03", "title": "outside", "itemType": "workout"},
        {"id": 3, "date": "2026-10-04", "title": "recorded", "itemType": "activity"},
        {"id": 4, "date": "2026-10-26", "title": "outside", "itemType": "workout"},
    ]
    preview = coach.preview_calendar_cleanup()
    assert [r["scheduled_id"] for r in preview["rows"]] == ["1"]
    assert fake.unscheduled == []
    with pytest.raises(CoachError, match="Conferma"):
        coach.apply_calendar_cleanup(preview["preview_id"])
    result = coach.apply_calendar_cleanup(preview["preview_id"], True)
    assert result["removed"] == ["1"]
    assert [r["id"] for r in fake.calendar] == [2, 3, 4]


def test_duplicate_selection_and_same_name_different_structure(coach, fake):
    plan = one_plan(coach)
    w = plan.workouts[0]
    wid = str(fake.upload_running_workout(build_workout(w))["workoutId"])
    fake.schedule_workout(wid, w.date.isoformat())
    fake.schedule_workout(wid, w.date.isoformat())
    bad = copy.deepcopy(fake.workouts[wid])
    bad["workoutId"] = "999"
    bad["workoutSegments"][0]["workoutSteps"][0]["endConditionValue"] = 1
    fake.workouts["999"] = bad
    fake.schedule_workout("999", w.date.isoformat())
    preview = coach.preview_calendar_cleanup()
    assert [r["action"] for r in preview["rows"]] == ["keep", "unschedule", "unschedule"]
    assert "Duplicato" in preview["rows"][1]["reason"]
    coach.apply_calendar_cleanup(preview["preview_id"], True)
    assert len(fake.calendar) == 1 and len(fake.workouts) == 2


def test_apply_rejects_changed_calendar_and_consumed_preview(coach, fake):
    fake.calendar = [{"id": 1, "date": "2026-10-04", "title": "old", "itemType": "workout"}]
    p = coach.preview_calendar_cleanup()
    fake.calendar[0]["title"] = "changed"
    with pytest.raises(CoachError, match="cambiato"):
        coach.apply_calendar_cleanup(p["preview_id"], True)
    assert not fake.unscheduled
    p = coach.preview_calendar_cleanup()
    coach.apply_calendar_cleanup(p["preview_id"], True)
    with pytest.raises(CoachError, match="preview"):
        coach.apply_calendar_cleanup(p["preview_id"], True)


def test_apply_rejects_changed_plan_and_expired_preview(coach, fake):
    p = coach.preview_calendar_cleanup()
    plan = coach.plan()
    plan.plan_name = "changed"
    coach.replace_plan(plan)
    with pytest.raises(CoachError):
        coach.apply_calendar_cleanup(p["preview_id"], True)
    p = coach.preview_calendar_cleanup()
    p["expires_at"] = (coach.settings.now() - timedelta(minutes=1)).isoformat()
    coach.db.set("cleanup_preview", p)
    with pytest.raises(CoachError, match="scaduta"):
        coach.apply_calendar_cleanup(p["preview_id"], True)


def test_sync_is_idempotent_and_recovers_state_loss(coach, fake):
    one_plan(coach)
    with pytest.raises(CoachError, match="test"):
        coach.sync_plan(True)
    proof = coach.test_workout()
    assert proof["valid"] and fake.uploads == 1 and fake.schedules == 0
    with pytest.raises(CoachError, match="Conferma"):
        coach.sync_plan()
    assert coach.sync_plan(True)["status"] == "complete"
    assert coach.sync_plan(True)["results"][0]["status"] == "already_scheduled"
    with coach.db.connection() as db:
        db.execute("DELETE FROM workouts")
    assert coach.sync_plan(True)["status"] == "complete"
    assert fake.uploads == 1 and fake.schedules == 1


def test_failed_validation_never_schedules_or_duplicates_upload(coach, fake):
    one_plan(coach)
    fake.corrupt = True
    with pytest.raises(CoachError, match="diversa"):
        coach.test_workout()
    assert fake.schedules == 0
    with pytest.raises(CoachError, match="non valida"):
        coach.test_workout()
    assert fake.uploads == 1


def test_new_future_version_replaces_only_old_schedule(coach, fake):
    plan = one_plan(coach)
    coach.test_workout()
    coach.sync_plan(True)
    old_id = fake.calendar[0]["id"]
    plan.workouts[0].steps[1].steps[0].duration_min = 9
    coach.replace_plan(plan)
    # Verify another current workout, preserving replacement journal for first.
    # A test may itself target the edited workout; original schedule must be retained in journal.
    coach.test_workout()
    assert coach.sync_plan(True)["status"] == "complete"
    assert fake.unscheduled == [old_id]
    assert len(fake.calendar) == 1 and len(fake.workouts) == 2


def test_uncertain_schedule_blocks_new_requests(coach, fake):
    one_plan(coach)
    coach.test_workout()
    fake.hide_schedule = True
    assert coach.sync_plan(True)["status"] == "partial"
    coach.test_workout()
    assert coach.sync_plan(True)["status"] == "partial"
    assert fake.schedules == 1


def test_recovery_after_upload_then_read_failure(coach, fake):
    one_plan(coach)
    fake.fail_read = True
    with pytest.raises(CoachError):
        coach.test_workout()
    assert fake.uploads == 1
    assert coach.test_workout()["valid"]
    assert fake.uploads == 1
