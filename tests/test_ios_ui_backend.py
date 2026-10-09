import json

import pytest
from fastapi.testclient import TestClient

from scripts.ios_ui_backend import prepare


def test_ui_backend_has_isolated_onboarding_and_context_cases(tmp_path):
    app = prepare(tmp_path, 8001)
    configuration = json.loads((tmp_path / "ui-test-access.json").read_text())
    with TestClient(app) as client:
        for account, eligible in [("first", True), ("context", False)]:
            login = client.post(
                "/v1/auth/login",
                json={"email": f"ui-{account}@example.test", "password": configuration["password"]},
            )
            assert login.status_code == 200
            headers = {"Authorization": "Bearer " + login.json()["access_token"]}
            profile = client.get("/v1/profile", headers=headers)
            if account == "first":
                assert profile.json()["code"] == "profile_required"
            else:
                assert profile.status_code == 200 and profile.json()["profile"]
            review = client.get("/v1/review/workout", headers=headers).json()
            assert review["program"]["eligible"] == eligible
            if not eligible:
                assert review["program"]["context_reasons"]
                assert len(review["detailed_review"]["analysis"]["laps"]) == 2
        assert (
            client.post(
                "/v1/auth/register",
                json={"email": "extra@example.test", "password": configuration["password"]},
            ).status_code
            == 403
        )
    with pytest.raises(ValueError, match="existing data is preserved"):
        prepare(tmp_path, 8001)
