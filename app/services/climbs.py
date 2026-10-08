"""Named Climbfinder routes and comparable elapsed times from Garmin GPS data."""

import math
from bisect import bisect_left
from collections import defaultdict

from app.garmin.activities import normalize_activity
from app.garmin.client import CoachError
from app.services.climb_catalog import load_catalog
from app.services.geography import Geography
from app.services.planner import atomic_json, canonical_hash

NOTE = "Solo salite nominate nel catalogo Climbfinder, con partenza, arrivo, direzione e distanza compatibili. I tempi sono stime GPS Garmin e includono le soste. I passaggi con perdita del segnale sono indicati come GPS parziale: almeno l’85% dei campioni deve corrispondere al percorso; gli altri devono coincidere con anomalie del segnale riconoscibili. La velocità media usa la distanza Garmin del passaggio e il tempo trascorso. Ogni variante ha il suo miglior tempo. Lunghezza, dislivello e quota di arrivo provengono dal catalogo; il profilo registrato proviene da Garmin."
ANCHOR_RADIUS_M = 60


def data_gap(a, b):
    """A long stop is not a missing road section: use recorded distance too."""
    return b[0] - a[0] > 250 or (
        b[1] - a[1] > 60 and b[0] - a[0] > 100 and haversine(a[3:5], b[3:5]) > 100
    )


def gps_segment(a, b):
    """Do not draw/interpolate across GPS reacquisition jumps or large gaps."""
    separation = haversine(a[3:5], b[3:5])
    dd, dt = b[0] - a[0], b[1] - a[1]
    return (
        not data_gap(a, b)
        and separation <= max(80, dd * 1.75 + 35)
        and not (dt > 0 and separation / dt > 40)
    )


def gps_uncertainty_span(trace, i):
    """Find a dead-reckoned straight run ending in a GPS reacquisition jump.

    A straight road alone is never sufficient: an invalid GPS edge must follow,
    and at least eight preceding positions must be collinear within 50 cm.
    """
    a, b = trace[i], trace[i + 1]
    low = a[0]
    if i:
        scale = math.cos(math.radians(a[3]))
        dx = (a[4] - trace[i - 1][4]) * scale * 111195
        dy = (a[3] - trace[i - 1][3]) * 111195
        size = math.hypot(dx, dy)
        j = i - 1
        if size > 0.1:
            while j >= 0 and a[0] - trace[j][0] <= 2000:
                x = (trace[j][4] - a[4]) * scale * 111195
                y = (trace[j][3] - a[3]) * 111195
                if abs(dx * y - dy * x) / size > 0.5 or dx * x + dy * y > 0:
                    break
                j -= 1
            if i - j >= 8 and a[0] - trace[j + 1][0] >= 100:
                low = trace[j + 1][0]
    return low, b[0]


class TraceIndex:
    """Index valid GPS segments in ~100 m cells for local route matching."""

    def __init__(self, trace):
        self.trace = trace
        self.grid = defaultdict(list)
        self.distances = [p[0] for p in trace]
        self.gps_issues = []
        for i, (a, b) in enumerate(zip(trace, trace[1:], strict=False)):
            if not gps_segment(a, b):
                if not data_gap(a, b):
                    self.gps_issues.append(gps_uncertainty_span(trace, i))
                continue
            x0, y0 = self.cell(a[3:5])
            x1, y1 = self.cell(b[3:5])
            for x in range(min(x0, x1), max(x0, x1) + 1):
                for y in range(min(y0, y1), max(y0, y1) + 1):
                    self.grid[x, y].append(i)

    @staticmethod
    def cell(point):
        return math.floor(point[1] * 800), math.floor(point[0] * 1112)

    def nearby(self, target, low=-math.inf, high=math.inf, radius=40):
        x, y = self.cell(target)
        indices = {
            i for dx in (-1, 0, 1) for dy in (-1, 0, 1) for i in self.grid.get((x + dx, y + dy), [])
        }
        found = []
        scale = math.cos(math.radians(target[0]))
        for i in indices:
            a, b = self.trace[i], self.trace[i + 1]
            if b[0] < low or a[0] > high:
                continue
            ax, ay = (a[4] - target[1]) * scale, a[3] - target[0]
            bx, by = (b[4] - target[1]) * scale, b[3] - target[0]
            dx, dy = bx - ax, by - ay
            ratio = max(0, min(1, -(ax * dx + ay * dy) / (dx * dx + dy * dy))) if dx or dy else 0
            point = [u + ratio * (v - u) for u, v in zip(a, b, strict=True)]
            separation = haversine(target, point[3:5])
            if separation <= radius and low <= point[0] <= high:
                found.append((separation, point))
        return sorted(found, key=lambda item: item[1][0])


