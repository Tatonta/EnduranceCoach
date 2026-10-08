from __future__ import annotations
import argparse, json, os, sys
from datetime import date
from getpass import getpass
from pathlib import Path
from typing import Any

START_DATE = date(2026, 9, 29)
END_DATE = date(2026, 10, 25)


def cleanup_calendar(client, plan_file="workouts.json", apply=False):
    plan = json.loads(Path(plan_file).read_text(encoding="utf-8"))

    # Workout che devono rimanere nel calendario.
    keep = {
        (w["date"], w["name"])
        for w in plan["workouts"]
        if w["sport"] in {"running", "cycling"}
    }

    calendar_items = []

    # Il piano attraversa settembre e ottobre.
    for year, month in [(2026, 9), (2026, 10)]:
        data = client.get_scheduled_workouts(year, month) or {}
        calendar_items.extend(data.get("calendarItems") or [])

    foreign = []

    for item in calendar_items:
        if item.get("itemType") != "workout":
            continue

        item_date = item.get("date")
        title = item.get("title")

        if not item_date:
            continue

        d = date.fromisoformat(item_date)

        if not (START_DATE <= d <= END_DATE):
            continue

        if (item_date, title) not in keep:
            foreign.append(item)

    print("\n=== WORKOUT EXTRA DA RIMUOVERE ===\n")

    if not foreign:
        print("Calendario già pulito.")
        return

    for item in foreign:
        print(
            f"{item.get('date')} | "
            f"{item.get('title')} | "
            f"id={item.get('id')}"
        )

    if not apply:
        print(
            "\nPREVIEW soltanto. "
            "Richiama cleanup_calendar(..., apply=True) "
            "per rimuoverli."
        )
        return

    print("\n=== RIMOZIONE ===\n")

    for item in foreign:
        scheduled_id = item.get("id")

        if scheduled_id is None:
            print(
                f"SKIP {item.get('date')} {item.get('title')}: "
                "manca scheduled ID"
            )
            continue

        try:
            # Verifica che l'ID sia realmente uno scheduled workout.
            client.get_scheduled_workout_by_id(scheduled_id)

            client.unschedule_workout(scheduled_id)

            print(
                f"✓ Rimosso: "
                f"{item.get('date')} | {item.get('title')}"
            )

        except Exception as exc:
            print(
                f"✗ Non rimosso: "
                f"{item.get('date')} | {item.get('title')} "
                f"({exc})"
            )

try:
    import pydantic  # noqa
except ImportError as e:
    raise RuntimeError('Installa: python -m pip install -U "garminconnect[workout]" curl_cffi pydantic') from e

from garminconnect import Garmin
from garminconnect.exceptions import GarminConnectAuthenticationError
from garminconnect.workout import (
    CyclingWorkout, HeartRateZoneTarget, PaceTarget, RunningWorkout, WorkoutSegment,
    create_cooldown_step, create_distance_interval_step, create_interval_step,
    create_recovery_step, create_repeat_group, create_targeted_distance_interval_step,
    create_targeted_interval_step, create_warmup_step, pace_to_mps,
)

TOKEN_STORE = str(Path("~/.garminconnect").expanduser())
STATE_FILE = "garmin_sync_state.json"

SPORTS = {
    "running": (1, "running", 1, RunningWorkout, "upload_running_workout"),
    "cycling": (2, "cycling", 2, CyclingWorkout, "upload_cycling_workout"),
}

def login() -> Garmin:
    try:
        g = Garmin()
        g.login(TOKEN_STORE)
        cleanup_calendar(
            g,
            "workouts.json",
            apply=False,
        )
        return
        print("✓ Login Garmin tramite token")
        return g
    except GarminConnectAuthenticationError:
        pass
    email = os.getenv("GARMIN_EMAIL") or input("Garmin email: ").strip()
    password = getpass("Garmin password: ")
    g = Garmin(email, password, prompt_mfa=lambda: input("Garmin MFA code: ").strip())
    g.login(TOKEN_STORE)
    print("✓ Login riuscito; token salvati")
    return g

def pace(s: str):
    m, sec = map(int, s.split(":"))
    return m, sec

def target(spec):
    if not spec:
        return None
    if spec["type"] == "pace":
        sm, ss = pace(spec["slow"])
        fm, fs = pace(spec["fast"])
        return PaceTarget(
            lower_limit=pace_to_mps(sm, ss, "km"),
            upper_limit=pace_to_mps(fm, fs, "km"),
        )
    if spec["type"] == "hr_zone":
        return HeartRateZoneTarget(zone_number=int(spec["zone"]))
    raise ValueError(f"Target non supportato: {spec}")

def seconds(spec):
    if "duration_s" in spec:
        return float(spec["duration_s"])
    if "duration_min" in spec:
        return float(spec["duration_min"]) * 60
    return None

def make_step(spec, order):
    t = spec["type"]
    if t == "repeat":
        return create_repeat_group(
            iterations=int(spec["iterations"]),
            step_order=order,
            workout_steps=[make_step(s, i) for i, s in enumerate(spec["steps"], 1)],
        )

    secs = seconds(spec)
    tgt = target(spec.get("target"))
    dist = spec.get("distance_m")

    if t == "warmup":
        return create_warmup_step(secs, step_order=order)
    if t == "cooldown":
        return create_cooldown_step(secs, step_order=order)
    if t == "recovery":
        return create_recovery_step(secs, step_order=order)
    if t in ("run", "interval"):
        if secs is not None:
            return (create_interval_step(secs, step_order=order) if tgt is None
                    else create_targeted_interval_step(secs, step_order=order, target=tgt))
        if dist is not None:
            return (create_distance_interval_step(float(dist), step_order=order) if tgt is None
                    else create_targeted_distance_interval_step(float(dist), step_order=order, target=tgt))
    raise ValueError(f"Step non valido: {spec}")

