"""
vector/embeddings.py  (Abrar)
Shared embedding helper used by:
  * vector/embed_flight_notes.py      (Flow 5 - load embeddings)
  * vector/similarity_search.py       (Flow 6 - CLI search)
  * dashboard/pages/4_Semantic_Search.py  (search box)

Every text MUST be embedded with the same provider/model, otherwise the
vectors are not comparable. All providers return 1536-dimension vectors to
match the column type vector(1536).

Providers (choose with EMBED_PROVIDER env var / Streamlit secret):
  openai  - text-embedding-3-small (1536 dims natively). Needs OPENAI_API_KEY.
  gemini  - gemini-embedding-001 with output_dimensionality=1536.
            Needs GEMINI_API_KEY. Has a free tier.
  local   - deterministic hashing "bag of words" vector. NO API, NO cost.
            Only for offline testing - it matches shared words, it does NOT
            understand meaning. Never use it for the final demo.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from typing import List

EMBED_DIM = 1536
MODEL_NAMES = {
    "openai": "text-embedding-3-small",
    "gemini": "gemini-embedding-001",
    "local": "local-hashing-1536",
}


def _setting(name: str, default: str | None = None) -> str | None:
    """Read a setting from env vars first, then Streamlit secrets (if running in Streamlit)."""
    if os.getenv(name):
        return os.getenv(name)
    try:
        import streamlit as st  # only available inside the dashboard
        if name in st.secrets:
            return str(st.secrets[name])
        if "embeddings" in st.secrets and name in st.secrets["embeddings"]:
            return str(st.secrets["embeddings"][name])
    except Exception:
        pass
    return default


def get_provider() -> str:
    provider = (_setting("EMBED_PROVIDER", "openai") or "openai").lower()
    if provider not in MODEL_NAMES:
        raise ValueError(f"Unknown EMBED_PROVIDER '{provider}'. Use one of {list(MODEL_NAMES)}")
    return provider


def model_name(provider: str | None = None) -> str:
    return MODEL_NAMES[provider or get_provider()]


def _normalise(vec: List[float]) -> List[float]:
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _embed_openai(texts: List[str]) -> List[List[float]]:
    from openai import OpenAI
    client = OpenAI(api_key=_setting("OPENAI_API_KEY"))
    resp = client.embeddings.create(model=MODEL_NAMES["openai"], input=texts)
    return [d.embedding for d in sorted(resp.data, key=lambda d: d.index)]


def _embed_gemini(texts: List[str], is_query: bool) -> List[List[float]]:
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=_setting("GEMINI_API_KEY"))
    resp = client.models.embed_content(
        model=MODEL_NAMES["gemini"],
        contents=texts,
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY" if is_query else "RETRIEVAL_DOCUMENT",
            output_dimensionality=EMBED_DIM,
        ),
    )
    # Gemini only pre-normalises 3072-d output, so normalise the 1536-d vectors ourselves
    return [_normalise(list(e.values)) for e in resp.embeddings]


_STOP = set("a an the and or of to in on at by for with from is was were be been it its as this that "
            "due no not into than then".split())


def _embed_local(texts: List[str]) -> List[List[float]]:
    out = []
    for text in texts:
        vec = [0.0] * EMBED_DIM
        words = [w for w in re.findall(r"[a-z]+", text.lower()) if w not in _STOP]
        grams = words + [a + "_" + b for a, b in zip(words, words[1:])]
        for g in grams:
            h = int(hashlib.md5(g.encode()).hexdigest(), 16)
            vec[h % EMBED_DIM] += 1.0 if (h >> 11) % 2 else -1.0
        out.append(_normalise(vec))
    return out


def embed_texts(texts: List[str], is_query: bool = False, provider: str | None = None) -> List[List[float]]:
    """Embed a batch of texts. Returns one 1536-float list per text."""
    provider = provider or get_provider()
    if not texts:
        return []
    if provider == "openai":
        vectors = _embed_openai(texts)
    elif provider == "gemini":
        vectors = _embed_gemini(texts, is_query)
    else:
        vectors = _embed_local(texts)
    for v in vectors:
        if len(v) != EMBED_DIM:
            raise ValueError(f"Expected {EMBED_DIM} dimensions, got {len(v)} from {provider}")
    return vectors


def embed_query(text: str, provider: str | None = None) -> List[float]:
    return embed_texts([text], is_query=True, provider=provider)[0]


def to_pgvector(vec: List[float]) -> str:
    """Format a Python list as a pgvector literal: '[0.1,0.2,...]' (cast with ::vector in SQL)."""
    return "[" + ",".join(f"{v:.7f}" for v in vec) + "]"