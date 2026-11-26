-- Databricks notebook source
-- MAGIC %md
-- MAGIC # 04 · Analytical queries on the star schema
-- MAGIC **Owner:** Fatema Alashiri (Member 2)
-- MAGIC
-- MAGIC Five analytical queries, saved as views in `workspace.airline_gold` so the dashboard
-- MAGIC (page 2, Warehouse) reads exactly the same logic:
-- MAGIC
-- MAGIC | View | Question it answers |
-- MAGIC |---|---|
-- MAGIC | `v_on_time_by_carrier_month` | **Q1** How punctual is each airline, month by month? |
-- MAGIC | `v_revenue_by_route_cabin` | **Q2** Which routes and cabins bring in the revenue? |
-- MAGIC | `v_top_passengers` | **Q3** Who are the most frequent travellers, across both airlines? |
-- MAGIC | `v_ticket_volume_by_carrier_month` | **Q4** How many tickets does each airline sell per month? (dashboard carrier filter) |
-- MAGIC | `v_fare_reconciliation` | **Q5** Do the fares match the shared ticket fare model? |
-- MAGIC
-- MAGIC Only revenue tickets count towards revenue and volume (refunded, void and cancelled are excluded).

-- COMMAND ----------

-- Q1 · On-time performance by carrier and month (flight level; on time = departed within 15 min)
CREATE OR REPLACE VIEW workspace.airline_gold.v_on_time_by_carrier_month
COMMENT 'Q1: on-time performance by carrier and month (departed within 15 minutes)'
AS
SELECT d.year_month,
       f.carrier_name,
       SUM(CASE WHEN f.is_departed THEN 1 ELSE 0 END)                              AS departed_flights,
       SUM(CASE WHEN f.is_on_time = TRUE THEN 1 ELSE 0 END)                        AS on_time_flights,
       ROUND(100.0 * SUM(CASE WHEN f.is_on_time = TRUE THEN 1 ELSE 0 END)
             / NULLIF(SUM(CASE WHEN f.is_on_time IS NOT NULL THEN 1 ELSE 0 END), 0), 1) AS on_time_pct,
       ROUND(AVG(f.delay_minutes), 1)                                              AS avg_delay_min,
       SUM(CASE WHEN f.flight_status = 'CANCELLED' THEN 1 ELSE 0 END)              AS cancelled_flights,
       SUM(CASE WHEN f.is_departed AND f.is_on_time IS NULL THEN 1 ELSE 0 END)     AS delay_not_reported
FROM workspace.airline_gold.dim_flight f
JOIN workspace.airline_gold.dim_date d ON d.date_key = f.flight_date_key
WHERE f.is_departed OR f.flight_status = 'CANCELLED'
GROUP BY d.year_month, f.carrier_name;

-- COMMAND ----------

-- Q2 · Revenue by route and cabin
CREATE OR REPLACE VIEW workspace.airline_gold.v_revenue_by_route_cabin
COMMENT 'Q2: revenue tickets, revenue and average fare by route and cabin'
AS
SELECT c.carrier_name,
       fl.route,
       cb.cabin_name,
       cb.cabin_rank,
       COUNT(*)                     AS tickets,
       SUM(f.revenue_bhd)           AS revenue_bhd,
       ROUND(AVG(f.fare_bhd), 3)    AS avg_fare_bhd
FROM workspace.airline_gold.fact_ticket f
JOIN workspace.airline_gold.dim_flight  fl ON fl.flight_key  = f.flight_key
JOIN workspace.airline_gold.dim_cabin   cb ON cb.cabin_key   = f.cabin_key
JOIN workspace.airline_gold.dim_carrier c  ON c.carrier_key  = f.carrier_key
WHERE f.is_revenue
GROUP BY c.carrier_name, fl.route, cb.cabin_name, cb.cabin_rank;

-- COMMAND ----------

-- Q3 · Top passengers by trips (one person may have flown with both airlines)
CREATE OR REPLACE VIEW workspace.airline_gold.v_top_passengers
COMMENT 'Q3: trips, flights flown, airlines used and revenue per merged passenger'
AS
SELECT p.passenger_key,
       p.full_name,
       p.source_systems,
       p.country_name,
       p.loyalty_tier,
       COUNT(DISTINCT f.flight_key)                          AS trips,
       SUM(CASE WHEN fl.is_departed THEN 1 ELSE 0 END)        AS flights_flown,
       COUNT(DISTINCT f.carrier_key)                         AS airlines_used,
       SUM(f.revenue_bhd)                                    AS revenue_bhd
FROM workspace.airline_gold.fact_ticket f
JOIN workspace.airline_gold.dim_passenger p  ON p.passenger_key = f.passenger_key
JOIN workspace.airline_gold.dim_flight    fl ON fl.flight_key   = f.flight_key
WHERE f.is_revenue
GROUP BY p.passenger_key, p.full_name, p.source_systems, p.country_name, p.loyalty_tier;

-- COMMAND ----------

-- Q4 · Ticket volume by carrier and month (feeds the dashboard carrier filter)
CREATE OR REPLACE VIEW workspace.airline_gold.v_ticket_volume_by_carrier_month
COMMENT 'Q4: revenue tickets and revenue per carrier per flight month'
AS
SELECT d.year_month,
       c.carrier_code,
       c.carrier_name,
       COUNT(*)              AS tickets,
       SUM(f.revenue_bhd)    AS revenue_bhd
FROM workspace.airline_gold.fact_ticket f
JOIN workspace.airline_gold.dim_carrier c ON c.carrier_key = f.carrier_key
JOIN workspace.airline_gold.dim_date    d ON d.date_key    = f.flight_date_key
WHERE f.is_revenue
GROUP BY d.year_month, c.carrier_code, c.carrier_name;

-- COMMAND ----------

-- Q5 · Fare reconciliation against the shared ticket fare model (base fare x cabin multiplier)
CREATE OR REPLACE VIEW workspace.airline_gold.v_fare_reconciliation
COMMENT 'Q5: how many fares match, drift from or were rebuilt from the ticket fare model'
AS
SELECT c.carrier_name,
       f.fare_check,
       COUNT(*)                         AS tickets,
       SUM(f.fare_bhd)                  AS fare_bhd,
       SUM(f.expected_fare_bhd)         AS expected_fare_bhd,
       SUM(f.fare_variance_bhd)         AS variance_bhd
FROM workspace.airline_gold.fact_ticket f
JOIN workspace.airline_gold.dim_carrier c ON c.carrier_key = f.carrier_key
GROUP BY c.carrier_name, f.fare_check;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Results

-- COMMAND ----------

SELECT * FROM workspace.airline_gold.v_on_time_by_carrier_month ORDER BY year_month, carrier_name;

-- COMMAND ----------

SELECT * FROM workspace.airline_gold.v_revenue_by_route_cabin ORDER BY revenue_bhd DESC LIMIT 15;

-- COMMAND ----------

SELECT * FROM workspace.airline_gold.v_top_passengers ORDER BY trips DESC, revenue_bhd DESC LIMIT 10;

-- COMMAND ----------

SELECT * FROM workspace.airline_gold.v_ticket_volume_by_carrier_month ORDER BY year_month, carrier_code;

-- COMMAND ----------

SELECT * FROM workspace.airline_gold.v_fare_reconciliation ORDER BY carrier_name, fare_check;