def anchor_passages(index, target):
    clusters = []
    for candidate in index.nearby(target, radius=ANCHOR_RADIUS_M):
        if clusters and candidate[1][0] - clusters[-1][-1][1][0] < 100:
            clusters[-1].append(candidate)
        else:
            clusters.append([candidate])
    return [min(cluster, key=lambda c: c[0])[1] for cluster in clusters]


def bounded_gps_misses(misses, count, index, start, end, reference_length):
    """Only tolerate short GPS-corrupted spans, never unexplained missing road."""
    if not misses:
        return True
    if len(misses) / max(1, count) > 0.15:
        return False
    streak = 0
    previous = -math.inf
    for d in misses:
        streak = streak + 100 if d - previous <= 100.01 else 100
        previous = d
        if streak > 2000:
            return False
        ridden_d = start + d / reference_length * (end - start)
        if not any(low - 300 <= ridden_d <= high + 300 for low, high in index.gps_issues):
            return False
    return True


def catalog_attempts(climb, index):
    """Match full catalog geometry, ordered direction, and repeat passages."""
    path = climb["path"]
    cumulative = [0.0]
    for a, b in zip(path, path[1:], strict=False):
        cumulative.append(cumulative[-1] + haversine(a, b))
    geometry_length = cumulative[-1]
    if geometry_length < 50:
        return []
    route = [[d, 0, 0, *p] for d, p in zip(cumulative, path, strict=True)]
    samples = [
        interpolate(route, cumulative, d)[3:5] for d in range(0, int(geometry_length), 100)
    ] + [path[-1]]
    matches = []
    for start in anchor_passages(index, path[0]):
        for end in anchor_passages(index, path[-1]):
            length = end[0] - start[0]
            if length <= 0 or abs(length / climb["distance_m"] - 1) > 0.08:
                continue
            if end[2] - start[2] < max(10, climb["gain_m"] * 0.3):
                continue
            # Reference samples must occur in order; GPS exceptions are bounded.
            previous = start[0]
            missing_reference = []
            for sample_number, target in enumerate(samples[1:-1], 1):
                candidates = index.nearby(target, previous - 25, end[0], radius=60)
                expected = start[0] + sample_number * 100 / geometry_length * length
                if any(low <= expected <= high for low, high in index.gps_issues):
                    # A reconstructed straight line can touch a later hairpin.
                    # Avoid advancing past the actual GPS reacquisition point.
                    candidates = [c for c in candidates if abs(c[1][0] - expected) <= 300]
                if not candidates:
                    missing_reference.append(sample_number * 100)
                    continue
                nearest = min(candidates, key=lambda c: c[0])[1]
                previous = max(previous, nearest[0])
            if bounded_gps_misses(
                missing_reference, len(samples) - 2, index, start[0], end[0], geometry_length
            ):
                ridden = [start] + [p for p in index.trace if start[0] < p[0] < end[0]] + [end]
                if any(data_gap(a, b) for a, b in zip(ridden, ridden[1:], strict=False)):
                    continue
                # Also reject excursions/shortcuts absent from the catalog route.
                route_index = TraceIndex(route)
                missing_ridden = []
                for d in range(0, int(length), 100):
                    p = index.trace[
                        min(bisect_left(index.distances, start[0] + d), len(index.trace) - 1)
                    ]
                    if not route_index.nearby(p[3:5], radius=60):
                        missing_ridden.append(d)
                if not bounded_gps_misses(
                    missing_ridden, math.ceil(length / 100), index, start[0], end[0], length
                ):
                    continue
                if end[1] > start[1]:
                    matches.append(
                        {
                            "duration_s": end[1] - start[1],
                            "distance_m": length,
                            "avg_speed_kmh": length / (end[1] - start[1]) * 3.6,
                            "gps_coverage_pct": 100
                            * min(
                                1 - len(missing_reference) / max(1, len(samples) - 2),
                                1 - len(missing_ridden) / math.ceil(length / 100),
                            ),
                            "gps_tolerance_used": bool(missing_reference or missing_ridden),
                            "start_elapsed_s": start[1],
                            "end_elapsed_s": end[1],
                            "trace": ridden,
                        }
                    )
                break
    return matches


