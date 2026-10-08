"""Measured workout phases and running dynamics, independent of network and storage."""

import math
from datetime import UTC, datetime


def valid(value, positive=False):
    return (
        isinstance(value, (int, float))
        and math.isfinite(value)
        and (value > 0 if positive else True)
    )


def timestamp(value):
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return (stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)).timestamp()
    except (ValueError, TypeError, AttributeError):
        return None


def step_structure(workout, fit_indices=True):
    mapping, expected, index = {}, [], 0
    for step in workout.steps if workout else []:
        if step.type == "repeat":
            children = []
            for child in step.steps:
                mapping[index] = child
                children.append(index)
                index += 1
            expected.extend(children * step.iterations)
            if fit_indices:
                index += 1  # FIT repeat instruction follows its children and has no lap.
        else:
            mapping[index] = step
            expected.append(index)
            index += 1
    return mapping, expected


def analyze_session(activity, raw, workout=None):
    details, summary = raw.get("details") or {}, (raw.get("summary") or {}).get("summaryDTO") or {}
    descriptors = {
        d.get("key"): d.get("metricsIndex") for d in details.get("metricDescriptors", [])
    }
    start = timestamp(summary.get("startTimeGMT")) or timestamp(activity.get("start_time"))
    samples = []
    for row in details.get("activityDetailMetrics") or []:
        values = row.get("metrics") or []

        def metric(key, values=values):
            index = descriptors.get(key)
            return (
                values[index]
                if isinstance(index, int) and 0 <= index < len(values) and valid(values[index])
                else None
            )

        elapsed, distance = metric("sumElapsedDuration"), metric("sumDistance")
        if elapsed is None or distance is None or elapsed < 0 or distance < 0:
            continue
        speed, hr = metric("directSpeed"), metric("directHeartRate")
        cadence = metric("directDoubleCadence")
        if cadence is None and metric("directRunCadence") is not None:
            cadence = 2 * (metric("directRunCadence") + (metric("directFractionalCadence") or 0))
        stride, latitude, longitude = (
            metric("directStrideLength"),
            metric("directLatitude"),
            metric("directLongitude"),
        )
        sample = {
            "elapsed_s": elapsed,
            "distance_m": distance,
            "time": metric("directTimestamp"),
            "pace_s_km": 1000 / speed if speed and 0.5 <= speed <= 12 else None,
            "hr": hr if hr and 30 <= hr <= 250 else None,
            "cadence_spm": cadence if cadence and 60 <= cadence <= 260 else None,
            "stride_m": stride / 100 if stride and 20 <= stride <= 400 else None,
            "power_w": metric("directPower"),
            "elevation_m": metric("directElevation"),
            "gct_ms": metric("directGroundContactTime"),
            "vertical_cm": metric("directVerticalOscillation"),
        }
        if (
            latitude is not None
            and longitude is not None
            and -90 <= latitude <= 90
            and -180 <= longitude <= 180
            and (latitude or longitude)
        ):
            sample["lat"], sample["lon"] = latitude, longitude
        if samples and elapsed <= samples[-1]["elapsed_s"]:
            continue
        samples.append(sample)
    zones = sorted(
        [z for z in raw.get("hr_zones", []) if valid(z.get("zoneLowBoundary"), True)],
        key=lambda z: z["zoneNumber"],
    )
    zone_limits = {
        z["zoneNumber"]: (
            z["zoneLowBoundary"],
            zones[i + 1]["zoneLowBoundary"] - 1 if i + 1 < len(zones) else None,
        )
        for i, z in enumerate(zones)
    }
    mapping, expected = step_structure(workout)
    lap_rows = []
    labels = {
        "warmup": "Riscaldamento",
        "run": "Corsa",
        "interval": "Lavoro",
        "recovery": "Recupero",
        "cooldown": "Defaticamento",
    }
    for lap in (raw.get("splits") or {}).get("lapDTOs", []):
        duration, distance = lap.get("duration"), lap.get("distance")
        if not valid(duration, True) or not valid(distance) or distance < 0:
            continue
        index, intensity = lap.get("wktStepIndex"), lap.get("intensityType", "UNKNOWN")
        step = mapping.get(index)
        phase_type = (
            step.type
            if step
            else {
                "WARMUP": "warmup",
                "ACTIVE": "run",
                "RECOVERY": "recovery",
                "REST": "recovery",
                "COOLDOWN": "cooldown",
            }.get(intensity, "unknown")
        )
        row = {
            "lap": lap.get("lapIndex"),
            "step_index": index,
            "phase": labels.get(phase_type, intensity),
            "phase_type": phase_type,
            "duration_s": duration,
            "distance_m": distance,
            "elapsed_s": lap.get("elapsedDuration") or duration,
            "pace_s_km": duration / distance * 1000 if distance > 0 else None,
            "avg_hr": lap.get("averageHR"),
            "max_hr": lap.get("maxHR"),
            "cadence_spm": lap.get("averageRunCadence"),
            "stride_m": lap["strideLength"] / 100 if valid(lap.get("strideLength"), True) else None,
            "gct_ms": lap.get("groundContactTime"),
            "vertical_cm": lap.get("verticalOscillation"),
            "power_w": lap.get("averagePower"),
            "ascent_m": lap.get("elevationGain"),
            "start_elapsed_s": max(0, timestamp(lap.get("startTimeGMT")) - start)
            if start and timestamp(lap.get("startTimeGMT"))
            else None,
        }
        if valid(row["avg_hr"], True):
            row["hr_zone"] = next(
                (
                    z
                    for z, (low, high) in zone_limits.items()
                    if low <= row["avg_hr"] and (high is None or row["avg_hr"] <= high)
                ),
                None,
            )
        row["quality_flags"] = []
        if valid(row["cadence_spm"]) and row["cadence_spm"] < 60 and distance > 100:
            row["quality_flags"].append(
                "Dinamiche del lap non rappresentative: cadenza media molto bassa rispetto al movimento registrato."
            )
        lap_rows.append(row)
    route = [[sample["lat"], sample["lon"]] for sample in samples if "lat" in sample]
    if not route:
        route = [
            [point["lat"], point["lon"]]
            for point in (details.get("geoPolylineDTO") or {}).get("polyline", [])
            if point.get("valid", True) and valid(point.get("lat")) and valid(point.get("lon"))
        ]
    locomotion = {
        key: sum(
            row.get("duration", 0)
            for row in (raw.get("typed_splits") or {}).get("splits", [])
            if row.get("type") == key and valid(row.get("duration"))
        )
        for key in ("RWD_RUN", "RWD_WALK", "RWD_STAND")
    }
    evidence = {
        "laps": lap_rows,
        "samples": samples,
        "route": route,
        "zones": zones,
        "locomotion_s": locomotion,
        "reported_sample_count": details.get("measurementCount"),
        "dynamics": {
            "cadence_spm": summary.get("averageRunCadence"),
            "stride_m": summary["strideLength"] / 100
            if valid(summary.get("strideLength"), True)
            else None,
            "gct_ms": summary.get("groundContactTime"),
            "vertical_cm": summary.get("verticalOscillation"),
            "vertical_ratio_percent": summary.get("verticalRatio"),
            "power_w": summary.get("averagePower"),
        },
    }
    result = evaluate_measured_session(
        activity, evidence, workout, source_label="Garmin", fit_indices=True
    )
    result["method"] = (
        "Lap Garmin raggruppati per step FIT e intensità; ritmo distanza/tempo, FC ponderata per durata. Stride cm→m, cadenza completa in passi/min."
    )
    return result


