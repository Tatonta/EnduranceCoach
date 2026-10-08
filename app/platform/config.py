import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class PlatformSettings:
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "COACH_PLATFORM_DATABASE_URL",
            f"sqlite:///{(ROOT / 'data/platform/coach.sqlite3').as_posix()}",
        )
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
        default_factory=lambda: os.getenv("COACH_PLATFORM_REGISTRATION", "false").lower() == "true"
    )
    require_https: bool = field(
        default_factory=lambda: os.getenv("COACH_PLATFORM_REQUIRE_HTTPS", "true").lower() == "true"
    )
    session_hours: int = 24
    schema_version: int = 1
    pool_size: int = 5
    pool_overflow: int = 5
    database_connect_timeout: int = 10
    database_statement_timeout_ms: int = 30_000
    database_lock_timeout_ms: int = 5_000

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
