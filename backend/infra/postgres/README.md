# PostgreSQL least-privilege bootstrap

After applying Alembic migrations as the database owner, run `psql -f roles.sql`
with an owner credential and set passwords/secrets out of band. Run
`psql -f verify_roles.sql` in CI to assert `app_rw` has no DDL, cannot delete run
traces or cited evidence, and that courses are readable by everyone but writable
only by their owner.

API requests must set `app.current_user_id` transaction-locally from an already
authenticated JWT/session before querying RLS-protected tables. Do not grant
`BYPASSRLS`, schema `CREATE`, or database-owner credentials to runtime roles.
Re-run `roles.sql` after the LiteLLM proxy has created `LiteLLM_SpendLogs` so the
API can read model calls from it.
