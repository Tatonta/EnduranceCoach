"""Smoke test a disposable private pilot; never run this against real athlete accounts."""

import argparse
import json
import secrets
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit


def wait_for_ready(probe, attempts=45):
    for attempt in range(attempts):
        try:
            assert probe()["status"] == "ok"
            return
        except (urllib.error.URLError, TimeoutError, ConnectionError) as failure:
            # A published Docker port can reset connections briefly before a
            # worker binds its socket. Retry readiness, never a mutation.
            if attempt == attempts - 1:
                detail = f"HTTP {failure.code}" if isinstance(failure, urllib.error.HTTPError) else type(failure).__name__
                raise RuntimeError(f"Pilot did not become ready ({detail})") from None
            time.sleep(2)


def verify(origin):
    parts = urlsplit(origin)
    if parts.hostname not in {"localhost", "127.0.0.1"} or parts.path not in {"", "/"}:
        raise ValueError("Smoke tests require a disposable loopback-only pilot")

    def request(path, method="GET", payload=None, token=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body = json.dumps(payload).encode() if payload is not None else None
        with urllib.request.urlopen(
            urllib.request.Request(origin.rstrip("/") + path, data=body, headers=headers, method=method),
            timeout=10,
        ) as response:
            data = response.read()
            return json.loads(data) if data else None

    wait_for_ready(lambda: request("/health"))
    credentials = {"email": f"smoke-{secrets.token_hex(8)}@example.test", "password": secrets.token_urlsafe(32)}
    token = None
    try:
        identity = request("/v1/auth/register", "POST", credentials)
        token = request("/v1/auth/login", "POST", credentials)["access_token"]
        assert request("/v1/me", token=token)["id"] == identity["id"]
        plan = {
            "plan_name": "Synthetic smoke plan", "athlete": {},
            "workouts": [{"id": "smoke-easy", "date": "2026-12-01", "name": "Corsa facile",
                          "sport": "running", "estimated_duration_min": 30,
                          "steps": [{"type": "run", "duration_min": 30}]}],
        }
        assert request("/v1/plan", "PUT", {"expected_version": 0, "plan": plan}, token)["version"] == 1
        review = request("/v1/review/workout", token=token)
        assert review["last_workout"] is None and not review["program"]["eligible"]
        activity = {
            "source": "apple_health", "source_activity_id": "synthetic-" + secrets.token_hex(12),
            "name": "Synthetic easy smoke workout", "sport": "running", "activity_type": "running",
            "start_time": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
            "distance_m": 4000, "duration_s": 1800, "elapsed_duration_s": 1800,
            "avg_pace_s_km": 450, "avg_hr": 140, "max_hr": 150, "elevation_gain_m": 10,
        }
        imported = request("/v1/activities/import", "POST", {"activities": [activity], "ingestion_method": "client_import"}, token)
        assert imported["imported"] == 1 and imported["unique_workouts"] == 1
        latest = request("/v1/review/workout", token=token)
        assert latest["last_workout"]["source_activity_id"] == activity["source_activity_id"]
        assert latest["last_workout"]["avg_hr"] == 140 and latest["advice"]
        assert not latest["program"]["eligible"] and latest["program"]["decision"] == "keep"
        try:
            request("/v1/review/adjustments/preview", "POST", token=token)
        except urllib.error.HTTPError as error:
            with error:
                assert error.code == 409
                assert json.loads(error.read())["code"] == "adjustment_not_recommended"
        else:
            raise AssertionError("One workout must not enable a program adjustment")
        assert request("/v1/integrations", token=token)["live_vendor_connections"] == 0
        assert request("/v1/me/export", token=token)["account"]["id"] == identity["id"]
    finally:
        if token:
            request("/v1/me", "DELETE", {"password": credentials["password"], "confirmed": True}, token)
    print("Pilot smoke passed: readiness, auth, plan, import, last-workout advice, no premature adjustment, export, deletion; no live vendors")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="http://127.0.0.1:8001")
    verify(parser.parse_args().origin)
