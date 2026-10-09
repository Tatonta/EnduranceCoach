"""Disposable loopback platform for native UI tests; never loads personal Garmin data."""

import argparse
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import uvicorn
from fastapi.testclient import TestClient

from app.platform.config import PlatformSettings
from app.platform.main import create_platform_app
from app.platform.store import PlatformStore


def prepare(directory, port):
    directory = Path(directory).resolve()
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("Use an empty, dedicated UI-test directory; existing data is preserved")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    database = directory / "ui-test.sqlite3"
    if database.exists():
        raise ValueError("Use an empty, dedicated UI-test directory; existing data is preserved")
    settings = PlatformSettings(
        database_url=f"sqlite:///{database.as_posix()}",
        registration_enabled=True,
        require_https=False,
    )
    now = datetime.now(UTC)
    password = secrets.token_urlsafe(36)
    store = PlatformStore(settings)
    store.initialize()
    with TestClient(create_platform_app(settings, store)) as client:
        for account in ("first", "context"):
            credentials = {"email": f"ui-{account}@example.test", "password": password}
            reply = client.post(
                "/v1/auth/register", json={**credentials, "timezone": "Europe/Rome"}
            )
            assert reply.status_code == 201, reply.status_code
            login = client.post("/v1/auth/login", json=credentials)
            assert login.status_code == 200, login.status_code
            headers = {"Authorization": "Bearer " + login.json()["access_token"]}
            activities = [
                {
                    "source": "coros",
                    "source_activity_id": f"synthetic-{index}",
                    "name": "Corsa facile sintetica",
                    "sport": "running",
                    "activity_type": "running",
                    "start_time": (now - timedelta(days=10 - 3 * index)).isoformat(),
                    "distance_m": 2400 / pace * 1000,
                    "duration_s": 2400,
                    "elapsed_duration_s": 2400,
                    "avg_pace_s_km": pace,
                    "avg_hr": 140,
                    "max_hr": 180,
                    "elevation_gain_m": 10,
                }
                for index, pace in enumerate((360, 350, 340, 330))
            ]
            # Athlete timezone is explicit, so the plan date matches the canonical source date.
            local_now = now.astimezone(ZoneInfo("Europe/Rome"))
            plan = {
                "plan_name": "Programma sintetico UI",
                "workouts": [
                    {
                        "id": key,
                        "date": (local_now + timedelta(days=offset)).date().isoformat(),
                        "name": "Corsa facile sintetica",
                        "sport": "running",
                        "estimated_duration_min": 40,
                        "steps": [
                            {
                                "type": "run",
                                "duration_min": 40,
                                "target": {"type": "hr_zone", "zone": 2},
                            }
                        ],
                    }
                    for key, offset in (("past-easy", -1), ("future-easy", 2))
                ],
            }
            reply = client.put(
                "/v1/plan", headers=headers, json={"expected_version": 0, "plan": plan}
            )
            assert reply.status_code == 200, reply.status_code
            reply = client.post(
                "/v1/activities/import", headers=headers, json={"activities": activities}
            )
            assert reply.status_code == 200, reply.status_code
            if account == "context":
                profile = {
                    "primary_sport": "running",
                    "goal_type": "fitness",
                    "goal_description": "Obiettivo sintetico per la verifica UI",
                    "device_vendor": "none",
                        "running_years": 0,
                        "cycling_years": 0,
                        "recent_running_km_week": 0,
                        "recent_cycling_km_week": 0,
                        "gym_sessions_week": 0,
                    "availability": [{"weekday": 0, "minutes": 45}],
                    "coaching_consent": True,
                }
                reply = client.put(
                    "/v1/profile", headers=headers, json={"expected_version": 0, "profile": profile}
                )
                assert reply.status_code == 200, reply.status_code
                path = "/v1/activities/coros/synthetic-3/details"
                state = client.get(path, headers=headers).json()
                details = {
                    "plan_version": 1,
                    "plan_workout_id": "past-easy",
                    "hr_zones": [{"zone": 2, "low_bpm": 125, "high_bpm": 149}],
                    "laps": [
                        {
                            "lap": index + 1,
                            "step_index": 0,
                            "phase_type": "run",
                            "start_elapsed_s": index * 1200,
                            "duration_s": 1200,
                            "elapsed_s": 1200,
                            "distance_m": activities[-1]["distance_m"] / 2,
                            "avg_hr": hr,
                        }
                        for index, hr in enumerate((120, 160))
                    ],
                }
                reply = client.put(
                    path,
                    headers=headers,
                    json={
                        "expected_details_version": 0,
                        "expected_activity_hash": state["activity_hash"],
                        "details": details,
                    },
                )
                assert reply.status_code == 200, reply.status_code
            review = client.get("/v1/review/workout", headers=headers).json()
            assert review["program"]["eligible"] == (account == "first")
    configuration = directory / "ui-test-access.json"
    configuration.touch(mode=0o600, exist_ok=False)
    configuration.write_text(
        json.dumps({"origin": f"http://localhost:{port}", "password": password}), encoding="utf-8"
    )
    settings.registration_enabled = False
    return create_platform_app(settings, PlatformStore(settings))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    uvicorn.run(prepare(args.directory, args.port), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
