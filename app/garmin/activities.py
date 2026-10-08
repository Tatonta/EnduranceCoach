from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.garmin.client import CoachError


def normalize_activity(raw, tz="Europe/Rome"):
    kind = (raw.get("activityType") or {}).get("typeKey", "unknown")
    sport_id = raw.get("sportTypeId") or (raw.get("activityType") or {}).get("parentTypeId")
    sport = (
        "running"
        if "running" in kind or sport_id == 1
        else "cycling"
        if "biking" in kind or "cycling" in kind or sport_id == 2
        else "strength"
        if "strength" in kind
        else "other"
    )
    stamp = raw.get("startTimeGMT")
    if stamp:
        start = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        start = start.astimezone(ZoneInfo(tz))
    else:
        start = datetime.fromisoformat(raw["startTimeLocal"]).replace(tzinfo=ZoneInfo(tz))
    speed = raw.get("averageSpeed") or 0
    return {
        "activity_id": str(raw["activityId"]),
        "source": "garmin",
        "source_activity_id": str(raw["activityId"]),
        "name": raw.get("activityName", kind),
        "sport": sport,
        "activity_type": kind,
        "start_time": start.isoformat(),
        "date": start.date().isoformat(),
        "distance_m": raw.get("distance") or 0,
        "duration_s": raw.get("duration") or 0,
        "elapsed_duration_s": raw.get("elapsedDuration") or raw.get("duration") or 0,
        "avg_pace_s_km": 1000 / speed if speed > 0 and sport == "running" else None,
        "avg_hr": raw.get("averageHR") or None,
        "max_hr": raw.get("maxHR") or None,
        "elevation_gain_m": raw.get("elevationGain"),
        "training_load": raw.get("activityTrainingLoad"),
        "aerobic_training_effect": raw.get("aerobicTrainingEffect"),
        "workout_id": str(raw.get("workoutId") or ""),
    }


def fetch_recent_activities(client, now, earliest=None, max_pages=20):
    earliest = earliest or now.date() - timedelta(days=42)
    activities = {}
    for page in range(max_pages):
        raw = client.get_activities(page * 100, 100)
        if not isinstance(raw, list):
            raise CoachError("Formato attività Garmin sconosciuto", "activities_schema")
        batch = [normalize_activity(a, str(now.tzinfo)) for a in raw]
        for activity in batch:
            if earliest.isoformat() <= activity["date"] <= now.date().isoformat():
                activities[activity["activity_id"]] = activity
        if len(raw) < 100 or any(a["date"] < earliest.isoformat() for a in batch):
            return sorted(activities.values(), key=lambda a: a["start_time"], reverse=True)
    raise CoachError(
        "Storico attività oltre il limite di paginazione: aumentare il limite prima della review",
        "activities_incomplete",
    )
