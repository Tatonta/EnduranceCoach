"""Create local Compose secrets without printing them or overwriting an existing setup."""

import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def prepare(root=ROOT):
    directory = root / "data" / "deployment"
    directory.mkdir(parents=True, exist_ok=True)
    password_path, url_path = directory / "postgres-password.txt", directory / "database-url.txt"
    if password_path.exists() or url_path.exists():
        raise ValueError("Pilot secrets already exist; preserve them and the associated database")
    password = secrets.token_urlsafe(40)
    # token_urlsafe characters are safe in a URL userinfo password component.
    values = {password_path: password, url_path: f"postgresql+psycopg://coach:{password}@db:5432/endurance_coach"}
    for path, value in values.items():
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o444)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value + "\n")
    # Compose bind-mounted secrets preserve host modes. This directory is owner-only
    # on Unix; individual read-only files remain readable by the non-root container UID.
    if os.name != "nt":
        directory.chmod(0o700)
    return directory


if __name__ == "__main__":
    try:
        directory = prepare()
    except ValueError as error:
        raise SystemExit(str(error)) from None
    print(f"Created private pilot secret files in {directory}; contents were not printed.")
    print("On Windows, restrict this directory to your account before sharing the machine.")
