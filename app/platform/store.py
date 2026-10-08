from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, select, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.errors import CoachError
from app.platform.tables import Athlete, Base, SchemaRevision


class PlatformStore:
    def __init__(self, settings):
        self.settings = settings
        options = {"pool_pre_ping": True, "hide_parameters": True}
        if settings.database_url.startswith("sqlite:"):
            options["connect_args"] = {"check_same_thread": False, "timeout": 30}
            if settings.database_url.endswith(":memory:"):
                options["poolclass"] = StaticPool
        else:
            options.update(
                pool_size=settings.pool_size,
                max_overflow=settings.pool_overflow,
                pool_timeout=settings.database_connect_timeout,
                connect_args={
                    "connect_timeout": settings.database_connect_timeout,
                    "options": (
                        f"-c statement_timeout={settings.database_statement_timeout_ms} "
                        f"-c lock_timeout={settings.database_lock_timeout_ms} "
                        f"-c idle_in_transaction_session_timeout={settings.database_statement_timeout_ms}"
                    ),
                },
            )
        self.engine = create_engine(settings.database_url, **options)
        if self.engine.dialect.name == "sqlite":

            @event.listens_for(self.engine, "connect")
            def configure_sqlite(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA journal_mode=WAL")

        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        # Readers use one coherent snapshot even when another worker commits an
        # import or adaptation between the plan, activity and evidence queries.
        self.read_sessions = sessionmaker(
            self.engine.execution_options(isolation_level="REPEATABLE READ")
            if self.engine.dialect.name == "postgresql"
            else self.engine,
            expire_on_commit=False,
        )

    def initialize(self):
        """Explicit initial migration. Future schema versions require new migrations."""
        if self.engine.dialect.name == "sqlite" and self.engine.url.database != ":memory:":
            Path(self.engine.url.database).parent.mkdir(parents=True, exist_ok=True)
        existing = inspect(self.engine).get_table_names()
        if existing:
            self.check_schema()
            return
        Base.metadata.create_all(self.engine)
        with self.transaction() as session:
            session.add(SchemaRevision(id=1, version=self.settings.schema_version))

    def check_schema(self):
        if not inspect(self.engine).has_table("ac_schema_revision"):
            raise RuntimeError(
                "Initialize the platform database: python -m app.platform.cli init-db"
            )
        with self.sessions() as session:
            revision = session.get(SchemaRevision, 1)
            if not revision or revision.version != self.settings.schema_version:
                raise RuntimeError(
                    "Platform database schema version does not match this application"
                )
        missing = set(Base.metadata.tables) - set(inspect(self.engine).get_table_names())
        if missing:
            raise RuntimeError("Platform database schema is incomplete")

    @contextmanager
    def transaction(self):
        with self.sessions.begin() as session:
            yield session

    @contextmanager
    def read_session(self):
        with self.read_sessions() as session:
            if self.engine.dialect.name == "sqlite":
                # sqlite3's legacy transaction mode does not BEGIN on SELECT.
                # Explicitly start a read transaction so the WAL provides a snapshot.
                session.connection().exec_driver_sql("BEGIN")
            yield session

    def lock_athlete(self, session, athlete_id):
        # This real write acquires a PostgreSQL row lock or SQLite write lock.
        # It serializes mutations across processes, including proposal application.
        result = session.execute(
            update(Athlete)
            .where(Athlete.id == athlete_id)
            .values(write_revision=Athlete.write_revision + 1)
        )
        if result.rowcount != 1:
            raise CoachError("Account unavailable", "unauthorized", 401)
        return session.scalar(
            select(Athlete)
            .where(Athlete.id == athlete_id)
            .execution_options(populate_existing=True)
        )

    def close(self):
        self.engine.dispose()
