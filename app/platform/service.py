import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select

from app.errors import CoachError
from app.models import Plan
from app.platform.tables import (
    Activity,
    ActivityDetails,
    AdjustmentProposal,
    Athlete,
    AthleteProfile,
    AuditEvent,
    PlanVersion,
)
from app.services.adjustment_context import contextualize_adjustment
from app.services.planner import canonical_hash
from app.services.reviewer import review_latest_workouts
from app.services.workout_review import adjusted_plan, last_workout_review
from app.training_profile import profile_brief


class AthleteService:
    def __init__(self, store):
        self.store = store
        self.settings = store.settings

    def audit(self, session, athlete_id, event, payload):
        session.add(
            AuditEvent(
                id=str(uuid.uuid4()),
                athlete_id=athlete_id,
                event=event,
                created_at=self.settings.now().isoformat(),
                payload=payload,
            )
        )

    def current_plan(self, session, athlete):
        if not athlete or athlete.plan_version == 0:
            raise CoachError("Create a training plan first", "plan_required", 404)
        version = session.get(PlanVersion, (athlete.id, athlete.plan_version))
        if not version:
            raise CoachError("Plan version unavailable", "plan_unavailable", 409)
        return Plan.model_validate(version.payload)

    def profile(self, athlete_id):
        with self.store.read_session() as session:
            row = session.get(AthleteProfile, athlete_id)
            if not row:
                raise CoachError("Completa il questionario iniziale.", "profile_required", 404)
            return {"version": row.version, "profile": row.payload, "updated_at": row.updated_at}

    def save_profile(self, athlete_id, profile, expected_version):
        with self.store.transaction() as session:
            athlete = self.store.lock_athlete(session, athlete_id)
            profile.validate_calendar(self.settings.now().astimezone(ZoneInfo(athlete.timezone)).date())
            row = session.get(AthleteProfile, athlete_id)
            version = row.version if row else 0
            if version != expected_version:
                raise CoachError("Il profilo è cambiato. Ricaricalo prima di salvare.", "version_conflict", 409)
            if row is None:
                row = AthleteProfile(athlete_id=athlete_id)
                session.add(row)
            row.version = version + 1
            row.payload = profile.model_dump(mode="json")
            row.updated_at = self.settings.now().isoformat()
            self.audit(session, athlete_id, "profile_saved", {"version": row.version})
            result = {"version": row.version, "profile": row.payload, "updated_at": row.updated_at,
                      "brief": profile_brief(profile)}
        return result

    def plan(self, athlete_id):
        with self.store.read_session() as session:
            athlete = session.get(Athlete, athlete_id)
            plan = self.current_plan(session, athlete)
            return {"version": athlete.plan_version, "plan": plan.model_dump(mode="json")}

    def write_plan(self, session, athlete, plan, reason):
        athlete.plan_version += 1
        version = athlete.plan_version
        session.add(
            PlanVersion(
                athlete_id=athlete.id,
                version=version,
                payload=plan.model_dump(mode="json"),
                created_at=self.settings.now().isoformat(),
                reason=reason,
            )
        )
        session.execute(
            delete(AdjustmentProposal).where(
                AdjustmentProposal.athlete_id == athlete.id, AdjustmentProposal.status == "pending"
            )
        )
        self.audit(session, athlete.id, "plan_saved", {"version": version, "reason": reason})
        return version

    def replace_plan(self, athlete_id, plan, expected_version):
        with self.store.transaction() as session:
            athlete = self.store.lock_athlete(session, athlete_id)
            if athlete.plan_version != expected_version:
                raise CoachError("Plan changed. Reload it before saving.", "version_conflict", 409)
            version = self.write_plan(session, athlete, plan, "user_edit")
        return {"version": version, "plan": plan.model_dump(mode="json")}

    def history(self, athlete_id):
        with self.store.read_session() as session:
            versions = session.scalars(
                select(PlanVersion)
                .where(PlanVersion.athlete_id == athlete_id)
                .order_by(PlanVersion.version.desc())
            ).all()
            return [
                {
                    "version": v.version,
                    "created_at": v.created_at,
                    "reason": v.reason,
                    "plan": v.payload,
                }
                for v in versions
            ]

    @staticmethod
    def exact_duplicate(left, right):
        # Deliberately narrow: uncertain similarities must never erase real workouts.
        return (
            left["source"] != right["source"]
            and "manual" not in {left["source"], right["source"]}
            and left["sport"] == right["sport"]
            and abs(
                (
                    datetime.fromisoformat(left["start_time"])
                    - datetime.fromisoformat(right["start_time"])
                ).total_seconds()
            )
            <= 2
            and abs(left["duration_s"] - right["duration_s"]) <= 1
            and abs(left["distance_m"] - right["distance_m"]) <= 1
        )

    def ingest(self, athlete_id, records):
        now = self.settings.now()
        if any(record.start_time > now or record.source == "manual" and record.start_time + timedelta(seconds=record.elapsed_duration_s) > now for record in records):
            raise CoachError("Future activities cannot be imported", "future_activity", 422)
        identities = [(r.source, r.source_activity_id) for r in records]
        if len(set(identities)) != len(identities):
            raise CoachError(
                "Each provider activity may occur only once per batch", "duplicate_identity", 422
            )
        with self.store.transaction() as session:
            athlete = self.store.lock_athlete(session, athlete_id)
            touched = []
            new_roots = set()
            for record in records:
                payload = record.payload(athlete.timezone)
                row = session.get(Activity, (athlete_id, record.source, record.source_activity_id))
                if row:
                    peers = list(
                        session.scalars(
                            select(Activity).where(
                                Activity.athlete_id == athlete_id,
                                Activity.canonical_id == row.canonical_id,
                            )
                        )
                    )
                    if any(
                        peer is not row and not self.exact_duplicate(payload, peer.payload)
                        for peer in peers
                    ):
                        preferred = min(
                            peers,
                            key=lambda peer: (
                                peer.provider != "garmin",
                                peer.provider,
                                peer.provider_id,
                            ),
                        )
                        fork = str(uuid.uuid4())
                        new_roots.add(fork)
                        if preferred is row:
                            for peer in peers:
                                if peer is not row:
                                    peer.canonical_id = fork
                        else:
                            row.canonical_id = fork
                    row.payload = payload
                    row.updated_at = now.isoformat()
                    row.start_epoch = record.start_time.timestamp()
                else:
                    root = str(uuid.uuid4())
                    new_roots.add(root)
                    row = Activity(
                        athlete_id=athlete_id,
                        provider=record.source,
                        provider_id=record.source_activity_id,
                        canonical_id=root,
                        payload=payload,
                        updated_at=now.isoformat(),
                        ingestion_method="client_import",
                        start_epoch=record.start_time.timestamp(),
                    )
                    session.add(row)
                touched.append(row)
            session.flush()
            accepted_ids = set((athlete.last_adjustment or {}).get("evidence_activity_ids", []))
            for row in touched:
                # Indexed time window: deduplication must not scan years of history.
                nearby = list(
                    session.scalars(
                        select(Activity).where(
                            Activity.athlete_id == athlete_id,
                            Activity.start_epoch >= row.start_epoch - 2,
                            Activity.start_epoch <= row.start_epoch + 2,
                        )
                    )
                )
                candidates = {
                    peer.canonical_id
                    for peer in nearby
                    if peer is row or self.exact_duplicate(row.payload, peer.payload)
                }
                if len(candidates) <= 1:
                    continue
                members = list(
                    session.scalars(
                        select(Activity).where(
                            Activity.athlete_id == athlete_id, Activity.canonical_id.in_(candidates)
                        )
                    )
                )
                # Two possible matches from the same vendor are ambiguous. Also
                # reject transitive chains where the endpoints do not really match.
                if len({member.provider for member in members}) != len(members):
                    continue
                ambiguous = False
                for member in members:
                    alternatives = session.scalars(
                        select(Activity).where(
                            Activity.athlete_id == athlete_id,
                            Activity.start_epoch >= member.start_epoch - 2,
                            Activity.start_epoch <= member.start_epoch + 2,
                            Activity.canonical_id.not_in(candidates),
                        )
                    )
                    if any(
                        self.exact_duplicate(member.payload, other.payload)
                        for other in alternatives
                    ):
                        ambiguous = True
                        break
                if ambiguous:
                    continue
                if not all(
                    self.exact_duplicate(a.payload, b.payload)
                    for i, a in enumerate(members)
                    for b in members[i + 1 :]
                ):
                    continue
                root = min(
                    candidates,
                    key=lambda value: (value not in accepted_ids, value in new_roots, value),
                )
                for member in members:
                    member.canonical_id = root
                if athlete.last_adjustment:
                    retained = dict(athlete.last_adjustment)
                    retained["evidence_activity_ids"] = list(
                        dict.fromkeys(
                            root if value in candidates else value
                            for value in retained["evidence_activity_ids"]
                        )
                    )
                    athlete.last_adjustment = retained
                session.flush()
            athlete.activities_updated_at = now.isoformat()
            self.audit(
                session,
                athlete_id,
                "activities_imported",
                {"records": len(records), "method": "client_import"},
            )
            session.flush()
            count = session.scalar(
                select(func.count(func.distinct(Activity.canonical_id))).where(
                    Activity.athlete_id == athlete_id
                )
            )
            source_hashes = [{"source": row.provider, "source_activity_id": row.provider_id,
                              "activity_hash": canonical_hash(row.payload)} for row in touched]
        return {
            "imported": len(records),
            "unique_workouts": count,
            "ingestion_method": "client_import",
            "source_activity_hashes": source_hashes,
        }

    def activity_payloads(self, session, athlete_id, *, limit=None, offset=0, earliest=None):
        filters = [Activity.athlete_id == athlete_id]
        if earliest is not None:
            filters.append(Activity.start_epoch >= earliest)
        query = select(Activity).where(*filters)
        if limit is not None:
            canonical_ids = list(
                session.scalars(
                    select(Activity.canonical_id)
                    .where(*filters)
                    .group_by(Activity.canonical_id)
                    .order_by(func.max(Activity.start_epoch).desc(), Activity.canonical_id)
                    .offset(offset)
                    .limit(limit)
                )
            )
            if not canonical_ids:
                return []
            query = query.where(Activity.canonical_id.in_(canonical_ids))
        groups = defaultdict(list)
        for record in session.scalars(query):
            groups[record.canonical_id].append(record)
        result = []
        for canonical_id, records in groups.items():
            # Keep a deterministic preferred source without inventing missing metrics.
            records.sort(key=lambda r: (r.provider != "garmin", r.provider, r.provider_id))
            item = dict(records[0].payload)
            item["activity_id"] = canonical_id
            item["source_references"] = [
                {
                    "source": r.provider,
                    "source_activity_id": r.provider_id,
                    "ingestion_method": r.ingestion_method,
                }
                for r in records
            ]
            result.append(item)
        return sorted(result, key=lambda a: datetime.fromisoformat(a["start_time"]), reverse=True)

    def activities(self, athlete_id, limit=50, offset=0):
        with self.store.read_session() as session:
            count = session.scalar(
                select(func.count(func.distinct(Activity.canonical_id))).where(
                    Activity.athlete_id == athlete_id
                )
            )
            rows = self.activity_payloads(session, athlete_id, limit=limit, offset=offset)
            return {
                "activities": rows,
                "total": count,
                "next_offset": offset + len(rows) if offset + len(rows) < count else None,
            }

    def delete_activity(self, athlete_id, provider, provider_id):
        with self.store.transaction() as session:
            self.store.lock_athlete(session, athlete_id)
            row = session.get(Activity, (athlete_id, provider, provider_id))
            if not row:
                raise CoachError("Activity not found", "not_found", 404)
            session.delete(row)
            self.audit(session, athlete_id, "activity_removed", {"provider": provider})

    def build_review(self, session, athlete, include_details=False):
        plan = self.current_plan(session, athlete)
        now = self.settings.now().astimezone(ZoneInfo(athlete.timezone))
        earliest_day = min(plan.start, now.date() - timedelta(days=42))
        earliest = datetime.combine(
            earliest_day, datetime.min.time(), tzinfo=now.tzinfo
        ).timestamp()
        activities = self.activity_payloads(session, athlete.id, limit=2001, earliest=earliest)
        if len(activities) > 2000:
            raise CoachError(
                "Review history exceeds the supported limit; no adjustment was proposed",
                "activities_incomplete",
                409,
            )
        snapshot = review_latest_workouts(plan, activities, now)
        review = last_workout_review(
            plan, activities, now, snapshot, athlete.activities_updated_at, athlete.last_adjustment
        )
        review["plan_version"] = athlete.plan_version
        detail_context = {}
        if review["program"]["eligible"]:
            from app.platform.detailed_review import ActivityDetailService

            details = ActivityDetailService(self.store)
            detail_context = {
                row["activity_id"]: details.for_canonical(session, athlete.id, row["activity_id"])
                or {"status": "not_loaded"}
                for row in review["program"]["evidence"]
            }
        review = contextualize_adjustment(review, detail_context, activities, now)
        if include_details and review["last_workout"]:
            from app.platform.detailed_review import ActivityDetailService

            review["detailed_review"] = detail_context.get(
                review["last_workout"]["activity_id"]
            ) or ActivityDetailService(self.store).for_canonical(
                session, athlete.id, review["last_workout"]["activity_id"]
            )
            if review["detailed_review"] and review["detailed_review"]["status"] == "ready":
                analysis = review["detailed_review"]["analysis"]
                review["verdict"] = analysis["verdict"]
                review["advice"] = list(dict.fromkeys(review["advice"] + analysis["actions"]))
        review["limitations"].append(
            "Imported data is supplied by the signed-in athlete; it is not verified against a vendor API."
        )
        return review

    def review(self, athlete_id):
        with self.store.read_session() as session:
            return self.build_review(session, session.get(Athlete, athlete_id), include_details=True)

    def preview(self, athlete_id):
        with self.store.transaction() as session:
            athlete = self.store.lock_athlete(session, athlete_id)
            review = self.build_review(session, athlete)
            if not review["program"]["eligible"]:
                raise CoachError(review["program"]["reason"], "adjustment_not_recommended", 409)
            proposed, changes = adjusted_plan(
                self.current_plan(session, athlete),
                self.settings.now().astimezone(ZoneInfo(athlete.timezone)),
                review["program"]["direction"],
            )
            expires = self.settings.now() + timedelta(minutes=10)
            proposal = {
                "proposal_id": str(uuid.uuid4()),
                "base_version": athlete.plan_version,
                "expires_at": expires.isoformat(),
                "direction": review["program"]["direction"],
                "reason": review["program"]["reason"],
                "changes": changes,
                "proposed_plan": proposed.model_dump(mode="json"),
                "evidence_activity_ids": [e["activity_id"] for e in review["program"]["evidence"]],
            }
            session.add(
                AdjustmentProposal(
                    id=proposal["proposal_id"],
                    athlete_id=athlete_id,
                    base_version=athlete.plan_version,
                    evidence_hash=review["evidence_hash"],
                    expires_at=expires.timestamp(),
                    payload=proposal,
                    status="pending",
                )
            )
        return proposal

    def apply(self, athlete_id, proposal_id, expected_version, confirmed):
        if not confirmed:
            raise CoachError(
                "Confirm the proposal before applying it", "confirmation_required", 409
            )
        with self.store.transaction() as session:
            athlete = self.store.lock_athlete(session, athlete_id)
            proposal = session.scalar(
                select(AdjustmentProposal).where(
                    AdjustmentProposal.id == proposal_id,
                    AdjustmentProposal.athlete_id == athlete_id,
                )
            )
            if not proposal:
                raise CoachError("Proposal not found", "not_found", 404)
            review = self.build_review(session, athlete)
            if (
                proposal.status != "pending"
                or proposal.expires_at <= self.settings.now().timestamp()
                or athlete.plan_version != expected_version
                or proposal.base_version != expected_version
                or proposal.evidence_hash != review["evidence_hash"]
                or not review["program"]["eligible"]
            ):
                raise CoachError(
                    "Proposal or evidence changed. Generate a new preview.", "proposal_stale", 409
                )
            plan = Plan.model_validate(proposal.payload["proposed_plan"])
            # The plan, consumed evidence and audit commit together or all roll back.
            proposal.status = "applied"
            session.flush()
            version = self.write_plan(session, athlete, plan, "accepted_adjustment")
            athlete.last_adjustment = {
                "applied_at": self.settings.now().isoformat(),
                "direction": proposal.payload["direction"],
                "evidence_activity_ids": proposal.payload["evidence_activity_ids"],
                "changes": proposal.payload["changes"],
            }
            self.audit(
                session,
                athlete_id,
                "adjustment_applied",
                {"proposal_id": proposal_id, "version": version},
            )
        return {
            "status": "applied",
            "version": version,
            "changes": proposal.payload["changes"],
            "vendor_sync": "not_implemented",
        }

    def export(self, athlete_id):
        with self.store.read_session() as session:
            athlete = session.get(Athlete, athlete_id)
            if not athlete:
                raise CoachError("Account unavailable", "unauthorized", 401)
            plans = session.scalars(
                select(PlanVersion)
                .where(PlanVersion.athlete_id == athlete_id)
                .order_by(PlanVersion.version)
            ).all()
            sources = session.scalars(
                select(Activity).where(Activity.athlete_id == athlete_id)
            ).all()
            audits = session.scalars(
                select(AuditEvent)
                .where(AuditEvent.athlete_id == athlete_id)
                .order_by(AuditEvent.created_at)
            ).all()
            proposals = session.scalars(
                select(AdjustmentProposal).where(AdjustmentProposal.athlete_id == athlete_id)
            ).all()
            return {
                "schema_version": 1,
                "exported_at": self.settings.now().isoformat(),
                "account": {
                    "id": athlete.id,
                    "email": athlete.email,
                    "timezone": athlete.timezone,
                    "created_at": athlete.created_at,
                },
                "current_plan_version": athlete.plan_version,
                "activity_details": [{"source": row.provider, "source_activity_id": row.provider_id,
                    "version": row.version, "summary_hash": row.summary_hash, "details": row.payload}
                    for row in session.scalars(select(ActivityDetails).where(ActivityDetails.athlete_id == athlete_id))],
                "training_profile": ({"version": profile.version, "profile": profile.payload,
                                      "updated_at": profile.updated_at}
                                     if (profile := session.get(AthleteProfile, athlete_id)) else None),
                "plans": [
                    {
                        "version": p.version,
                        "plan": p.payload,
                        "created_at": p.created_at,
                        "reason": p.reason,
                    }
                    for p in plans
                ],
                "activity_sources": [
                    {
                        "activity": a.payload,
                        "canonical_id": a.canonical_id,
                        "ingestion_method": a.ingestion_method,
                    }
                    for a in sources
                ],
                "adjustment_proposals": [
                    {"proposal": p.payload, "status": p.status} for p in proposals
                ],
                "last_adjustment": athlete.last_adjustment,
                "audit": [
                    {"event": a.event, "created_at": a.created_at, "payload": a.payload}
                    for a in audits
                ],
            }
