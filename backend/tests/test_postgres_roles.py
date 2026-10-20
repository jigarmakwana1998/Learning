from pathlib import Path

ROLES = Path(__file__).parents[1] / "infra" / "postgres"


def test_courses_are_shared_but_owner_writable():
    sql = (ROLES / "roles.sql").read_text(encoding="utf-8")

    assert "CREATE POLICY courses_read ON courses FOR SELECT USING (true);" in sql
    owner = next(line for line in sql.splitlines() if line.startswith("CREATE POLICY courses_owner"))
    assert "owner_user_id = current_setting('app.current_user_id', true)" in owner
    assert "WITH CHECK" in owner


def test_traces_and_evidence_are_never_deletable_by_the_api():
    sql = (ROLES / "roles.sql").read_text(encoding="utf-8")

    for line in sql.splitlines():
        if line.startswith("GRANT") and "DELETE" in line:
            assert not any(table in line for table in ("agent_events", "claims", "resource_versions"))
    assert "GRANT ALL" not in sql


def test_postgres_ci_script_checks_no_ddl_and_owner_policies():
    script = (ROLES / "verify_roles.sql").read_text(encoding="utf-8")

    assert "has_schema_privilege('app_rw', 'public', 'CREATE')" in script
    assert "'courses_read', 'courses_owner'" in script
