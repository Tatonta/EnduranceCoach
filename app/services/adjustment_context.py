"""Context checks for proposed adjustments; no diagnostics or vendor/network access."""

from copy import deepcopy
from datetime import datetime, timedelta

from app.services.planner import canonical_hash


def contextualize_adjustment(review, details, activities, now):
    result = deepcopy(review)
    program = result["program"]
    checks, reasons = [], []
    evidence = {row["activity_id"]: row for row in program["evidence"]}
    ids = {row["activity_id"] for row in program["evidence"]}
    for activity_id in sorted(ids):
        item = details.get(activity_id, {"status": "not_loaded"})
        status = item.get("status", "not_loaded")
        blockers = (
            (item.get("analysis") or {}).get("comparison_blockers", []) if status == "ready" else []
        )
        check = {
            "activity_id": activity_id,
            "status": status,
            "version": item.get("version"),
            "fingerprint": item.get("fingerprint") or item.get("activity_hash"),
            "blockers": blockers,
        }
        checks.append(check)
        label = evidence[activity_id].get("date", activity_id)
        if status in {"stale", "unverified"}:
            reasons.append(
                f"Seduta del {label}: dettagli presenti ma non aggiornati/verificati sul riepilogo. Rileggili prima del confronto."
            )
        if blockers:
            reasons.extend(f"Seduta del {label}: {blocker['note']}" for blocker in blockers)
    feedback_checks = []
    for activity in activities:
        try:
            start = datetime.fromisoformat(activity["start_time"])
            if not start.tzinfo or not now - timedelta(days=2) <= start <= now:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        feedback = activity.get("feedback") or {}
        if feedback.get("discomfort") == "present" or feedback.get("feeling") == "very_fatigued":
            feedback_checks.append(
                {
                    "activity_id": activity["activity_id"],
                    "start_time": activity["start_time"],
                    "discomfort": feedback.get("discomfort"),
                    "feeling": feedback.get("feeling"),
                }
            )
            reasons.append(
                "Hai segnalato fastidi o forte stanchezza nelle ultime 48 ore: chiarisci il contesto prima di accettare un adattamento."
            )
    program["context_checks"] = checks
    program["recent_feedback_checks"] = feedback_checks
    if program["eligible"] and reasons:
        program.update(
            eligible=False,
            decision="keep",
            reason="Mantieni il piano: il trend medio richiede un confronto contestuale. "
            + reasons[0],
        )
    program["context_reasons"] = list(dict.fromkeys(reasons))
    result["evidence_hash"] = canonical_hash(
        {
            "base": review["evidence_hash"],
            "detail_context": checks,
            "recent_feedback": feedback_checks,
        }
    )
    return result