def haversine(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    value = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 6371000 * 2 * math.asin(min(1, math.sqrt(value)))


def cycling_traces(detail):
    keys = [
        "sumDistance",
        "sumElapsedDuration",
        "directElevation",
        "directLatitude",
        "directLongitude",
    ]
    indices = {d.get("key"): d.get("metricsIndex") for d in detail.get("metricDescriptors", [])}
    if not all(isinstance(indices.get(key), int) and indices[key] >= 0 for key in keys):
        return []
    traces, points, missing_gps = [], [], False

    def finish():
        if len(points) >= 3:
            traces.append(points[:])
        points.clear()

    for raw in detail.get("activityDetailMetrics", []):
        values = raw.get("metrics") or []
        if len(values) <= max(indices[key] for key in keys):
            finish()
            continue
        point = [values[indices[key]] for key in keys]
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in point[:3]):
            finish()
            continue
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in point[3:]):
            missing_gps = True
            continue
        d, t, z, lat, lon = point
        if (
            d < 0
            or t < 0
            or not (-500 <= z <= 9000 and -90 <= lat <= 90 and -180 <= lon <= 180)
            or (lat == lon == 0)
        ):
            finish()
            continue
        if points:
            previous = points[-1]
            dd, dt = d - previous[0], t - previous[1]
            separation = haversine(point[3:5], previous[3:5])
            if missing_gps and not (
                0 <= dd <= 150 and separation <= 250 and (dt <= 60 or dd <= 50)
            ):
                finish()
            if (
                dd < 0
                or dt < 0
                or (dt == 0 and (dd > 0 or separation > 5))
                or (dt > 0 and dd / dt > 40)
                or (dt > 0 and separation / dt > 40 and (separation > 600 or dd > 50 or dt > 15))
            ):
                finish()
            elif dd == 0:
                # Keep both sides of a stop: subsequent timing includes the pause.
                points.append(point)
                missing_gps = False
                continue
        missing_gps = False
        points.append(point)
    finish()
    return traces


def interpolate(points, distances, distance):
    index = bisect_left(distances, distance)
    if index == 0:
        return points[0][:]
    if index >= len(points):
        return points[-1][:]
    left, right = points[index - 1], points[index]
    ratio = (distance - left[0]) / (right[0] - left[0]) if right[0] > left[0] else 0
    return [distance] + [a + (b - a) * ratio for a, b in zip(left[1:], right[1:], strict=True)]


