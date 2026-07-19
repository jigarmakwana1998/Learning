"""persist end-to-end learning workflow progress and submissions

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "learning_run_quiz_submissions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_run_id", sa.String(36), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("score_percent", sa.Integer(), nullable=False),
        sa.Column("feedback", sa.JSON(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "learning_run_assignment_submissions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_run_id", sa.String(36), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("feedback", sa.JSON(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "learning_run_lesson_progress",
        sa.Column("agent_run_id", sa.String(36), sa.ForeignKey("agent_runs.id"), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("lesson_id", sa.String(160), primary_key=True),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name, table, column in [
        ("ix_quiz_submissions_run", "learning_run_quiz_submissions", "agent_run_id"),
        ("ix_quiz_submissions_user", "learning_run_quiz_submissions", "user_id"),
        ("ix_assignment_submissions_run", "learning_run_assignment_submissions", "agent_run_id"),
        ("ix_assignment_submissions_user", "learning_run_assignment_submissions", "user_id"),
    ]:
        op.create_index(name, table, [column])


def downgrade():
    for name, table in [
        ("ix_assignment_submissions_user", "learning_run_assignment_submissions"),
        ("ix_assignment_submissions_run", "learning_run_assignment_submissions"),
        ("ix_quiz_submissions_user", "learning_run_quiz_submissions"),
        ("ix_quiz_submissions_run", "learning_run_quiz_submissions"),
    ]:
        op.drop_index(name, table_name=table)
    op.drop_table("learning_run_lesson_progress")
    op.drop_table("learning_run_assignment_submissions")
    op.drop_table("learning_run_quiz_submissions")
