-- =====================================================================
-- File   : sql/postgres/09_close_departed_flights.sql   (Abrar - Member 1)
-- Purpose: Keep the sample data realistic as time passes.
--   The seed data is a snapshot taken on 20 Nov 2026. Every day, more
--   "SCHEDULED" flights reach their departure time. This function marks
--   them as flown in BOTH schemas, so the dashboard never shows a departed
--   flight as still scheduled (or lets someone book it).
--
--   mainline_carrier
--     1. SCHEDULED flights that have arrived -> LANDED (<= 15 min late) or
--        DELAYED (> 15 min), with actual times = scheduled + a simulated delay
--        (see "Simulated delay" below); "Planned:" notes are reworded.
--     2. ISSUED tickets on flown flights -> USED
--     3. CONFIRMED bookings whose flights have all flown -> COMPLETED
--   regional_partner
--     4. 'scheduled' routes that have departed -> 'operated' / 'delayed'
--        with the same simulated delay_minutes
--     5. fare_line.line_status follows its route: 'used' on departed routes,
--        'active' on routes that have not departed (void lines untouched)
--     6. Confirmed reservations whose lines have all been used -> 'Flown'
--
--   Simulated delay (audit L-5): there are no real actual times for these
--   flights, so a fixed, repeatable delay is derived from the id:
--   7 in 10 flights leave 0-12 min late (on time), 3 in 10 leave 20-60 min
--   late. Setting every flight exactly on time would push the on-time % up
--   the longer the data ages.
--
-- Run it in the Supabase SQL Editor before the demo / marking:
--     SELECT * FROM mainline_carrier.close_departed_flights();
-- Safe to run any number of times (the second run returns all zeros).
-- If notes were reworded, run  python vector/embed_flight_notes.py  or the
-- "Run embedding pipeline" button on dashboard page 4 (re-embeds only the
-- changed notes).
-- Run order: after 01-04 and 07. Re-run this file whenever 01 is re-run
-- (01 drops the mainline_carrier schema, and this function with it).
-- =====================================================================

-- The return columns changed (4 -> 7 counters), so drop the old version first.
DROP FUNCTION IF EXISTS mainline_carrier.close_departed_flights();

-- Repeatable simulated delay in minutes for a flight_id / route_id.
CREATE OR REPLACE FUNCTION mainline_carrier.simulated_delay_min(p_id INTEGER)
RETURNS INTEGER LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN p_id % 10 IN (3, 6, 9) THEN 20 + (p_id * 13) % 41   -- 20-60 min late
              ELSE (p_id * 7) % 13                                    -- 0-12 min (on time)
         END;
$$;

COMMENT ON FUNCTION mainline_carrier.simulated_delay_min IS
  'Repeatable delay (minutes) used by close_departed_flights(): 70% on time, 30% 20-60 min late.';

CREATE FUNCTION mainline_carrier.close_departed_flights()
RETURNS TABLE (flights_closed      INTEGER,
               flights_delayed     INTEGER,
               tickets_used        INTEGER,
               bookings_completed  INTEGER,
               routes_operated     INTEGER,
               fare_lines_updated  INTEGER,
               reservations_flown  INTEGER)
LANGUAGE plpgsql AS $$
DECLARE
  v_flights INTEGER; v_delayed INTEGER; v_tickets INTEGER; v_bookings INTEGER;
  v_routes INTEGER; v_lines_used INTEGER; v_lines_active INTEGER; v_res INTEGER;
  v_local_now TIMESTAMP := now() AT TIME ZONE 'Asia/Bahrain';   -- route times are Bahrain local