class ClimbService:
    def __init__(self, settings, db, client, geography=None):
        self.settings, self.db, self.client = settings, db, client
        self.geography = geography or Geography()

    def history(self):
        seen, history = set(), []
        for page in range(100):
            batch = self.client.get_activities(page * 100, 100, "cycling")
            if not isinstance(batch, list):
                raise CoachError("Storico bici Garmin non leggibile", "cycling_schema")
            for raw in batch:
                activity = normalize_activity(raw, self.settings.timezone)
                if activity["sport"] == "cycling" and activity["activity_id"] not in seen:
                    history.append((activity, raw))
                    seen.add(activity["activity_id"])
            if len(batch) < 100:
                return sorted(history, key=lambda pair: pair[0]["start_time"])
        raise CoachError(
            "Storico oltre 10.000 uscite: analisi incompleta bloccata", "cycling_incomplete"
        )

    def refresh(self):
        try:
            catalog = load_catalog(self.settings.data_dir / "climbfinder-catalog.json")
        except (ValueError, TypeError, KeyError, OSError):
            raise CoachError(
                "Catalogo Climbfinder locale non leggibile: controlla il file di importazione",
                "climb_catalog",
                503,
            ) from None
        history, previous = self.history(), self.db.get("cycling_trace_cache", {})
        cache, groups, missing, matched_rides = {}, {}, [], set()
        for index, (activity, raw) in enumerate(history):
            aid = activity["activity_id"]
            self.db.set("climb_progress", {"current": index + 1, "total": len(history)})
            version = canonical_hash(
                {
                    "algorithm": 3,
                    "distance": activity["distance_m"],
                    "elapsed": activity["elapsed_duration_s"],
                    "updated": raw.get("updateDate"),
                }
            )
            stored = previous.get(aid)
            if stored and stored.get("version") == version and stored.get("available"):
                cache[aid] = stored
            else:
                try:
                    traces = cycling_traces(
                        self.client.get_activity_details(aid, maxchart=100000, maxpoly=0)
                    )
                    cache[aid] = {"version": version, "available": bool(traces), "traces": traces}
                except CoachError:
                    cache[aid] = {"version": version, "available": False, "traces": []}
                # Incremental cache survives an interrupted first import.
                self.db.set("cycling_trace_cache", {**previous, **cache})
            if not cache[aid]["available"]:
                missing.append(aid)
            for trace in cache[aid]["traces"]:
                ride_index = TraceIndex(trace)
                for climb in catalog["rows"]:
                    if not ride_index.nearby(climb["path"][0], radius=ANCHOR_RADIUS_M):
                        continue
                    for matched in catalog_attempts(climb, ride_index):
                        attempt = {
                            "activity_id": aid,
                            "activity_name": activity["name"],
                            "date": activity["date"],
                            "duration_s": matched["duration_s"],
                            "distance_m": matched["distance_m"],
                            "avg_speed_kmh": matched["avg_speed_kmh"],
                            "gps_coverage_pct": matched["gps_coverage_pct"],
                            "gps_tolerance_used": matched["gps_tolerance_used"],
                            "start_elapsed_s": matched["start_elapsed_s"],
                            "end_elapsed_s": matched["end_elapsed_s"],
                            "garmin_url": f"https://connect.garmin.com/modern/activity/{aid}",
                        }
                        group = groups.setdefault(
                            climb["id"],
                            {"climb": climb, "attempts": [], "best_trace": matched["trace"]},
                        )
                        if not group["attempts"] or attempt["duration_s"] < min(
                            a["duration_s"] for a in group["attempts"]
                        ):
                            group["best_trace"] = matched["trace"]
                        group["attempts"].append(attempt)
                        matched_rides.add(aid)
        rows = []
        for group in groups.values():
            climb, trace = group["climb"], group["best_trace"]
            place = self.geography.lookup(*climb["path"][len(climb["path"]) // 2])
            profile = [[p[0] - trace[0][0], p[2]] for p in trace[:: max(1, len(trace) // 150)]]
            if profile[-1] != [trace[-1][0] - trace[0][0], trace[-1][2]]:
                profile.append([trace[-1][0] - trace[0][0], trace[-1][2]])
            rows.append(
                {
                    **climb,
                    **place,
                    "grade_pct": 100 * climb["gain_m"] / climb["distance_m"],
                    "attempt_count": len(group["attempts"]),
                    "best": min(group["attempts"], key=lambda a: a["duration_s"]),
                    "attempts": sorted(group["attempts"], key=lambda a: a["duration_s"]),
                    "start": climb["path"][0],
                    "end": climb["path"][-1],
                    "profile": profile,
                    "start_altitude_m": profile[0][1],
                    "end_altitude_m": profile[-1][1],
                }
            )
        snapshot = {
            "algorithm": "climbfinder-v1",
            "generated_at": self.settings.now().isoformat(),
            "rows": sorted(rows, key=lambda r: (r["country"], r["region"], r["zone"], r["name"])),
            "catalog": {
                "source": "Climbfinder",
                "source_url": "https://climbfinder.com/it",
                "imported_at": catalog.get("imported_at"),
                "regions": catalog.get("regions", []),
                "routes": len(catalog["rows"]),
                "index_count": catalog.get("index_count", len(catalog["rows"])),
                "import": catalog.get("import"),
            },
            "coverage": {
                "cycling_activities": len(history),
                "history_complete": True,
                "details_missing": len(missing),
                "detected_climbs": len(rows),
                "matched_rides": len(matched_rides),
                "rides_without_catalog_match": len(history) - len(missing) - len(matched_rides),
                "attempts": sum(r["attempt_count"] for r in rows),
                "oldest_date": min((a["date"] for a, _ in history), default=None),
            },
            "note": NOTE,
        }
        self.db.set("cycling_trace_cache", cache)
        self.db.set("climbs", snapshot)
        self.db.set("climb_progress", None)
        atomic_json(self.settings.data_dir / "cycling_climbs.json", snapshot)
        return self.latest()

    def latest(self):
        snapshot = self.db.get("climbs", {})
        if snapshot.get("algorithm") != "climbfinder-v1":
            snapshot = {
                "algorithm": "climbfinder-v1",
                "generated_at": None,
                "rows": [],
                "coverage": None,
                "note": NOTE,
                "catalog": None,
            }
        return {
            **snapshot,
            "progress": self.db.get("climb_progress"),
            "error": self.db.get("climb_error"),
        }
