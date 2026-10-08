import json
import sqlite3
from contextlib import contextmanager


class Database:
    def __init__(self, path, user_id="local"):
        self.path = str(path)
        self.user_id = user_id
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS state (
                    user_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
                    PRIMARY KEY(user_id, key)
                );
                CREATE TABLE IF NOT EXISTS workouts (
                    user_id TEXT NOT NULL, plan_workout_id TEXT NOT NULL,
                    garmin_workout_id TEXT, scheduled_workout_id TEXT,
                    date TEXT NOT NULL, status TEXT NOT NULL, json_hash TEXT NOT NULL,
                    last_sync TEXT NOT NULL,
                    PRIMARY KEY(user_id, plan_workout_id)
                );
                CREATE TABLE IF NOT EXISTS activities (
                    user_id TEXT NOT NULL, activity_id TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(user_id, activity_id)
                );
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, key, default=None):
        with self.connection() as db:
            row = db.execute(
                "SELECT value FROM state WHERE user_id=? AND key=?", (self.user_id, key)
            ).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        with self.connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO state VALUES(?,?,?)", (self.user_id, key, json.dumps(value))
            )

    def rows(self):
        with self.connection() as db:
            return [
                dict(r)
                for r in db.execute("SELECT * FROM workouts WHERE user_id=?", (self.user_id,))
            ]

    def row(self, key):
        return next((r for r in self.rows() if r["plan_workout_id"] == key), None)

    def save_workout(self, **row):
        names = [
            "plan_workout_id",
            "garmin_workout_id",
            "scheduled_workout_id",
            "date",
            "status",
            "json_hash",
            "last_sync",
        ]
        with self.connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO workouts VALUES(?,?,?,?,?,?,?,?)",
                [self.user_id] + [row.get(n) for n in names],
            )

    def save_activities(self, activities):
        with self.connection() as db:
            db.executemany(
                "INSERT OR REPLACE INTO activities VALUES(?,?,?)",
                [(self.user_id, str(a["activity_id"]), json.dumps(a)) for a in activities],
            )

    def activities(self):
        with self.connection() as db:
            items = [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT payload FROM activities WHERE user_id=?", (self.user_id,)
                )
            ]
        return sorted(items, key=lambda a: a["start_time"], reverse=True)

    def delete_manual_activity(self, activity_id):
        with self.connection() as db:
            row = db.execute("SELECT payload FROM activities WHERE user_id=? AND activity_id=?", (self.user_id, activity_id)).fetchone()
            if not row or json.loads(row[0]).get("source") != "manual":
                return False
            db.execute("DELETE FROM activities WHERE user_id=? AND activity_id=?", (self.user_id, activity_id))
        return True
