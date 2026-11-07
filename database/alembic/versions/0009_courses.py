"""course versions built from a research run, and the source pages they cite"""

from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "source_pages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("research_run_id", sa.String(36), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("research_run_id", "position"),
    )
    op.create_index("ix_source_pages_research_run_id", "source_pages", ["research_run_id"])
    op.create_table(
        "courses",
        sa.Column("id", sa.String(36), sa.ForeignKey("agent_runs.id"), primary_key=True),
        sa.Column("research_run_id", sa.String(36), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("chapters", sa.JSON(), nullable=False),
        sa.Column("sections", sa.JSON(), nullable=False),
        sa.UniqueConstraint("research_run_id", "version"),
    )
    op.create_index("ix_courses_research_run_id", "courses", ["research_run_id"])


def downgrade():
    op.drop_index("ix_courses_research_run_id", table_name="courses")
    op.drop_table("courses")
    op.drop_index("ix_source_pages_research_run_id", table_name="source_pages")
    op.drop_table("source_pages")
