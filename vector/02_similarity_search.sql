-- =====================================================================
-- File   : vector/02_similarity_search.sql   (Abrar - Member 1)
-- Purpose: The similarity search written out as plain SQL (what the
--          match_flight_notes() function does internally) - useful for
--          the report and for explaining Flow 6 in the viva.
--
-- In SQL we cannot call the embedding API, so this example uses the
-- vector of an EXISTING note as the query ("find flights similar to
-- flight X"). The dashboard/CLI embed free text instead.
-- =====================================================================

-- 1. Coverage check: how many flights with notes have an embedding?
SELECT count(*) FILTER (WHERE e.flight_id IS NOT NULL) AS embedded,
       count(*)                                         AS flights_with_notes
FROM mainline_carrier.flight f
LEFT JOIN vector_store.flight_note_embeddings e
       ON e.flight_id = f.flight_id AND e.source_type = 'flight_notes'
WHERE f.notes IS NOT NULL;

-- 2. "More like this": PAST flights whose notes are closest to flight 28's note,
--    enriched with route, delay and passenger counts (join back to mainline).
WITH query AS (
  SELECT embedding FROM vector_store.flight_note_embeddings
  WHERE flight_id = 28 AND source_type = 'flight_notes'
)
SELECT f.flight_number,
       f.origin_code || '-' || f.destination_code                                  AS route,
       f.flight_status,
       CASE WHEN f.actual_departure IS NULL THEN NULL                              -- cancelled: no delay
            ELSE GREATEST((EXTRACT(EPOCH FROM (f.actual_departure - f.scheduled_departure)) / 60)::int, 0)
       END
                                                                                   AS delay_min,
       (SELECT count(*) FROM mainline_carrier.ticket t
        WHERE t.flight_id = f.flight_id AND t.ticket_status <> 'REFUNDED')         AS passengers,
       round((1 - (e.embedding <=> q.embedding))::numeric, 3)                     AS similarity,
       left(e.notes, 90)                                                           AS notes
FROM vector_store.flight_note_embeddings e
CROSS JOIN query q
JOIN mainline_carrier.flight f ON f.flight_id = e.flight_id
WHERE e.flight_id <> 28
  AND f.scheduled_departure < now()          -- only flights that already happened
ORDER BY e.embedding <=> q.embedding        -- <=> = cosine distance operator
LIMIT 5;

-- 3. Same search through the reusable function. The function would also return
--    flight 28 itself (similarity 1.000), so ask for 6 and leave flight 28 out,
--    exactly like query 2. The function only returns flights that have already
--    departed ("similar PAST flights") and adds city names, bookings and revenue.
SELECT flight_number, route, flight_status, delay_min, passengers, bookings,
       round(similarity::numeric, 3) AS similarity
FROM vector_store.match_flight_notes(
  (SELECT embedding FROM vector_store.flight_note_embeddings
   WHERE flight_id = 28 AND source_type = 'flight_notes'), 6, 1.0)
WHERE flight_id <> 28
ORDER BY similarity DESC
LIMIT 5;

-- 4. Proof that the HNSW index is used (look for "Index Scan using idx_flight_note_emb_hnsw").
--    With very few rows the planner may prefer a sequential scan; SET enable_seqscan = off forces the index
--    for the demonstration only.
SET enable_seqscan = off;
EXPLAIN
SELECT flight_id FROM vector_store.flight_note_embeddings
ORDER BY embedding <=> (SELECT embedding FROM vector_store.flight_note_embeddings LIMIT 1)
LIMIT 5;
RESET enable_seqscan;
