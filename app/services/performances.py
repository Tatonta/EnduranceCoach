"""Personal running bests, with explicit provenance and verified-distance coverage."""

import math
from bisect import bisect_left, bisect_right
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.garmin.activities import normalize_activity
from app.garmin.client import CoachError
from app.services.planner import atomic_json, canonical_hash

DISTANCES = [
    ("400m", "400 m", 400, None),
    ("800m", "800 m", 800, None),
    ("1k", "1 km", 1000, 1),
    ("1500m", "1.500 m", 1500, None),
    ("mile", "1 miglio", 1609.344, 2),
    ("2k", "2 km", 2000, None),
    ("3k", "3 km", 3000, None),
    ("2miles", "2 miglia", 3218.688, None),
    ("5k", "5 km", 5000, 3),
    ("10k", "10 km", 10000, 4),
    ("15k", "15 km", 15000, None),
    ("10miles", "10 miglia", 16093.44, None),
    ("20k", "20 km", 20000, None),
    ("half", "Mezza maratona", 21097.5, 5),
    ("30k", "30 km", 30000, None),
    ("marathon", "Maratona", 42195, 6),
]


def recorded_segments(detail):
    descriptors = {d.get("key"): d.get("metricsIndex") for d in detail.get("metricDescriptors", [])}
    if "sumDistance" not in descriptors or "sumElapsedDuration" not in descriptors:
        return []
    distance_index, time_index = descriptors["sumDistance"], descriptors["sumElapsedDuration"]
    if not isinstance(distance_index, int) or not isinstance(time_index, int):
        return []
    points, segments = [], []

    def finish():
        if len(points) >= 2:
            segments.append(points[:])
        points.clear()

    for row in detail.get("activityDetailMetrics") or []:
        values = row.get("metrics") or []
        if len(values) <= max(distance_index, time_index):
            return []
        distance, elapsed = values[distance_index], values[time_index]
        if not all(
            isinstance(v, (int, float)) and math.isfinite(v) and v >= 0 for v in (distance, elapsed)
        ):
            finish()
            continue
        if points:
            dd, dt = distance - points[-1][0], elapsed - points[-1][1]
            # Broken counters, time reversal and impossible jumps cannot produce a PB.
            if dd < 0 or dt < 0 or (dt == 0 and dd > 0) or (dt > 0 and dd / dt > 15):
                finish()
            if dd == dt == 0:
                continue
        points.append((float(distance), float(elapsed)))
    finish()
    return segments


def recorded_points(detail):
    segments = recorded_segments(detail)
    return segments[0] if len(segments) == 1 else []


def fastest_recorded_effort(points, distance):
    """Minimum elapsed-time window on a piecewise linear distance/time trace.

    Check both start and finish breakpoints; checking starts alone misses optima.
    Plateaus retain pause time inside the effort while allowing a start after a stop.
    """
    if not points or points[-1][0] - points[0][0] < distance:
        return None
    distances = [p[0] for p in points]
    best = None

    def accept(seconds):
        nonlocal best
        if seconds > 0 and (best is None or seconds < best):
            best = seconds

    for start_d, start_t in points:
        target = start_d + distance
        j = bisect_left(distances, target)
        if j >= len(points):
            continue
        end_d, end_t = points[j]
        if end_d != target:
            prior_d, prior_t = points[j - 1]
            end_t = prior_t + (end_t - prior_t) * (target - prior_d) / (end_d - prior_d)
        accept(end_t - start_t)
    for end_d, end_t in points:
        target = end_d - distance
        i = bisect_right(distances, target) - 1
        if i < 0:
            continue
        start_d, start_t = points[i]
        if start_d != target:
            next_d, next_t = points[i + 1]
            start_t += (next_t - start_t) * (target - start_d) / (next_d - start_d)
        accept(end_t - start_t)
    return best


def reported_efforts(raw):
    result = {}
    for key, _, meters, _ in DISTANCES:
        # Garmin's common split keys use rounded meters for miles and half marathon.
        candidates = {int(meters), round(meters)}
        values = [raw.get(f"fastestSplit_{m}") for m in candidates]
        valid = [v for v in values if isinstance(v, (int, float)) and math.isfinite(v) and v > 0]
        if valid:
            result[key] = min(valid)
    return result


