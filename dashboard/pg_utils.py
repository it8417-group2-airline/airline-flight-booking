"""
dashboard/pg_utils.py  ( Abrar)
Small PostgreSQL (Supabase) helper used by pages 1_Operational and
4_Semantic_Search. Member 3 can merge get_pg_conn() into the shared db.py;
the pages only depend on query_df() and get_pg_conn().

Secrets (.streamlit/secrets.toml or Streamlit Cloud -> Settings -> Secrets):
    [postgres]
    url = "postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres"
Falls back to the DATABASE_URL environment variable for local runs.
"""
from __future__ import annotations

import os

import pandas as pd
import psycopg
import streamlit as st


def _database_url() -> str:
    try:
        return st.secrets["postgres"]["url"]
    except Exception:
        url = os.getenv("DATABASE_URL")
        if not url:
            st.error("PostgreSQL is not configured: add [postgres] url to secrets.toml or set DATABASE_URL.")
            st.stop()
        return url


@st.cache_resource(show_spinner=False)
def _connect() -> psycopg.Connection:
    # autocommit: every SELECT sees the latest data (live dashboard);
    # writes that must be atomic use `with conn.transaction():`
    # prepare_threshold=None: compatible with Supabase's pgbouncer pooler
    return psycopg.connect(_database_url(), autocommit=True, prepare_threshold=None, connect_timeout=10)


def get_pg_conn() -> psycopg.Connection:
    """Cached connection with a health check - reconnects if Supabase dropped it."""
    conn = _connect()
    try:
        conn.execute("SELECT 1")
    except Exception:
        _connect.clear()
        conn = _connect()
    return conn


def query_df(sql: str, params: tuple | dict | None = None) -> pd.DataFrame:
    """Run a SELECT and return a DataFrame."""
    with get_pg_conn().cursor() as cur:
        cur.execute(sql, params)
        if cur.description is None:
            return pd.DataFrame()
        return pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description])


def scalar(sql: str, params: tuple | dict | None = None):
    with get_pg_conn().cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return row[0] if row else None