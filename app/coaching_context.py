"""Bounded coaching evidence shared by local and authenticated runtimes; no transport."""

import json
import math
from datetime import datetime, timedelta

from app.errors import CoachError
from app.services.planner import canonical_hash

SUMMARY_FIELDS = (
    "activity_id",
    "date",
    "name",
    "sport",
    "source",
    "duration_s",
    "elapsed_duration_s",
    "distance_m",
    "avg_hr",
    "max_hr",
    "avg_pace_s_km",
    "elevation_gain_m",
    "training_load",
    "feedback",
    "evidence_kind",
    "distance_known",
)
ANALYSIS_FIELDS = (
    "verdict",
    "positive",
    "issues",
    "actions",
    "comparison_blockers",
    "missing_phases",
    "coverage",
    "dynamics",
    "zones",
    "method",
)
LAP_FIELDS = (
    "lap",
    "phase",
    "phase_type",
    "step_index",
    "duration_s",
    "elapsed_s",
    "distance_m",
    "pace_s_km",
    "avg_hr",
    "max_hr",
    "hr_zone",
    "cadence_spm",
    "cadence_rpm",
    "stride_m",
    "power_w",
    "gct_ms",
    "vertical_cm",
    "ascent_m",
    "quality_flags",
)
SAMPLE_FIELDS = (
    "elapsed_s",
    "distance_m",
    "pace_s_km",
    "hr",
    "cadence_spm",
    "cadence_rpm",
    "stride_m",
    "power_w",
    "gct_ms",
    "vertical_cm",
    "segment",
)
PHASE_FIELDS = (
    "number",
    "name",
    "type",
    "step_index",
    "duration_s",
    "distance_m",
    "pace_s_km",
    "avg_hr",
    "lap_numbers",
    "verdict",
    "target",
    "planned_duration_s",
    "duration_compliance",
    "pace_delta_s",
    "hr_reference",
    "hr_mean_difference_bpm",
)


def select_fields(row, keys):
    return {key: row[key] for key in keys if key in row}


def representative(rows, limit):
    if len(rows) <= limit:
        return list(rows)
    return [rows[round(index * (len(rows) - 1) / (limit - 1))] for index in range(limit)]


def detail_context(detail):
    result = select_fields(
        detail, ("status", "version", "activity_hash", "fingerprint", "source", "plan_reference")
    )
    if detail.get("status") != "ready":
        return result
    analysis = detail.get("analysis") or {}
    value = select_fields(analysis, ANALYSIS_FIELDS)
    value["dynamics"] = select_fields(
        analysis.get("dynamics") or {},
        ("cadence_spm", "cadence_rpm", "stride_m", "gct_ms", "vertical_cm", "power_w"),
    )
    coverage = {}
    for key, fields, limit in [
        ("phases", PHASE_FIELDS, 100),
        ("laps", LAP_FIELDS, 100),
        ("series", SAMPLE_FIELDS, 120),
    ]:
        rows = analysis.get(key) or []
        value[key] = [select_fields(row, fields) for row in representative(rows, limit)]
        if key == "phases":
            for phase in value[key]:
                if phase.get("target"):
                    phase["target"] = select_fields(
                        phase["target"], ("type", "zone", "fast", "slow")
                    )
                if phase.get("hr_reference"):
                    phase["hr_reference"] = select_fields(
                        phase["hr_reference"], ("zone", "low", "high", "explicit")
                    )
        coverage[key] = {
            "available": len(rows),
            "included": len(value[key]),
            "representative_sample": len(rows) > limit,
        }
    result["analysis"] = value
    result["context_coverage"] = coverage
    return result


def completed_history(activities, now):
    since = now - timedelta(days=42)
    completed = []
    for row in activities:
        try:
            start = datetime.fromisoformat(row["start_time"])
            elapsed = row.get("elapsed_duration_s", row["duration_s"])
            if not isinstance(elapsed, (float, int)) or not math.isfinite(elapsed) or elapsed <= 0:
                continue
            if start.tzinfo and since <= start and start + timedelta(seconds=elapsed) <= now:
                completed.append(row)
        except (KeyError, TypeError, ValueError):
            continue
    completed.sort(key=lambda row: datetime.fromisoformat(row["start_time"]), reverse=True)
    return completed


def build_coaching_context(profile, profile_version, plan, plan_version, activities, details, now):
    completed = completed_history(activities, now)
    recent = completed[:20]
    start_day, end_day = now.date() - timedelta(days=14), now.date() + timedelta(days=14)
    plan_data = None
    if plan:
        plan_data = plan.model_dump(mode="json", exclude={"athlete"})
        plan_data["workouts"] = [
            row.model_dump(mode="json") for row in plan.workouts if start_day <= row.date <= end_day
        ]
    detail_rows = [
        {
            "activity_id": row["activity_id"],
            **detail_context(details.get(row["activity_id"], {"status": "not_loaded"})),
        }
        for row in recent[:2]
    ]
    value = {
        "schema_version": 1,
        "today": now.date().isoformat(),
        "training_profile": profile.model_dump(mode="json")
        if hasattr(profile, "model_dump")
        else profile,
        "profile_version": profile_version,
        "plan_version": plan_version,
        "current_plan": plan_data,
        "recent_activity_summaries": [select_fields(row, SUMMARY_FIELDS) for row in recent],
        "recent_session_evidence": detail_rows,
        "context_coverage": {
            "history_days": 42,
            "history_available": len(completed),
            "history_included": len(recent),
            "history_truncated": len(completed) > len(recent),
            "plan_from": start_day.isoformat(),
            "plan_to": end_day.isoformat(),
            "plan_workouts_total": len(plan.workouts) if plan else 0,
            "plan_workouts_included": len(plan_data["workouts"]) if plan_data else 0,
        },
        "evidence_rules": [
            "Il profilo e i feedback sono dichiarazioni dell'atleta; le fonti importate non sono API vendor verificate.",
            "Assenza di dati e campioni rappresentativi non dimostrano la conformità dell'intera seduta.",
            "Il contesto non include campi GPS, credenziali o metadati liberi del vecchio profilo Plan.athlete.",
            "Una risposta AI non autorizza modifiche: serve la proposta verificata e la conferma dell'atleta.",
        ],
    }
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(encoded) > 300_000:
        raise CoachError(
            "Contesto troppo grande; nessuna richiesta AI preparata.", "context_too_large", 409
        )
    return {"context": value, "context_hash": canonical_hash(value)}
