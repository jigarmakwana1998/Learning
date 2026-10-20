-- Read-only privilege assertions for CI against a PostgreSQL instance after
-- roles.sql. Execute as a database owner or migration role.
DO $$
BEGIN
  IF has_schema_privilege('app_rw', 'public', 'CREATE') THEN
    RAISE EXCEPTION 'app_rw must not have CREATE/DDL access to public';
  END IF;
  IF has_table_privilege('app_rw', 'agent_events', 'DELETE, TRUNCATE') OR has_table_privilege('app_rw', 'claims', 'DELETE, TRUNCATE') OR has_table_privilege('app_rw', 'resource_versions', 'DELETE, TRUNCATE') THEN
    RAISE EXCEPTION 'app_rw must not delete run traces or cited evidence';
  END IF;
  IF NOT has_table_privilege('app_rw', 'courses', 'SELECT, INSERT, UPDATE, DELETE') THEN
    RAISE EXCEPTION 'app_rw must be able to manage courses through row-level security';
  END IF;
  IF NOT (SELECT relrowsecurity FROM pg_class WHERE oid = 'courses'::regclass) THEN
    RAISE EXCEPTION 'courses must enforce row-level security';
  END IF;
  IF (SELECT count(*) FROM pg_policies WHERE tablename = 'courses' AND policyname IN ('courses_read', 'courses_owner')) <> 2 THEN
    RAISE EXCEPTION 'courses must be readable by all and writable only by the owner';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN ('agent_writer', 'promoter')) THEN
    RAISE EXCEPTION 'retired staging roles must not exist';
  END IF;
END $$;
