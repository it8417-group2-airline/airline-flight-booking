-- =====================================================================
-- File   : sql/postgres/12_upgrade_live_audit_fixes.sql   (Abrar - Member 1)
-- Purpose: Bring the LIVE Supabase database in line with the audit fixes
--          that were made in 01, 02 and 04, without rebuilding anything.
--          Run ONCE in the Supabase SQL Editor, then run 09 (which also
--          corrects the regional fare_line statuses - audit I-4).
--   1. Regional time convention (audit I-8): last_modified is always UTC,
--      reserved_at / registered_on default to Bahrain local time, whatever
--      the time zone of the connection (the dashboard uses Asia/Bahrain,
--      the SQL Editor uses UTC).
--   2. Foreign key check (audit I-1): makes sure the embeddings table still
--      points to mainline_carrier.flight.
-- A fresh rebuild (01-04 ...) already contains all of this; it is safe to
-- run this file more than once.
-- =====================================================================

-- 1. regional_partner: same audit/time definitions as the new 02 file
CREATE OR REPLACE FUNCTION regional_partner.touch_last_modified()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.last_modified := now() AT TIME ZONE 'UTC';
  RETURN NEW;
END;
$$;

ALTER TABLE regional_partner.traveler    ALTER COLUMN last_modified SET DEFAULT (now() AT TIME ZONE 'UTC');
ALTER TABLE regional_partner.route       ALTER COLUMN last_modified SET DEFAULT (now() AT TIME ZONE 'UTC');
ALTER TABLE regional_partner.reservation ALTER COLUMN last_modified SET DEFAULT (now() AT TIME ZONE 'UTC');
ALTER TABLE regional_partner.fare_line   ALTER COLUMN last_modified SET DEFAULT (now() AT TIME ZONE 'UTC');
ALTER TABLE regional_partner.traveler    ALTER COLUMN registered_on SET DEFAULT (now() AT TIME ZONE 'Asia/Bahrain')::date;
ALTER TABLE regional_partner.reservation ALTER COLUMN reserved_at   SET DEFAULT (now() AT TIME ZONE 'Asia/Bahrain');

COMMENT ON COLUMN regional_partner.reservation.reserved_at IS 'Bahrain local time (same as route.departure_date/time)';
COMMENT ON COLUMN regional_partner.fare_line.fare_amount   IS 'Copied from route.fare_amount x class factor (Economy 1.00, Premium Economy 1.45, Business 2.60) at sale time';
COMMENT ON COLUMN regional_partner.traveler.last_modified  IS 'UTC - ETL watermark column';
COMMENT ON COLUMN regional_partner.route.last_modified     IS 'UTC - ETL watermark column';
COMMENT ON COLUMN regional_partner.reservation.last_modified IS 'UTC - ETL watermark column';
COMMENT ON COLUMN regional_partner.fare_line.last_modified IS 'UTC - ETL watermark column';

-- 2. embeddings foreign key (restores it only if it is missing)
DO $$
BEGIN
  IF to_regclass('vector_store.flight_note_embeddings') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_constraint
                     WHERE conname = 'flight_note_embeddings_flight_id_fkey') THEN
    ALTER TABLE vector_store.flight_note_embeddings
      ADD CONSTRAINT flight_note_embeddings_flight_id_fkey
      FOREIGN KEY (flight_id) REFERENCES mainline_carrier.flight(flight_id) ON DELETE CASCADE;
  END IF;
END $$;

-- Check: expect 1 foreign key and the new defaults
SELECT (SELECT count(*) FROM pg_constraint
        WHERE conname = 'flight_note_embeddings_flight_id_fkey')               AS embeddings_fk,
       (SELECT column_default FROM information_schema.columns
        WHERE table_schema = 'regional_partner' AND table_name = 'reservation'
          AND column_name = 'reserved_at')                                      AS reserved_at_default,
       (SELECT column_default FROM information_schema.columns
        WHERE table_schema = 'regional_partner' AND table_name = 'fare_line'
          AND column_name = 'last_modified')                                    AS last_modified_default;
