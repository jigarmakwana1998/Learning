"""merge overlapping tables

- profiles                                   -> users
- learning_requests                          -> agent_runs
- agent_sessions, transcript_entries,
  mcp_tool_invocations, agent_trace_events   -> agent_events
- evaluations, learning_run_quiz_submissions,
  learning_run_assignment_submissions        -> attempts

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    # users <- profiles
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("display_name", sa.String(120), nullable=True))
        batch.add_column(sa.Column("expertise_preferences", sa.JSON(), nullable=True))
    op.execute("""
        UPDATE users SET
            display_name = (SELECT p.display_name FROM profiles p WHERE p.user_id = users.id),
            expertise_preferences = (SELECT p.expertise_preferences FROM profiles p WHERE p.user_id = users.id)
    """)
    op.drop_table("profiles")

    # agent_events <- agent_sessions + transcript_entries + agent_trace_events + mcp_tool_invocations
    op.create_table(
        "agent_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("agent_events.id"), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=True),
        sa.Column("output_payload", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_cost_usd", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in ("run_id", "session_id", "created_at"):
        op.create_index(f"ix_agent_events_{column}", "agent_events", [column])
    op.execute("""
        INSERT INTO agent_events (id, run_id, session_id, sequence, event_type, name, status, input_payload, output_payload, error_message, duration_ms, created_at, completed_at)
        SELECT id, agent_run_id, NULL, 0, 'session', agent_name, status, input_payload, output_payload, error_message, duration_ms, started_at, completed_at
        FROM agent_sessions
    """)
    op.execute("""
        INSERT INTO agent_events (id, run_id, session_id, sequence, event_type, name, status, content, created_at)
        SELECT t.id, s.agent_run_id, t.session_id, t.sequence, 'message', t.role, 'completed', t.encrypted_content, t.created_at
        FROM transcript_entries t JOIN agent_sessions s ON s.id = t.session_id
    """)
    op.execute("""
        INSERT INTO agent_events (id, run_id, session_id, sequence, event_type, name, status, input_payload, output_payload, metadata_json, error_message, duration_ms, prompt_tokens, completion_tokens, total_cost_usd, created_at)
        SELECT id, run_id, session_id, sequence, event_type, name, status, input_payload, output_payload, metadata_json, error_message, duration_ms, prompt_tokens, completion_tokens, total_cost_usd, created_at
        FROM agent_trace_events
    """)
    # Tool invocations were mirrored into agent_trace_events from 0005 on; only
    # sessions without any mirrored tool event still need their invocations copied.
    op.execute("""
        INSERT INTO agent_events (id, run_id, session_id, sequence, event_type, name, status, metadata_json, error_message, duration_ms, created_at)
        SELECT m.id, s.agent_run_id, m.session_id, 0, 'tool', m.tool_name, m.status, m.metadata_json, m.error_message, m.duration_ms, m.created_at
        FROM mcp_tool_invocations m JOIN agent_sessions s ON s.id = m.session_id
        WHERE NOT EXISTS (SELECT 1 FROM agent_trace_events e WHERE e.session_id = m.session_id AND e.event_type = 'tool')
    """)
    op.execute("UPDATE agent_events SET status = 'completed' WHERE status = 'success'")
    for table in ("mcp_tool_invocations", "transcript_entries", "agent_trace_events", "agent_sessions"):
        op.drop_table(table)

    # agent_runs <- learning_requests
    op.drop_index("ix_agent_runs_request_id", table_name="agent_runs")
    with op.batch_alter_table("agent_runs") as batch:
        batch.add_column(sa.Column("user_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("topic", sa.String(160), nullable=True))
        batch.add_column(sa.Column("level", sa.String(32), nullable=True))
        batch.add_column(sa.Column("hours_per_week", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("weeks", sa.Integer(), nullable=True))
    op.execute("""
        UPDATE agent_runs SET
            user_id = (SELECT r.user_id FROM learning_requests r WHERE r.id = agent_runs.learning_request_id),
            topic = (SELECT r.topic FROM learning_requests r WHERE r.id = agent_runs.learning_request_id),
            level = (SELECT r.level FROM learning_requests r WHERE r.id = agent_runs.learning_request_id),
            hours_per_week = (SELECT r.hours_per_week FROM learning_requests r WHERE r.id = agent_runs.learning_request_id),
            weeks = (SELECT r.weeks FROM learning_requests r WHERE r.id = agent_runs.learning_request_id)
    """)
    with op.batch_alter_table("agent_runs") as batch:
        for name, type_ in (("user_id", sa.String(36)), ("topic", sa.String(160)), ("level", sa.String(32)), ("hours_per_week", sa.Integer()), ("weeks", sa.Integer())):
            batch.alter_column(name, existing_type=type_, nullable=False)
        batch.create_foreign_key("fk_agent_runs_user_id", "users", ["user_id"], ["id"])
        batch.drop_column("learning_request_id")
    op.create_index("ix_agent_runs_user_id", "agent_runs", ["user_id"])
    op.create_index("ix_agent_runs_started_at", "agent_runs", ["started_at"])
    op.drop_table("learning_requests")

    # attempts <- evaluations + learning_run_quiz_submissions + learning_run_assignment_submissions
    with op.batch_alter_table("attempts") as batch:
        batch.alter_column("assessment_id", existing_type=sa.String(36), nullable=True)
        batch.alter_column("answers", existing_type=sa.JSON(), nullable=True)
        batch.add_column(sa.Column("agent_run_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("kind", sa.String(24), nullable=False, server_default="quiz"))
        batch.add_column(sa.Column("content", sa.Text(), nullable=True))
        batch.add_column(sa.Column("status", sa.String(24), nullable=False, server_default="submitted"))
        batch.add_column(sa.Column("score", sa.Float(), nullable=True))
        batch.add_column(sa.Column("feedback", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("attempts") as batch:
        batch.create_foreign_key("fk_attempts_agent_run_id", "agent_runs", ["agent_run_id"], ["id"], ondelete="CASCADE")
        batch.create_check_constraint("ck_attempts_score", "score IS NULL OR (score >= 0 AND score <= 1)")
        batch.create_check_constraint("ck_attempts_target", "assessment_id IS NOT NULL OR agent_run_id IS NOT NULL")
    op.create_index("ix_attempts_agent_run_id", "attempts", ["agent_run_id"])
    # An attempt keeps its latest evaluation.
    latest = "FROM evaluations e WHERE e.attempt_id = attempts.id ORDER BY e.evaluated_at DESC LIMIT 1"
    op.execute(f"""
        UPDATE attempts SET
            score = (SELECT e.score {latest}),
            feedback = (SELECT e.feedback {latest}),
            evaluated_at = (SELECT e.evaluated_at {latest}),
            status = 'evaluated'
        WHERE EXISTS (SELECT 1 FROM evaluations e WHERE e.attempt_id = attempts.id)
    """)
    op.execute("""
        INSERT INTO attempts (id, agent_run_id, user_id, kind, answers, status, score, feedback, submitted_at, evaluated_at)
        SELECT id, agent_run_id, user_id, 'quiz', answers, 'evaluated', score_percent / 100.0, feedback, submitted_at, submitted_at
        FROM learning_run_quiz_submissions
    """)
    op.execute("""
        INSERT INTO attempts (id, agent_run_id, user_id, kind, content, status, feedback, submitted_at, evaluated_at)
        SELECT id, agent_run_id, user_id, kind, content, status, feedback, submitted_at, submitted_at
        FROM learning_run_assignment_submissions
    """)
    for table in ("evaluations", "learning_run_quiz_submissions", "learning_run_assignment_submissions"):
        op.drop_table(table)


def downgrade():
    # attempts -> evaluations + learning_run_quiz_submissions + learning_run_assignment_submissions
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
        "evaluations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("attempt_id", sa.String(length=36), sa.ForeignKey("attempts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("feedback", sa.JSON(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("score >= 0 AND score <= 1", name="ck_evaluations_score"),
    )
    for name, table, column in [
        ("ix_quiz_submissions_run", "learning_run_quiz_submissions", "agent_run_id"),
        ("ix_quiz_submissions_user", "learning_run_quiz_submissions", "user_id"),
        ("ix_assignment_submissions_run", "learning_run_assignment_submissions", "agent_run_id"),
        ("ix_assignment_submissions_user", "learning_run_assignment_submissions", "user_id"),
    ]:
        op.create_index(name, table, [column])
    op.execute("""
        INSERT INTO learning_run_quiz_submissions (id, agent_run_id, user_id, answers, score_percent, feedback, submitted_at)
        SELECT id, agent_run_id, user_id, answers, CAST(ROUND(score * 100) AS INTEGER), feedback, submitted_at
        FROM attempts WHERE assessment_id IS NULL AND kind = 'quiz'
    """)
    op.execute("""
        INSERT INTO learning_run_assignment_submissions (id, agent_run_id, user_id, kind, content, status, feedback, submitted_at)
        SELECT id, agent_run_id, user_id, kind, content, status, feedback, submitted_at
        FROM attempts WHERE assessment_id IS NULL AND kind <> 'quiz'
    """)
    op.execute("""
        INSERT INTO evaluations (id, attempt_id, score, feedback, evaluated_at)
        SELECT id, id, score, COALESCE(feedback, '[]'), COALESCE(evaluated_at, submitted_at)
        FROM attempts WHERE assessment_id IS NOT NULL AND score IS NOT NULL
    """)
    op.execute("DELETE FROM attempts WHERE assessment_id IS NULL")
    op.execute("UPDATE attempts SET answers = '{}' WHERE answers IS NULL")
    op.drop_index("ix_attempts_agent_run_id", table_name="attempts")
    with op.batch_alter_table("attempts") as batch:
        batch.drop_constraint("ck_attempts_target", type_="check")
        batch.drop_constraint("ck_attempts_score", type_="check")
        batch.drop_constraint("fk_attempts_agent_run_id", type_="foreignkey")
        for column in ("evaluated_at", "feedback", "score", "status", "content", "kind", "agent_run_id"):
            batch.drop_column(column)
        batch.alter_column("answers", existing_type=sa.JSON(), nullable=False)
        batch.alter_column("assessment_id", existing_type=sa.String(36), nullable=False)

    # agent_runs -> learning_requests
    op.create_table(
        "learning_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("topic", sa.String(160), nullable=False),
        sa.Column("level", sa.String(32), nullable=False),
        sa.Column("hours_per_week", sa.Integer, nullable=False),
        sa.Column("weeks", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_learning_requests_user_id", "learning_requests", ["user_id"])
    op.execute("""
        INSERT INTO learning_requests (id, user_id, topic, level, hours_per_week, weeks, created_at)
        SELECT id, user_id, topic, level, hours_per_week, weeks, started_at FROM agent_runs
    """)
    op.drop_index("ix_agent_runs_started_at", table_name="agent_runs")
    op.drop_index("ix_agent_runs_user_id", table_name="agent_runs")
    with op.batch_alter_table("agent_runs") as batch:
        batch.add_column(sa.Column("learning_request_id", sa.String(36), nullable=True))
    op.execute("UPDATE agent_runs SET learning_request_id = id")
    with op.batch_alter_table("agent_runs") as batch:
        batch.alter_column("learning_request_id", existing_type=sa.String(36), nullable=False)
        batch.create_foreign_key("fk_agent_runs_learning_request_id", "learning_requests", ["learning_request_id"], ["id"])
        batch.drop_constraint("fk_agent_runs_user_id", type_="foreignkey")
        for column in ("weeks", "hours_per_week", "level", "topic", "user_id"):
            batch.drop_column(column)
    op.create_index("ix_agent_runs_request_id", "agent_runs", ["learning_request_id"])

    # agent_events -> agent_sessions + transcript_entries + agent_trace_events + mcp_tool_invocations
    op.create_table("agent_sessions", sa.Column("id", sa.String(36), primary_key=True), sa.Column("agent_run_id", sa.String(36), sa.ForeignKey("agent_runs.id"), nullable=False), sa.Column("agent_name", sa.String(32), nullable=False), sa.Column("provider", sa.String(32), nullable=False), sa.Column("status", sa.String(16), nullable=False), sa.Column("input_payload", sa.JSON, nullable=True), sa.Column("output_payload", sa.JSON, nullable=True), sa.Column("error_message", sa.Text, nullable=True), sa.Column("started_at", sa.DateTime(timezone=True), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True), sa.Column("duration_ms", sa.Integer, nullable=True))
    op.create_table("transcript_entries", sa.Column("id", sa.String(36), primary_key=True), sa.Column("session_id", sa.String(36), sa.ForeignKey("agent_sessions.id"), nullable=False), sa.Column("sequence", sa.Integer, nullable=False), sa.Column("role", sa.String(32), nullable=False), sa.Column("encrypted_content", sa.Text, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("mcp_tool_invocations", sa.Column("id", sa.String(36), primary_key=True), sa.Column("session_id", sa.String(36), sa.ForeignKey("agent_sessions.id"), nullable=False), sa.Column("tool_name", sa.String(80), nullable=False), sa.Column("status", sa.String(16), nullable=False), sa.Column("metadata_json", sa.JSON, nullable=True), sa.Column("error_message", sa.Text, nullable=True), sa.Column("duration_ms", sa.Integer, nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
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
    for name, table, column in [
        ("ix_agent_sessions_run_id", "agent_sessions", "agent_run_id"),
        ("ix_transcript_entries_session_id", "transcript_entries", "session_id"),
        ("ix_mcp_tool_invocations_session_id", "mcp_tool_invocations", "session_id"),
        ("ix_agent_trace_events_run_id", "agent_trace_events", "run_id"),
        ("ix_agent_trace_events_session_id", "agent_trace_events", "session_id"),
        ("ix_agent_trace_events_event_type", "agent_trace_events", "event_type"),
        ("ix_agent_trace_events_status", "agent_trace_events", "status"),
        ("ix_agent_trace_events_created_at", "agent_trace_events", "created_at"),
    ]:
        op.create_index(name, table, [column])
    op.execute("""
        INSERT INTO agent_sessions (id, agent_run_id, agent_name, provider, status, input_payload, output_payload, error_message, started_at, completed_at, duration_ms)
        SELECT e.id, e.run_id, SUBSTR(e.name, 1, 32), r.provider, e.status, e.input_payload, e.output_payload, e.error_message, e.created_at, e.completed_at, e.duration_ms
        FROM agent_events e JOIN agent_runs r ON r.id = e.run_id WHERE e.event_type = 'session'
    """)
    op.execute("""
        INSERT INTO transcript_entries (id, session_id, sequence, role, encrypted_content, created_at)
        SELECT id, session_id, sequence, SUBSTR(name, 1, 32), COALESCE(content, ''), created_at
        FROM agent_events WHERE event_type = 'message'
    """)
    op.execute("""
        INSERT INTO mcp_tool_invocations (id, session_id, tool_name, status, metadata_json, error_message, duration_ms, created_at)
        SELECT id, session_id, SUBSTR(name, 1, 80), CASE WHEN status = 'completed' THEN 'success' ELSE status END, metadata_json, error_message, duration_ms, created_at
        FROM agent_events WHERE event_type = 'tool'
    """)
    op.execute("""
        INSERT INTO agent_trace_events (id, run_id, session_id, sequence, event_type, name, status, input_payload, output_payload, metadata_json, error_message, duration_ms, prompt_tokens, completion_tokens, total_cost_usd, created_at)
        SELECT id, run_id, session_id, sequence, event_type, name, status, input_payload, output_payload, metadata_json, error_message, duration_ms, prompt_tokens, completion_tokens, total_cost_usd, created_at
        FROM agent_events WHERE event_type NOT IN ('session', 'message')
    """)
    op.drop_table("agent_events")

    # users -> profiles
    op.create_table(
        "profiles",
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("display_name", sa.String(length=120), nullable=True),
        sa.Column("expertise_preferences", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute("""
        INSERT INTO profiles (user_id, display_name, expertise_preferences, created_at, updated_at)
        SELECT id, display_name, expertise_preferences, created_at, created_at
        FROM users WHERE display_name IS NOT NULL OR expertise_preferences IS NOT NULL
    """)
    with op.batch_alter_table("users") as batch:
        batch.drop_column("expertise_preferences")
        batch.drop_column("display_name")
