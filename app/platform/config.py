import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]


def database_url_from_environment():
    direct = os.getenv("COACH_PLATFORM_DATABASE_URL")
    secret_path = os.getenv("COACH_PLATFORM_DATABASE_URL_FILE")
    if direct is not None and secret_path is not None:
        raise ValueError("Configure DATABASE_URL or DATABASE_URL_FILE, not both")
    if secret_path is not None:
        path = Path(secret_path)
        if not path.is_file() or path.stat().st_size > 4096:
            raise ValueError("Database secret file is missing or too large")
        direct = path.read_text(encoding="utf-8").strip()
    if direct is not None:
        if not direct.strip():
            raise ValueError("Database URL cannot be empty")
        return direct.strip()
    return f"sqlite:///{(ROOT / 'data/platform/coach.sqlite3').as_posix()}"


def environment_boolean(name, default):
    value = os.getenv(name, str(default)).strip().lower()
    if value not in {"true", "false"}:
        raise ValueError(f"{name} must be true or false")
    return value == "true"


def environment_integer(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        raise ValueError(f"{name} must be an integer") from None


@dataclass
class PlatformSettings:
    database_url: str = field(
        default_factory=database_url_from_environment,
        repr=False,
    )
    allowed_hosts: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            value.strip()
            for value in os.getenv(
                "COACH_PLATFORM_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver"
            ).split(",")
            if value.strip()
        )
    )
    registration_enabled: bool = field(
        default_factory=lambda: environment_boolean("COACH_PLATFORM_REGISTRATION", False)
    )
    require_https: bool = field(
        default_factory=lambda: environment_boolean("COACH_PLATFORM_REQUIRE_HTTPS", True)
    )
    session_hours: int = field(
        default_factory=lambda: environment_integer("COACH_PLATFORM_SESSION_HOURS", 24)
    )
    schema_version: int = 3
    pool_size: int = field(default_factory=lambda: environment_integer("COACH_PLATFORM_POOL_SIZE", 5))
    pool_overflow: int = field(
        default_factory=lambda: environment_integer("COACH_PLATFORM_POOL_OVERFLOW", 5)
    )
    database_connect_timeout: int = field(
        default_factory=lambda: environment_integer("COACH_PLATFORM_DB_CONNECT_TIMEOUT", 10)
    )
    database_statement_timeout_ms: int = field(
        default_factory=lambda: environment_integer("COACH_PLATFORM_DB_STATEMENT_TIMEOUT_MS", 30_000)
    )
    database_lock_timeout_ms: int = field(
        default_factory=lambda: environment_integer("COACH_PLATFORM_DB_LOCK_TIMEOUT_MS", 5_000)
    )

    def __post_init__(self):
        url = make_url(self.database_url)
        if url.drivername not in {"sqlite", "postgresql+psycopg"}:
            raise ValueError("Use sqlite for local testing or postgresql+psycopg for hosting")
        if not self.allowed_hosts or "*" in self.allowed_hosts:
            raise ValueError("Configure explicit allowed hostnames")
        if not 1 <= self.session_hours <= 168:
            raise ValueError("Session lifetime must be between one hour and seven days")
        if not 1 <= self.pool_size <= 50 or not 0 <= self.pool_overflow <= 50:
            raise ValueError("Configure a bounded database pool")
        if not 1 <= self.database_connect_timeout <= 60:
            raise ValueError("Database connection timeout must be between one and sixty seconds")
        if not 100 <= self.database_lock_timeout_ms <= self.database_statement_timeout_ms <= 120_000:
            raise ValueError("Configure bounded lock and statement timeouts")
        if url.drivername == "sqlite" and url.database and url.database != ":memory:":
            path = Path(url.database).resolve()
            if path == (ROOT / "data/coach.sqlite3").resolve():
                raise ValueError("The platform must not use the personal coach database")

    def now(self):
        return datetime.now(UTC)
