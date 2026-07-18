"""initial persistent agent analytics schema"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("users", sa.Column("id", sa.String(36), primary_key=True), sa.Column("email", sa.String(320), nullable=False, unique=True), sa.Column("password_hash", sa.String(512), nullable=False), sa.Column("role", sa.String(16), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("learning_requests", sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("topic", sa.String(160), nullable=False), sa.Column("level", sa.String(32), nullable=False), sa.Column("hours_per_week", sa.Integer, nullable=False), sa.Column("weeks", sa.Integer, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("agent_runs", sa.Column("id", sa.String(36), primary_key=True), sa.Column("learning_request_id", sa.String(36), sa.ForeignKey("learning_requests.id"), nullable=False), sa.Column("provider", sa.String(32), nullable=False), sa.Column("status", sa.String(16), nullable=False), sa.Column("result", sa.JSON, nullable=True), sa.Column("started_at", sa.DateTime(timezone=True), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table("agent_sessions", sa.Column("id", sa.String(36), primary_key=True), sa.Column("agent_run_id", sa.String(36), sa.ForeignKey("agent_runs.id"), nullable=False), sa.Column("agent_name", sa.String(32), nullable=False), sa.Column("provider", sa.String(32), nullable=False), sa.Column("status", sa.String(16), nullable=False), sa.Column("input_payload", sa.JSON, nullable=True), sa.Column("output_payload", sa.JSON, nullable=True), sa.Column("error_message", sa.Text, nullable=True), sa.Column("started_at", sa.DateTime(timezone=True), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True), sa.Column("duration_ms", sa.Integer, nullable=True))
    op.create_table("transcript_entries", sa.Column("id", sa.String(36), primary_key=True), sa.Column("session_id", sa.String(36), sa.ForeignKey("agent_sessions.id"), nullable=False), sa.Column("sequence", sa.Integer, nullable=False), sa.Column("role", sa.String(32), nullable=False), sa.Column("encrypted_content", sa.Text, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("mcp_tool_invocations", sa.Column("id", sa.String(36), primary_key=True), sa.Column("session_id", sa.String(36), sa.ForeignKey("agent_sessions.id"), nullable=False), sa.Column("tool_name", sa.String(80), nullable=False), sa.Column("status", sa.String(16), nullable=False), sa.Column("metadata_json", sa.JSON, nullable=True), sa.Column("error_message", sa.Text, nullable=True), sa.Column("duration_ms", sa.Integer, nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    for name, table, column in [("ix_users_email", "users", "email"), ("ix_learning_requests_user_id", "learning_requests", "user_id"), ("ix_agent_runs_request_id", "agent_runs", "learning_request_id"), ("ix_agent_sessions_run_id", "agent_sessions", "agent_run_id"), ("ix_transcript_entries_session_id", "transcript_entries", "session_id"), ("ix_mcp_tool_invocations_session_id", "mcp_tool_invocations", "session_id")]: op.create_index(name, table, [column])


def downgrade():
    for name, table in [("ix_mcp_tool_invocations_session_id", "mcp_tool_invocations"), ("ix_transcript_entries_session_id", "transcript_entries"), ("ix_agent_sessions_run_id", "agent_sessions"), ("ix_agent_runs_request_id", "agent_runs"), ("ix_learning_requests_user_id", "learning_requests"), ("ix_users_email", "users")]: op.drop_index(name, table_name=table)
    for table in ["mcp_tool_invocations", "transcript_entries", "agent_sessions", "agent_runs", "learning_requests", "users"]: op.drop_table(table)
