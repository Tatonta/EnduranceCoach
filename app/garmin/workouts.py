import math

from garminconnect.workout import (
    CyclingWorkout,
    HeartRateZoneTarget,
    PaceTarget,
    RunningWorkout,
    WorkoutSegment,
    create_distance_interval_step,
    create_interval_step,
    create_repeat_group,
)

from app.garmin.client import CoachError
from app.models import Step, Workout, pace_seconds
from app.services.planner import workout_hash


def pace_to_mps(value: str):
    return 1000 / pace_seconds(value)


def marker(workout, user_id="local"):
    return f"[GAC:{user_id}:{workout_hash(workout)}]"


def make_step(step: Step, order: int):
    if step.type == "repeat":
        return create_repeat_group(
            step.iterations, [make_step(s, order + i) for i, s in enumerate(step.steps, 1)], order
        )
    target = None
    if step.target:
        target = (
            PaceTarget(
                lower_limit=pace_to_mps(step.target.slow), upper_limit=pace_to_mps(step.target.fast)
            )
            if step.target.type == "pace"
            else HeartRateZoneTarget(zone_number=step.target.zone)
        )
    result = (
        create_interval_step(step.seconds, step_order=order)
        if step.seconds is not None
        else create_distance_interval_step(step.distance_m, step_order=order)
    )
    kinds = {
        "warmup": (1, 1),
        "interval": (3, 3),
        "run": (3, 3),
        "recovery": (4, 4),
        "cooldown": (2, 2),
    }
    sid, display = kinds[step.type]
    result.stepType = {
        "stepTypeId": sid,
        "stepTypeKey": "interval" if step.type == "run" else step.type,
        "displayOrder": display,
    }
    if target:
        result.targetType = {
            "workoutTargetTypeId": target.target_type,
            "workoutTargetTypeKey": target.target_type_key,
        }
        result.targetValueOne = target.lower_limit
        result.targetValueTwo = target.upper_limit
        result.zoneNumber = target.zone_number
    return result


def build_workout(workout: Workout, user_id="local"):
    if workout.sport not in {"running", "cycling"}:
        raise CoachError("Rest/manual non sono workout Garmin")
    cls = RunningWorkout if workout.sport == "running" else CyclingWorkout
    sport = {"sportTypeId": 1 if workout.sport == "running" else 2, "sportTypeKey": workout.sport}
    steps, order = [], 1
    for step in workout.steps:
        steps.append(make_step(step, order))
        order += 1 + (len(step.steps) if step.type == "repeat" else 0)
    return cls(
        workoutName=workout.name,
        description=f"{workout.description}\n{marker(workout, user_id)}",
        estimatedDurationInSecs=round(workout.estimated_duration_min * 60),
        workoutSegments=[WorkoutSegment(segmentOrder=1, sportType=sport, workoutSteps=steps)],
    )


def shape_step(step):
    """Retain all meaningful Garmin fields, ignoring server-generated IDs."""
    base = {
        "dto": step.get("type"),
        "order": step.get("stepOrder"),
        "kind": (step.get("stepType") or {}).get("stepTypeKey"),
        "end": (step.get("endCondition") or {}).get("conditionTypeKey"),
        "value": step.get("endConditionValue"),
    }
    if base["dto"] == "RepeatGroupDTO":
        base.update(
            iterations=step.get("numberOfIterations"),
            steps=[shape_step(s) for s in step.get("workoutSteps", [])],
        )
    else:
        base.update(
            target=(step.get("targetType") or {}).get("workoutTargetTypeKey"),
            lower=step.get("targetValueOne"),
            upper=step.get("targetValueTwo"),
            zone=step.get("zoneNumber"),
        )
    return base


def equal_shape(expected, actual):
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and expected.keys() == actual.keys()
            and all(equal_shape(v, actual[k]) for k, v in expected.items())
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(expected) == len(actual)
            and all(equal_shape(a, b) for a, b in zip(expected, actual, strict=True))
        )
    if isinstance(expected, (float, int)) and not isinstance(expected, bool):
        return isinstance(actual, (float, int)) and math.isclose(
            expected, actual, rel_tol=1e-5, abs_tol=0.001
        )
    # Garmin sometimes serializes unused HR zone as zero instead of null.
    return expected == actual


def validate_remote(workout: Workout, remote: dict, user_id="local"):
    expected = build_workout(workout, user_id).to_dict()
    segments = remote.get("workoutSegments") or []
    expected_steps = [shape_step(s) for s in expected["workoutSegments"][0]["workoutSteps"]]
    actual_steps = (
        [shape_step(s) for s in segments[0].get("workoutSteps", [])] if len(segments) == 1 else []
    )

    # Normalize unused fields only; targeted ranges and HR zone remain mandatory.
    def normalize(steps):
        for s in steps:
            if "steps" in s:
                normalize(s["steps"])
            else:
                if s.get("target") != "heart.rate.zone" and s.get("zone") == 0:
                    s["zone"] = None
                if s.get("target") in {"no.target", "heart.rate.zone"}:
                    for key in ("lower", "upper"):
                        if s.get(key) == 0:
                            s[key] = None

    normalize(actual_steps)
    valid = (
        len(segments) == 1
        and segments[0].get("segmentOrder") == 1
        and (remote.get("sportType") or {}).get("sportTypeKey") == workout.sport
        and (segments[0].get("sportType") or {}).get("sportTypeKey") == workout.sport
        and remote.get("workoutName") == workout.name
        and equal_shape(expected_steps, actual_steps)
    )
    return {
        "valid": valid,
        "expected": expected_steps,
        "actual": actual_steps,
        "message": "Struttura verificata"
        if valid
        else "Struttura Garmin diversa dal JSON: schedulazione bloccata",
    }


def upload_workout(client, workout, user_id="local"):
    result = getattr(client, f"upload_{workout.sport}_workout")(build_workout(workout, user_id))
    wid = result.get("workoutId") if isinstance(result, dict) else None
    if wid is None:
        raise CoachError(
            "Upload senza workoutId: interrompere e verificare la libreria Garmin",
            "upload_uncertain",
        )
    return str(wid)
