-- =====================================================================
-- File   : sql/postgres/11_read_only_role.sql   (Abrar - Member 1)   OPTIONAL
-- Purpose: A read-only database login for Databricks (Member 2's extract)
--          or for the tutor, instead of sharing the owner password (audit I-7).
--
-- Why policies are needed: RLS is enabled on all 10 tables (files 01/02) to
-- block Supabase's public API. The table OWNER is not affected, but any other
-- login sees 0 rows until it gets a SELECT policy. This file adds one.
--
-- How to use
--   1. Replace <choose-a-strong-password> below (the script refuses to run
--      with the placeholder), then run the whole file in the Supabase SQL Editor.
--   2. Connection string for the new login (session pooler, port 5432):
--      postgresql://etl_reader.<project-ref>:<password>@aws-1-ap-northeast-1.pooler.supabase.com:5432/postgres
--      (the user name is the role name + "." + the project ref)
--   3. Share that password privately (never in GitHub).
-- Safe to re-run: the role, grants and policies are created only if missing.
-- Default decision of the team: Databricks and the tutor use the OWNER connection
-- string (README.md, "Tutor access"), so this file is only needed if a
-- separate login is wanted.
-- =====================================================================

DO $$
DECLARE
  v_password TEXT := '<choose-a-strong-password>';
BEGIN
  IF v_password LIKE '<%' THEN
    RAISE EXCEPTION 'Edit the password in 11_read_only_role.sql before running it.';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'etl_reader') THEN
    EXECUTE format('CREATE ROLE etl_reader LOGIN PASSWORD %L', v_password);
  ELSE
    EXECUTE format('ALTER ROLE etl_reader LOGIN PASSWORD %L', v_password);
  END IF;
END $$;

-- Read access to the three schemas (current and future tables / views)
GRANT USAGE  ON SCHEMA mainline_carrier, regional_partner, vector_store TO etl_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA mainline_carrier, regional_partner, vector_store TO etl_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA mainline_carrier, regional_partner, vector_store
  GRANT SELECT ON TABLES TO etl_reader;

-- One SELECT policy per RLS-protected table (RLS stays on for the public API)
DO $$
DECLARE t RECORD;
BEGIN
  FOR t IN SELECT schemaname, tablename
           FROM pg_tables
           WHERE schemaname IN ('mainline_carrier', 'regional_partner')
  LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_policies
                   WHERE schemaname = t.schemaname AND tablename = t.tablename
                     AND policyname = 'read_only_select') THEN
      EXECUTE format('CREATE POLICY read_only_select ON %I.%I FOR SELECT TO etl_reader USING (true)',
                     t.schemaname, t.tablename);
    END IF;
  END LOOP;
END $$;

-- Check: 10 policies, and the role can read but not write
SELECT schemaname, tablename, policyname
FROM pg_policies
WHERE policyname = 'read_only_select'
ORDER BY 1, 2;
