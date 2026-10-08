from pathlib import Path
from types import SimpleNamespace

import pytest
from garminconnect.exceptions import GarminConnectAuthenticationError

from app.garmin.client import CoachError, GarminClient


def test_persistent_login_and_reuse(monkeypatch):
    calls = []

    class Session:
        def login(self, path):
            calls.append(path)

        def get_activities(self, start, limit):
            return []

    monkeypatch.setattr("app.garmin.client.Garmin", lambda: Session())
    adapter = GarminClient(Path("outside-repository"))
    assert adapter.login() is adapter
    adapter.login()
    assert adapter.get_activities(0, 20) == []
    assert calls == ["outside-repository"]
    with pytest.raises(AttributeError):
        adapter.delete_workout(1)


def test_missing_tokens_never_prompt_in_web(monkeypatch):
    class Session:
        def login(self, path):
            raise GarminConnectAuthenticationError("private-provider-data")

    monkeypatch.setattr("app.garmin.client.Garmin", lambda: Session())

    def forbidden(*args):
        raise AssertionError("Unexpected interactive prompt")

    monkeypatch.setattr("builtins.input", forbidden)
    with pytest.raises(CoachError) as exc:
        GarminClient(Path("outside")).login()
    assert exc.value.code == "login_required"
    assert "private-provider-data" not in str(exc.value)


def test_interactive_password_mfa_hidden_and_tokens_saved(monkeypatch, capsys):
    calls = []

    class Session:
        def __init__(self, email=None, password=None, prompt_mfa=None):
            self.email, self.password, self.prompt_mfa = email, password, prompt_mfa
            self.client = SimpleNamespace(dump=lambda path: calls.append(("saved", path)))

        def login(self, path=None):
            if not self.email:
                raise GarminConnectAuthenticationError("expired")
            calls.append(("mfa", self.prompt_mfa()))

    monkeypatch.setattr("app.garmin.client.Garmin", Session)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "test-user")
    values = iter(["PASSWORD_SENTINEL", "MFA_SENTINEL"])
    monkeypatch.setattr("app.garmin.client.getpass", lambda prompt: next(values))
    adapter = GarminClient(Path("outside"))
    adapter.login(interactive=True)
    assert calls == [("mfa", "MFA_SENTINEL"), ("saved", "outside")]
    assert adapter.client.password is None
    output = capsys.readouterr()
    assert "SENTINEL" not in output.out + output.err
