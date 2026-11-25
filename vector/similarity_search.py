"""
vector/similarity_search.py  (Abrar - Member 1)  -  FLOW 6: pgvector -> PostgreSQL enrichment

Embeds a free-text question with the SAME model used for the notes, then calls
vector_store.match_flight_notes(), which:
  1. ranks stored note vectors by cosine distance (<=>) using the HNSW index
  2. joins the matches back to mainline_carrier.flight / airport / ticket
     to add route, delay, passengers, revenue and MongoDB-synced rating.

Usage (needs DATABASE_URL and GEMINI_API_KEY - see .env.example)
  python vector/similarity_search.py "flight delayed by weather at a connecting hub"
  python vector/similarity_search.py "technical fault aircraft swap" --k 3
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent))
from embeddings import embed_query, to_pgvector  # noqa: E402

SEARCH_SQL = "SELECT * FROM vector_store.match_flight_notes(%s::vector, %s, %s)"


def search(conn, text: str, k: int = 5, max_distance: float = 1.0) -> list[dict]:
    qvec = to_pgvector(embed_query(text))
    with conn.cursor() as cur:
        cur.execute(SEARCH_SQL, (qvec, k, max_distance))
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def main() -> None:
    ap = argparse.ArgumentParser(description="Semantic search over flight disruption notes")
    ap.add_argument("query", help="free-text description, e.g. 'sandstorm delay at the hub'")
    ap.add_argument("--k", type=int, default=5, help="number of results (top-k)")
    ap.add_argument("--max-distance", type=float, default=1.0, help="cosine distance cut-off (lower = stricter)")
    args = ap.parse_args()
    if not 1 <= args.k <= 50:
        ap.error("--k must be between 1 and 50")

    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit("Set DATABASE_URL to the Supabase connection string first (see .env.example).")
    with psycopg.connect(url, prepare_threshold=None) as conn:
        conn.execute("SET TIME ZONE 'Asia/Bahrain'")   # Supabase runs in UTC; show Bahrain time (UTC+3)
        rows = search(conn, args.query, args.k, args.max_distance)

    print(f'\nTop {len(rows)} similar past flights for: "{args.query}"\n')
    if not rows:
        print("No past flight within that distance. Raise --max-distance or rephrase.")
    for i, r in enumerate(rows, 1):
        rating = f"{r['avg_rating']}/5 ({r['review_count']} reviews)" if r["avg_rating"] is not None else "no reviews synced"
        print(f"{i}. {r['flight_number']}  {r['route']}  similarity={r['similarity']:.3f}")
        print(f"   {r['scheduled_departure']:%Y-%m-%d %H:%M}  status={r['flight_status']}  "
              f"delay={r['delay_min']} min  passengers={r['passengers']}  revenue={r['revenue_bhd']} BHD  "
              f"rating={rating}")
        print(f"   [{r['source_type']}] {r['matched_text']}\n")


if __name__ == "__main__":
    main()
