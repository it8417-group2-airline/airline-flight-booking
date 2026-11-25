"""
vector/embed_flight_notes.py  (Abrar - Member 1)  -  FLOW 5: PostgreSQL / MongoDB -> pgvector

Steps
  1. EXTRACT  text to embed:
       a) mainline_carrier.flight.notes          (always)
       b) MongoDB passenger_feedback.reviews[].comment  (optional, --include-mongo)
  2. SKIP     rows whose md5(text) is already stored (incremental - only new or
              changed notes cost an API call)
  3. EMBED    in batches with Gemini gemini-embedding-001 (1536 dims)
  4. LOAD     upsert into vector_store.flight_note_embeddings
              (ON CONFLICT ... DO UPDATE, so re-running is safe / idempotent)

MongoDB settings (agreed with Member 3), first match wins:
  MONGO_URI   env var  ->  st.secrets["MONGO_URI"]  ->  st.secrets["mongo"]["uri"]
  MONGO_DB    env var  ->  st.secrets["MONGO_DB"]   ->  st.secrets["mongo"]["db"]   -> "airline"
Reviews whose flight_id is not in mainline_carrier.flight are skipped (and
counted in the log), so one bad document cannot abort the whole batch.

Usage
  export DATABASE_URL="postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres"
  export GEMINI_API_KEY=...              # PowerShell: $env:GEMINI_API_KEY = "..."
  python vector/embed_flight_notes.py                  # flight notes only
  python vector/embed_flight_notes.py --include-mongo  # + MongoDB review text (needs MONGO_URI)
  (all variables are listed in .env.example)
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


def _setting(name: str, section_key: str, default: str | None = None) -> str | None:
    """Env var first (CLI), then Streamlit secrets: top-level NAME or [mongo] section_key."""
    value = os.getenv(name)
    if value:
        return value
    try:
        import streamlit as st
        if name in st.secrets:
            return str(st.secrets[name])
        if "mongo" in st.secrets and section_key in st.secrets["mongo"]:
            return str(st.secrets["mongo"][section_key])
    except Exception:
        pass
    return default


def mongo_settings() -> tuple[str | None, str]:
    """(uri, database name) for Member 3's MongoDB Atlas cluster."""
    return _setting("MONGO_URI", "uri"), _setting("MONGO_DB", "db", "airline")


def extract_mongo_reviews(log=print) -> list[dict]:
    """Review comments written in MongoDB (Member 3's passenger_feedback collection)."""
    uri, db_name = mongo_settings()
    if not uri:
        log("  ! MongoDB is not configured (MONGO_URI or [mongo] uri) - skipping review text")
        return []
    from pymongo import MongoClient
    client = MongoClient(uri, serverSelectionTimeoutMS=8000)
    try:
        db = client[db_name]
        items = []
        for doc in db.passenger_feedback.find({"reviews.0": {"$exists": True}},
                                              {"flight_id": 1, "reviews": 1}):
            try:
                flight_id = int(doc.get("flight_id"))
            except (TypeError, ValueError):
                continue                                   # no usable flight_id on this document
            for i, review in enumerate(doc.get("reviews") or []):
                comment = (review.get("comment") or "").strip() if isinstance(review, dict) else ""
                if comment:
                    ref = str(review.get("review_id") or f"{doc['_id']}:{i}")
                    items.append({"flight_id": flight_id, "source_type": "mongo_review",
                                  "source_ref": ref[:64], "text": comment})
        return items
    finally:
        client.close()


def keep_known_flights(conn, items: list[dict], log=print) -> list[dict]:
    """Drop items whose flight_id is not in mainline_carrier.flight (the FK would reject them)."""
    valid = {r[0] for r in conn.execute("SELECT flight_id FROM mainline_carrier.flight").fetchall()}
    kept = [it for it in items if it["flight_id"] in valid]
    if len(kept) < len(items):
        log(f"  ! skipped {len(items) - len(kept)} MongoDB reviews whose flight_id is not in mainline_carrier.flight")
    return kept


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
        mongo_items = keep_known_flights(conn, extract_mongo_reviews(log), log)
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
                    for it, vec in zip(batch, vectors, strict=True)
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
        sys.exit("Set DATABASE_URL to the Supabase connection string first (see .env.example).")
    # autocommit + explicit transactions per batch; prepare_threshold=None also works
    # through Supabase's transaction pooler (port 6543)
    with psycopg.connect(url, autocommit=True, prepare_threshold=None) as conn:
        run_embedding(conn, include_mongo=args.include_mongo, rebuild=args.rebuild)


if __name__ == "__main__":
    main()
