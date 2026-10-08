"""Generate synthetic native-client fixtures using the real platform API; no personal data."""

import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.platform.config import PlatformSettings
from app.platform.main import create_platform_app
from app.platform.store import PlatformStore

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "ios" / "AdaptiveCoachTests" / "Fixtures"


def generate(destination=FIXTURES):
    now = datetime(2026, 10, 5, 20, tzinfo=UTC)
    with tempfile.TemporaryDirectory(prefix="coach-ios-contract-") as directory:
        settings = PlatformSettings(
            database_url=f"sqlite:///{Path(directory).as_posix()}/contract.sqlite3",
            registration_enabled=True,
            require_https=False,
        )
        settings.now = lambda: now
        store = PlatformStore(settings)
        store.initialize()
        with TestClient(create_platform_app(settings, store)) as client:
            credentials = {
                "email": "native-fixture@example.test",
                "password": "synthetic fixture password only",
            }
            assert client.post("/v1/auth/register", json=credentials).status_code == 201
            token = client.post("/v1/auth/login", json=credentials).json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            def get(path):
                result = client.get(path, headers=headers)
                assert result.status_code == 200, result.text
                return result.json()

            plan = {
                "plan_name": "Synthetic native contract plan",
                "goal": "A consistent, easy training week",
                "athlete": {"custom_key_must_survive": {"CaseSensitive": [1, True, None]}},
                "notes": ["Synthetic data, never a recommended personal program."],
                "workouts": [
                    {
                        "id": f"easy-{index}",
                        "date": (now + timedelta(days=index)).date().isoformat(),
                        "name": "Corsa facile",
                        "sport": "running",
                        "estimated_duration_min": 40,
                        "steps": [
                            {"type": "warmup", "duration_min": 5},
                            {
                                "type": "run",
                                "duration_min": 30,
                                "target": {"type": "hr_zone", "zone": 2},
                            },
                            {"type": "cooldown", "duration_min": 5},
                        ],
                    }
                    for index in (1, 3, 5)
                ],
            }
            response = client.put(
                "/v1/plan", headers=headers, json={"expected_version": 0, "plan": plan}
            )
            assert response.status_code == 200, response.text
            fixtures = {
                "plan": get("/v1/plan"),
                "review-empty": get("/v1/review/workout"),
                "integrations": get("/v1/integrations"),
            }
            activities = []
            for index, pace in enumerate((360, 350, 340, 330)):
                activities.append(
                    {
                        "source": "apple_health",
                        "source_activity_id": f"synthetic-workout-{index}",
                        "name": "Corsa facile",
                        "sport": "running",
                        "activity_type": "running",
                        "start_time": (now - timedelta(days=10 - 3 * index)).isoformat(),
                        "distance_m": 2400 / pace * 1000,
                        "duration_s": 2400,
                        "elapsed_duration_s": 2400,
                        "avg_pace_s_km": pace,
                        "avg_hr": 140,
                        "max_hr": 155,
                        "elevation_gain_m": 10,
                        "training_load": None,
                        "aerobic_training_effect": None,
                        "workout_id": "",
                    }
                )
            fixtures["apple-health-import"] = {
                "activities": activities,
                "ingestion_method": "client_import",
            }
            response = client.post(
                "/v1/activities/import", headers=headers, json=fixtures["apple-health-import"]
            )
            assert response.status_code == 200, response.text
            fixtures["review-improving"] = get("/v1/review/workout")
            assert fixtures["review-improving"]["program"]["eligible"]
            response = client.post("/v1/review/adjustments/preview", headers=headers)
            assert response.status_code == 200, response.text
            fixtures["proposal"] = response.json()
            response = client.post(
                f"/v1/review/adjustments/{response.json()['proposal_id']}/apply",
                headers=headers,
                json={"expected_version": 1, "confirmed": True},
            )
            assert response.status_code == 200, response.text
            fixtures["applied"] = response.json()
            fixtures["review-keep"] = get("/v1/review/workout")
            assert not fixtures["review-keep"]["program"]["eligible"]
        destination.mkdir(parents=True, exist_ok=True)
        for name, payload in fixtures.items():
            (destination / f"{name}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
    return len(fixtures)


if __name__ == "__main__":
    print(f"Generated {generate()} synthetic iOS fixtures in {FIXTURES}")
