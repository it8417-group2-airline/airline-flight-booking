-- =====================================================================
-- File   : sql/postgres/06_crud_regional_partner.sql   (Abrar - Member 1)
-- Purpose: CRUD demonstration on the denormalised regional_partner schema.
-- Notice how the different structure changes the SQL compared with
-- 05_crud_mainline_carrier.sql:
--   * the text key 'TRV-xxxx' and the BIGINT reservation_no must be made by us
--   * travel_class is typed as free text (no cabin table to look up)
--   * fare_amount is COPIED from route into fare_line (denormalised)
-- Run ONE section at a time in the Supabase SQL Editor.
-- The script cleans up after itself, so the sample data ends unchanged.
-- =====================================================================

-- ============================ CREATE ============================

-- C1. Add a traveler. There is no SERIAL here, so we build the next
--     text key ourselves: highest existing number + 1, e.g. TRV-0033.
INSERT INTO regional_partner.traveler
       (traveler_code, full_name, email_address, birth_date_text, country, loyalty_tier)
SELECT 'TRV-' || lpad((max(substring(traveler_code FROM 5)::int) + 1)::text, 4, '0'),
       'Eman Khamdan', 'Eman.Khamdan@example.com', '21/06/1990', 'Bahrain', 'Blue'
FROM regional_partner.traveler
RETURNING traveler_code, full_name;

-- C2. Create a reservation. reservation_no is a BIGINT we generate as max + 1.
--     travel_class is plain text - nothing checks the spelling.
INSERT INTO regional_partner.reservation
       (reservation_no, pnr, traveler_code, travel_class, reservation_status, sales_channel)
SELECT (SELECT max(reservation_no) + 1 FROM regional_partner.reservation),
       'EKHA01', traveler_code, 'Economy', 'Confirmed', 'Website'
FROM regional_partner.traveler
WHERE email_address = 'Eman.Khamdan@example.com'
RETURNING reservation_no, pnr, travel_class;

-- C3. Add a fare line for the next route that has not departed yet
--     (route times are Bahrain local time, Supabase's clock is UTC). The fare is COPIED
--     from route.fare_amount into fare_line.fare_amount (denormalised); Economy uses
--     class factor 1.00 (Premium Economy 1.45, Business 2.60 - see 04 seed header).
INSERT INTO regional_partner.fare_line
       (reservation_no, route_id, fare_amount, tax_amount, currency, seat_label, line_status)
SELECT r.reservation_no, rt.route_id, rt.fare_amount, round(rt.fare_amount * 0.10, 3),
       'BHD', '12A', 'active'
FROM regional_partner.reservation r, regional_partner.route rt
WHERE r.pnr = 'EKHA01'
  AND rt.route_id = (SELECT route_id FROM regional_partner.route
                     WHERE departure_date + departure_time > (now() AT TIME ZONE 'Asia/Bahrain')
                     ORDER BY departure_date, departure_time LIMIT 1)
RETURNING fare_line_id, route_id, fare_amount;

-- ============================ READ ============================

-- R1. Eman's itinerary: only 3 joins, because there is no cabin table.
SELECT t.full_name, r.pnr, r.travel_class, rt.route_code,
       rt.origin_city || ' -> ' || rt.destination_city AS route,
       rt.departure_date, rt.departure_time,
       f.fare_amount, f.currency
FROM regional_partner.traveler t
JOIN regional_partner.reservation r  ON r.traveler_code  = t.traveler_code
JOIN regional_partner.fare_line   f  ON f.reservation_no = r.reservation_no
JOIN regional_partner.route       rt ON rt.route_id      = f.route_id
WHERE t.email_address = 'Eman.Khamdan@example.com';

-- R2. Travelers from Bahrain. lower() is needed because the free-text
--     country column holds 'Bahrain', 'bahrain', 'BAHRAIN', ...
SELECT traveler_code, full_name, country
FROM regional_partner.traveler
WHERE lower(country) IN ('bahrain', 'kingdom of bahrain')
ORDER BY traveler_code;

-- ============================ UPDATE ============================

-- U1. Upgrade the class. It is free text, so a typo like 'Busines'
--     would also be accepted - a weakness the ETL must clean later.
UPDATE regional_partner.reservation
SET travel_class = 'Business'
WHERE pnr = 'EKHA01'
RETURNING reservation_no, travel_class, last_modified;

-- U2. Show the update anomaly of denormalisation: raise the route fare
--     by 5% ...
UPDATE regional_partner.route
SET fare_amount = round(fare_amount * 1.05, 3)
WHERE route_id = (SELECT f.route_id
                  FROM regional_partner.fare_line f
                  JOIN regional_partner.reservation r ON r.reservation_no = f.reservation_no
                  WHERE r.pnr = 'EKHA01')
RETURNING route_id, fare_amount;

-- ... the copied price in fare_line still holds the OLD fare.
SELECT f.fare_line_id,
       f.fare_amount  AS fare_on_fare_line,
       rt.fare_amount AS current_route_fare
FROM regional_partner.fare_line f
JOIN regional_partner.route       rt ON rt.route_id      = f.route_id
JOIN regional_partner.reservation r  ON r.reservation_no = f.reservation_no
WHERE r.pnr = 'EKHA01';

-- Put the route fare back to what it was (undo U2): the old price is
-- exactly the copy that fare_line kept.
UPDATE regional_partner.route rt
SET fare_amount = f.fare_amount
FROM regional_partner.fare_line f
JOIN regional_partner.reservation r ON r.reservation_no = f.reservation_no
WHERE r.pnr = 'EKHA01'
  AND rt.route_id = f.route_id
RETURNING rt.route_id, rt.fare_amount;

-- ============================ DELETE ============================

-- D1. Delete the reservation; its fare_line goes too (ON DELETE CASCADE).
DELETE FROM regional_partner.reservation
WHERE pnr = 'EKHA01'
RETURNING reservation_no, pnr;

-- D2. Delete the traveler (allowed now that no reservation points to her).
DELETE FROM regional_partner.traveler
WHERE email_address = 'Eman.Khamdan@example.com'
RETURNING traveler_code, full_name;

-- D3. Check: nothing from the demo is left (all counts should be 0).
SELECT (SELECT count(*) FROM regional_partner.traveler    WHERE email_address = 'Eman.Khamdan@example.com') AS travelers_left,
       (SELECT count(*) FROM regional_partner.reservation WHERE pnr = 'EKHA01')                       AS reservations_left;
