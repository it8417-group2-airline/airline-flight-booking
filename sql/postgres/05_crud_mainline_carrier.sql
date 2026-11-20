-- =====================================================================
-- 05_crud_mainline_carrier.sql   (Abrar)
-- CRUD demonstration on the normalised mainline_carrier schema.
-- Run ONE section at a time in the Supabase SQL Editor
-- (highlight the section, then Run) to see each result.
-- The script creates a test passenger + booking, reads, updates and
-- finally deletes them again, so the sample data ends unchanged.
-- =====================================================================

-- ============================ CREATE ============================

-- C1. Add myself as a new passenger. RETURNING shows the row that was created,
--     including the passenger_id that SERIAL generated automatically.
INSERT INTO mainline_carrier.passenger
       (first_name, last_name, email, date_of_birth, nationality, phone)
VALUES ('Abrar', 'Alawadhi', 'abrar.alawadhi@example.com', '2000-01-01', 'BH', '+973 30000000')
RETURNING passenger_id, first_name, last_name, created_at;

-- C2. Create a booking for me (we look up my passenger_id
--     by email instead of typing the number).
INSERT INTO mainline_carrier.booking
       (booking_reference, passenger_id, booking_channel, payment_method)
SELECT 'ABR001', passenger_id, 'WEB', 'CARD'
FROM mainline_carrier.passenger
WHERE email = 'abrar.alawadhi@example.com'
RETURNING booking_id, booking_reference, booking_status;

-- C3. Add a ticket to the booking for the next scheduled flight, in Economy.
--     Normalised design: the price is CALCULATED from flight.base_fare
--     x cabin_class.fare_multiplier, not typed in by hand.
INSERT INTO mainline_carrier.ticket
       (ticket_number, booking_id, flight_id, cabin_class_id, seat_number, fare_paid)
SELECT '607-2499999901', b.booking_id, f.flight_id, c.cabin_class_id, '21C',
       round(f.base_fare * c.fare_multiplier, 3)
FROM mainline_carrier.booking b, mainline_carrier.flight f, mainline_carrier.cabin_class c
WHERE b.booking_reference = 'ABR001'
  AND c.cabin_code = 'Y'
  AND f.flight_id = (SELECT flight_id FROM mainline_carrier.flight
                     WHERE flight_status = 'SCHEDULED'
                     ORDER BY scheduled_departure LIMIT 1)
RETURNING ticket_id, ticket_number, flight_id, seat_number, fare_paid;

-- ============================ READ ============================

-- R1. My full itinerary: joins 5 tables using the foreign keys.
SELECT p.first_name || ' ' || p.last_name           AS passenger,
       b.booking_reference,
       b.booking_status,
       f.flight_number,
       f.origin_code || ' -> ' || f.destination_code AS route,
       f.scheduled_departure,
       c.cabin_name,
       t.seat_number,
       t.fare_paid
FROM mainline_carrier.passenger p
JOIN mainline_carrier.booking     b ON b.passenger_id   = p.passenger_id
JOIN mainline_carrier.ticket      t ON t.booking_id     = b.booking_id
JOIN mainline_carrier.flight      f ON f.flight_id      = t.flight_id
JOIN mainline_carrier.cabin_class c ON c.cabin_class_id = t.cabin_class_id
WHERE p.email = 'abrar.alawadhi@example.com';

-- R2. Upcoming flights and how many seats each has sold.
SELECT f.flight_number, f.origin_code, f.destination_code, f.scheduled_departure,
       count(t.ticket_id) AS seats_sold
FROM mainline_carrier.flight f
LEFT JOIN mainline_carrier.ticket t
       ON t.flight_id = f.flight_id AND t.ticket_status <> 'REFUNDED'
WHERE f.flight_status = 'SCHEDULED'
GROUP BY f.flight_id
ORDER BY f.scheduled_departure
LIMIT 10;

-- ============================ UPDATE ============================

-- U1. Upgrade me to Business (cabin 3) and move me to seat 3A.
--     The trigger sets updated_at to the current time automatically.
UPDATE mainline_carrier.ticket
SET seat_number = '3A', cabin_class_id = 3
WHERE ticket_number = '607-2499999901'
RETURNING ticket_number, seat_number, cabin_class_id, updated_at;

-- U2. Cancel the booking and refund its ticket (two related updates).
UPDATE mainline_carrier.booking
SET booking_status = 'CANCELLED'
WHERE booking_reference = 'ABR001'
RETURNING booking_reference, booking_status, updated_at;

UPDATE mainline_carrier.ticket
SET ticket_status = 'REFUNDED'
WHERE ticket_number = '607-2499999901'
RETURNING ticket_number, ticket_status;

-- ============================ DELETE ============================

-- D1. Delete the booking. Its ticket is deleted too, because the
--     foreign key was created with ON DELETE CASCADE.
DELETE FROM mainline_carrier.booking
WHERE booking_reference = 'ABR001'
RETURNING booking_id, booking_reference;

-- D2. Delete the passenger. This only works now that I have no booking:
--     while a booking pointed to me, the foreign key would block it.
DELETE FROM mainline_carrier.passenger
WHERE email = 'abrar.alawadhi@example.com'
RETURNING passenger_id, first_name, last_name;

-- D3. Check: nothing from the demo is left (all three counts should be 0).
SELECT (SELECT count(*) FROM mainline_carrier.passenger WHERE email = 'abrar.alawadhi@example.com') AS passengers_left,
       (SELECT count(*) FROM mainline_carrier.booking   WHERE booking_reference = 'ABR001')            AS bookings_left,
       (SELECT count(*) FROM mainline_carrier.ticket    WHERE ticket_number = '607-2499999901')       AS tickets_left;