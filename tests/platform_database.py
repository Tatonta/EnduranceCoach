"""Isolated databases for the same API tests on SQLite and real PostgreSQL."""

import os
import uuid
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy.engine import make_url


@contextmanager
def isolated_database(tmp_path):
    secret_file = os.getenv("COACH_TEST_POSTGRES_URL_FILE")
    admin_url = Path(secret_file).read_text().strip() if secret_file else os.getenv("COACH_TEST_POSTGRES_URL")
    if not admin_url:
        yield f"sqlite:///{(tmp_path / 'platform.sqlite3').as_posix()}"
        return
    import psycopg
    from psycopg import sql

    url = make_url(admin_url)
    if url.drivername != "postgresql+psycopg" or url.host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Integration tests require a dedicated, local PostgreSQL admin database")
    params = {"host": url.host, "port": url.port or 5432, "dbname": url.database,
              "user": url.username, "password": url.password, "connect_timeout": 10}
    database_name = f"coach_test_{uuid.uuid4().hex}"
    with psycopg.connect(**params, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(database_name)))
        try:
            yield url.set(database=database_name).render_as_string(hide_password=False)
        finally:
            # Only the unique database created by this context; never the supplied admin DB.
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name)))