def build(item):
    sid, skey, disp, cls, _ = SPORTS[item["sport"]]
    segment = WorkoutSegment(
        segmentOrder=1,
        sportType={"sportTypeId": sid, "sportTypeKey": skey, "displayOrder": disp},
        workoutSteps=[make_step(s, i) for i, s in enumerate(item["steps"], 1)],
    )
    return cls(
        workoutName=item["name"],
        description=item.get("description"),
        estimatedDurationInSecs=int(float(item["estimated_duration_min"]) * 60),
        workoutSegments=[segment],
    )

def upload(g, item):
    *_, uploader = SPORTS[item["sport"]]
    result = getattr(g, uploader)(build(item))
    for key in ("workoutId", "workout_id", "id"):
        if isinstance(result, dict) and result.get(key) is not None:
            return str(result[key])
    raise RuntimeError(f"workoutId non trovato: {result}")

def remote_shape(step):
    st = (step.get("stepType") or {}).get("stepTypeKey")
    if step.get("type") == "RepeatGroupDTO" or st == "repeat":
        return {
            "type": "repeat",
            "iterations": int(step.get("numberOfIterations", 0)),
            "steps": [remote_shape(x) for x in sorted(step.get("workoutSteps") or [], key=lambda x: x.get("stepOrder", 999))]
        }
    return {
        "type": st,
        "end": (step.get("endCondition") or {}).get("conditionTypeKey"),
        "value": step.get("endConditionValue"),
        "target": (step.get("targetType") or {}).get("workoutTargetTypeKey"),
        "zone": step.get("zoneNumber"),
    }

def expected_shape(spec):
    if spec["type"] == "repeat":
        return {"type": "repeat", "iterations": int(spec["iterations"]), "steps": [expected_shape(x) for x in spec["steps"]]}
    t = "interval" if spec["type"] == "run" else spec["type"]
    secs = seconds(spec)
    tgt = spec.get("target")
    return {
        "type": t,
        "end": "time" if secs is not None else "distance",
        "value": secs if secs is not None else float(spec["distance_m"]),
        "target": "pace.zone" if tgt and tgt["type"] == "pace" else ("heart.rate.zone" if tgt and tgt["type"] == "hr_zone" else "no.target"),
        "zone": int(tgt["zone"]) if tgt and tgt["type"] == "hr_zone" else None,
    }

def same(a, b):
    if a["type"] != b["type"]:
        return False
    if a["type"] == "repeat":
        return a["iterations"] == b["iterations"] and len(a["steps"]) == len(b["steps"]) and all(same(x, y) for x, y in zip(a["steps"], b["steps"]))
    value_ok = abs(float(a["value"]) - float(b["value"])) < 0.01
    return value_ok and a["end"] == b["end"] and a["target"] == b["target"] and a.get("zone") == b.get("zone")

def verify(g, wid, item):
    remote = g.get_workout_by_id(wid)
    segs = remote.get("workoutSegments") or []
    if not segs:
        return False
    actual = [remote_shape(x) for x in sorted(segs[0].get("workoutSteps") or [], key=lambda x: x.get("stepOrder", 999))]
    expected = [expected_shape(x) for x in item["steps"]]
    return len(actual) == len(expected) and all(same(x, y) for x, y in zip(expected, actual))

def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))

def save_state(path, state):
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan", nargs="?", default="workouts.json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    plan_path = Path(args.plan)
    plan = read_json(plan_path)
    state_path = plan_path.parent / STATE_FILE
    state = read_json(state_path) if state_path.exists() else {}
    today = date.today()
    g = None if args.dry_run else login()

    print(f"\n{plan.get('plan_name', plan_path.name)}\n")

    for item in plan["workouts"]:
        key = f"{item['date']}|{item['name']}"
        print(f"[{item['date']}] {item['name']}")

        if item["sport"] in ("rest", "manual"):
            print(f"  → {item.get('description','')}")
            continue
        if date.fromisoformat(item["date"]) < today and not args.force:
            print("  → data passata, salto")
            continue
        if state.get(key, {}).get("status") == "scheduled" and not args.force:
            print("  ✓ già sincronizzato")
            continue
        if args.dry_run:
            print(f"  → DRY RUN: {item['sport']}, {len(item['steps'])} step top-level")
            continue

        wid = None if args.force else state.get(key, {}).get("workout_id")
        if not wid:
            wid = upload(g, item)
            state[key] = {"workout_id": wid, "status": "uploaded"}
            save_state(state_path, state)
            print(f"  ✓ upload workoutId={wid}")
        else:
            print(f"  → riuso workoutId={wid}")

        if not verify(g, wid, item):
            state[key]["status"] = "validation_failed"
            save_state(state_path, state)
            print("  ❌ struttura Garmin diversa dal JSON: NON schedulato")
            continue

        print("  ✓ step Garmin verificati")
        g.schedule_workout(wid, item["date"])
        state[key]["status"] = "scheduled"
        save_state(state_path, state)
        print("  ✓ schedulato")

    print(f"\nFatto. Stato: {state_path}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
