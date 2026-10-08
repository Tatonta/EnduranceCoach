import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


@dataclass
class Settings:
    data_dir: Path = field(
        default_factory=lambda: Path(os.getenv("COACH_DATA_DIR", str(ROOT / "data")))
    )
    token_dir: Path = field(
        default_factory=lambda: Path(os.getenv("GARMIN_TOKEN_DIR", "~/.garminconnect")).expanduser()
    )
    user_id: str = "local"
    timezone: str = field(default_factory=lambda: os.getenv("COACH_TIMEZONE", "Europe/Rome"))
    port: int = field(default_factory=lambda: int(os.getenv("COACH_PORT", "8000")))
    scheduler_enabled: bool = field(
        default_factory=lambda: os.getenv("COACH_SCHEDULER", "true").lower() == "true"
    )
    startup_refresh: bool = field(
        default_factory=lambda: os.getenv("COACH_STARTUP_REFRESH", "true").lower() == "true"
    )

    def __post_init__(self):
        if not self.data_dir.is_absolute():
            self.data_dir = ROOT / self.data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def now(self):
        return datetime.now(ZoneInfo(self.timezone))

    @property
    def plan_path(self):
        return self.data_dir / "workouts.json"
