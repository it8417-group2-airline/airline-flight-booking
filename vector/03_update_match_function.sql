-- =====================================================================
-- File   : vector/03_update_match_function.sql   (Abrar - Member 1)
-- Purpose: Update ONLY the Flow 6 search function, without touching the
--          stored embeddings (safe to re-run on Supabase).
--   * returns only flights that already happened ("similar PAST flights")
--   * early departures show 0 min delay instead of a negative number
--   * "bookings" excludes refunded tickets, the same as "passengers"
-- =====================================================================

CREATE OR REPLACE FUNCTION vector_store.match_flight_notes(
  query_embedding vector(1536),
  match_count     INTEGER DEFAULT 5,
  max_distance    DOUBLE PRECISION DEFAULT 1.0
)
RETURNS TABLE (
  flight_id           INTEGER,
  flight_number       VARCHAR,
  route               TEXT,
  scheduled_departure TIMESTAMPTZ,
  flight_status       VARCHAR,
  delay_min           INTEGER,
  passengers          BIGINT,
  bookings            BIGINT,
  revenue_bhd         NUMERIC,
  avg_rating          NUMERIC,
  review_count        INTEGER,
  source_type         VARCHAR,
  matched_text        TEXT,
  cosine_distance     DOUBLE PRECISION,
  similarity          DOUBLE PRECISION
)
LANGUAGE sql STABLE AS $$
  WITH nearest AS (                       -- 1) vector search (uses the HNSW index)
    SELECT e.flight_id, e.source_type, e.notes,
           e.embedding <=> query_embedding AS dist
    FROM vector_store.flight_note_embeddings e
    JOIN mainline_carrier.flight pf ON pf.flight_id = e.flight_id
    WHERE pf.scheduled_departure < now()  -- only flights that already happened ("similar PAST flights")
    ORDER BY e.embedding <=> query_embedding
    LIMIT match_count * 4                 -- over-fetch, then keep best hit per flight
  ),
  best_per_flight AS (
    SELECT DISTINCT ON (n.flight_id) n.*
    FROM nearest n
    WHERE n.dist <= max_distance
    ORDER BY n.flight_id, n.dist
  ),
  ticket_stats AS (                       -- 2) relational enrichment (join back)
    SELECT t.flight_id,
           count(*) FILTER (WHERE t.ticket_status <> 'REFUNDED') AS passengers,
           count(DISTINCT t.booking_id) FILTER (WHERE t.ticket_status <> 'REFUNDED') AS bookings,
           sum(t.fare_paid) FILTER (WHERE t.ticket_status <> 'REFUNDED') AS revenue_bhd
    FROM mainline_carrier.ticket t
    WHERE t.flight_id IN (SELECT b.flight_id FROM best_per_flight b)
    GROUP BY t.flight_id
  )
  SELECT f.flight_id,
         f.flight_number,
         ao.city || ' (' || f.origin_code || ') -> ' || ad.city || ' (' || f.destination_code || ')',
         f.scheduled_departure,
         f.flight_status,
         GREATEST((EXTRACT(EPOCH FROM (f.actual_departure - f.scheduled_departure)) / 60)::int, 0),  -- early = 0 min delay
         coalesce(ts.passengers, 0),
         coalesce(ts.bookings, 0),
         coalesce(ts.revenue_bhd, 0),
         f.avg_rating,
         f.review_count,
         b.source_type,
         b.notes,
         b.dist,
         1 - b.dist
  FROM best_per_flight b
  JOIN mainline_carrier.flight  f  ON f.flight_id     = b.flight_id
  JOIN mainline_carrier.airport ao ON ao.airport_code = f.origin_code
  JOIN mainline_carrier.airport ad ON ad.airport_code = f.destination_code
  LEFT JOIN ticket_stats ts        ON ts.flight_id    = b.flight_id
  ORDER BY b.dist
  LIMIT match_count;
$$;

COMMENT ON FUNCTION vector_store.match_flight_notes IS
  'Flow 6: cosine similarity search over flight-note embeddings, enriched with mainline_carrier relational data.';