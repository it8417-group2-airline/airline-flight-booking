"""
dashboard/app.py  -  app shell: sidebar navigation + home page.
(Design by Fatema - Member 2, for Member 3's app shell; replaces Abrar's temporary home page.)

Run from the repo root:   streamlit run dashboard/app.py

Pages live in dashboard/pages/. Pages 1, 2 and 4 are listed below; any other page file
dropped into that folder (e.g. Member 3's MongoDB page, "3_Passenger_Feedback.py") is
picked up automatically and shown in the right place in the sidebar.
"""
from __future__ import annotations

import re
from pathlib import Path

import streamlit as st

import ui

HERE = Path(__file__).resolve().parent
PAGES_DIR = HERE / "pages"
ASSETS = HERE / "assets"

st.set_page_config(page_title="Airline Flight Booking", page_icon="✈️", layout="wide")

# Known pages: file -> (sidebar title, icon, page number on the home page)
KNOWN = {
    "1_Operational.py": ("Operational data", ":material/database:"),
    "2_Warehouse.py": ("Data warehouse", ":material/warehouse:"),
    "4_Semantic_Search.py": ("Semantic search", ":material/travel_explore:"),
}
NUMBER_ICONS = {"3": ":material/reviews:"}   # default icon for Member 3's MongoDB page


def page_number(file: Path) -> str:
    m = re.match(r"(\d+)_", file.name)
    return m.group(1) if m else "9"


def page_title(file: Path) -> str:
    return KNOWN.get(file.name, (re.sub(r"^\d+_", "", file.stem).replace("_", " ").capitalize(), ""))[0]


# Every page file in dashboard/pages, sorted by its number (1, 2, 3, 4 ...)
page_files = sorted(PAGES_DIR.glob("[0-9]*_*.py"), key=lambda f: (int(page_number(f)), f.name))
PAGES = {}
for f in page_files:
    title, icon = KNOWN.get(f.name, (page_title(f), NUMBER_ICONS.get(page_number(f), ":material/dashboard:")))
    PAGES[page_number(f)] = st.Page(f"pages/{f.name}", title=title, icon=icon)


# ------------------------------------------------------------------------------------------
# Home page
# ------------------------------------------------------------------------------------------
PAGE_INFO = {   # number -> (emoji, title, what it shows, tags, gold tag)
    "1": ("🗄️", "Operational data", "Both schemas live from Supabase. Compare the two designs and add a real booking.",
          ["2 schemas", "Bookings"], "PostgreSQL"),
    "2": ("🏛️", "Data warehouse", "Databricks star schema with on-time charts, a carrier filter and Sync now.",
          ["Star schema", "Sync now"], "Databricks"),
    "3": ("💬", "Passenger feedback", "MongoDB documents side by side, plus a form for reviews and photo likes.",
          ["Reviews", "Photo likes"], "MongoDB"),
    "4": ("🔎", "Semantic search", "Describe a disruption in plain words and find similar past flights.",
          ["Embeddings", "Cosine search"], "pgvector"),
}
FLOWS = [
    ("1", "PostgreSQL → Databricks", "ETL with cleansing, column exclusion and reconciliation into a star schema."),
    ("2", "PostgreSQL → MongoDB", "Core records imported with their original IDs."),
    ("3", "MongoDB (extend)", "Reviews, ratings and photo likes added directly in MongoDB."),
    ("4", "MongoDB → PostgreSQL", "Review counts and ratings synced back to the summary table."),
    ("5", "PostgreSQL / MongoDB → pgvector", "Text extracted, embedded and loaded as vectors."),
    ("6", "pgvector → PostgreSQL", "Similar flights enriched with relational detail."),
    ("7", "All four → this dashboard", "Live views plus actions: Sync now, bookings, feedback and search."),
]
TEAM = [
    ("Abrar", "Member 1 · Operational & vector engineer", "PostgreSQL schemas, pgvector, pages 1 and 4"),
    ("Fatema", "Member 2 · Warehouse & ETL engineer", "Databricks ETL, star schema, page 2"),
    ("Eman", "Member 3 · NoSQL & dashboard lead", "MongoDB, app shell and deployment, page 3"),
]


def home() -> None:
    ui.apply_theme()
    ui.hero(
        "Airline Flight Booking",
        "Four databases, three cloud platforms, one live dashboard. Book a flight in PostgreSQL and watch it flow "
        "into the Databricks warehouse, MongoDB feedback and pgvector search.",
        eyebrow="IT8417 · Advanced Cloud Databases · Group 2",
        gold_chip="Live integration dashboard",
        chips=["Supabase PostgreSQL", "pgvector", "Databricks", "MongoDB Atlas", "Streamlit"],
    )
    ui.kpi_row([
        ui.Kpi("Databases", "4", "relational, vector, warehouse, document", "🗄️"),
        ui.Kpi("Operational schemas", "2", "mainline carrier + regional partner", "✈️", accent="teal"),
        ui.Kpi("Data flows", "7", "between the databases and this app", "🔁"),
        ui.Kpi("Live pages", str(len(PAGES)), "each one connected live to its database", "📊", accent="teal"),
    ])

    ui.section("Explore the dashboard", "Every page connects live to its database. Open one to start.", icon="🧭")
    cols = st.columns(4, gap="medium")
    for col, number in zip(cols, ["1", "2", "3", "4"], strict=True):
        emoji, title, text, tags, gold = PAGE_INFO[number]
        with col, ui.card_container(f"home_page_{number}"):
            ui.page_card(f"0{number}", emoji, title, text, tags, gold_tag=gold)
            if number in PAGES:
                st.page_link(PAGES[number], label="Open page", icon=":material/arrow_forward:")
            else:
                ui.coming_soon("Coming soon")

    ui.section("How the data flows", "The seven integration flows from the brief, and where you can see each one.",
               icon="🔁")
    ui.flow_cards(FLOWS)

    ui.section("Team", "IT8417 Group 2", icon="👥")
    ui.team_cards(TEAM)
    ui.footer()


# ------------------------------------------------------------------------------------------
# Navigation
# ------------------------------------------------------------------------------------------
st.logo(str(ASSETS / "logo.png"), icon_image=str(ASSETS / "logo_icon.png"), size="large")
nav = st.navigation({
    "Overview": [st.Page(home, title="Home", icon=":material/home:", default=True)],
    "Live databases": [PAGES[n] for n in sorted(PAGES, key=int)],
})
with st.sidebar:
    ui.apply_theme()        # shared CSS for every page, even ones that forget to call it
    ui.sidebar_status()
nav.run()
