-- =====================================================================
-- 07_views_and_queries.sql   (Abrar)
-- Non-trivial queries (brief: "min. 2 non-trivial queries, e.g. views,
-- joins"). Saved as VIEWS so the dashboard can reuse them.
--   Q1  mainline_carrier.v_on_time_performance_by_route  (multi-table join)
--   Q2  regional_partner.v_revenue_per_cabin              (cleans free text)
--   Q3  regional_partner.v_route_performance              (Q1 on the other schema)
--   Q4  customers who appear in BOTH schemas               (cross-schema join)
-- =====================================================================


-- ---------------------------------------------------------------------
-- Q1. On-time performance per route (mainline).
--     A flight is "on time" if it departed no more than 15 minutes late.
--     Joins flight + airport (twice: origin and destination) + ticket.
--     Tickets are counted per flight FIRST (in the WITH part); otherwise
--     each flight would be repeated once per ticket and counted wrongly.
-- ---------------------------------------------------------------------
DROP VIEW IF EXISTS mainline_carrier.v_on_time_performance_by_route;
CREATE VIEW mainline_carrier.v_on_time_performance_by_route AS
WITH ticket_stats AS (
  SELECT flight_id,
         count(*)       AS passengers,
         sum(fare_paid) AS revenue_bhd
  FROM mainline_carrier.ticket
  WHERE ticket_status IN ('ISSUED', 'USED')
  GROUP BY flight_id
)
SELECT f.origin_code || '-' || f.destination_code  AS route,
       ao.city || ' -> ' || ad.city                AS route_name,
       count(*)                                    AS flights_flown,
       count(*) FILTER (WHERE f.actual_departure <= f.scheduled_departure + interval '15 minutes')
                                                   AS on_time_flights,
       round(100.0 * count(*) FILTER (WHERE f.actual_departure <= f.scheduled_departure + interval '15 minutes')
             / count(*), 1)                        AS on_time_pct,
       round(avg(GREATEST(EXTRACT(EPOCH FROM (f.actual_departure - f.scheduled_departure)) / 60, 0)), 1)
                                                   AS avg_delay_min,
       coalesce(sum(ts.passengers), 0)             AS passengers,
       coalesce(sum(ts.revenue_bhd), 0)            AS revenue_bhd
FROM mainline_carrier.flight f
JOIN mainline_carrier.airport ao ON ao.airport_code = f.origin_code
JOIN mainline_carrier.airport ad ON ad.airport_code = f.destination_code
LEFT JOIN ticket_stats ts        ON ts.flight_id    = f.flight_id
WHERE f.actual_departure IS NOT NULL          -- only flights that really departed
GROUP BY f.origin_code, f.destination_code, ao.city, ad.city;

-- Try it:
SELECT * FROM mainline_carrier.v_on_time_performance_by_route ORDER BY on_time_pct;


-- ---------------------------------------------------------------------
-- Q2. Revenue per cabin (regional).
--     travel_class is free text ('Economy', 'ECONOMY', 'econ', 'Y' ...),
--     so CASE groups the spellings into proper cabin names.
--     Some fare lines are in USD, so they are converted to BHD
--     (1 USD = 0.376 BHD). Cancelled ('void') lines and empty fares are left out.
-- ---------------------------------------------------------------------
DROP VIEW IF EXISTS regional_partner.v_revenue_per_cabin;
CREATE VIEW regional_partner.v_revenue_per_cabin AS
SELECT CASE
         WHEN lower(r.travel_class) IN ('economy', 'econ', 'y')          THEN 'Economy'
         WHEN lower(r.travel_class) IN ('premium economy', 'prem econ')  THEN 'Premium Economy'
         WHEN lower(r.travel_class) IN ('business', 'j')                 THEN 'Business'
         ELSE 'Unknown'
       END                                                   AS cabin,
       count(*)                                              AS fare_lines,
       round(sum(CASE WHEN upper(f.currency) = 'USD' THEN f.fare_amount * 0.376
                      ELSE f.fare_amount END), 3)            AS revenue_bhd
FROM regional_partner.fare_line f
JOIN regional_partner.reservation r ON r.reservation_no = f.reservation_no
WHERE lower(coalesce(f.line_status, '')) <> 'void'
  AND f.fare_amount IS NOT NULL
GROUP BY 1;

-- Try it:
SELECT * FROM regional_partner.v_revenue_per_cabin ORDER BY revenue_bhd DESC;


-- ---------------------------------------------------------------------
-- Q3. On-time performance per route (regional) - the same question as Q1
--     on the other schema. It has no actual times (only delay_minutes)
--     and messy city names, which are tidied on the fly.
-- ---------------------------------------------------------------------
DROP VIEW IF EXISTS regional_partner.v_route_performance;
CREATE VIEW regional_partner.v_route_performance AS
WITH clean_route AS (
  SELECT route_id, delay_minutes,
         CASE lower(origin_city)      WHEN 'bahrain' THEN 'Manama' WHEN 'kuwait' THEN 'Kuwait City'
                                      WHEN 'alula'   THEN 'Al Ula' ELSE initcap(origin_city) END      AS origin_city,
         CASE lower(destination_city) WHEN 'bahrain' THEN 'Manama' WHEN 'kuwait' THEN 'Kuwait City'
                                      WHEN 'alula'   THEN 'Al Ula' ELSE initcap(destination_city) END AS destination_city
  FROM regional_partner.route
  WHERE lower(route_status) IN ('operated', 'delayed')
)
SELECT origin_city || ' -> ' || destination_city                    AS route_name,
       count(*)                                                      AS flights_flown,
       count(*) FILTER (WHERE delay_minutes <= 15)                   AS on_time_flights,
       round(100.0 * count(*) FILTER (WHERE delay_minutes <= 15)
             / NULLIF(count(delay_minutes), 0), 1)                   AS on_time_pct,
       round(avg(delay_minutes), 1)                                  AS avg_delay_min
FROM clean_route
GROUP BY origin_city, destination_city;

-- Try it:
SELECT * FROM regional_partner.v_route_performance ORDER BY route_name;


-- ---------------------------------------------------------------------
-- Q4. Customers who exist in BOTH schemas (matched on email, ignoring
--     upper/lower case). These are the duplicates Member 2's ETL must
--     merge into one dim_passenger row.
-- ---------------------------------------------------------------------
SELECT p.passenger_id,
       p.first_name || ' ' || p.last_name AS mainline_name,
       t.traveler_code,
       t.full_name                        AS regional_name,
       lower(p.email)                     AS matched_email
FROM mainline_carrier.passenger p
JOIN regional_partner.traveler t ON lower(t.email_address) = lower(p.email)
ORDER BY p.passenger_id;