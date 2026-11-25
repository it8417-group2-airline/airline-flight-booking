"""
dashboard/pg_utils.py  (Abrar - Member 1)
Small PostgreSQL (Supabase) helper used by pages 1_Operational and
4_Semantic_Search. Member 3 can merge these functions into the shared db.py;
the pages only depend on query_df(), scalar(), get_pg_conn() and new_pg_conn().

Secrets (.streamlit/secrets.toml or Streamlit Cloud -> Settings -> Secrets):
    [postgres]
    url = "postgresql://postgres.<project-ref>:<password>@aws-1-<region>.pooler.supabase.com:5432/postgres"
Falls back to the DATABASE_URL environment variable for local runs.

Two kinds of connection
  * get_pg_conn()  - ONE cached autocommit connection shared by every visitor,
                     used for reads (each SELECT sees the latest data).
  * new_pg_conn()  - a short-lived PRIVATE connection for writes that must be
                     atomic (booking + ticket). Two visitors booking at the same
                     moment never share a transaction (audit L-3).
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

import pandas as pd
import psycopg
import streamlit as st

TIME_ZONE = "Asia/Bahrain"   # Supabase runs in UTC; the dashboard shows Bahrain time (UTC+3)


def _database_url() -> str:
    try:
        return st.secrets["postgres"]["url"]
    except Exception:
        url = os.getenv("DATABASE_URL")
        if not url:
            st.error("PostgreSQL is not configured: add [postgres] url to .streamlit/secrets.toml "
                     "or set the DATABASE_URL environment variable (see README.md).")
            st.stop()
        return url


def _open(autocommit: bool) -> psycopg.Connection:
    # prepare_threshold=None: compatible with Supabase's pgbouncer/Supavisor pooler
    conn = psycopg.connect(_database_url(), autocommit=autocommit,
                           prepare_threshold=None, connect_timeout=10)
    # Every timestamp, to_char() label and DataFrame value on the dashboard is local time.
    conn.execute(f"SET TIME ZONE '{TIME_ZONE}'")
    if not autocommit:
        conn.commit()          # end the implicit transaction opened by SET
    return conn


@st.cache_resource(show_spinner=False)
def _connect() -> psycopg.Connection:
    # autocommit: every SELECT sees the latest data (live dashboard)
    return _open(autocommit=True)


def get_pg_conn() -> psycopg.Connection:
    """Shared, cached read connection with a health check - reconnects if Supabase dropped it."""
    conn = _connect()
    try:
        conn.execute("SELECT 1")
    except Exception:
        _connect.clear()
        conn = _connect()
    return conn


@contextmanager
def new_pg_conn(autocommit: bool = False) -> Iterator[psycopg.Connection]:
    """Private connection for one write action. Commits on success, rolls back on error, always closes.

        with new_pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT ...")
    """
    conn = _open(autocommit=autocommit)
    try:
        yield conn
        if not autocommit:
            conn.commit()
    except Exception:
        if not autocommit:
            conn.rollback()
        raise
    finally:
        conn.close()


def query_df(sql: str, params: tuple | dict | None = None) -> pd.DataFrame:
    """Run a SELECT and return a DataFrame."""
    with get_pg_conn().cursor() as cur:
        cur.execute(sql, params)
        if cur.description is None:
            return pd.DataFrame()
        return pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description])


def scalar(sql: str, params: tuple | dict | None = None):
    """Run a SELECT that returns one value."""
    with get_pg_conn().cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return row[0] if row else None
