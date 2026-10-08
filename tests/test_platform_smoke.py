import pytest

from scripts.platform_smoke import wait_for_ready


def test_readiness_retries_connection_resets_before_worker_listens(monkeypatch):
    calls = []
    monkeypatch.setattr("scripts.platform_smoke.time.sleep", lambda _: None)

    def probe():
        calls.append(True)
        if len(calls) < 3:
            raise ConnectionResetError("Worker has not bound its socket yet")
        return {"status": "ok"}

    wait_for_ready(probe, attempts=3)
    assert len(calls) == 3


def test_readiness_stops_after_bounded_attempts(monkeypatch):
    calls = []
    monkeypatch.setattr("scripts.platform_smoke.time.sleep", lambda _: None)

    def probe():
        calls.append(True)
        raise ConnectionRefusedError("No listening worker")

    with pytest.raises(RuntimeError, match="ConnectionRefusedError"):
        wait_for_ready(probe, attempts=3)
    assert len(calls) == 3
