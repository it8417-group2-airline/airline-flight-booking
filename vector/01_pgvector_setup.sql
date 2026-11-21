-- =====================================================================
-- File   : vector/01_pgvector_setup.sql   (Abrar)
-- Purpose: Vector role (pgvector) - storage, index and search function.
--   Flow 5 : flight.notes (and optionally MongoDB review text) is embedded
--            by embed_flight_notes.py and loaded into flight_note_embeddings.
--   Flow 6 : match_flight_notes() finds the nearest notes by cosine
--            distance and ENRICHES them with relational data joined back
--            from mainline_carrier (flight, airport, ticket, booking).
-- Run AFTER sql/postgres/01..08.
-- =====================================================================

-- On Supabase you can also enable it in Dashboard -> Database -> Extensions.
-- Supabase installs extensions into the "extensions" schema, which is already
-- on the search_path, so the type "vector" resolves without a prefix.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS vector_store;
COMMENT ON SCHEMA vector_store IS 'pgvector role: embeddings of flight / disruption notes.';

-- ---------------------------------------------------------------------
-- Embeddings table (Appendix I: flight_note_embeddings(flight_id, notes,
-- embedding vector(1536)) + housekeeping columns)
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS vector_store.flight_note_embeddings CASCADE;
CREATE TABLE vector_store.flight_note_embeddings (
  embedding_id  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  flight_id     INTEGER      NOT NULL
                REFERENCES mainline_carrier.flight(flight_id) ON DELETE CASCADE,
  source_type   VARCHAR(20)  NOT NULL DEFAULT 'flight_notes'
                CHECK (source_type IN ('flight_notes', 'mongo_review')),
  source_ref    VARCHAR(64)  NOT NULL DEFAULT '',      -- '' for flight notes; Mongo review id otherwise
  notes         TEXT         NOT NULL,                 -- the exact text that was embedded
  content_hash  CHAR(32)     NOT NULL,                 -- md5(notes): skip re-embedding unchanged text
  embedding     vector(1536) NOT NULL,                 -- OpenAI text-embedding-3-small / Gemini @1536
  model_name    VARCHAR(60)  NOT NULL,
  created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT uq_embedding_source UNIQUE (flight_id, source_type, source_ref)
);

-- HNSW approximate-nearest-neighbour index for COSINE distance (<=>).
-- HNSW chosen over IVFFlat: no training step / no need for data before
-- building, good recall on small and growing tables, works with inserts.
CREATE INDEX idx_flight_note_emb_hnsw
  ON vector_store.flight_note_embeddings
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

CREATE INDEX idx_flight_note_emb_flight ON vector_store.flight_note_embeddings (flight_id);

-- ---------------------------------------------------------------------
-- Flow 6: similarity search + relational enrichment in ONE function.
-- The dashboard and the CLI both call this, so the logic lives in one place.
--   query_embedding : vector of the user's search text (same model!)
--   match_count     : top-k
--   max_distance    : cosine distance cut-off (0 = identical, 2 = opposite)
-- ---------------------------------------------------------------------
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
           count(DISTINCT t.booking_id)                          AS bookings,
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
         (EXTRACT(EPOCH FROM (f.actual_departure - f.scheduled_departure)) / 60)::int,
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