-- Execute as the database owner after `alembic upgrade head`.
-- Application credentials must use one of these roles; never distribute the
-- owner/migration credential to API workers.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rw') THEN CREATE ROLE app_rw NOINHERIT LOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'readonly') THEN CREATE ROLE readonly NOINHERIT LOGIN; END IF;
  -- Retired with the staging tables (revision 0009): agents never hold database credentials.
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_writer') THEN DROP OWNED BY agent_writer; DROP ROLE agent_writer; END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'promoter') THEN DROP OWNED BY promoter; DROP ROLE promoter; END IF;
END $$;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC, app_rw, readonly;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC, app_rw, readonly;

GRANT USAGE ON SCHEMA public TO app_rw, readonly;

-- API role: no DDL. Run traces and cited evidence are never deleted so a wrong
-- statement can always be traced back to its run and source passage.
GRANT SELECT, INSERT, UPDATE ON users, agent_runs, agent_events, attempts, learning_run_lesson_progress, mastery_estimates TO app_rw;
GRANT SELECT, INSERT, UPDATE ON resources, resource_versions, concepts, claims TO app_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON courses, assessments, course_concepts TO app_rw;

GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly;

-- Model calls are read from LiteLLM's own spend log table (same database, created by the proxy).
DO $$
BEGIN
  IF to_regclass('"LiteLLM_SpendLogs"') IS NOT NULL THEN GRANT SELECT ON "LiteLLM_SpendLogs" TO app_rw; END IF;
END $$;

-- API identity is set by the authenticated request on a transaction-local basis:
--   SELECT set_config('app.current_user_id', '<uuid>', true);
ALTER TABLE courses ENABLE ROW LEVEL SECURITY;
ALTER TABLE assessments ENABLE ROW LEVEL SECURITY;
ALTER TABLE course_concepts ENABLE ROW LEVEL SECURITY;
ALTER TABLE attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE mastery_estimates ENABLE ROW LEVEL SECURITY;

-- Courses are shared: every learner reads them, only the owner changes them.
DROP POLICY IF EXISTS courses_owner ON courses;
DROP POLICY IF EXISTS courses_read ON courses;
CREATE POLICY courses_read ON courses FOR SELECT USING (true);
CREATE POLICY courses_owner ON courses USING (owner_user_id = current_setting('app.current_user_id', true)) WITH CHECK (owner_user_id = current_setting('app.current_user_id', true));
DROP POLICY IF EXISTS assessments_read ON assessments;
DROP POLICY IF EXISTS assessments_owner ON assessments;
CREATE POLICY assessments_read ON assessments FOR SELECT USING (true);
CREATE POLICY assessments_owner ON assessments USING (EXISTS (SELECT 1 FROM courses WHERE courses.id = assessments.course_id AND courses.owner_user_id = current_setting('app.current_user_id', true))) WITH CHECK (EXISTS (SELECT 1 FROM courses WHERE courses.id = assessments.course_id AND courses.owner_user_id = current_setting('app.current_user_id', true)));
DROP POLICY IF EXISTS course_concepts_read ON course_concepts;
DROP POLICY IF EXISTS course_concepts_owner ON course_concepts;
CREATE POLICY course_concepts_read ON course_concepts FOR SELECT USING (true);
CREATE POLICY course_concepts_owner ON course_concepts USING (EXISTS (SELECT 1 FROM courses WHERE courses.id = course_concepts.course_id AND courses.owner_user_id = current_setting('app.current_user_id', true))) WITH CHECK (EXISTS (SELECT 1 FROM courses WHERE courses.id = course_concepts.course_id AND courses.owner_user_id = current_setting('app.current_user_id', true)));

-- Learner-owned records.
DROP POLICY IF EXISTS attempts_owner ON attempts;
CREATE POLICY attempts_owner ON attempts USING (user_id = current_setting('app.current_user_id', true)) WITH CHECK (user_id = current_setting('app.current_user_id', true));
DROP POLICY IF EXISTS mastery_owner ON mastery_estimates;
CREATE POLICY mastery_owner ON mastery_estimates USING (user_id = current_setting('app.current_user_id', true)) WITH CHECK (user_id = current_setting('app.current_user_id', true));

-- Run `ALTER ROLE <migration-owner> SET row_security = off` only for migrations;
-- never grant BYPASSRLS to app_rw or readonly.
