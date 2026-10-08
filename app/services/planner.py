import hashlib
import json
import os
import tempfile
from datetime import UTC
from pathlib import Path

from app.models import Plan, Workout


def canonical_hash(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", exclude_none=True)
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def workout_hash(workout: Workout):
    # Date and stable identity govern scheduling; content governs template versioning.
    return canonical_hash(
        workout.model_dump(mode="json", exclude={"id", "date"}, exclude_none=True)
    )


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def load_plan(path: Path) -> Plan:
    return Plan.model_validate_json(path.read_text(encoding="utf-8-sig"))


def replace_plan(path: Path, plan: Plan):
    if path.exists():
        from datetime import datetime

        old = load_plan(path)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        atomic_json(path.parent / "backups" / f"plan-{stamp}.json", old.model_dump(mode="json"))
    atomic_json(path, plan.model_dump(mode="json", exclude_none=True))
