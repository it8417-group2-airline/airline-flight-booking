-- =====================================================================
-- File   : 10_fix_booking_dates.sql   (Abrar - Member 1)
-- Purpose: Fix booking dates in the LIVE Supabase data.
--   45 mainline bookings and 33 regional reservations were dated
--   after the data snapshot (20 Nov 2026), i.e. "made in the future".
--   They are moved to before 20 Nov 2026 (and so before their flights).
--   The seed files 03/04 already contain these dates, so a fresh rebuild
--   does not need this file. Run it ONCE in the Supabase SQL Editor.
--   Bookings created later from the dashboard (id > 140 / no > 900000080)
--   are real, so they are not touched.
-- =====================================================================

UPDATE mainline_carrier.booking AS b
SET booking_date = v.d
FROM (VALUES
  (4, TIMESTAMPTZ '2026-11-14 20:00:00+03'),
  (5, TIMESTAMPTZ '2026-11-13 13:00:00+03'),
  (6, TIMESTAMPTZ '2026-11-12 06:00:00+03'),
  (12, TIMESTAMPTZ '2026-11-06 12:00:00+03'),
  (13, TIMESTAMPTZ '2026-11-05 05:00:00+03'),
  (18, TIMESTAMPTZ '2026-10-31 18:00:00+03'),
  (25, TIMESTAMPTZ '2026-11-18 17:00:00+03'),
  (26, TIMESTAMPTZ '2026-11-17 10:00:00+03'),
  (29, TIMESTAMPTZ '2026-11-14 13:00:00+03'),
  (31, TIMESTAMPTZ '2026-11-12 23:00:00+03'),
  (33, TIMESTAMPTZ '2026-11-10 09:00:00+03'),
  (40, TIMESTAMPTZ '2026-11-03 08:00:00+03'),
  (41, TIMESTAMPTZ '2026-11-02 01:00:00+03'),
  (46, TIMESTAMPTZ '2026-10-28 14:00:00+03'),
  (47, TIMESTAMPTZ '2026-10-27 07:00:00+03'),
  (48, TIMESTAMPTZ '2026-10-27 00:00:00+03'),
  (49, TIMESTAMPTZ '2026-10-25 17:00:00+03'),
  (51, TIMESTAMPTZ '2026-11-17 03:00:00+03'),
  (54, TIMESTAMPTZ '2026-11-14 06:00:00+03'),
  (55, TIMESTAMPTZ '2026-11-13 23:00:00+03'),
  (58, TIMESTAMPTZ '2026-11-10 02:00:00+03'),
  (62, TIMESTAMPTZ '2026-11-06 22:00:00+03'),
  (65, TIMESTAMPTZ '2026-11-03 01:00:00+03'),
  (71, TIMESTAMPTZ '2026-10-28 07:00:00+03'),
  (74, TIMESTAMPTZ '2026-10-25 10:00:00+03'),
  (76, TIMESTAMPTZ '2026-11-17 20:00:00+03'),
  (78, TIMESTAMPTZ '2026-11-15 06:00:00+03'),
  (80, TIMESTAMPTZ '2026-11-13 16:00:00+03'),
  (81, TIMESTAMPTZ '2026-11-12 09:00:00+03'),
  (82, TIMESTAMPTZ '2026-11-11 02:00:00+03'),
  (87, TIMESTAMPTZ '2026-11-06 15:00:00+03'),
  (90, TIMESTAMPTZ '2026-11-03 18:00:00+03'),
  (93, TIMESTAMPTZ '2026-10-31 21:00:00+03'),
  (107, TIMESTAMPTZ '2026-11-11 19:00:00+03'),
  (109, TIMESTAMPTZ '2026-11-09 05:00:00+03'),
  (113, TIMESTAMPTZ '2026-11-05 01:00:00+03'),
  (116, TIMESTAMPTZ '2026-11-02 04:00:00+03'),
  (119, TIMESTAMPTZ '2026-10-30 07:00:00+03'),
  (121, TIMESTAMPTZ '2026-10-28 17:00:00+03'),
  (123, TIMESTAMPTZ '2026-10-26 03:00:00+03'),
  (124, TIMESTAMPTZ '2026-10-25 20:00:00+03'),
  (131, TIMESTAMPTZ '2026-11-12 19:00:00+03'),
  (133, TIMESTAMPTZ '2026-11-10 05:00:00+03'),
  (135, TIMESTAMPTZ '2026-11-08 15:00:00+03'),
  (136, TIMESTAMPTZ '2026-11-07 08:00:00+03')
) AS v(booking_id, d)
WHERE b.booking_id = v.booking_id;

