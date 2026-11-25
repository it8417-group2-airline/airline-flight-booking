-- =====================================================================
-- File   : sql/postgres/01_mainline_carrier_schema.sql   (Abrar - Member 1)
-- Purpose: Schema 1 of 2: MAINLINE carrier - normalised (3NF), 6 tables.
--          Columns marked [ETL-DROP] are excluded by Member 2's Databricks ETL.
--
-- !! WARNING: running this file on Supabase DELETES the whole mainline_carrier
-- !! schema (DROP SCHEMA ... CASCADE): all its data, the views of file 07 and
-- !! the function close_departed_flights() of file 09. The embeddings table is
-- !! kept and its foreign key to flight is restored at the end of this file.
-- !! Only run it to rebuild from scratch, then follow the run order:
-- !!   01 -> 02 -> 03 -> 04 -> 07 -> vector/01 -> 09   (see README.md)
-- =====================================================================

DROP SCHEMA IF EXISTS mainline_carrier CASCADE;
CREATE SCHEMA mainline_carrier;
SET search_path TO mainline_carrier;

-- Keeps updated_at current on every UPDATE (used by the ETL to load only changed rows)
CREATE OR REPLACE FUNCTION mainline_carrier.set_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

-- 1. airport
CREATE TABLE airport (
  airport_code    CHAR(3)      PRIMARY KEY,
  airport_name    VARCHAR(120) NOT NULL,
  city            VARCHAR(80)  NOT NULL,
  country_code    CHAR(2)      NOT NULL,
  is_hub          BOOLEAN      NOT NULL DEFAULT FALSE,
  timezone_name   VARCHAR(40),            -- [ETL-DROP]
  terminal_count  SMALLINT                -- [ETL-DROP]
);

-- 2. cabin_class
CREATE TABLE cabin_class (
  cabin_class_id      SMALLINT     PRIMARY KEY,
  cabin_code          CHAR(1)      NOT NULL UNIQUE,
  cabin_name          VARCHAR(30)  NOT NULL UNIQUE,
  fare_multiplier     NUMERIC(4,2) NOT NULL CHECK (fare_multiplier >= 1),
  lounge_access_code  VARCHAR(10),        -- [ETL-DROP]
  display_colour      VARCHAR(7)          -- [ETL-DROP]
);

