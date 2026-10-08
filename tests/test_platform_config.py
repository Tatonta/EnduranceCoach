import pytest

pytest.importorskip("sqlalchemy")

from app.platform.config import PlatformSettings
from scripts.prepare_private_pilot import prepare


def test_database_secret_file_and_no_url_in_repr(tmp_path, monkeypatch):
    secret = tmp_path / "database.txt"
    secret.write_text("postgresql+psycopg://test:synthetic-only-secret@localhost/test\n")
    monkeypatch.delenv("COACH_PLATFORM_DATABASE_URL", raising=False)
    monkeypatch.setenv("COACH_PLATFORM_DATABASE_URL_FILE", str(secret))
    settings = PlatformSettings()
    assert settings.database_url.endswith("@localhost/test")
    assert "synthetic-only-secret" not in repr(settings)
    monkeypatch.setenv("COACH_PLATFORM_DATABASE_URL", "sqlite:///:memory:")
    with pytest.raises(ValueError, match="not both"):
        PlatformSettings()


@pytest.mark.parametrize("contents", ["", "x" * 4097])
def test_invalid_database_secret_file_fails_closed(tmp_path, monkeypatch, contents):
    secret = tmp_path / "database.txt"
    secret.write_text(contents)
    monkeypatch.delenv("COACH_PLATFORM_DATABASE_URL", raising=False)
    monkeypatch.setenv("COACH_PLATFORM_DATABASE_URL_FILE", str(secret))
    with pytest.raises(ValueError):
        PlatformSettings()


def test_mistyped_https_setting_does_not_disable_https(monkeypatch):
    monkeypatch.setenv("COACH_PLATFORM_REQUIRE_HTTPS", "enabled")
    with pytest.raises(ValueError, match="true or false"):
        PlatformSettings()


def test_bounded_pool_configuration_from_environment(monkeypatch):
    monkeypatch.setenv("COACH_PLATFORM_POOL_SIZE", "3")
    monkeypatch.setenv("COACH_PLATFORM_POOL_OVERFLOW", "2")
    settings = PlatformSettings()
    assert settings.pool_size == 3 and settings.pool_overflow == 2
    monkeypatch.setenv("COACH_PLATFORM_POOL_SIZE", "1000")
    with pytest.raises(ValueError, match="bounded"):
        PlatformSettings()


def test_pilot_setup_never_replaces_existing_database_credentials(tmp_path):
    directory = prepare(tmp_path)
    original = (directory / "postgres-password.txt").read_bytes()
    with pytest.raises(ValueError, match="preserve"):
        prepare(tmp_path)
    assert (directory / "postgres-password.txt").read_bytes() == original
