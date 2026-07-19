-- Read-only privilege assertions for CI against a PostgreSQL instance after
-- roles.sql. Execute as a database owner or migration role.
DO $$
BEGIN
  IF has_schema_privilege('agent_writer', 'public', 'CREATE') THEN
    RAISE EXCEPTION 'agent_writer must not have CREATE/DDL access to public';
  END IF;
  IF has_table_privilege('agent_writer', 'resources', 'SELECT, INSERT, UPDATE, DELETE, TRUNCATE') THEN
    RAISE EXCEPTION 'agent_writer must have no canonical resources privileges';
  END IF;
  IF has_table_privilege('agent_writer', 'claims', 'SELECT, INSERT, UPDATE, DELETE, TRUNCATE') THEN
    RAISE EXCEPTION 'agent_writer must have no canonical claims privileges';
  END IF;
  IF NOT has_table_privilege('agent_writer', 'resources_staging', 'INSERT') THEN
    RAISE EXCEPTION 'agent_writer must be able to insert staged resources';
  END IF;
  IF has_table_privilege('agent_writer', 'resources_staging', 'SELECT, UPDATE, DELETE, TRUNCATE') THEN
    RAISE EXCEPTION 'agent_writer must be insert-only on staged resources';
  END IF;
  IF NOT has_table_privilege('promoter', 'resources', 'INSERT') OR NOT has_table_privilege('promoter', 'resources_staging', 'UPDATE') THEN
    RAISE EXCEPTION 'promoter must be able to promote and mark staged resources';
  END IF;
END $$;
