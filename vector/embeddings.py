"""
vector/embeddings.py  (Abrar - Member 1)
Shared embedding helper used by:
  * vector/embed_flight_notes.py           (Flow 5 - load embeddings)
  * vector/similarity_search.py            (Flow 6 - CLI search)
  * dashboard/pages/4_Semantic_Search.py   (search box)

ONE provider everywhere: Google Gemini, model gemini-embedding-001, with
output_dimensionality=1536 to match the column type vector(1536).
The stored notes and every search query MUST use the same model -
vectors from different models are not comparable.

The API key is read from the GEMINI_API_KEY environment variable, or from
Streamlit secrets:   [embeddings]  GEMINI_API_KEY = "..."
"""
from __future__ import annotations

import math
import os
from typing import List

EMBED_DIM = 1536
MODEL_NAME = "gemini-embedding-001"


def _api_key() -> str:
    """Read GEMINI_API_KEY from env vars first, then Streamlit secrets (inside the dashboard)."""
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        try:
            import streamlit as st
            if "GEMINI_API_KEY" in st.secrets:
                key = st.secrets["GEMINI_API_KEY"]
            elif "embeddings" in st.secrets:
                key = st.secrets["embeddings"].get("GEMINI_API_KEY")
        except Exception:
            pass
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set (environment variable or [embeddings] in secrets.toml).")
    return str(key)


def model_name() -> str:
    return MODEL_NAME


def _normalise(vec: List[float]) -> List[float]:
    # Gemini only pre-normalises 3072-d output, so normalise the 1536-d vectors ourselves
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _embed_gemini(texts: List[str], is_query: bool) -> List[List[float]]:
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=_api_key())
    resp = client.models.embed_content(
        model=MODEL_NAME,
        contents=texts,
        config=types.EmbedContentConfig(
            # notes are "documents"; the user's search text is a "query"
            task_type="RETRIEVAL_QUERY" if is_query else "RETRIEVAL_DOCUMENT",
            output_dimensionality=EMBED_DIM,
        ),
    )
    return [_normalise(list(e.values)) for e in resp.embeddings]


def embed_texts(texts: List[str], is_query: bool = False) -> List[List[float]]:
    """Embed a batch of texts. Returns one 1536-float list per text."""
    if not texts:
        return []
    vectors = _embed_gemini(texts, is_query)
    for v in vectors:
        if len(v) != EMBED_DIM:
            raise ValueError(f"Expected {EMBED_DIM} dimensions, got {len(v)}")
    return vectors


def embed_query(text: str) -> List[float]:
    return embed_texts([text], is_query=True)[0]


def to_pgvector(vec: List[float]) -> str:
    """Format a Python list as a pgvector literal: '[0.1,0.2,...]' (cast with ::vector in SQL)."""
    return "[" + ",".join(f"{v:.7f}" for v in vec) + "]"