class PerformanceService:
    def __init__(self, settings, db, client):
        self.settings, self.db, self.client = settings, db, client

    def history(self):
        history, seen = [], set()
        for page in range(100):
            batch = self.client.get_activities(page * 100, 100, "running")
            if not isinstance(batch, list):
                raise CoachError("Storico corsa Garmin non leggibile", "history_schema")
            for raw in batch:
                activity = normalize_activity(raw, self.settings.timezone)
                if activity["sport"] == "running" and activity["activity_id"] not in seen:
                    seen.add(activity["activity_id"])
                    history.append((activity, raw))
            if len(batch) < 100:
                return history
        raise CoachError(
            "Storico oltre 10.000 corse: analisi incompleta bloccata", "history_incomplete"
        )

    def refresh(self, deep=True):
        previous = self.db.get("performance_activity_efforts", {})
        cache, history = {}, self.history()
        self.db.set("performance_history", [a for a, _ in history])
        personal = self.client.get_personal_record()
        if not isinstance(personal, list):
            raise CoachError("Formato record Garmin sconosciuto", "records_schema")
        reported, calculated, missing_details = {}, {}, []

        def candidate(store, key, seconds, activity, source):
            if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0:
                return
            row = {
                "duration_s": seconds,
                "activity_id": activity["activity_id"],
                "activity_name": activity["name"],
                "date": activity["date"],
                "source": source,
            }
            if key not in store or seconds < store[key]["duration_s"]:
                store[key] = row

        for index, (activity, raw) in enumerate(history):
            aid = activity["activity_id"]
            self.db.set("performance_progress", {"current": index + 1, "total": len(history)})
            for key, seconds in reported_efforts(raw).items():
                candidate(reported, key, seconds, activity, "Garmin best split")
            version = canonical_hash(
                {
                    "algorithm_version": 2,
                    "distance": activity["distance_m"],
                    "duration": activity["duration_s"],
                    "updated": raw.get("updateDate"),
                    "split": reported_efforts(raw),
                }
            )
            cached = previous.get(aid)
            if cached and cached.get("version") == version and cached.get("available"):
                cache[aid] = cached
            elif deep:
                try:
                    detail = self.client.get_activity_details(aid, maxchart=100000, maxpoly=0)
                    segments = recorded_segments(detail)
                    efforts = {
                        key: min(values)
                        for key, _, meters, _ in DISTANCES
                        if (
                            values := [
                                seconds
                                for points in segments
                                if (seconds := fastest_recorded_effort(points, meters)) is not None
                            ]
                        )
                    }
                    cache[aid] = {
                        "version": version,
                        "efforts": efforts,
                        "samples": sum(len(points) for points in segments),
                        "sample_segments": len(segments),
                        "measurement_count": detail.get("measurementCount"),
                        "available": bool(segments),
                    }
                except CoachError:
                    cache[aid] = {"version": version, "efforts": {}, "available": False}
            if aid not in cache or not cache[aid].get("available"):
                missing_details.append(aid)
            for key, seconds in cache.get(aid, {}).get("efforts", {}).items():
                candidate(calculated, key, seconds, activity, "Campioni Garmin · tempo trascorso")

        pr_types = {record_type: key for key, _, _, record_type in DISTANCES if record_type}
        for raw in personal:
            if (
                raw.get("activityType") != "running"
                or raw.get("status") != "ACCEPTED"
                or raw.get("typeId") not in pr_types
            ):
                continue
            local = raw.get("activityStartDateTimeLocalFormatted")
            if local:
                day = str(local)[:10]
            elif raw.get("activityStartDateTimeInGMT"):
                day = (
                    datetime.fromtimestamp(raw["activityStartDateTimeInGMT"] / 1000, UTC)
                    .astimezone(ZoneInfo(self.settings.timezone))
                    .date()
                    .isoformat()
                )
            else:
                continue
            activity = {
                "activity_id": str(raw.get("activityId") or ""),
                "name": raw.get("activityName") or "Record Garmin",
                "date": day,
            }
            candidate(
                reported,
                pr_types[raw["typeId"]],
                raw.get("value"),
                activity,
                "Record personale Garmin",
            )

        rows = []
        for key, label, meters, _ in DISTANCES:
            result = reported.get(key) or calculated.get(key)
            rows.append(
                {
                    "distance_key": key,
                    "distance_label": label,
                    "distance_m": meters,
                    "available": result is not None,
                    **(result or {}),
                    "avg_pace_s_km": result["duration_s"] / meters * 1000 if result else None,
                }
            )
        snapshot = {
            "generated_at": self.settings.now().isoformat(),
            "rows": rows,
            "coverage": {
                "running_activities": len(history),
                "history_complete": True,
                "oldest_date": min((a["date"] for a, _ in history), default=None),
                "details_missing": len(missing_details),
                "details_complete": not missing_details,
                "activities_with_sample_breaks": sum(
                    v.get("sample_segments", 1) > 1 for v in cache.values()
                ),
            },
            "note": "Migliori tratti, non necessariamente gare. I best split riportati da Garmin hanno priorità; le altre distanze sono calcolate dai campioni registrati con tempo trascorso e interpolazione. I tratti che attraversano salti GPS o contatori incoerenti sono esclusi. Non sono record certificati.",
        }
        self.db.set("performance_activity_efforts", cache)
        self.db.set("performances", snapshot)
        self.db.set("performance_progress", None)
        atomic_json(self.settings.data_dir / "best_performances.json", self.latest(snapshot))
        return self.latest(snapshot)

    def latest(self, snapshot=None):
        snapshot = (
            snapshot
            or self.db.get("performances")
            or {
                "generated_at": None,
                "rows": [
                    {
                        "distance_key": key,
                        "distance_label": label,
                        "distance_m": meters,
                        "available": False,
                    }
                    for key, label, meters, _ in DISTANCES
                ],
                "coverage": None,
            }
        )
        rows = []
        for row in snapshot["rows"]:
            aid = row.get("activity_id")
            rows.append(
                {
                    **row,
                    "garmin_url": f"https://connect.garmin.com/modern/activity/{aid}"
                    if aid and aid.isdigit() and int(aid) > 0
                    else None,
                }
            )
        return {**snapshot, "rows": rows, "progress": self.db.get("performance_progress")}
