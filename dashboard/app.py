"""
dashboard/app.py - TEMPORARY home page (Abrar, for local testing only).
Member 3 owns the real app shell; this file is replaced by theirs.
Run from the repo root:   streamlit run dashboard/app.py
"""
import streamlit as st

st.set_page_config(page_title="Airline Flight Booking", page_icon="✈️", layout="wide")
st.title("✈️ Airline Flight Booking — Integration Dashboard")
st.write("Choose a page in the sidebar.")
st.markdown("""
| Page | Owner | Database |
|---|---|---|
| 1 Operational | Member 1 | PostgreSQL (mainline_carrier + regional_partner) |
| 2 Warehouse | Member 2 | Databricks |
| 3 Passenger Feedback | Member 3 | MongoDB |
| 4 Semantic Search | Member 1 | PostgreSQL + pgvector |
""")