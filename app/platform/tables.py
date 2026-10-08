from sqlalchemy import JSON, Float, ForeignKey, ForeignKeyConstraint, Index, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SchemaRevision(Base):
    __tablename__ = "ac_schema_revision"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer)


class Athlete(Base):
    __tablename__ = "ac_athletes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(40))
    write_revision: Mapped[int] = mapped_column(Integer, default=0)
    plan_version: Mapped[int] = mapped_column(Integer, default=0)
    activities_updated_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_adjustment: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class AuthSession(Base):
    __tablename__ = "ac_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    athlete_id: Mapped[str] = mapped_column(
        ForeignKey("ac_athletes.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[float] = mapped_column(Float, index=True)
    created_at: Mapped[str] = mapped_column(String(40))


class AthleteProfile(Base):
    __tablename__ = "ac_athlete_profiles"
    athlete_id: Mapped[str] = mapped_column(
        ForeignKey("ac_athletes.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[str] = mapped_column(String(40))


class RateLimit(Base):
    __tablename__ = "ac_rate_limits"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer)
    window_end: Mapped[float] = mapped_column(Float, index=True)


class PlanVersion(Base):
    __tablename__ = "ac_plan_versions"
    athlete_id: Mapped[str] = mapped_column(
        ForeignKey("ac_athletes.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(String(40))


class Activity(Base):
    __tablename__ = "ac_activities"
    __table_args__ = (Index("ix_ac_activity_athlete_time", "athlete_id", "start_epoch"),)
    athlete_id: Mapped[str] = mapped_column(
        ForeignKey("ac_athletes.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(String(40), primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    canonical_id: Mapped[str] = mapped_column(String(36), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[str] = mapped_column(String(40))
    ingestion_method: Mapped[str] = mapped_column(String(40))
    start_epoch: Mapped[float] = mapped_column(Float)


class ActivityDetails(Base):
    __tablename__ = "ac_activity_details"
    __table_args__ = (ForeignKeyConstraint(
        ["athlete_id", "provider", "provider_id"],
        ["ac_activities.athlete_id", "ac_activities.provider", "ac_activities.provider_id"], ondelete="CASCADE"),)
    athlete_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    summary_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[str] = mapped_column(String(40))


class AdjustmentProposal(Base):
    __tablename__ = "ac_adjustment_proposals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    athlete_id: Mapped[str] = mapped_column(
        ForeignKey("ac_athletes.id", ondelete="CASCADE"), index=True
    )
    base_version: Mapped[int] = mapped_column(Integer)
    evidence_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[float] = mapped_column(Float)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="pending")


class AuditEvent(Base):
    __tablename__ = "ac_audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    athlete_id: Mapped[str] = mapped_column(
        ForeignKey("ac_athletes.id", ondelete="CASCADE"), index=True
    )
    event: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
