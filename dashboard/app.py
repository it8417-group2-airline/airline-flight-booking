"""
dashboard/app.py  (Abrar - Member 1)  -  TEMPORARY home page for local testing.
Member 3 owns the real app shell: when their app.py and db.py are pushed, this
file is replaced by theirs and pg_utils.py is merged into db.py (audit G-5).
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
