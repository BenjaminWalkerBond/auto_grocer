-- One-time bootstrap for the auto_grocier database on a local Postgres.
-- Run as the postgres superuser:
--   psql -U postgres -h localhost -p 5432 -f database/bootstrap_local.sql
-- Safe to re-run (idempotent).

-- 1. Create the application role if it does not already exist.
DO
$$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'grocier_user') THEN
      CREATE ROLE grocier_user LOGIN PASSWORD 'grocier_pass_123';
   END IF;
END
$$;

-- 2. Create the database (owned by grocier_user) if it does not already exist.
SELECT 'CREATE DATABASE auto_grocier OWNER grocier_user'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'auto_grocier')
\gexec

-- 3. Grant database-level privileges.
GRANT ALL PRIVILEGES ON DATABASE auto_grocier TO grocier_user;

-- 4. Connect to the new database and grant schema privileges.
\connect auto_grocier
GRANT ALL ON SCHEMA public TO grocier_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO grocier_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO grocier_user;
