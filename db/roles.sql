-- Idempotent privilege setup. Run by db/provision.py as the admin role (neondb_owner), AFTER the
-- roles exist. Contains no secrets.
--
-- Security model (see SECURITY.md):
--   * analyst_ro: the ONLY role the agent's SQL tool uses. Its safety comes from PRIVILEGES: it
--     holds SELECT on analytics.* and nothing else, so writes/DDL fail even if the validator is
--     bypassed. The role-level settings below (read-only default, timeouts) are defence in depth:
--     a session can override them with SET, which is why privileges are the real guarantee.
--   * app_rw: threads/checkpoints in schema "app". No access to analytics.
--   * neondb_owner (admin): migrations and seeding only; never used by the agent.

CREATE SCHEMA IF NOT EXISTS analytics;
CREATE SCHEMA IF NOT EXISTS app;

-- ---------- analyst_ro ----------
REVOKE ALL ON SCHEMA public FROM analyst_ro;
REVOKE ALL ON SCHEMA app FROM analyst_ro;
GRANT CONNECT ON DATABASE neondb TO analyst_ro;
GRANT USAGE ON SCHEMA analytics TO analyst_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO analyst_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA analytics GRANT SELECT ON TABLES TO analyst_ro;

ALTER ROLE analyst_ro SET search_path = analytics;
ALTER ROLE analyst_ro SET default_transaction_read_only = on;
ALTER ROLE analyst_ro SET statement_timeout = '15s';
ALTER ROLE analyst_ro SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE analyst_ro CONNECTION LIMIT 10;

-- ---------- app_rw ----------
REVOKE ALL ON SCHEMA analytics FROM app_rw;
REVOKE ALL ON SCHEMA public FROM app_rw;
GRANT CONNECT ON DATABASE neondb TO app_rw;
GRANT ALL ON SCHEMA app TO app_rw;
ALTER ROLE app_rw SET search_path = app;

-- app_rw needs the application tables created by migrations (owned by the admin role).
GRANT ALL ON ALL TABLES IN SCHEMA app TO app_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT ALL ON TABLES TO app_rw;
