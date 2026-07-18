-- Execute as the database owner after `alembic upgrade head`.
-- Application credentials must use one of these roles; never distribute the
-- owner/migration credential to API or agent workers.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rw') THEN CREATE ROLE app_rw NOINHERIT LOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_writer') THEN CREATE ROLE agent_writer NOINHERIT LOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'promoter') THEN CREATE ROLE promoter NOINHERIT LOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'readonly') THEN CREATE ROLE readonly NOINHERIT LOGIN; END IF;
END $$;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC, app_rw, agent_writer, promoter, readonly;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC, app_rw, agent_writer, promoter, readonly;

GRANT USAGE ON SCHEMA public TO app_rw, agent_writer, promoter, readonly;

-- API role: no DDL and no agent registry access. Per-user tables are RLS-bound.
GRANT SELECT, INSERT, UPDATE ON users, profiles, courses, enrollments, assessments, attempts, evaluations, mastery_estimates TO app_rw;
GRANT SELECT ON resources, resource_versions, sections, concepts, claims, coverage_ledger TO app_rw;

-- The agent role gets INSERT-only staging access. It cannot read canonical data,
-- update validation state, delete evidence, or execute DDL.
GRANT INSERT ON resources_staging, resource_versions_staging, sections_staging, concepts_staging, claims_staging, courses_staging, assessments_staging TO agent_writer;

-- Deterministic promoter may read/mark staging and write canonical registry data.
GRANT SELECT, UPDATE ON resources_staging, resource_versions_staging, sections_staging, concepts_staging, claims_staging, courses_staging, assessments_staging TO promoter;
GRANT INSERT, UPDATE ON resources, resource_versions, sections, concepts, claims, courses, assessments TO promoter;

GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly;

-- API identity is set by the authenticated request on a transaction-local basis:
--   SELECT set_config('app.current_user_id', '<uuid>', true);
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE courses ENABLE ROW LEVEL SECURITY;
ALTER TABLE enrollments ENABLE ROW LEVEL SECURITY;
ALTER TABLE attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE evaluations ENABLE ROW LEVEL SECURITY;
ALTER TABLE mastery_estimates ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS profiles_owner ON profiles;
CREATE POLICY profiles_owner ON profiles USING (user_id = current_setting('app.current_user_id', true)) WITH CHECK (user_id = current_setting('app.current_user_id', true));
DROP POLICY IF EXISTS courses_owner ON courses;
CREATE POLICY courses_owner ON courses USING (owner_user_id = current_setting('app.current_user_id', true)) WITH CHECK (owner_user_id = current_setting('app.current_user_id', true));
DROP POLICY IF EXISTS enrollments_owner ON enrollments;
CREATE POLICY enrollments_owner ON enrollments USING (user_id = current_setting('app.current_user_id', true)) WITH CHECK (user_id = current_setting('app.current_user_id', true));
DROP POLICY IF EXISTS attempts_owner ON attempts;
CREATE POLICY attempts_owner ON attempts USING (user_id = current_setting('app.current_user_id', true)) WITH CHECK (user_id = current_setting('app.current_user_id', true));
DROP POLICY IF EXISTS evaluations_owner ON evaluations;
CREATE POLICY evaluations_owner ON evaluations USING (EXISTS (SELECT 1 FROM attempts WHERE attempts.id = evaluations.attempt_id AND attempts.user_id = current_setting('app.current_user_id', true)));
DROP POLICY IF EXISTS mastery_owner ON mastery_estimates;
CREATE POLICY mastery_owner ON mastery_estimates USING (user_id = current_setting('app.current_user_id', true)) WITH CHECK (user_id = current_setting('app.current_user_id', true));

-- Run `ALTER ROLE <migration-owner> SET row_security = off` only for migrations;
-- never grant BYPASSRLS to app_rw, agent_writer, promoter, or readonly.
