"""
Page 4 - Semantic search (PostgreSQL + pgvector)              Owner:(Abrar)

Brief requirements covered on this page
  * A working semantic-search box backed by pgvector         (Flow 6)
  * Results enriched with relational data (join back to mainline_carrier)
  * Button that runs the embedding pipeline for new/changed notes (Flow 5)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from pg_utils import get_pg_conn, query_df, scalar

# make the shared vector/ modules importable (repo_root/vector)
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "vector"))
from embeddings import embed_query, model_name, to_pgvector  # noqa: E402
from embed_flight_notes import run_embedding  # noqa: E402

st.set_page_config(page_title="Semantic search", page_icon="🔎", layout="wide")
st.title("🔎 Semantic search over flight disruption notes")
st.caption("Free text → embedding (1536-d) → cosine-distance search in pgvector → "
           "results joined back to `mainline_carrier` for route, delay, passengers, revenue and rating.")

EXAMPLES = [
    "flight delayed by weather at a connecting hub",
    "sandstorm with low visibility",
    "technical fault, aircraft swap needed",
    "crew shortage caused the delay",
    "passenger medical emergency and diversion",
    "baggage left behind",
]

# ------------------------------------------------------------------ status + Flow 5 button
c1, c2, c3, c4 = st.columns(4)
with_notes = scalar("SELECT count(*) FROM mainline_carrier.flight WHERE notes IS NOT NULL AND btrim(notes) <> ''")
embedded = scalar("SELECT count(DISTINCT flight_id) FROM vector_store.flight_note_embeddings "
                  "WHERE source_type = 'flight_notes'")
stale = scalar("""SELECT count(*) FROM mainline_carrier.flight f
                  LEFT JOIN vector_store.flight_note_embeddings e
                         ON e.flight_id = f.flight_id AND e.source_type = 'flight_notes'
                  WHERE f.notes IS NOT NULL AND btrim(f.notes) <> ''
                    AND (e.flight_id IS NULL OR e.content_hash <> md5(btrim(f.notes)))""")
c1.metric("Flights with notes", with_notes)
c2.metric("Embedded", embedded)
c3.metric("New / changed, not embedded", stale)
c4.metric("Embedding model", model_name())
# Vectors from different models cannot be compared, so warn if any stored vector used another model
other_models = scalar("SELECT count(*) FROM vector_store.flight_note_embeddings WHERE model_name <> %s", (model_name(),))
if other_models:
    st.warning(f"{other_models} stored vectors were made with a different model. "
               "Run the Flow 5 pipeline below: it re-embeds any vector whose model does not match.")

with st.expander("⚙️ Flow 5 — embed new or changed notes"):
    st.write("Reads `mainline_carrier.flight.notes`, skips text whose md5 hash is already stored, "
             "embeds the rest and upserts into `vector_store.flight_note_embeddings`.")
    include_mongo = st.checkbox("Also embed MongoDB review comments (passenger_feedback.reviews[].comment)")
    if st.button("Run embedding pipeline"):
        log = []
        with st.spinner("Embedding…"):
            result = run_embedding(get_pg_conn(), include_mongo=include_mongo, log=log.append)
        st.code("\n".join(log))
        st.success(f"Embedded {result['embedded']} text(s); table now holds {result['total']} vectors.")

st.divider()

# ------------------------------------------------------------------ search box (Flow 6)
if "search_text" not in st.session_state:
    st.session_state.search_text = EXAMPLES[0]


def use_example(text: str) -> None:
    st.session_state.search_text = text


st.write("Try an example:")
ex_cols = st.columns(len(EXAMPLES))
for col, ex in zip(ex_cols, EXAMPLES):
    col.button(ex, on_click=use_example, args=(ex,), width="stretch")

with st.form("search"):
    query = st.text_input("Describe the disruption you are looking for", key="search_text")
    s1, s2 = st.columns(2)
    k = s1.slider("Number of results (top-k)", 1, 10, 5)
    max_dist = s2.slider("Max cosine distance (lower = stricter)", 0.1, 1.0, 1.0, 0.05)
    go = st.form_submit_button("Search", type="primary")

SEARCH_SQL = "SELECT * FROM vector_store.match_flight_notes(%s::vector, %s, %s)"

if go and query.strip():
    with st.spinner("Embedding the query and searching…"):
        qvec = embed_query(query.strip())
        results = query_df(SEARCH_SQL, (to_pgvector(qvec), k, max_dist))

    if results.empty:
        st.info("No notes within that distance. Raise the max distance or rephrase.")
    else:
        for c in ("similarity", "cosine_distance", "revenue_bhd", "avg_rating"):
            results[c] = pd.to_numeric(results[c], errors="coerce")
        st.subheader(f"Top {len(results)} similar past flights")
        st.dataframe(
            results[["flight_number", "route", "scheduled_departure", "flight_status", "delay_min",
                     "passengers", "revenue_bhd", "avg_rating", "review_count", "similarity", "matched_text"]],
            hide_index=True, width="stretch",
            column_config={
                "similarity": st.column_config.ProgressColumn("similarity", min_value=0.0, max_value=1.0,
                                                              format="%.3f"),
                "scheduled_departure": st.column_config.DatetimeColumn("departure", format="DD MMM YYYY HH:mm"),
                "delay_min": st.column_config.NumberColumn("delay (min)"),
                "revenue_bhd": st.column_config.NumberColumn("revenue (BHD)", format="%.3f"),
                "matched_text": st.column_config.TextColumn("matched note", width="large"),
            })

        for i, r in results.iterrows():
            rating = f"⭐ {r['avg_rating']:.2f} ({int(r['review_count'])} reviews)" if pd.notna(r["avg_rating"]) \
                else "no MongoDB reviews synced yet"
            with st.container(border=True):
                st.markdown(f"**{i + 1}. {r['flight_number']} · {r['route']}** — similarity **{r['similarity']:.3f}**")
                st.markdown(f"> {r['matched_text']}")
                st.caption(f"{r['flight_status']} · delay {r['delay_min'] if pd.notna(r['delay_min']) else '—'} min · "
                           f"{int(r['passengers'])} passengers · {r['revenue_bhd']:.3f} BHD · {rating} · "
                           f"source: {r['source_type']}")

    with st.expander("SQL behind this search"):
        st.code("SELECT * FROM vector_store.match_flight_notes(:query_vector, :k, :max_distance);\n\n"
                "-- inside the function:\n"
                "-- 1) ORDER BY embedding <=> query_vector   (cosine distance, HNSW index)\n"
                "-- 2) keep best match per flight\n"
                "-- 3) JOIN mainline_carrier.flight, airport, ticket  (enrichment)", language="sql")