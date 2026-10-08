import pytest
from pydantic import ValidationError

from app.garmin.workouts import build_workout, pace_to_mps, validate_remote
from app.models import Plan, Step, Workout
from app.services.planner import canonical_hash, load_plan, workout_hash


def test_parse_initial_json(plan, settings):
    settings.plan_path.write_text(plan.model_dump_json(), encoding="utf-8")
    parsed = load_plan(settings.plan_path)
    assert len(parsed.workouts) == 22
    assert parsed.workouts[0].sport == "rest"
    assert parsed.workouts[1].sport == "manual"
    assert parsed.start.isoformat() == "2026-10-04"


@pytest.mark.parametrize(
    "spec",
    [
        {"type": "run"},
        {"type": "run", "duration_min": 5, "duration_s": 300},
        {"type": "repeat", "iterations": 3, "steps": []},
        {"type": "run", "duration_s": -1},
        {"type": "run", "duration_s": float("inf")},
        {
            "type": "interval",
            "duration_min": 8,
            "target": {"type": "pace", "slow": "4:10", "fast": "4:18"},
        },
        {"type": "run", "duration_min": 5, "target": {"type": "hr_zone", "zone": 6}},
        {
            "type": "run",
            "duration_min": 5,
            "target": {"type": "pace", "slow": "4:99", "fast": "4:00"},
        },
    ],
)
def test_invalid_steps_rejected(spec):
    with pytest.raises(ValidationError):
        Step.model_validate(spec)


@pytest.mark.parametrize("pace,expected", [("4:10", 4.0), ("5:00", 10 / 3), ("3:45", 1000 / 225)])
def test_pace_conversion(pace, expected):
    assert pace_to_mps(pace) == pytest.approx(expected)


def test_repeat_and_workout_builder(plan):
    w = plan.workouts[2]
    payload = build_workout(w).to_dict()
    steps = payload["workoutSegments"][0]["workoutSteps"]
    assert [s["stepOrder"] for s in steps] == [1, 2, 5]
    assert steps[1]["type"] == "RepeatGroupDTO"
    assert steps[1]["numberOfIterations"] == 3
    assert [s["stepOrder"] for s in steps[1]["workoutSteps"]] == [3, 4]
    interval = steps[1]["workoutSteps"][0]
    assert interval["endConditionValue"] == 480
    assert interval["targetValueOne"] == pytest.approx(1000 / 320)
    assert interval["targetValueTwo"] == pytest.approx(1000 / 310)
    assert steps[1]["workoutSteps"][1]["stepType"]["stepTypeKey"] == "recovery"


def test_distance_and_cycling_builder(plan):
    w = next(w for w in plan.workouts if w.id == "oct-10")
    payload = build_workout(w).to_dict()
    interval = payload["workoutSegments"][0]["workoutSteps"][1]["workoutSteps"][0]
    assert interval["endCondition"]["conditionTypeKey"] == "distance"
    assert interval["endConditionValue"] == 800
    bike = next(w for w in plan.workouts if w.id == "oct-08")
    payload = build_workout(bike).to_dict()
    assert payload["sportType"]["sportTypeKey"] == "cycling"
    assert payload["workoutSegments"][0]["workoutSteps"][1]["zoneNumber"] == 2


def test_distance_target_warmup_and_recovery_supported(plan):
    data = plan.workouts[2].model_dump(mode="json", exclude_none=True)
    data["steps"] = [
        {"type": "warmup", "distance_m": 1000, "target": {"type": "hr_zone", "zone": 2}},
        {"type": "recovery", "distance_m": 200},
        {"type": "cooldown", "duration_s": 300},
    ]
    w = Workout.model_validate(data)
    assert validate_remote(w, build_workout(w).to_dict())["valid"]


@pytest.mark.parametrize(
    "mutation",
    ["type", "iterations", "duration", "distance", "target", "order", "count", "sport", "zone"],
)
def test_post_upload_rejects_changed_structure(plan, mutation):
    w = next(w for w in plan.workouts if w.id == ("oct-08" if mutation == "zone" else "oct-10"))
    payload = build_workout(w).to_dict()
    steps = payload["workoutSegments"][0]["workoutSteps"]
    if mutation == "type":
        steps[0]["type"] = "RepeatGroupDTO"
    elif mutation == "iterations":
        steps[1]["numberOfIterations"] = 7
    elif mutation == "duration":
        steps[0]["endConditionValue"] = 60
    elif mutation == "distance":
        steps[1]["workoutSteps"][0]["endConditionValue"] = 1000
    elif mutation == "target":
        steps[1]["workoutSteps"][0]["targetValueOne"] = 5
    elif mutation == "order":
        steps[2]["stepOrder"] = 1
    elif mutation == "count":
        steps.pop()
    elif mutation == "sport":
        payload["sportType"]["sportTypeKey"] = "cycling"
    elif mutation == "zone":
        steps[1]["zoneNumber"] = 3
    assert not validate_remote(w, payload)["valid"]


def test_hash_is_canonical_and_version_sensitive(plan):
    w = plan.workouts[2]
    reversed_dict = dict(reversed(list(w.model_dump(mode="json", exclude_none=True).items())))
    assert canonical_hash(w) == canonical_hash(reversed_dict)
    changed = w.model_copy(deep=True)
    changed.steps[1].steps[0].duration_min = 9
    assert workout_hash(w) != workout_hash(changed)
    moved = w.model_copy(update={"date": w.date.replace(day=7)})
    assert workout_hash(w) == workout_hash(moved)


def test_duplicate_ids_rejected(plan):
    data = plan.model_dump(mode="json")
    data["workouts"][1]["id"] = data["workouts"][0]["id"]
    with pytest.raises(ValidationError):
        Plan.model_validate(data)
