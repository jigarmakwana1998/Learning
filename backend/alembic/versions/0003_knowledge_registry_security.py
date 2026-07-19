"""knowledge registry, coverage ledger, and agent-write staging boundary

Revision ID: 0003
Revises: 0002
"""

from alembic import op
import sqlalchemy as sa


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


staging_status = sa.Enum(
    "pending", "passed", "failed", "quarantined",
    name="staging_validation_status",
    native_enum=False,
    create_constraint=True,
)


def _staging_columns() -> list[sa.Column]:
    return [
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=128), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("validation_status", staging_status, nullable=False, server_default="pending"),
        sa.Column("validation_errors", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade():
    # Canonical registry and learner-owned records. Agent workers are never granted
    # write access to these tables (see infra/postgres/roles.sql).
    op.create_table(
        "profiles",
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("display_name", sa.String(length=120), nullable=True),
        sa.Column("expertise_preferences", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "resources",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("canonical_url", sa.String(length=2048), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("external_ids", sa.JSON(), nullable=True),
        sa.Column("license", sa.String(length=128), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("canonical_url", name="uq_resources_canonical_url"),
    )
    op.create_table(
        "resource_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("resource_id", sa.String(length=36), sa.ForeignKey("resources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("etag", sa.String(length=512), nullable=True),
        sa.Column("last_modified", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("storage_uri", sa.String(length=2048), nullable=False),
        sa.Column("simhash", sa.String(length=64), nullable=True),
        sa.CheckConstraint("length(content_hash) >= 16", name="ck_resource_versions_content_hash"),
        sa.UniqueConstraint("resource_id", "content_hash", name="uq_resource_versions_resource_hash"),
    )
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
        "concepts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("normalized_name", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("normalized_name", name="uq_concepts_normalized_name"),
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
    op.create_table(
        "courses",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("owner_user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("intent_fingerprint", sa.String(length=64), sa.ForeignKey("coverage_ledger.intent_fingerprint", ondelete="RESTRICT"), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("outline", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "enrollments",
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("course_id", sa.String(length=36), sa.ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("progress >= 0 AND progress <= 1", name="ck_enrollments_progress"),
    )
    op.create_table(
        "assessments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("course_id", sa.String(length=36), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "attempts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("assessment_id", sa.String(length=36), sa.ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "evaluations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("attempt_id", sa.String(length=36), sa.ForeignKey("attempts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("feedback", sa.JSON(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("score >= 0 AND score <= 1", name="ck_evaluations_score"),
    )
    op.create_table(
        "mastery_estimates",
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("concept_id", sa.String(length=36), sa.ForeignKey("concepts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("mastery", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("mastery >= 0 AND mastery <= 1", name="ck_mastery_estimates_value"),
    )

    # Staging twins: no agent-originated material is written to a canonical table.
    op.create_table("resources_staging", sa.Column("id", sa.String(36), primary_key=True), sa.Column("canonical_url", sa.String(2048), nullable=False), sa.Column("title", sa.String(500), nullable=False), sa.Column("external_ids", sa.JSON(), nullable=True), sa.Column("license", sa.String(128), nullable=True), *_staging_columns())
    op.create_table("resource_versions_staging", sa.Column("id", sa.String(36), primary_key=True), sa.Column("resource_staging_id", sa.String(36), sa.ForeignKey("resources_staging.id", ondelete="CASCADE"), nullable=False), sa.Column("content_hash", sa.String(128), nullable=False), sa.Column("etag", sa.String(512), nullable=True), sa.Column("last_modified", sa.DateTime(timezone=True), nullable=True), sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False), sa.Column("storage_uri", sa.String(2048), nullable=False), sa.Column("simhash", sa.String(64), nullable=True), sa.CheckConstraint("length(content_hash) >= 16", name="ck_resource_versions_staging_content_hash"), *_staging_columns())
    op.create_table("sections_staging", sa.Column("id", sa.String(36), primary_key=True), sa.Column("resource_version_staging_id", sa.String(36), sa.ForeignKey("resource_versions_staging.id", ondelete="CASCADE"), nullable=False), sa.Column("path", sa.String(2048), nullable=False), sa.Column("section_hash", sa.String(128), nullable=False), sa.Column("char_span_start", sa.Integer(), nullable=False), sa.Column("char_span_end", sa.Integer(), nullable=False), sa.CheckConstraint("char_span_start >= 0 AND char_span_end >= char_span_start", name="ck_sections_staging_char_span"), *_staging_columns())
    op.create_table("concepts_staging", sa.Column("id", sa.String(36), primary_key=True), sa.Column("name", sa.String(300), nullable=False), sa.Column("normalized_name", sa.String(300), nullable=False), sa.Column("description", sa.Text(), nullable=True), *_staging_columns())
    op.create_table("claims_staging", sa.Column("id", sa.String(36), primary_key=True), sa.Column("subject_concept_id", sa.String(36), nullable=False), sa.Column("predicate", sa.String(80), nullable=False), sa.Column("object_value", sa.String(500), nullable=False), sa.Column("section_id", sa.String(36), nullable=False), sa.Column("evidence_char_start", sa.Integer(), nullable=False), sa.Column("evidence_char_end", sa.Integer(), nullable=False), sa.Column("confidence", sa.Float(), nullable=False), sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_claims_staging_confidence"), *_staging_columns())
    op.create_table("courses_staging", sa.Column("id", sa.String(36), primary_key=True), sa.Column("owner_user_id", sa.String(36), nullable=False), sa.Column("intent_fingerprint", sa.String(64), nullable=False), sa.Column("title", sa.String(300), nullable=False), sa.Column("outline", sa.JSON(), nullable=False), *_staging_columns())
    op.create_table("assessments_staging", sa.Column("id", sa.String(36), primary_key=True), sa.Column("course_id", sa.String(36), nullable=False), sa.Column("title", sa.String(300), nullable=False), sa.Column("items", sa.JSON(), nullable=False), *_staging_columns())

    for name, table, column in [
        ("ix_resource_versions_resource_id", "resource_versions", "resource_id"),
        ("ix_sections_resource_version_id", "sections", "resource_version_id"),
        ("ix_claims_subject_concept_id", "claims", "subject_concept_id"),
        ("ix_claims_section_id", "claims", "section_id"),
        ("ix_courses_owner_user_id", "courses", "owner_user_id"),
        ("ix_attempts_user_id", "attempts", "user_id"),
        ("ix_coverage_ledger_fresh_until", "coverage_ledger", "fresh_until"),
        ("ix_resources_staging_run_id", "resources_staging", "run_id"),
        ("ix_resources_staging_status", "resources_staging", "validation_status"),
        ("ix_claims_staging_run_id", "claims_staging", "run_id"),
        ("ix_claims_staging_status", "claims_staging", "validation_status"),
    ]:
        op.create_index(name, table, [column])

    # JSONB expression indexes enforce a single known external ID per registry.
    # SQLite retains the portable table constraints; production PostgreSQL gets the
    # deduplication indexes required by the ingestion ladder.
    if op.get_bind().dialect.name == "postgresql":
        for key in ("doi", "isbn", "openalex", "arxiv"):
            # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text -- key is from the fixed tuple above, never user input.
            op.execute(sa.text(f"CREATE UNIQUE INDEX uq_resources_external_{key} ON resources ((external_ids->>'{key}')) WHERE external_ids ? '{key}'"))


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        for key in ("doi", "isbn", "openalex", "arxiv"):
            # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text -- key is from the fixed tuple above, never user input.
            op.execute(sa.text(f"DROP INDEX IF EXISTS uq_resources_external_{key}"))
    for name, table in [
        ("ix_claims_staging_status", "claims_staging"), ("ix_claims_staging_run_id", "claims_staging"),
        ("ix_resources_staging_status", "resources_staging"), ("ix_resources_staging_run_id", "resources_staging"),
        ("ix_coverage_ledger_fresh_until", "coverage_ledger"), ("ix_attempts_user_id", "attempts"),
        ("ix_courses_owner_user_id", "courses"), ("ix_claims_section_id", "claims"),
        ("ix_claims_subject_concept_id", "claims"), ("ix_sections_resource_version_id", "sections"),
        ("ix_resource_versions_resource_id", "resource_versions"),
    ]:
        op.drop_index(name, table_name=table)
    for table in [
        "assessments_staging", "courses_staging", "claims_staging", "concepts_staging", "sections_staging",
        "resource_versions_staging", "resources_staging", "mastery_estimates", "evaluations", "attempts",
        "assessments", "enrollments", "courses", "coverage_ledger", "claims", "concepts", "sections",
        "resource_versions", "resources", "profiles",
    ]:
        op.drop_table(table)
