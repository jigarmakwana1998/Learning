"""append-only agent run telemetry ledger"""

from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    settings = sa.table("system_settings", sa.column("key", sa.String), sa.column("value", sa.String))
    connection = op.get_bind()
    legacy_harness = connection.execute(
        sa.select(settings.c.value).where(settings.c.key == "agent_provider")
    ).scalar_one_or_none()
    current_harness = connection.execute(
        sa.select(settings.c.value).where(settings.c.key == "agent_harness")
    ).scalar_one_or_none()
    if legacy_harness is not None and current_harness is None:
        connection.execute(
            settings.update().where(settings.c.key == "agent_provider").values(key="agent_harness")
        )
    elif legacy_harness is not None:
        connection.execute(settings.delete().where(settings.c.key == "agent_provider"))

    op.create_table(
        "agent_trace_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("agent_sessions.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=True),
        sa.Column("output_payload", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_cost_usd", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name, column in [("ix_agent_trace_events_run_id", "run_id"), ("ix_agent_trace_events_session_id", "session_id"), ("ix_agent_trace_events_event_type", "event_type"), ("ix_agent_trace_events_status", "status"), ("ix_agent_trace_events_created_at", "created_at")]:
        op.create_index(name, "agent_trace_events", [column])


def downgrade():
    for name in ["ix_agent_trace_events_created_at", "ix_agent_trace_events_status", "ix_agent_trace_events_event_type", "ix_agent_trace_events_session_id", "ix_agent_trace_events_run_id"]:
        op.drop_index(name, table_name="agent_trace_events")
    op.drop_table("agent_trace_events")
    settings = sa.table("system_settings", sa.column("key", sa.String), sa.column("value", sa.String))
    connection = op.get_bind()
    current_harness = connection.execute(
        sa.select(settings.c.value).where(settings.c.key == "agent_harness")
    ).scalar_one_or_none()
    legacy_harness = connection.execute(
        sa.select(settings.c.value).where(settings.c.key == "agent_provider")
    ).scalar_one_or_none()
    if current_harness is not None and legacy_harness is None:
        connection.execute(
            settings.update().where(settings.c.key == "agent_harness").values(key="agent_provider")
        )
