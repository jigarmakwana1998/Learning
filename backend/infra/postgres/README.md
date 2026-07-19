# PostgreSQL least-privilege bootstrap

After applying Alembic migrations as the database owner, run `psql -f roles.sql`
with an owner credential and set passwords/secrets out of band. Run
`psql -f verify_roles.sql` in CI to assert the `agent_writer` role cannot access
canonical records or create DDL, while the deterministic `promoter` can promote
validated staged records.

API requests must set `app.current_user_id` transaction-locally from an already
authenticated JWT/session before querying RLS-protected learner tables. Do not
grant `BYPASSRLS`, schema `CREATE`, or database-owner credentials to runtime
roles.
