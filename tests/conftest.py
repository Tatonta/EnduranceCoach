import copy
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.models import Plan
from app.services.coach import Coach
from app.services.planner import atomic_json
from scripts.create_initial_plan import initial_plan


class FakeGarmin:
    def __init__(self):
        self.workouts = {}
        self.calendar = []
        self.uploads = self.schedules = 0
        self.unscheduled = []
        self.corrupt = False
        self.hide_schedule = False
        self.fail_schedule = False
        self.fail_read = False
        self.activity_data = []

    def get_workouts(self, start=0, limit=100):
        return copy.deepcopy(list(self.workouts.values())[start : start + limit])

    def upload_running_workout(self, workout):
        self.uploads += 1
        wid = str(1000 + self.uploads)
        payload = workout.to_dict()
        payload["workoutId"] = wid
        if self.corrupt:
            payload["workoutSegments"][0]["workoutSteps"][0]["endConditionValue"] = 1
        self.workouts[wid] = payload
        return {"workoutId": wid}

    upload_cycling_workout = upload_running_workout

    def get_workout_by_id(self, wid):
        from app.garmin.client import CoachError

        if self.fail_read:
            self.fail_read = False
            raise CoachError("Read failed")
        return copy.deepcopy(self.workouts[str(wid)])

    def get_scheduled_workouts(self, year, month):
        return {"calendarItems": copy.deepcopy(self.calendar)}

    def schedule_workout(self, wid, day):
        from app.garmin.client import CoachError

        self.schedules += 1
        if self.fail_schedule:
            raise CoachError("Schedule request failed", "garmin_request_failed")
        item = {
            "id": str(2000 + self.schedules),
            "date": day,
            "title": self.workouts[wid]["workoutName"],
            "itemType": "workout",
            "workoutId": wid,
        }
        if not self.hide_schedule:
            self.calendar.append(item)
        return {"workoutScheduleId": item["id"]}

    def get_scheduled_workout_by_id(self, sid):
        row = next(r for r in self.calendar if str(r["id"]) == str(sid))
        return {
            "workoutScheduleId": sid,
            "calendarDate": row["date"],
            "workout": {"workoutId": row.get("workoutId")},
        }

    def unschedule_workout(self, sid):
        self.unscheduled.append(str(sid))
        self.calendar = [r for r in self.calendar if str(r["id"]) != str(sid)]

    def delete_workout(self, *args):
        raise AssertionError("Template deletion must never be called")

    def get_activities(self, start=0, limit=100, activitytype=None):
        rows = self.activity_data
        if activitytype == "running":
            rows = [
                a for a in rows if "running" in (a.get("activityType") or {}).get("typeKey", "")
            ]
        elif activitytype == "cycling":
            rows = [
                a
                for a in rows
                if any(
                    k in (a.get("activityType") or {}).get("typeKey", "")
                    for k in ("cycling", "biking")
                )
            ]
        return copy.deepcopy(rows[start : start + limit])

    def get_personal_record(self):
        return []

    def get_activity_details(self, aid, maxchart=2000, maxpoly=4000):
        return {}

    def get_max_metrics(self, day):
        return {"generic": {"vo2MaxPreciseValue": 42}}


@pytest.fixture(autouse=True)
def forbid_real_garmin(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Tests cannot instantiate real Garmin")

    monkeypatch.setattr("app.garmin.client.Garmin", forbidden)
    monkeypatch.setattr("requests.sessions.Session.request", forbidden)


@pytest.fixture
def settings(tmp_path):
    result = Settings(
        data_dir=tmp_path,
        scheduler_enabled=False,
        startup_refresh=False,
    )
    result.now = lambda: datetime(2026, 10, 3, 20, 0, tzinfo=ZoneInfo("Europe/Rome"))
    return result


@pytest.fixture
def plan():
    return Plan.model_validate(initial_plan())


@pytest.fixture
def fake():
    return FakeGarmin()


@pytest.fixture
def coach(settings, plan, fake):
    atomic_json(settings.plan_path, plan.model_dump(mode="json", exclude_none=True))
    return Coach(settings, fake)
