from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    """Supabase identity mirror plus the learner profile (formerly `profiles`)."""
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    auth_subject: Mapped[str | None] = mapped_column(String(36), unique=True, nullable=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    role: Mapped[str] = mapped_column(String(16), default="learner")
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    expertise_preferences: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AgentRun(Base):
    """One learner request and the agent run that answers it (formerly also `learning_requests`)."""
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    topic: Mapped[str] = mapped_column(String(160))
    level: Mapped[str] = mapped_column(String(32))
    hours_per_week: Mapped[int] = mapped_column(Integer)
    weeks: Mapped[int] = mapped_column(Integer)
    # The physical column keeps its historical name for migration compatibility.
    # The value identifies an agent harness, never an LLM provider.
    harness: Mapped[str] = mapped_column("provider", String(32))
    status: Mapped[str] = mapped_column(String(16), default="running")
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The shared course this run produced or reused.
    course_id: Mapped[str | None] = mapped_column(ForeignKey("courses.id", ondelete="SET NULL"), index=True, nullable=True)


class AgentEvent(Base):
    """Append-only run log: sessions, transcript messages, tool calls, model calls and lifecycle.

    A session is the row with event_type="session" (name = agent name); every other row of
    that session points at it through session_id. Transcript rows are event_type="message"
    (name = role) with Fernet-encrypted `content`. Model calls are not stored here: they
    live in LiteLLM's spend logs, tagged with run_id/session_id (app/harness/spend_logs.py).
    """
    __tablename__ = "agent_events"
    __table_args__ = (
        Index("uq_agent_events_session_sequence", "session_id", "sequence", unique=True),
        Index("ix_agent_events_run_created", "run_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"))
    session_id: Mapped[str | None] = mapped_column(ForeignKey("agent_events.id"), nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    event_type: Mapped[str] = mapped_column(String(24))
    name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(16), default="completed")
    input_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_cost_usd: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Attempt(Base):
    """A learner submission and its evaluation (formerly `attempts`, `evaluations` and the
    per-run quiz/assignment submission tables). It answers either a canonical assessment or
    the assessment embedded in an agent run's result."""
    __tablename__ = "attempts"
    __table_args__ = (
        CheckConstraint("score IS NULL OR (score >= 0 AND score <= 1)", name="ck_attempts_score"),
        CheckConstraint("assessment_id IS NOT NULL OR agent_run_id IS NOT NULL", name="ck_attempts_target"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    assessment_id: Mapped[str | None] = mapped_column(ForeignKey("assessments.id", ondelete="CASCADE"), nullable=True)
    agent_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True, nullable=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(24), default="quiz")
    answers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="submitted")
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    feedback: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LessonProgressRecord(Base):
    __tablename__ = "learning_run_lesson_progress"
    agent_run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    lesson_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    completed: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


# Knowledge registry. Every agent-derived row records the run that produced it, and the
# page text a claim cites is kept in resource_versions, so a wrong statement in a lesson
# can be traced to the exact source passage and corrected.


class Resource(Base):
    __tablename__ = "resources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    canonical_url: Mapped[str] = mapped_column(String(2048), unique=True)
    title: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    external_ids: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    license: Mapped[str | None] = mapped_column(String(128), nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    first_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True)


class ResourceVersion(Base):
    """The page text exactly as an agent read it."""
    __tablename__ = "resource_versions"
    __table_args__ = (UniqueConstraint("resource_id", "content_hash", name="uq_resource_versions_resource_hash"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id", ondelete="RESTRICT"), index=True)
    content_hash: Mapped[str] = mapped_column(String(128))
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    etag: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_modified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    storage_uri: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    simhash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True)


class Concept(Base):
    __tablename__ = "concepts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(300))
    normalized_name: Mapped[str] = mapped_column(String(300), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Claim(Base):
    """A statement taken from a source passage: evidence_start/end index into ResourceVersion.content."""
    __tablename__ = "claims"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_claims_confidence"),
        CheckConstraint("evidence_start IS NULL OR (evidence_start >= 0 AND evidence_end >= evidence_start)", name="ck_claims_evidence_span"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    resource_version_id: Mapped[str] = mapped_column(ForeignKey("resource_versions.id", ondelete="RESTRICT"), index=True)
    concept_id: Mapped[str | None] = mapped_column(ForeignKey("concepts.id", ondelete="SET NULL"), index=True, nullable=True)
    statement: Mapped[str] = mapped_column(Text)
    evidence_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float] = mapped_column(Float)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Course(Base):
    """Readable by every learner; only the owner may change it (row-level security in roles.sql)."""
    __tablename__ = "courses"
    __table_args__ = (CheckConstraint("coverage_score IS NULL OR (coverage_score >= 0 AND coverage_score <= 1)", name="ck_courses_coverage_score"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # TopicIntent.fingerprint: equivalent requests find the same course for reuse.
    intent_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(300))
    outline: Mapped[dict] = mapped_column(JSON)
    coverage_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    fresh_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL", use_alter=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=now, nullable=True)


class CourseConcept(Base):
    """Per-concept coverage of a course; the indexed input to compute_coverage_gaps."""
    __tablename__ = "course_concepts"
    __table_args__ = (
        CheckConstraint("status IN ('covered', 'partial', 'missing')", name="ck_course_concepts_status"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_course_concepts_confidence"),
    )
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True)
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id", ondelete="CASCADE"), primary_key=True, index=True)
    status: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float)


class Assessment(Base):
    """A course can have many assessments of different kinds (quiz, assignment, project, ...)."""
    __tablename__ = "assessments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(24), default="quiz")
    title: Mapped[str] = mapped_column(String(300))
    items: Mapped[list | dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MasteryEstimate(Base):
    __tablename__ = "mastery_estimates"
    __table_args__ = (CheckConstraint("mastery >= 0 AND mastery <= 1", name="ck_mastery_estimates_value"),)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id", ondelete="CASCADE"), primary_key=True)
    mastery: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
