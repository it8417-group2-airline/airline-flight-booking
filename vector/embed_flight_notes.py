"""
vector/embed_flight_notes.py  (Abrar)  -  FLOW 5: PostgreSQL / MongoDB -> pgvector

Steps
  1. EXTRACT  text to embed:
       a) mainline_carrier.flight.notes          (always)
       b) MongoDB passenger_feedback.reviews[].comment  (optional, --include-mongo)
  2. SKIP     rows whose md5(text) is already stored (incremental - only new or
              changed notes cost an API call)
  3. EMBED    in batches with Gemini gemini-embedding-001 (1536 dims)
  4. LOAD     upsert into vector_store.flight_note_embeddings
              (ON CONFLICT ... DO UPDATE, so re-running is safe / idempotent)

Usage
  export DATABASE_URL="postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres"
  export GEMINI_API_KEY=...              # PowerShell: $env:GEMINI_API_KEY = "..."
  python vector/embed_flight_notes.py                  # flight notes only
  python vector/embed_flight_notes.py --include-mongo  # + MongoDB review text (needs MONGO_URI)
  python vector/embed_flight_notes.py --rebuild        # wipe and re-embed everything
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent))
from embeddings import embed_texts, model_name, to_pgvector  # noqa: E402

BATCH_SIZE = 50

EXTRACT_SQL = """
    SELECT flight_id, notes
    FROM mainline_carrier.flight
    WHERE notes IS NOT NULL AND btrim(notes) <> ''
    ORDER BY flight_id
"""

UPSERT_SQL = """
    INSERT INTO vector_store.flight_note_embeddings
          (flight_id, source_type, source_ref, notes, content_hash, embedding, model_name)
    VALUES (%s, %s, %s, %s, %s, %s::vector, %s)
    ON CONFLICT (flight_id, source_type, source_ref) DO UPDATE
      SET notes        = EXCLUDED.notes,
          content_hash = EXCLUDED.content_hash,
          embedding    = EXCLUDED.embedding,
          model_name   = EXCLUDED.model_name,
          created_at   = now()
"""


def md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def extract_flight_notes(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(EXTRACT_SQL)
        return [{"flight_id": fid, "source_type": "flight_notes", "source_ref": "", "text": notes.strip()}
                for fid, notes in cur.fetchall()]


def extract_mongo_reviews() -> list[dict]:
    """Review comments written in MongoDB (Member 3's passenger_feedback collection)."""
    uri = os.getenv("MONGO_URI")
    if not uri:
        print("  ! MONGO_URI not set - skipping MongoDB review text")
        return []
    from pymongo import MongoClient
    db = MongoClient(uri)[os.getenv("MONGO_DB", "airline")]
    items = []
    for doc in db.passenger_feedback.find({"reviews.0": {"$exists": True}},
                                          {"flight_id": 1, "reviews": 1}):
        for i, review in enumerate(doc.get("reviews", [])):
            comment = (review.get("comment") or "").strip()
            if comment and doc.get("flight_id") is not None:
                ref = str(review.get("review_id") or f"{doc['_id']}:{i}")
                items.append({"flight_id": int(doc["flight_id"]), "source_type": "mongo_review",
                              "source_ref": ref[:64], "text": comment})
    return items


def existing_hashes(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("""SELECT flight_id, source_type, source_ref, content_hash, model_name
                       FROM vector_store.flight_note_embeddings""")
        return {(r[0], r[1], r[2]): (r[3], r[4]) for r in cur.fetchall()}


def run_embedding(conn, include_mongo: bool = False, rebuild: bool = False, log=print) -> dict:
    """Run Flow 5 end to end on an open psycopg connection. Also called by the dashboard."""
    model = model_name()
    log(f"Model: {model}")
    if rebuild:
        conn.execute("TRUNCATE vector_store.flight_note_embeddings")
        log("  rebuilt: table truncated")

    items = extract_flight_notes(conn)
    log(f"1. Extracted {len(items)} flight notes from mainline_carrier.flight")
    if include_mongo:
        mongo_items = extract_mongo_reviews()
        log(f"   + {len(mongo_items)} review comments from MongoDB passenger_feedback")
        items += mongo_items

    known = existing_hashes(conn)
    todo = [it for it in items
            if known.get((it["flight_id"], it["source_type"], it["source_ref"])) != (md5(it["text"]), model)]
    log(f"2. {len(items) - len(todo)} unchanged (skipped), {len(todo)} new/changed to embed")

    loaded = 0
    for start in range(0, len(todo), BATCH_SIZE):
        batch = todo[start:start + BATCH_SIZE]
        vectors = embed_texts([it["text"] for it in batch])
        with conn.transaction():
            with conn.cursor() as cur:
                cur.executemany(UPSERT_SQL, [
                    (it["flight_id"], it["source_type"], it["source_ref"], it["text"], md5(it["text"]),
                     to_pgvector(vec), model)
                    for it, vec in zip(batch, vectors)
                ])
        loaded += len(batch)
        log(f"3-4. Embedded and loaded {loaded}/{len(todo)}")
        time.sleep(1)   # stay well inside the free-tier rate limit

    total = conn.execute("SELECT count(*) FROM vector_store.flight_note_embeddings").fetchone()[0]
    log(f"Done. vector_store.flight_note_embeddings now holds {total} vectors.")
    return {"extracted": len(items), "embedded": loaded, "skipped": len(items) - len(todo), "total": total}


def main() -> None:
    ap = argparse.ArgumentParser(description="Flow 5: embed flight notes into pgvector")
    ap.add_argument("--include-mongo", action="store_true", help="also embed MongoDB review comments")
    ap.add_argument("--rebuild", action="store_true", help="delete all embeddings first")
    args = ap.parse_args()

    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit("Set DATABASE_URL to the Supabase connection string first.")
    # autocommit + explicit transactions per batch; prepare_threshold=None also works
    # through Supabase's transaction pooler (port 6543)
    with psycopg.connect(url, autocommit=True, prepare_threshold=None) as conn:
        run_embedding(conn, include_mongo=args.include_mongo, rebuild=args.rebuild)


if __name__ == "__main__":
    main()