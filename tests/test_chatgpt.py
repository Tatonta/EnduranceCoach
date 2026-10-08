import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.errors import CoachError
from app.services.chatgpt import ISSUER, ChatGPTService, LocalVault


class Response:
    status_code = 200
    def __init__(self, data=None, events=None):
        self.data, self.events = data or {}, events or []
    def json(self):
        return self.data
    def __enter__(self):
        return self
    def __exit__(self, *_):
        pass
    def iter_lines(self):
        for event in self.events:
            yield b"data: " + json.dumps(event).encode()


@pytest.fixture
def service(tmp_path):
    return ChatGPTService(SimpleNamespace(data_dir=tmp_path, port=8000))


def test_registration_uses_persistent_host_pkce_and_never_an_api_key(service):
    url, state = service.start()
    args = parse_qs(urlsplit(url).query)
    assert args["client_id"] == ["dynamic_agent_client"]
    assert args["agent_name_hint"] == ["EnduranceCoach"]
    assert args["redirect_uri"] == ["http://127.0.0.1:8000/auth/callback"]
    assert args["code_challenge_method"] == ["S256"]
    assert "chatgpt.tokens.use.direct" in args["scope"][0]
    first = service.vault.read()
    assert first["pending"]["state"] == state
    service.start()
    assert service.vault.read()["host_id"] == first["host_id"]
    assert "api_key" not in args and "code_verifier" not in args


def test_id_token_checks_signature_audience_nonce_and_expiry(service, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr("app.services.chatgpt.jwt.PyJWKClient", lambda *a, **k: SimpleNamespace(get_signing_key_from_jwt=lambda _: SimpleNamespace(key=key.public_key())))
    payload = {"iss": ISSUER, "sub": "synthetic-subject", "aud": "oaiapp_synthetic", "nonce": "expected", "iat": int(time.time()), "exp": int(time.time()) + 300}
    token = jwt.encode(payload, key, algorithm="RS256")
    assert service.validate_identity(token, "oaiapp_synthetic", "expected")["sub"] == "synthetic-subject"
    for audience, nonce in [("other-client", "expected"), ("oaiapp_synthetic", "wrong")]:
        with pytest.raises(CoachError):
            service.validate_identity(token, audience, nonce)
    expired = jwt.encode({**payload, "exp": int(time.time()) - 60}, key, algorithm="RS256")
    with pytest.raises(CoachError):
        service.validate_identity(expired, "oaiapp_synthetic", "expected")


def test_callback_rejects_bad_state_and_unauthorized_plan_use(service, monkeypatch):
    _, state = service.start()
    with pytest.raises(CoachError):
        service.callback({"state": "wrong", "code": "unused", "client_id": "oaiapp_synthetic"}, state)
    monkeypatch.setattr(service, "token_request", lambda _: {"access_token": "synthetic-token", "id_token": "synthetic-id", "scope": "openid email"})
    monkeypatch.setattr(service, "validate_identity", lambda *a: {"sub": "synthetic", "email": "user@example.test"})
    query = {"state": state, "code": "synthetic-code", "client_id": "oaiapp_synthetic"}
    service.callback(query, state)
    assert service.status()["connected"]
    assert not service.status()["plan_enabled"]
    assert not service.status()["welcome_required"]
    with pytest.raises(CoachError):
        service.access()
    with pytest.raises(CoachError):
        service.callback(query, state)


def connected(service):
    with service.vault.lock:
        data = service.vault.read()
        data["profiles"]["profile"] = {"client_id": "oaiapp_synthetic", "subject": "synthetic", "access_token": "synthetic-private-token",
            "refresh_token": "synthetic-refresh", "scopes": ["chatgpt.tokens.use.direct"], "expires_at": time.time() + 3600}
        data["active"] = "profile"
        service.vault.write(data)


def test_completed_stream_required_and_preview_contract_is_supported(service, monkeypatch):
    connected(service)
    monkeypatch.setattr(service, "models", lambda: [{"id": "available-model", "name": "Available"}])
    sent = []
    def post(_, **args):
        sent.append(args)
        return Response(events=[{"type": "response.output_text.delta", "delta": "Una review misurata."}, {"type": "response.completed"}])
    service.http = SimpleNamespace(post=post)
    answer = service.review({"analysis": {"positive": ["Target rispettato"]}}, "available-model")
    assert answer["text"] == "Una review misurata."
    body = sent[0]["json"]
    assert body["store"] is False and body["stream"] is True
    assert isinstance(body["input"], list)
    assert not set(body) & {"max_output_tokens", "temperature", "conversation", "previous_response_id", "prompt"}
    service.http = SimpleNamespace(post=lambda *a, **k: Response(events=[{"type": "response.output_text.delta", "delta": "Parziale"}]))
    with pytest.raises(CoachError):
        service.review({}, "available-model")


def test_status_never_returns_credentials_and_revocation_clears_locally(service):
    connected(service)
    assert "synthetic-private-token" not in json.dumps(service.status())
    service.http = SimpleNamespace(post=lambda *a, **k: SimpleNamespace(status_code=503))
    assert not service.disconnect()["remote_revoked"]
    assert not service.status()["connected"]
    stored = service.vault.read()["profiles"]["profile"]
    assert not set(stored) & {"access_token", "refresh_token", "id_token"}


def test_vault_roundtrip_and_protected_storage(tmp_path):
    vault = LocalVault(tmp_path)
    with vault.lock:
        data = vault.read()
        data["sample"] = "synthetic-only-sensitive-value"
        vault.write(data)
        assert vault.read()["sample"] == data["sample"]
    import os
    if os.name == "nt":
        assert b"synthetic-only-sensitive-value" not in vault.path.read_bytes()
    else:
        assert vault.path.stat().st_mode & 0o077 == 0
