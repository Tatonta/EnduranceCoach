"""Smoke test a disposable private pilot; never run this against real athlete accounts."""

import argparse
import json
import secrets
import time
import urllib.error
import urllib.request
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
        assert request("/v1/integrations", token=token)["live_vendor_connections"] == 0
        assert request("/v1/me/export", token=token)["account"]["id"] == identity["id"]
    finally:
        if token:
            request("/v1/me", "DELETE", {"password": credentials["password"], "confirmed": True}, token)
    print("Pilot smoke passed: readiness, auth, plan, conservative review, export, deletion; no live vendors")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="http://127.0.0.1:8001")
    verify(parser.parse_args().origin)
