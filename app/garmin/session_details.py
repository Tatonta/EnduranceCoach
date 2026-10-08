"""Convert cached Garmin detail to the public canonical evidence contract."""

import math

from app.integrations.session_details import SessionDetails
from app.services.session_analysis import analyze_session, step_structure, valid


def normalize_garmin_details(activity, raw, workout=None, plan_version=None):
    # Parse measured values without borrowing phase labels from an unverified plan.
    parsed = analyze_session(activity, raw)
    fit_steps, _ = step_structure(workout)
    indices = (
        {index: leaf for leaf, index in enumerate(fit_steps)} if plan_version is not None else {}
    )
    if plan_version is not None and workout is None:
        raise ValueError("A versioned link requires its workout")

    def dynamics(value, bike=False):
        return {
            "cadence_spm": value.get("cadence_spm") if not bike else None,
            "stride_m": value.get("stride_m") if not bike else None,
            "ground_contact_s": value["gct_ms"] / 1000
            if valid(value.get("gct_ms"), True) and not bike
            else None,
            "vertical_oscillation_m": value["vertical_cm"] / 100
            if valid(value.get("vertical_cm")) and not bike
            else None,
            "vertical_ratio_percent": value.get("vertical_ratio_percent") if not bike else None,
            "power_w": value.get("power_w"),
        }

    bike = activity["sport"] == "cycling"
    laps = [
        {
            **dynamics(row, bike),
            "lap": row["lap"],
            "phase_type": row["phase_type"],
            "step_index": indices.get(row["step_index"]),
            "start_elapsed_s": row["start_elapsed_s"]
            if row["start_elapsed_s"] is not None
            else sum(
                previous["elapsed_s"] for previous in parsed["laps"] if previous["lap"] < row["lap"]
            ),
            "duration_s": row["duration_s"],
            "elapsed_s": row["elapsed_s"],
            "distance_m": row["distance_m"],
            "avg_hr": row["avg_hr"],
            "max_hr": row["max_hr"],
        }
        for row in parsed["laps"]
    ]
    samples = [
        {
            **dynamics(row, bike),
            "elapsed_s": row["elapsed_s"],
            "distance_m": row["distance_m"],
            "speed_m_s": 1000 / row["pace_s_km"] if row["pace_s_km"] else None,
            "hr": row["hr"],
        }
        for row in parsed["series"]
    ]
    summary = dynamics(parsed["dynamics"], bike)
    if bike:
        summary["cadence_rpm"] = ((raw.get("summary") or {}).get("summaryDTO") or {}).get(
            "averageBikeCadence"
        )
    zones = [
        {
            "zone": row["zoneNumber"],
            "low_bpm": row["zoneLowBoundary"],
            "time_s": row.get("secsInZone", 0),
        }
        for row in parsed["zones"]
    ]
    return SessionDetails.model_validate(
        {
            "laps": laps,
            "samples": samples,
            "route_segments": route_segments(raw),
            "dynamics": summary,
            "hr_zones": zones,
            "reported_sample_count": parsed["coverage"]["sample_count"],
            "coverage_note": "Campioni e geometria possono essere ridotti; buchi GPS espliciti restano segmenti distinti.",
            "plan_version": plan_version,
            "plan_workout_id": workout.key if plan_version is not None else None,
        }
    )


def route_segments(raw):
    details = raw.get("details") or {}
    descriptors = {
        item.get("key"): item.get("metricsIndex") for item in details.get("metricDescriptors", [])
    }
    points = []
    for row in details.get("activityDetailMetrics", []):
        values = row.get("metrics") or []

        def metric(key, values=values):
            index = descriptors.get(key)
            return values[index] if isinstance(index, int) and 0 <= index < len(values) else None

        lat, lon = metric("directLatitude"), metric("directLongitude")
        points.append(
            {"lat": lat, "lon": lon}
            if valid(lat)
            and valid(lon)
            and -90 <= lat <= 90
            and -180 <= lon <= 180
            and (lat or lon)
            else None
        )
    if not any(point is not None for point in points):
        points = [
            point
            if point.get("valid", True)
            and valid(point.get("lat"))
            and valid(point.get("lon"))
            and -90 <= point["lat"] <= 90
            and -180 <= point["lon"] <= 180
            else None
            for point in (details.get("geoPolylineDTO") or {}).get("polyline", [])
        ]
    segments, current = [], []
    for point in points + [None]:
        if point is None:
            if len(current) >= 2:
                segments.append(current)
            current = []
        else:
            current.append(point)
    segments = segments[:100]
    count = sum(map(len, segments))
    step = max(1, math.ceil(count / max(1, 2000 - 2 * len(segments))))
    result = []
    for segment in segments:
        reduced = segment[::step]
        if reduced[-1] != segment[-1]:
            reduced.append(segment[-1])
        if len(reduced) >= 2:
            result.append(reduced)
    return result
