"""reshape the knowledge registry for integration; model calls live only in LiteLLM

- agent_events: drop copied LiteLLM model calls, one sequence per session (unique),
  (run_id, created_at) index replaces the single-column indexes
- agent_runs.course_id links a run to the shared course it produced or reused
- resources/resource_versions keep the page text an agent read (content, run_id)
- claims cite a resource_version passage + run; sections dropped
- courses absorb coverage_ledger (coverage_score, fresh_until) + course_concepts
- assessments get a kind (many per course); enrollments dropped (agent_runs says who
  requested which course)
- the 7 *_staging tables are dropped: agents never hold database credentials
- users: drop ix_users_email, a duplicate of the unique constraint

The registry tables had no writer before this revision, so they are reshaped rather
than migrated row by row.

Revision ID: 0009
Revises: 0008
"""

import importlib.util
from pathlib import Path

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

STAGING = ["sections_staging", "resource_versions_staging", "resources_staging", "claims_staging", "concepts_staging", "courses_staging", "assessments_staging"]
SQLITE_FK_NAMES = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}


def upgrade():
    # SQLite batch rebuilds of `users` (0007/0008 downgrades) do not always keep it.
    op.drop_index("ix_users_email", table_name="users", if_exists=True)

    op.execute("DELETE FROM agent_events WHERE event_type = 'model'")
    # 0008 merged transcript and trace rows, which numbered themselves independently.
    op.execute("""
        UPDATE agent_events SET sequence = (
            SELECT ranked.position FROM (
                SELECT id, ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY created_at, sequence, id) AS position
                FROM agent_events WHERE session_id IS NOT NULL
            ) ranked WHERE ranked.id = agent_events.id
        ) WHERE session_id IS NOT NULL
    """)
    for name in ("ix_agent_events_run_id", "ix_agent_events_session_id", "ix_agent_events_created_at"):
        op.drop_index(name, table_name="agent_events")
    op.create_index("uq_agent_events_session_sequence", "agent_events", ["session_id", "sequence"], unique=True)
    op.create_index("ix_agent_events_run_created", "agent_events", ["run_id", "created_at"])

    for table in STAGING:
        op.drop_table(table)
    op.drop_table("claims")
    op.drop_table("sections")
    op.drop_table("enrollments")

    with op.batch_alter_table("resources") as batch:
        batch.add_column(sa.Column("kind", sa.String(32), nullable=True))
        batch.add_column(sa.Column("first_run_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_resources_first_run_id", "agent_runs", ["first_run_id"], ["id"], ondelete="SET NULL")
    with op.batch_alter_table("resource_versions") as batch:
        batch.alter_column("storage_uri", existing_type=sa.String(2048), nullable=True)
        batch.add_column(sa.Column("content", sa.Text(), nullable=True))
        batch.add_column(sa.Column("run_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_resource_versions_run_id", "agent_runs", ["run_id"], ["id"], ondelete="SET NULL")

    op.create_table(
        "claims",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("resource_version_id", sa.String(36), sa.ForeignKey("resource_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("concept_id", sa.String(36), sa.ForeignKey("concepts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("evidence_start", sa.Integer(), nullable=True),
        sa.Column("evidence_end", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_claims_confidence"),
        sa.CheckConstraint("evidence_start IS NULL OR (evidence_start >= 0 AND evidence_end >= evidence_start)", name="ck_claims_evidence_span"),
    )
    for column in ("resource_version_id", "concept_id", "run_id"):
        op.create_index(f"ix_claims_{column}", "claims", [column])

    # 0003 left this FK unnamed (SQLite) or auto-named (PostgreSQL); a 0009 downgrade names it.
    ledger_fk = next(fk["name"] for fk in sa.inspect(op.get_bind()).get_foreign_keys("courses") if fk["referred_table"] == "coverage_ledger")
    with op.batch_alter_table("courses", naming_convention=SQLITE_FK_NAMES) as batch:
        batch.drop_constraint(ledger_fk or "fk_courses_intent_fingerprint_coverage_ledger", type_="foreignkey")
    with op.batch_alter_table("courses") as batch:
        batch.add_column(sa.Column("coverage_score", sa.Float(), nullable=True))
        batch.add_column(sa.Column("fresh_until", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("created_by_run_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("courses") as batch:
        batch.create_foreign_key("fk_courses_created_by_run_id", "agent_runs", ["created_by_run_id"], ["id"], ondelete="SET NULL")
        batch.create_check_constraint("ck_courses_coverage_score", "coverage_score IS NULL OR (coverage_score >= 0 AND coverage_score <= 1)")
    op.create_index("ix_courses_intent_fingerprint", "courses", ["intent_fingerprint"])
    op.drop_table("coverage_ledger")

    op.create_table(
        "course_concepts",
        sa.Column("course_id", sa.String(36), sa.ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("concept_id", sa.String(36), sa.ForeignKey("concepts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.CheckConstraint("status IN ('covered', 'partial', 'missing')", name="ck_course_concepts_status"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_course_concepts_confidence"),
    )
    op.create_index("ix_course_concepts_concept_id", "course_concepts", ["concept_id"])

    with op.batch_alter_table("assessments") as batch:
        batch.add_column(sa.Column("kind", sa.String(24), nullable=False, server_default="quiz"))
    op.create_index("ix_assessments_course_id", "assessments", ["course_id"])

    with op.batch_alter_table("agent_runs") as batch:
        batch.add_column(sa.Column("course_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_agent_runs_course_id", "courses", ["course_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_agent_runs_course_id", "agent_runs", ["course_id"])


def _revision_0003():
    path = Path(__file__).with_name("0003_knowledge_registry_security.py")
    spec = importlib.util.spec_from_file_location("revision_0003", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def downgrade():
    staging_columns = _revision_0003()._staging_columns

    op.drop_index("ix_agent_runs_course_id", table_name="agent_runs")
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_constraint("fk_agent_runs_course_id", type_="foreignkey")
        batch.drop_column("course_id")

    op.drop_index("ix_assessments_course_id", table_name="assessments")
    with op.batch_alter_table("assessments") as batch:
        batch.drop_column("kind")

    op.drop_table("course_concepts")

    op.create_table(
        "coverage_ledger",
        sa.Column("intent_fingerprint", sa.String(length=64), primary_key=True),
        sa.Column("concepts", sa.JSON(), nullable=False),
        sa.Column("learning_objectives", sa.JSON(), nullable=False),
        sa.Column("expertise_level", sa.String(length=32), nullable=False),
        sa.Column("source_types", sa.JSON(), nullable=False),
        sa.Column("time_window_days", sa.Integer(), nullable=True),
        sa.Column("coverage_score", sa.Float(), nullable=False),
        sa.Column("known_gaps", sa.JSON(), nullable=False),
        sa.Column("fresh_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(intent_fingerprint) = 64", name="ck_coverage_fingerprint"),
        sa.CheckConstraint("coverage_score >= 0 AND coverage_score <= 1", name="ck_coverage_score"),
        sa.CheckConstraint("time_window_days IS NULL OR time_window_days > 0", name="ck_coverage_window"),
    )
    op.create_index("ix_coverage_ledger_fresh_until", "coverage_ledger", ["fresh_until"])
    # Courses kept their fingerprint; give each one the ledger row 0003 requires.
    op.execute("""
        INSERT INTO coverage_ledger (intent_fingerprint, concepts, learning_objectives, expertise_level, source_types, coverage_score, known_gaps, fresh_until, observed_at)
        SELECT intent_fingerprint, '[]', '[]', 'beginner', '[]', MAX(COALESCE(coverage_score, 0)), '[]', MAX(fresh_until), CURRENT_TIMESTAMP
        FROM courses GROUP BY intent_fingerprint
    """)
    op.drop_index("ix_courses_intent_fingerprint", table_name="courses")
    with op.batch_alter_table("courses") as batch:
        batch.drop_constraint("ck_courses_coverage_score", type_="check")
        batch.drop_constraint("fk_courses_created_by_run_id", type_="foreignkey")
        for column in ("updated_at", "created_by_run_id", "fresh_until", "coverage_score"):
            batch.drop_column(column)
    with op.batch_alter_table("courses") as batch:
        batch.create_foreign_key("courses_intent_fingerprint_fkey", "coverage_ledger", ["intent_fingerprint"], ["intent_fingerprint"], ondelete="RESTRICT")

    op.drop_table("claims")
    with op.batch_alter_table("resource_versions") as batch:
        batch.drop_constraint("fk_resource_versions_run_id", type_="foreignkey")
        batch.drop_column("run_id")
        batch.drop_column("content")
    op.execute("UPDATE resource_versions SET storage_uri = '' WHERE storage_uri IS NULL")
    with op.batch_alter_table("resource_versions") as batch:
        batch.alter_column("storage_uri", existing_type=sa.String(2048), nullable=False)
    with op.batch_alter_table("resources") as batch:
        batch.drop_constraint("fk_resources_first_run_id", type_="foreignkey")
        batch.drop_column("first_run_id")
        batch.drop_column("kind")

    op.create_table(
        "sections",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("resource_version_id", sa.String(length=36), sa.ForeignKey("resource_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("path", sa.String(length=2048), nullable=False),
        sa.Column("section_hash", sa.String(length=128), nullable=False),
        sa.Column("char_span_start", sa.Integer(), nullable=False),
        sa.Column("char_span_end", sa.Integer(), nullable=False),
        sa.CheckConstraint("char_span_start >= 0 AND char_span_end >= char_span_start", name="ck_sections_char_span"),
        sa.UniqueConstraint("resource_version_id", "section_hash", name="uq_sections_version_hash"),
    )
    op.create_table(
        "claims",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("subject_concept_id", sa.String(length=36), sa.ForeignKey("concepts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("predicate", sa.String(length=80), nullable=False),
        sa.Column("object_value", sa.String(length=500), nullable=False),
        sa.Column("section_id", sa.String(length=36), sa.ForeignKey("sections.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("evidence_char_start", sa.Integer(), nullable=False),
        sa.Column("evidence_char_end", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_claims_confidence"),
        sa.CheckConstraint("evidence_char_start >= 0 AND evidence_char_end >= evidence_char_start", name="ck_claims_evidence_span"),
    )
    op.create_table(
        "enrollments",
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("course_id", sa.String(length=36), sa.ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("progress >= 0 AND progress <= 1", name="ck_enrollments_progress"),
    )
    op.create_table("resources_staging", sa.Column("id", sa.String(36), primary_key=True), sa.Column("canonical_url", sa.String(2048), nullable=False), sa.Column("title", sa.String(500), nullable=False), sa.Column("external_ids", sa.JSON(), nullable=True), sa.Column("license", sa.String(128), nullable=True), *staging_columns())
    op.create_table("resource_versions_staging", sa.Column("id", sa.String(36), primary_key=True), sa.Column("resource_staging_id", sa.String(36), sa.ForeignKey("resources_staging.id", ondelete="CASCADE"), nullable=False), sa.Column("content_hash", sa.String(128), nullable=False), sa.Column("etag", sa.String(512), nullable=True), sa.Column("last_modified", sa.DateTime(timezone=True), nullable=True), sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False), sa.Column("storage_uri", sa.String(2048), nullable=False), sa.Column("simhash", sa.String(64), nullable=True), sa.CheckConstraint("length(content_hash) >= 16", name="ck_resource_versions_staging_content_hash"), *staging_columns())
    op.create_table("sections_staging", sa.Column("id", sa.String(36), primary_key=True), sa.Column("resource_version_staging_id", sa.String(36), sa.ForeignKey("resource_versions_staging.id", ondelete="CASCADE"), nullable=False), sa.Column("path", sa.String(2048), nullable=False), sa.Column("section_hash", sa.String(128), nullable=False), sa.Column("char_span_start", sa.Integer(), nullable=False), sa.Column("char_span_end", sa.Integer(), nullable=False), sa.CheckConstraint("char_span_start >= 0 AND char_span_end >= char_span_start", name="ck_sections_staging_char_span"), *staging_columns())
    op.create_table("concepts_staging", sa.Column("id", sa.String(36), primary_key=True), sa.Column("name", sa.String(300), nullable=False), sa.Column("normalized_name", sa.String(300), nullable=False), sa.Column("description", sa.Text(), nullable=True), *staging_columns())
    op.create_table("claims_staging", sa.Column("id", sa.String(36), primary_key=True), sa.Column("subject_concept_id", sa.String(36), nullable=False), sa.Column("predicate", sa.String(80), nullable=False), sa.Column("object_value", sa.String(500), nullable=False), sa.Column("section_id", sa.String(36), nullable=False), sa.Column("evidence_char_start", sa.Integer(), nullable=False), sa.Column("evidence_char_end", sa.Integer(), nullable=False), sa.Column("confidence", sa.Float(), nullable=False), sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_claims_staging_confidence"), *staging_columns())
    op.create_table("courses_staging", sa.Column("id", sa.String(36), primary_key=True), sa.Column("owner_user_id", sa.String(36), nullable=False), sa.Column("intent_fingerprint", sa.String(64), nullable=False), sa.Column("title", sa.String(300), nullable=False), sa.Column("outline", sa.JSON(), nullable=False), *staging_columns())
    op.create_table("assessments_staging", sa.Column("id", sa.String(36), primary_key=True), sa.Column("course_id", sa.String(36), nullable=False), sa.Column("title", sa.String(300), nullable=False), sa.Column("items", sa.JSON(), nullable=False), *staging_columns())
    for name, table, column in [
        ("ix_sections_resource_version_id", "sections", "resource_version_id"),
        ("ix_claims_subject_concept_id", "claims", "subject_concept_id"),
        ("ix_claims_section_id", "claims", "section_id"),
        ("ix_resources_staging_run_id", "resources_staging", "run_id"),
        ("ix_resources_staging_status", "resources_staging", "validation_status"),
        ("ix_claims_staging_run_id", "claims_staging", "run_id"),
        ("ix_claims_staging_status", "claims_staging", "validation_status"),
    ]:
        op.create_index(name, table, [column])

    # Deleted LiteLLM model-call copies are not restored; they remain in LiteLLM_SpendLogs.
    op.drop_index("ix_agent_events_run_created", table_name="agent_events")
    op.drop_index("uq_agent_events_session_sequence", table_name="agent_events")
    for column in ("run_id", "session_id", "created_at"):
        op.create_index(f"ix_agent_events_{column}", "agent_events", [column])

    op.create_index("ix_users_email", "users", ["email"])