-- 3. passenger
CREATE TABLE passenger (
  passenger_id       SERIAL       PRIMARY KEY,
  first_name         VARCHAR(60)  NOT NULL,
  last_name          VARCHAR(60)  NOT NULL,
  email              VARCHAR(120) UNIQUE,
  date_of_birth      DATE,
  nationality        CHAR(2),
  frequent_flyer_no  VARCHAR(12),
  phone              VARCHAR(20),         -- [ETL-DROP]
  passport_scan_ref  VARCHAR(40),         -- [ETL-DROP]
  created_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- 4. flight
CREATE TABLE flight (
  flight_id            SERIAL        PRIMARY KEY,
  flight_number        VARCHAR(8)    NOT NULL,
  origin_code          CHAR(3)       NOT NULL REFERENCES airport(airport_code),
  destination_code     CHAR(3)       NOT NULL REFERENCES airport(airport_code),
  scheduled_departure  TIMESTAMPTZ   NOT NULL,
  scheduled_arrival    TIMESTAMPTZ   NOT NULL,
  actual_departure     TIMESTAMPTZ,
  actual_arrival       TIMESTAMPTZ,
  flight_status        VARCHAR(10)   NOT NULL DEFAULT 'SCHEDULED'
                       CHECK (flight_status IN ('SCHEDULED','LANDED','DELAYED','CANCELLED','DIVERTED')),
  aircraft_type        VARCHAR(20),
  base_fare            NUMERIC(10,3) NOT NULL CHECK (base_fare > 0),
  notes                TEXT,               -- disruption notes -> pgvector (Flow 5)
  crew_manifest_ref    VARCHAR(30),        -- [ETL-DROP] (Appendix I)
  gate_code            VARCHAR(5),         -- [ETL-DROP]
  review_count         INTEGER       NOT NULL DEFAULT 0,   -- Flow 4 (Member 3)
  avg_rating           NUMERIC(3,2)  CHECK (avg_rating BETWEEN 1 AND 5),
  photo_like_total     INTEGER       NOT NULL DEFAULT 0,
  updated_at           TIMESTAMPTZ   NOT NULL DEFAULT now(),
  CHECK (origin_code <> destination_code),
  CHECK (scheduled_arrival > scheduled_departure)
);

-- 5. booking
CREATE TABLE booking (
  booking_id         SERIAL       PRIMARY KEY,
  booking_reference  CHAR(6)      NOT NULL UNIQUE,
  passenger_id       INTEGER      NOT NULL REFERENCES passenger(passenger_id),
  booking_date       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  booking_status     VARCHAR(10)  NOT NULL DEFAULT 'CONFIRMED'
                     CHECK (booking_status IN ('CONFIRMED','COMPLETED','CANCELLED')),
  booking_channel    VARCHAR(6)   NOT NULL DEFAULT 'WEB'
                     CHECK (booking_channel IN ('WEB','APP','AGENT')),
  payment_method     VARCHAR(20),
  session_ip         INET,                -- [ETL-DROP]
  agent_remarks      TEXT,                -- [ETL-DROP]
  updated_at         TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- 6. ticket (links ONE booking to ONE flight)
CREATE TABLE ticket (
  ticket_id           SERIAL        PRIMARY KEY,
  ticket_number       VARCHAR(14)   NOT NULL UNIQUE,
  booking_id          INTEGER       NOT NULL REFERENCES booking(booking_id) ON DELETE CASCADE,
  flight_id           INTEGER       NOT NULL REFERENCES flight(flight_id),
  cabin_class_id      SMALLINT      NOT NULL REFERENCES cabin_class(cabin_class_id),
  seat_number         VARCHAR(4),
  fare_paid           NUMERIC(10,3) NOT NULL CHECK (fare_paid >= 0),
  ticket_status       VARCHAR(8)    NOT NULL DEFAULT 'ISSUED'
                      CHECK (ticket_status IN ('ISSUED','USED','REFUNDED','VOID')),
  baggage_tag_ref     VARCHAR(20),        -- [ETL-DROP]
  issued_terminal_id  VARCHAR(10),        -- [ETL-DROP]
  updated_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
  UNIQUE (flight_id, seat_number)
);

-- updated_at triggers
CREATE TRIGGER trg_passenger_updated BEFORE UPDATE ON passenger
  FOR EACH ROW EXECUTE FUNCTION mainline_carrier.set_updated_at();
CREATE TRIGGER trg_flight_updated BEFORE UPDATE ON flight
  FOR EACH ROW EXECUTE FUNCTION mainline_carrier.set_updated_at();
CREATE TRIGGER trg_booking_updated BEFORE UPDATE ON booking
  FOR EACH ROW EXECUTE FUNCTION mainline_carrier.set_updated_at();
CREATE TRIGGER trg_ticket_updated BEFORE UPDATE ON ticket
  FOR EACH ROW EXECUTE FUNCTION mainline_carrier.set_updated_at();

-- Row Level Security: blocks Supabase's public API (anon key). The table owner
-- (our Supabase connection string) is not affected. A separate read-only login
-- needs SELECT policies - see sql/postgres/11_read_only_role.sql (optional).
ALTER TABLE airport     ENABLE ROW LEVEL SECURITY;
ALTER TABLE cabin_class ENABLE ROW LEVEL SECURITY;
ALTER TABLE passenger   ENABLE ROW LEVEL SECURITY;
ALTER TABLE flight      ENABLE ROW LEVEL SECURITY;
ALTER TABLE booking     ENABLE ROW LEVEL SECURITY;
ALTER TABLE ticket      ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------
-- Rebuild safety (audit I-1): DROP SCHEMA ... CASCADE above also dropped the
-- foreign key from vector_store.flight_note_embeddings to flight. If the
-- embeddings table already exists (re-run on Supabase), put the FK back.
-- NOT VALID: existing embedding rows are not re-checked now (flight is empty
-- until 03 runs); every new or changed row is checked as usual.
-- ---------------------------------------------------------------------
DO $$
BEGIN
  IF to_regclass('vector_store.flight_note_embeddings') IS NOT NULL THEN
    ALTER TABLE vector_store.flight_note_embeddings
      DROP CONSTRAINT IF EXISTS flight_note_embeddings_flight_id_fkey,
      ADD  CONSTRAINT flight_note_embeddings_flight_id_fkey
           FOREIGN KEY (flight_id) REFERENCES mainline_carrier.flight(flight_id)
           ON DELETE CASCADE NOT VALID;
    RAISE NOTICE 'Restored FK vector_store.flight_note_embeddings -> mainline_carrier.flight. Now re-run 03, 07 and 09.';
  END IF;
END $$;