BEGIN
  -- 1. mainline flights that have arrived (scheduled arrival + delay is in the past)
  WITH closed AS (
    UPDATE mainline_carrier.flight f
       SET flight_status    = CASE WHEN d.m > 15 THEN 'DELAYED' ELSE 'LANDED' END,
           actual_departure = f.scheduled_departure + make_interval(mins => d.m),
           actual_arrival   = f.scheduled_arrival   + make_interval(mins => d.m),
           notes = CASE WHEN f.notes NOT LIKE 'Planned:%' OR f.notes IS NULL THEN f.notes
                        WHEN d.m > 15 THEN 'Operated ' || d.m || ' min late - planned:' || substr(f.notes, 9)
                        ELSE 'Operated as planned:' || substr(f.notes, 9) END
      FROM (SELECT flight_id, mainline_carrier.simulated_delay_min(flight_id) AS m
            FROM mainline_carrier.flight) d
     WHERE d.flight_id = f.flight_id
       AND f.flight_status = 'SCHEDULED'
       AND f.scheduled_arrival + make_interval(mins => d.m) < now()
    RETURNING f.flight_status
  )
  SELECT count(*), count(*) FILTER (WHERE flight_status = 'DELAYED')
    INTO v_flights, v_delayed
    FROM closed;

  -- 2. their tickets have now been used
  UPDATE mainline_carrier.ticket t
     SET ticket_status = 'USED'
    FROM mainline_carrier.flight f
   WHERE t.flight_id = f.flight_id
     AND t.ticket_status = 'ISSUED'
     AND f.flight_status IN ('LANDED', 'DELAYED', 'DIVERTED');
  GET DIAGNOSTICS v_tickets = ROW_COUNT;

  -- 3. bookings whose every flight has flown are completed
  UPDATE mainline_carrier.booking b
     SET booking_status = 'COMPLETED'
   WHERE b.booking_status = 'CONFIRMED'
     AND EXISTS     (SELECT 1 FROM mainline_carrier.ticket t WHERE t.booking_id = b.booking_id)
     AND NOT EXISTS (SELECT 1 FROM mainline_carrier.ticket t
                     JOIN mainline_carrier.flight f ON f.flight_id = t.flight_id
                     WHERE t.booking_id = b.booking_id AND f.flight_status = 'SCHEDULED');
  GET DIAGNOSTICS v_bookings = ROW_COUNT;

  -- 4. regional routes that have departed
  UPDATE regional_partner.route r
     SET route_status  = CASE WHEN mainline_carrier.simulated_delay_min(r.route_id) > 15
                              THEN 'delayed' ELSE 'operated' END,
         delay_minutes = coalesce(r.delay_minutes, mainline_carrier.simulated_delay_min(r.route_id))
   WHERE lower(r.route_status) = 'scheduled'
     AND r.departure_date + r.departure_time
         + make_interval(mins => mainline_carrier.simulated_delay_min(r.route_id)) < v_local_now;
  GET DIAGNOSTICS v_routes = ROW_COUNT;

  -- 5. fare_line status follows its route (audit I-4)
  UPDATE regional_partner.fare_line f
     SET line_status = 'used'
    FROM regional_partner.route r
   WHERE f.route_id = r.route_id
     AND lower(f.line_status) = 'active'
     AND lower(r.route_status) IN ('operated', 'delayed');
  GET DIAGNOSTICS v_lines_used = ROW_COUNT;

  UPDATE regional_partner.fare_line f
     SET line_status = 'active'
    FROM regional_partner.route r
   WHERE f.route_id = r.route_id
     AND lower(f.line_status) = 'used'
     AND lower(r.route_status) = 'scheduled';
  GET DIAGNOSTICS v_lines_active = ROW_COUNT;

  -- 6. confirmed reservations whose (non-void) lines have all been used
  UPDATE regional_partner.reservation rv
     SET reservation_status = 'Flown'
   WHERE lower(rv.reservation_status) = 'confirmed'
     AND EXISTS     (SELECT 1 FROM regional_partner.fare_line f
                     WHERE f.reservation_no = rv.reservation_no
                       AND lower(coalesce(f.line_status, '')) <> 'void')
     AND NOT EXISTS (SELECT 1 FROM regional_partner.fare_line f
                     WHERE f.reservation_no = rv.reservation_no
                       AND lower(coalesce(f.line_status, '')) NOT IN ('used', 'void'));
  GET DIAGNOSTICS v_res = ROW_COUNT;

  RETURN QUERY SELECT v_flights, v_delayed, v_tickets, v_bookings,
                      v_routes, v_lines_used + v_lines_active, v_res;
END;
$$;

COMMENT ON FUNCTION mainline_carrier.close_departed_flights IS
  'Marks departed flights/routes as flown in both schemas (with a repeatable simulated delay) so the snapshot data stays realistic. Safe to re-run.';

-- Run it now:
SELECT * FROM mainline_carrier.close_departed_flights();
