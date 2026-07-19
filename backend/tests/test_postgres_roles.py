from pathlib import Path


def test_agent_writer_is_insert_only_on_staging_tables():
    sql = (Path(__file__).parents[1] / "infra" / "postgres" / "roles.sql").read_text(encoding="utf-8")

    agent_grant = next(line for line in sql.splitlines() if line.startswith("GRANT INSERT ON resources_staging"))
    assert "resources_staging" in agent_grant and "claims_staging" in agent_grant
    assert "GRANT INSERT, UPDATE ON resources" not in agent_grant
    assert "GRANT ALL" not in agent_grant


def test_postgres_ci_script_checks_canonical_denial_and_no_ddl():
    script = (Path(__file__).parents[1] / "infra" / "postgres" / "verify_roles.sql").read_text(encoding="utf-8")

    assert "has_schema_privilege('agent_writer', 'public', 'CREATE')" in script
    assert "'resources', 'SELECT, INSERT, UPDATE, DELETE, TRUNCATE'" in script
    assert "'resources_staging', 'SELECT, UPDATE, DELETE, TRUNCATE'" in script
