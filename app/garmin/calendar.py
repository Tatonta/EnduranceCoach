from datetime import date

from app.garmin.client import CoachError


def months_between(start: date, end: date):
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield year, month
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def calendar_workouts(client, start, end):
    rows = {}
    for year, month in months_between(start, end):
        result = client.get_scheduled_workouts(year, month)
        if not isinstance(result, dict) or not isinstance(result.get("calendarItems"), list):
            raise CoachError(
                "Formato calendario Garmin sconosciuto: operazione bloccata", "calendar_schema"
            )
        for item in result["calendarItems"]:
            if item.get("itemType") != "workout":
                continue
            try:
                day = date.fromisoformat(str(item["date"])[:10])
            except (KeyError, ValueError):
                raise CoachError(
                    "Workout Garmin senza data valida: preview bloccata", "calendar_schema"
                ) from None
            if start <= day <= end:
                sid = item.get("id")
                if sid is None:
                    raise CoachError(
                        "Workout Garmin senza scheduled ID: preview bloccata", "calendar_schema"
                    )
                rows[str(sid)] = {
                    "date": day.isoformat(),
                    "name": item.get("title", "Workout"),
                    "scheduled_id": str(sid),
                    "workout_id": str(item.get("workoutId") or item.get("workoutID") or ""),
                    "source": "Garmin Coach"
                    if item.get("trainingPlanId") or item.get("coachId")
                    else "Garmin",
                }
    return sorted(rows.values(), key=lambda r: (r["date"], r["scheduled_id"]))
