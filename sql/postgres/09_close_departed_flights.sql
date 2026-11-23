-- =====================================================================
-- File   : 09_close_departed_flights.sql   (Abrar - Member 1)
-- Purpose: Keep the sample data realistic as time passes.
--   The seed data is a snapshot taken on 20 Nov 2026. Every day, more
--   "SCHEDULED" flights reach their departure time. This function marks
--   them as flown, so the dashboard never shows a departed flight as
--   still scheduled (or lets someone book it).
--
--   mainline_carrier : SCHEDULED flights whose arrival time has passed
--                      -> LANDED, actual times = scheduled times (on time);
--                      their ISSUED tickets -> USED; bookings whose flights
--                      have all flown -> COMPLETED; "Planned:" notes are
--                      reworded to "Operated as planned:".
--   regional_partner : 'scheduled' routes that have departed -> 'operated'
--                      with delay_minutes 0.
--
-- Run it in the Supabase SQL Editor before the demo / marking:
--     SELECT * FROM mainline_carrier.close_departed_flights();
-- It is safe to run any number of times. If notes were reworded, run
-- python vector/embed_flight_notes.py afterwards (it re-embeds only the
-- changed notes).
-- =====================================================================

CREATE OR REPLACE FUNCTION mainline_carrier.close_departed_flights()
RETURNS TABLE (flights_landed INTEGER, tickets_used INTEGER, bookings_completed INTEGER, routes_operated INTEGER)
LANGUAGE plpgsql AS $$
DECLARE
  v_flights INTEGER; v_tickets INTEGER; v_bookings INTEGER; v_routes INTEGER;
BEGIN
  -- 1. mainline flights that have arrived
  UPDATE mainline_carrier.flight
     SET flight_status    = 'LANDED',
         actual_departure = scheduled_departure,
         actual_arrival   = scheduled_arrival,
         notes = CASE WHEN notes LIKE 'Planned:%'
                      THEN 'Operated as planned:' || substr(notes, 9)
                      ELSE notes END
   WHERE flight_status = 'SCHEDULED'
     AND scheduled_arrival < now();
  GET DIAGNOSTICS v_flights = ROW_COUNT;

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

  -- 4. regional routes that have departed (route times are Bahrain local time)
  UPDATE regional_partner.route
     SET route_status  = 'operated',
         delay_minutes = coalesce(delay_minutes, 0)
   WHERE lower(route_status) = 'scheduled'
     AND departure_date + departure_time < (now() AT TIME ZONE 'Asia/Bahrain');
  GET DIAGNOSTICS v_routes = ROW_COUNT;

  RETURN QUERY SELECT v_flights, v_tickets, v_bookings, v_routes;
END;
$$;

COMMENT ON FUNCTION mainline_carrier.close_departed_flights IS
  'Marks departed SCHEDULED flights/routes as flown so the snapshot data stays realistic. Safe to re-run.';

-- Run it now:
SELECT * FROM mainline_carrier.close_departed_flights();