UPDATE regional_partner.reservation AS r
SET reserved_at = v.d
FROM (VALUES
  (900000002::bigint, TIMESTAMP '2026-11-16 14:00:00'),
  (900000006::bigint, TIMESTAMP '2026-11-12 18:00:00'),
  (900000011::bigint, TIMESTAMP '2026-11-07 17:00:00'),
  (900000012::bigint, TIMESTAMP '2026-11-06 12:00:00'),
  (900000015::bigint, TIMESTAMP '2026-11-03 21:00:00'),
  (900000018::bigint, TIMESTAMP '2026-10-31 06:00:00'),
  (900000019::bigint, TIMESTAMP '2026-10-30 01:00:00'),
  (900000020::bigint, TIMESTAMP '2026-10-29 20:00:00'),
  (900000023::bigint, TIMESTAMP '2026-10-26 05:00:00'),
  (900000028::bigint, TIMESTAMP '2026-11-15 04:00:00'),
  (900000032::bigint, TIMESTAMP '2026-11-11 08:00:00'),
  (900000033::bigint, TIMESTAMP '2026-11-10 03:00:00'),
  (900000042::bigint, TIMESTAMP '2026-11-01 06:00:00'),
  (900000044::bigint, TIMESTAMP '2026-10-30 20:00:00'),
  (900000046::bigint, TIMESTAMP '2026-10-28 10:00:00'),
  (900000048::bigint, TIMESTAMP '2026-10-27 00:00:00'),
  (900000050::bigint, TIMESTAMP '2026-11-18 14:00:00'),
  (900000052::bigint, TIMESTAMP '2026-11-16 04:00:00'),
  (900000053::bigint, TIMESTAMP '2026-11-15 23:00:00'),
  (900000054::bigint, TIMESTAMP '2026-11-14 18:00:00'),
  (900000056::bigint, TIMESTAMP '2026-11-12 08:00:00'),
  (900000058::bigint, TIMESTAMP '2026-11-10 22:00:00'),
  (900000059::bigint, TIMESTAMP '2026-11-09 17:00:00'),
  (900000064::bigint, TIMESTAMP '2026-11-04 16:00:00'),
  (900000065::bigint, TIMESTAMP '2026-11-03 11:00:00'),
  (900000066::bigint, TIMESTAMP '2026-11-02 06:00:00'),
  (900000067::bigint, TIMESTAMP '2026-11-01 01:00:00'),
  (900000068::bigint, TIMESTAMP '2026-10-31 20:00:00'),
  (900000069::bigint, TIMESTAMP '2026-10-30 15:00:00'),
  (900000071::bigint, TIMESTAMP '2026-10-28 05:00:00'),
  (900000075::bigint, TIMESTAMP '2026-11-18 09:00:00'),
  (900000078::bigint, TIMESTAMP '2026-11-15 18:00:00'),
  (900000079::bigint, TIMESTAMP '2026-11-14 13:00:00')
) AS v(reservation_no, d)
WHERE r.reservation_no = v.reservation_no;

-- Check: all three counts must be 0
SELECT (SELECT count(*) FROM mainline_carrier.booking
        WHERE booking_id <= 140 AND booking_date > TIMESTAMPTZ '2026-11-20 00:00+03') AS future_bookings,
       (SELECT count(*) FROM mainline_carrier.booking b
        JOIN mainline_carrier.ticket t ON t.booking_id = b.booking_id
        JOIN mainline_carrier.flight f ON f.flight_id = t.flight_id
        WHERE b.booking_date > f.scheduled_departure)                             AS booked_after_flight,
       (SELECT count(*) FROM regional_partner.reservation
        WHERE reservation_no <= 900000080 AND reserved_at > TIMESTAMP '2026-11-20 00:00') AS future_reservations;