def evaluate_measured_session(
    activity, evidence, workout=None, *, source_label="Fonte", fit_indices=False
):
    """Evaluate normalized evidence without any vendor, network or persistence dependency."""
    mapping, expected = step_structure(workout, fit_indices=fit_indices)
    labels = {
        "warmup": "Riscaldamento",
        "run": "Corsa",
        "interval": "Lavoro",
        "recovery": "Recupero",
        "cooldown": "Defaticamento",
    }
    lap_rows = [dict(row) for row in evidence.get("laps", [])]
    samples, zones = evidence.get("samples", []), evidence.get("zones", [])
    zone_limits = {
        zone["zoneNumber"]: (
            zone["zoneLowBoundary"],
            zone.get("zoneHighBoundary")
            if zone.get("zoneHighBoundary") is not None
            else zones[i + 1]["zoneLowBoundary"] - 1
            if i + 1 < len(zones) and zones[i + 1]["zoneNumber"] == zone["zoneNumber"] + 1
            else None,
        )
        for i, zone in enumerate(zones)
    }
    easy_reference = bool(
        workout
        and not workout.quality
        and any(word in workout.name.lower() for word in ("easy", "recovery", "facile", "lenta"))
    )
    phases = []
    for row in lap_rows:
        index = row.get("step_index")
        step = mapping.get(index)
        phase_type = step.type if step else row.get("phase_type", "unknown")
        row["phase_type"] = phase_type
        row["phase"] = labels.get(phase_type, "Fase non identificata")
        row.setdefault("quality_flags", [])
        if valid(row.get("avg_hr"), True):
            row["hr_zone"] = next(
                (
                    zone
                    for zone, (low, high) in zone_limits.items()
                    if low <= row["avg_hr"]
                    and (high is not None and row["avg_hr"] <= high or high is None and zone == 5)
                ),
                None,
            )
        if (
            valid(row.get("cadence_spm"))
            and row["cadence_spm"] < 60
            and valid(row.get("distance_m"), True)
            and row["distance_m"] > 100
            and not row["quality_flags"]
        ):
            row["quality_flags"].append(
                "Dinamiche del lap non rappresentative: cadenza media molto bassa rispetto al movimento registrato."
            )
        intensity = phase_type
        key = (index, intensity)
        trailing_cooldown = bool(
            index is None
            and phase_type == "cooldown"
            and phases
            and phases[-1]["type"] == "cooldown"
        )
        if not phases or (phases[-1]["key"] != key and not trailing_cooldown):
            phases.append(
                {
                    "key": key,
                    "type": phase_type,
                    "step_index": index,
                    "name": labels.get(phase_type, intensity),
                    "laps": [],
                    "start_elapsed_s": row["start_elapsed_s"],
                }
            )
        phases[-1]["laps"].append(row)
    positives, issues, actions = [], [], []
    observed = []
    for number, phase in enumerate(phases, 1):
        rows = phase.pop("laps")
        duration = sum(r["duration_s"] for r in rows)
        distance = (
            sum(r["distance_m"] for r in rows)
            if all(r.get("distance_m") is not None for r in rows)
            else None
        )
        phase.update(
            number=number,
            duration_s=duration,
            distance_m=distance,
            pace_s_km=duration / distance * 1000 if distance is not None and distance > 0 else None,
            avg_hr=sum(
                (r["avg_hr"] or 0) * r["duration_s"] for r in rows if valid(r["avg_hr"], True)
            )
            / sum(r["duration_s"] for r in rows if valid(r["avg_hr"], True))
            if any(valid(r["avg_hr"], True) for r in rows)
            else None,
            lap_numbers=[r["lap"] for r in rows],
            verdict="descrittivo",
            target=None,
        )
        phase.pop("key")
        step = mapping.get(phase["step_index"])
        if step:
            observed.append(phase["step_index"])
            phase["planned_duration_s"] = step.seconds
            phase["target"] = step.target.model_dump() if step.target else None
            if step.seconds:
                ratio = duration / step.seconds
                phase["duration_compliance"] = (
                    "ok" if 0.85 <= ratio <= 1.15 else "breve" if ratio < 0.85 else "lunga"
                )
                if 0.85 <= ratio <= 1.15 and phase["type"] in {"warmup", "cooldown"}:
                    positives.append(
                        f"{phase['name']}: {duration / 60:.1f} min, durata coerente con i {step.seconds / 60:.1f} previsti."
                    )
                if ratio < 0.85:
                    issues.append(
                        f"{phase['name']} {number}: {duration / 60:.1f} min contro {step.seconds / 60:.1f} previsti."
                    )
            target = step.target
            pace = phase["pace_s_km"]
            if target and target.type == "pace" and pace:
                from app.models import pace_seconds

                fast, slow = pace_seconds(target.fast), pace_seconds(target.slow)
                phase["pace_delta_s"] = (
                    pace - fast if pace < fast else pace - slow if pace > slow else 0
                )
                phase["verdict"] = (
                    "troppo veloce"
                    if pace < fast - 3
                    else "troppo lento"
                    if pace > slow + 3
                    else "vicino al target (±3 s/km)"
                    if not fast <= pace <= slow
                    else "in target"
                )
                if phase["verdict"] in {"troppo veloce", "troppo lento"}:
                    issues.append(
                        f"{phase['name']} {number}: {phase['verdict']} di {abs(phase['pace_delta_s']):.0f} s/km rispetto al target {target.fast}–{target.slow}."
                    )
                elif phase["verdict"] == "in target":
                    positives.append(
                        f"{phase['name']} {number}: ritmo nel target {target.fast}–{target.slow}/km."
                    )
                else:
                    positives.append(
                        f"{phase['name']} {number}: ritmo vicino al target {target.fast}–{target.slow}/km, entro la tolleranza euristica di 3 s/km."
                    )
            reference_zone = (
                target.zone
                if target and target.type == "hr_zone"
                else 2
                if phase["type"] in {"warmup", "run", "cooldown"} and easy_reference
                else None
            )
            if reference_zone in zone_limits and phase["avg_hr"]:
                low, high = zone_limits[reference_zone]
                phase["hr_reference"] = {
                    "zone": reference_zone,
                    "low": low,
                    "high": high,
                    "explicit": bool(target and target.type == "hr_zone"),
                }
                if high and phase["avg_hr"] > high:
                    issues.append(
                        f"{phase['name']} {number}: FC media {phase['avg_hr']:.0f} bpm sopra Z{reference_zone} {source_label} ({low}–{high})."
                        + (
                            ""
                            if target and target.type == "hr_zone"
                            else " Riferimento indicativo per corsa facile, non target esplicito del piano."
                        )
                    )
                    actions.append(
                        f"Per il tratto facile parti più piano e verifica se la FC rientra nel riferimento configurato Z{reference_zone}; controlla le tue zone della fonte {source_label}."
                    )
        if (
            phase["type"] == "recovery"
            and number > 1
            and phase["avg_hr"]
            and phases[number - 2].get("avg_hr")
        ):
            phase["hr_mean_difference_bpm"] = phases[number - 2]["avg_hr"] - phase["avg_hr"]
    missing, remaining = [], observed[:]
    for index in expected:
        if index in remaining:
            remaining.remove(index)
        else:
            missing.append(labels.get(mapping[index].type, mapping[index].type))
    if expected and missing and phases:
        counts = {name: missing.count(name) for name in dict.fromkeys(missing)}
        issues.append(
            "Fasi previste non registrate: "
            + ", ".join(f"{count} × {name}" for name, count in counts.items())
            + ". Non considerate completate dal solo nome dell'attività."
        )
    if expected and observed != expected and not missing:
        issues.append("Le fasi sono presenti ma l’ordine degli step differisce dal piano riferito.")
    if phases and not missing and (not expected or observed == expected):
        positives.append(
            f"Riconosciute {len(phases)} fasi registrate"
            + (
                "; ordine degli step coerente con il piano riferito."
                if expected
                else "; nessun confronto verificato con gli step del piano."
            )
        )
    if any(p.get("verdict") == "troppo veloce" for p in phases):
        actions.append(
            "Nella prossima seduta di qualità rispetta il ritmo previsto già dalla prima ripetuta: andare più forte non equivale automaticamente a una seduta migliore."
        )
    if missing and phases:
        actions.append(
            "Non recuperare automaticamente i blocchi mancanti aggiungendoli alla prossima seduta; registra il motivo dell'interruzione."
        )
    route = evidence.get("route", [])
    locomotion = evidence.get("locomotion_s", {})
    easy_reference = bool(
        workout
        and not workout.quality
        and any(word in workout.name.lower() for word in ("easy", "recovery", "facile", "lenta"))
    )
    if easy_reference and 2 in zone_limits:
        low, high = zone_limits[2]
        high_laps = [
            r
            for r in lap_rows
            if r["phase_type"] in {"run", "warmup", "cooldown"}
            and valid(r["avg_hr"], True)
            and high
            and r["avg_hr"] > high
        ]
        for row in high_laps:
            issues.append(
                f"Lap {row['lap']} nella parte facile: FC media {row['avg_hr']:.0f} bpm in Z{row.get('hr_zone')} {source_label}, sopra il riferimento Z2 ({low}–{high})."
            )
        if high_laps:
            actions.append(
                "Rallenta i tratti facili che portano la FC sopra il riferimento Z2, senza imporre un ritmo numerico non definito nel piano; verifica sensazioni e calibrazione delle zone."
            )
    return {
        "activity_id": activity["activity_id"],
        "phases": phases,
        "laps": lap_rows,
        "locomotion_s": locomotion,
        "series": samples[:: max(1, math.ceil(len(samples) / 1800))],
        "route": route[:: max(1, math.ceil(len(route) / 1600))],
        "zones": zones,
        "dynamics": evidence.get("dynamics", {}),
        "positive": positives,
        "issues": issues,
        "actions": list(dict.fromkeys(actions)),
        "verdict": "Seduta da correggere"
        if issues
        else "Seduta coerente con gli step verificati"
        if phases and expected
        else "Dati acquisiti: valutazione contestuale con ChatGPT",
        "missing_phases": missing,
        "coverage": {
            "lap_count": len(lap_rows),
            "sample_count": len(samples),
            "reported_sample_count": evidence.get("reported_sample_count"),
            "gps_points": len(route),
        },
        "method": "Fasi raggruppate per step e intensità; ritmo da distanza/tempo e FC ponderata per durata.",
    }
