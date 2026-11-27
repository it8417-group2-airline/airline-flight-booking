"""
dashboard/pages/2_Warehouse.py  (Fatema - Member 2)
Page 2 - Data warehouse (Databricks star schema, Flow 1: PostgreSQL -> Databricks)

Brief / task-division requirements covered on this page
  * View into the warehouse: KPI summary + on-time-performance chart from the star schema
  * "Sync now" button: triggers the Databricks Job airline_etl_flow1 through the Jobs API,
    then shows fact row counts and the charts BEFORE and AFTER the run
  * Carrier filter (interactive): mainline-only / regional-only / combined ticket volumes
  * Extra drill-downs: revenue by route & cabin, top passengers, fare reconciliation

Every number comes from the views created by databricks/04_analytical_queries.sql,
so the dashboard and the notebooks always use exactly the same logic.
"""
from __future__ import annotations

import datetime as dt
import re

import altair as alt
import pandas as pd
import streamlit as st

import dbx_utils as dbx
import ui

st.set_page_config(page_title="Warehouse · Databricks", page_icon="🏛️", layout="wide")
ui.apply_theme()

GOLD, STAGING, AUDIT, BRONZE = dbx.GOLD, dbx.STAGING, dbx.AUDIT, dbx.BRONZE
CARRIER_ORDER = ["Mainline carrier", "Regional partner"]
CARRIER_RANGE = [ui.CARRIER_COLORS[c] for c in CARRIER_ORDER]
FILTERS = {"Mainline only": ["DM"], "Regional only": ["PX"], "Combined": ["DM", "PX"]}
CHART_BG = ui.CARD              # 2 px gaps between bars are drawn in the card colour (white)

# ------------------------------------------------------------------------------------------
# Queries (all read-only, all on the gold layer views/tables)
# ------------------------------------------------------------------------------------------
LATEST_BRONZE_RUN = f"(SELECT MAX(run_id) FROM {AUDIT} WHERE layer = 'bronze')"
SQL_OVERVIEW = f"""
SELECT
  (SELECT COUNT(*) FROM {GOLD}.fact_ticket)                                AS fact_rows,
  (SELECT COUNT(*) FROM {GOLD}.fact_ticket WHERE is_revenue)               AS revenue_tickets,
  (SELECT COALESCE(SUM(revenue_bhd), 0) FROM {GOLD}.fact_ticket)           AS revenue_bhd,
  (SELECT COUNT(*) FROM {GOLD}.dim_passenger)                              AS passengers,
  (SELECT COALESCE(SUM(records_merged), 0) FROM {GOLD}.dim_passenger)      AS passenger_records,
  (SELECT COUNT(*) FROM {GOLD}.dim_flight)                                 AS flights,
  (SELECT COUNT(*) FROM {GOLD}.dim_date)                                   AS calendar_days,
  (SELECT COUNT(*) FROM {GOLD}.dim_carrier)                                AS carriers,
  (SELECT COUNT(*) FROM {GOLD}.dim_cabin)                                  AS cabins,
  (SELECT ROUND(100.0 * SUM(CASE WHEN is_on_time THEN 1 ELSE 0 END)
               / NULLIF(SUM(CASE WHEN is_on_time IS NOT NULL THEN 1 ELSE 0 END), 0), 1)
     FROM {GOLD}.dim_flight)                                               AS on_time_pct,
  (SELECT COUNT(*) FROM {STAGING}.stg_booking)                             AS stg_bookings,
  (SELECT COUNT(*) FROM {STAGING}.stg_passenger)                           AS stg_passengers,
  (SELECT COUNT(DISTINCT table_name) FROM {AUDIT}
     WHERE layer = 'bronze' AND run_id = {LATEST_BRONZE_RUN})              AS bronze_tables,
  (SELECT SUM(rows_after) FROM {AUDIT}
     WHERE layer = 'bronze' AND run_id = {LATEST_BRONZE_RUN})              AS bronze_rows,
  (SELECT MAX(run_ts) FROM {AUDIT})                                        AS last_etl_utc
"""
SQL_TICKETS = f"""
SELECT f.ticket_nk, f.booking_reference, c.carrier_code, c.carrier_name, p.full_name AS passenger,
       fl.flight_number, fl.route, fl.flight_date, cb.cabin_name, f.ticket_status, f.fare_bhd, f.is_revenue
FROM {GOLD}.fact_ticket f
JOIN {GOLD}.dim_carrier   c  ON c.carrier_key   = f.carrier_key
JOIN {GOLD}.dim_passenger p  ON p.passenger_key = f.passenger_key
JOIN {GOLD}.dim_flight    fl ON fl.flight_key   = f.flight_key
JOIN {GOLD}.dim_cabin     cb ON cb.cabin_key    = f.cabin_key
"""
SQL_SOURCE_TICKETS = f"""
SELECT CONCAT('mainline:', TRIM(ticket_id)) AS ticket_nk FROM {BRONZE}.mainline_ticket
UNION ALL
SELECT CONCAT('regional:', TRIM(fare_line_id)) AS ticket_nk FROM {BRONZE}.regional_fare_line
"""
SQL_TICKET_RULES = f"""
SELECT step, rows_removed, note FROM {AUDIT}
WHERE table_name = 'stg_ticket' AND rows_removed > 0 AND run_id = (SELECT MAX(run_id) FROM {AUDIT})
"""
SQL_ON_TIME = f"""
SELECT year_month, carrier_name, departed_flights, on_time_flights, on_time_pct,
       avg_delay_min, cancelled_flights, delay_not_reported
FROM {GOLD}.v_on_time_by_carrier_month ORDER BY year_month, carrier_name
"""
SQL_VOLUME = f"""
SELECT year_month, carrier_code, carrier_name, tickets, revenue_bhd
FROM {GOLD}.v_ticket_volume_by_carrier_month ORDER BY year_month, carrier_code
"""
SQL_REVENUE = f"""
SELECT carrier_name, route, cabin_name, cabin_rank, tickets, revenue_bhd, avg_fare_bhd
FROM {GOLD}.v_revenue_by_route_cabin ORDER BY revenue_bhd DESC
"""
SQL_TOP = f"""
SELECT full_name, source_systems, country_name, loyalty_tier, trips, flights_flown, airlines_used, revenue_bhd
FROM {GOLD}.v_top_passengers ORDER BY trips DESC, revenue_bhd DESC LIMIT 10
"""
SQL_FARE = f"""
SELECT carrier_name, fare_check, tickets, fare_bhd, expected_fare_bhd, variance_bhd
FROM {GOLD}.v_fare_reconciliation ORDER BY carrier_name, fare_check
"""


@st.cache_data(ttl=600, show_spinner="Reading the Databricks warehouse…")
def load(statement: str) -> pd.DataFrame:
    """Cached for 10 minutes; Sync now clears it so the page shows the new data at once."""
    return dbx.query_df(statement)


@st.cache_data(ttl=30, show_spinner=False)
def job_status() -> dict:
    out: dict = {}
    try:
        out["last"] = dbx.last_finished_run()
        out["schedule"] = dbx.job_schedule()
    except dbx.DatabricksError as exc:
        out["error"] = str(exc)
    return out


load_errors: list[str] = []


def fetch(statement: str) -> pd.DataFrame | None:
    try:
        return load(statement)
    except dbx.DatabricksError as exc:
        load_errors.append(str(exc))
        return None


def take_snapshot() -> dict:
    """Uncached read of everything the before/after comparison needs."""
    return {"overview": dbx.query_df(SQL_OVERVIEW).iloc[0].to_dict(),
            "tickets": dbx.query_df(SQL_TICKETS),
            "source": dbx.query_df(SQL_SOURCE_TICKETS),      # ticket ids in bronze (raw source copy)
            "rules": dbx.query_df(SQL_TICKET_RULES),          # what the cleansing removed in that run
            "on_time": dbx.query_df(SQL_ON_TIME),
            "at": dt.datetime.now(dbx.BAHRAIN)}


RULE_WHY = {
    "double": "Double booking: this passenger already holds a live seat on the same flight. Duplicate passenger "
              "records (and both airlines) are merged into one person, and the earliest booking is kept.",
    "duplicate": "Exact copy of another source row.",
    "without booking": "Points to a booking or flight that does not exist.",
}


def stopped_by_rules(before: dict, after: dict) -> pd.DataFrame:
    """New tickets that reached bronze in this sync but were removed by a cleansing rule, with the reason."""
    if "source" not in before or "source" not in after:
        return pd.DataFrame()
    arrived = set(after["source"]["ticket_nk"]) - set(before["source"]["ticket_nk"])
    stopped = sorted(arrived - set(after["tickets"]["ticket_nk"]))
    rows = []
    for nk in stopped:
        rule, why = "removed during cleansing", "See workspace.airline_staging.etl_audit for this run."
        for r in after["rules"].itertuples():
            if re.search(rf"\b{re.escape(nk)}\b", str(r.note)):
                rule = re.sub(r"^\d+\s+", "", str(r.step))
                why = next((v for k, v in RULE_WHY.items() if k in rule), str(r.note))
                break
        rows.append({"ticket": nk, "rule": rule, "why": why})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------
# Formatting helpers
# ------------------------------------------------------------------------------------------
def _missing(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v))


def n0(v) -> str:
    return "—" if _missing(v) else f"{float(v):,.0f}"


def pct(v) -> str:
    return "—" if _missing(v) else f"{float(v):.1f}%"


def when(ts: dt.datetime | None) -> str:
    return ts.strftime("%d %b %Y, %H:%M") if ts else "—"


def duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    m, s = divmod(int(round(seconds)), 60)
    return f"{m} min {s:02d} s" if m else f"{s} s"


def delta_text(before, after, unit: str = "", decimals: int = 0) -> str:
    if _missing(before) or _missing(after):
        return ""
    d = round(float(after) - float(before), decimals)
    if d == 0:
        return "±0"
    sign = "+" if d > 0 else "−"
    return f"{sign}{abs(d):,.{decimals}f}{unit}"


def with_months(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Adds month_label ('Sep 2026') and returns the labels in calendar order."""
    df = df.copy()
    df["month_label"] = pd.to_datetime(df["year_month"].astype(str) + "-01").dt.strftime("%b %Y")
    order = list(dict.fromkeys(df.sort_values("year_month")["month_label"]))
    return df, order


TRIGGERS = {"ONE_TIME": "Run now / Sync now", "PERIODIC": "Nightly schedule", "RETRY": "Automatic retry"}
RESULT_TEXT = {"SUCCESS": "✅ Succeeded", "FAILED": "❌ Failed", "CANCELED": "⏹️ Cancelled",
               "TIMEDOUT": "⌛ Timed out", "SUCCESS_WITH_FAILURES": "⚠️ Partly failed"}


# ------------------------------------------------------------------------------------------
# Charts (Altair; colours follow the airline, never the rank)
# ------------------------------------------------------------------------------------------
def on_time_chart(df: pd.DataFrame, height: int = 300) -> alt.Chart:
    df, order = with_months(df)
    return alt.Chart(df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4,
                                  stroke=CHART_BG, strokeWidth=2).encode(
        x=alt.X("month_label:N", sort=order, title=None,
                axis=alt.Axis(labelAngle=0), scale=alt.Scale(paddingInner=0.3)),
        xOffset=alt.XOffset("carrier_name:N", sort=CARRIER_ORDER),
        y=alt.Y("on_time_pct:Q", title="On time (%)", scale=alt.Scale(domain=[0, 100])),
        color=alt.Color("carrier_name:N", title=None,
                        scale=alt.Scale(domain=CARRIER_ORDER, range=CARRIER_RANGE),
                        legend=alt.Legend(orient="top")),
        tooltip=[alt.Tooltip("month_label:N", title="Month"),
                 alt.Tooltip("carrier_name:N", title="Airline"),
                 alt.Tooltip("on_time_pct:Q", title="On time %", format=".1f"),
                 alt.Tooltip("on_time_flights:Q", title="On-time flights"),
                 alt.Tooltip("departed_flights:Q", title="Departed flights"),
                 alt.Tooltip("avg_delay_min:Q", title="Avg delay (min)", format=".1f"),
                 alt.Tooltip("cancelled_flights:Q", title="Cancelled")],
    ).properties(height=height)


def volume_chart(df: pd.DataFrame, codes: list[str]) -> alt.Chart:
    df, order = with_months(df[df["carrier_code"].isin(codes)])
    df["stack_order"] = df["carrier_code"].map({"DM": 0, "PX": 1})
    x = alt.X("month_label:N", sort=order, title=None, axis=alt.Axis(labelAngle=0),
              scale=alt.Scale(paddingInner=0.35))
    tooltip = [alt.Tooltip("month_label:N", title="Month"), alt.Tooltip("carrier_name:N", title="Airline"),
               alt.Tooltip("tickets:Q", title="Tickets"),
               alt.Tooltip("revenue_bhd:Q", title="Revenue (BHD)", format=",.3f")]
    bars = alt.Chart(df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4,
                                  stroke=CHART_BG, strokeWidth=2).encode(
        x=x, y=alt.Y("tickets:Q", title="Revenue tickets"),
        color=alt.Color("carrier_name:N", title=None,
                        scale=alt.Scale(domain=CARRIER_ORDER, range=CARRIER_RANGE),
                        legend=alt.Legend(orient="top") if len(codes) > 1 else None),
        order=alt.Order("stack_order:Q"), tooltip=tooltip)
    totals = df.groupby("month_label", as_index=False)["tickets"].sum()
    labels = alt.Chart(totals).mark_text(dy=-9, fontSize=12, fontWeight=600, color=ui.TEXT).encode(
        x=alt.X("month_label:N", sort=order), y=alt.Y("tickets:Q"), text=alt.Text("tickets:Q"))
    return alt.layer(bars, labels).properties(height=320)


def before_after_chart(before: pd.DataFrame, after: pd.DataFrame) -> alt.Chart:
    rows = []
    for state, frame in (("Before", before), ("After", after)):
        counts = frame.groupby("carrier_name").size()
        rows += [{"carrier_name": c, "state": state, "tickets": int(counts.get(c, 0))} for c in CARRIER_ORDER]
    data = pd.DataFrame(rows)
    return alt.Chart(data).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4,
                                    stroke=CHART_BG, strokeWidth=2).encode(
        x=alt.X("carrier_name:N", sort=CARRIER_ORDER, title=None, axis=alt.Axis(labelAngle=0),
                scale=alt.Scale(paddingInner=0.4)),
        xOffset=alt.XOffset("state:N", sort=["Before", "After"]),
        y=alt.Y("tickets:Q", title="Rows in fact_ticket"),
        color=alt.Color("state:N", title=None,
                        scale=alt.Scale(domain=["Before", "After"], range=[ui.BEFORE, ui.AFTER]),
                        legend=alt.Legend(orient="top")),
        tooltip=[alt.Tooltip("carrier_name:N", title="Airline"), alt.Tooltip("state:N", title="When"),
                 alt.Tooltip("tickets:Q", title="Tickets")],
    ).properties(height=260)


def revenue_chart(rev: pd.DataFrame) -> alt.Chart:
    top = (rev.groupby(["carrier_name", "route"], as_index=False)
              .agg(revenue_bhd=("revenue_bhd", "sum"), tickets=("tickets", "sum"))
              .sort_values("revenue_bhd", ascending=False).head(10))
    top["label"] = top["route"] + "  ·  " + top["carrier_name"].map({"Mainline carrier": "DM", "Regional partner": "PX"})
    return alt.Chart(top).mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4).encode(
        y=alt.Y("label:N", sort="-x", title=None, scale=alt.Scale(paddingInner=0.35)),
        x=alt.X("revenue_bhd:Q", title="Revenue (BHD)"),
        color=alt.Color("carrier_name:N", title=None,
                        scale=alt.Scale(domain=CARRIER_ORDER, range=CARRIER_RANGE),
                        legend=alt.Legend(orient="top")),
        tooltip=[alt.Tooltip("route:N", title="Route"), alt.Tooltip("carrier_name:N", title="Airline"),
                 alt.Tooltip("tickets:Q", title="Tickets"),
                 alt.Tooltip("revenue_bhd:Q", title="Revenue (BHD)", format=",.3f")],
    ).properties(height=max(220, 34 * len(top)))


# ------------------------------------------------------------------------------------------
# Sync progress + before/after result
# ------------------------------------------------------------------------------------------
def progress_markdown(info: dbx.RunInfo) -> str:
    lines = [f"**Run {info.run_id}** · {info.life_cycle.lower()} · {duration(info.seconds)} elapsed"
             + (f" · [open in Databricks]({info.url})" if info.url else "")]
    if not info.tasks:
        lines.append("⏳ Queued - waiting for serverless compute to start")
    for t in info.tasks:
        if t.life_cycle == "RUNNING":
            icon, text = "🔄", f"running · {duration(t.seconds)}"
        elif t.life_cycle in dbx.TERMINAL_STATES and t.result == "SUCCESS":
            icon, text = "✅", f"done in {duration(t.seconds)}"
        elif t.result in ("FAILED", "TIMEDOUT", "CANCELED"):
            icon, text = "❌", t.result.lower()
        elif t.result in ("UPSTREAM_FAILED", "UPSTREAM_CANCELED", "EXCLUDED") or t.life_cycle == "SKIPPED":
            icon, text = "⏭️", "skipped"
        else:
            icon, text = "⏳", "waiting"
        lines.append(f"{icon} **{t.key}** — {text}")
    return "  \n".join(lines)


def run_pending_sync(pending: dict, area) -> None:
    """Follows the Databricks run live, then stores the before/after result (or the error) and
    reloads the page, so every chart and KPI is redrawn from the refreshed warehouse."""
    with area, st.status(f"Syncing — Databricks run {pending['run_id']}", expanded=True) as status:
        if pending.get("attached"):
            st.write("A refresh was already running, so this follows that run instead of starting a second one.")
        board = st.empty()
        try:
            info = dbx.wait_for_run(pending["run_id"], on_update=lambda i: board.markdown(progress_markdown(i)))
            if not info.succeeded:
                raise dbx.DatabricksError(
                    f"The Databricks run ended with {info.result or info.life_cycle}. {info.message} "
                    f"Open the run to see which task failed: {info.url}")
            status.update(label="ETL finished — reading the warehouse again (after)…")
            load.clear()
            job_status.clear()
            after = take_snapshot()
            st.session_state["wh_sync_result"] = {"before": pending.get("before"), "after": after, "run": info}
            status.update(label="Sync complete", state="complete", expanded=False)
        except dbx.DatabricksError as exc:
            st.session_state["wh_sync_error"] = str(exc)
            status.update(label="Sync did not finish", state="error")
        finally:
            st.session_state.pop("wh_sync_pending", None)
    st.rerun()


def render_sync_result(result: dict) -> None:
    before, after, info = result["before"], result["after"], result["run"]
    st.success(f"Sync complete · finished {when(info.ended)} · took {duration(info.seconds)} · "
               f"run {info.run_id}" + (f" · [open in Databricks]({info.url})" if info.url else ""))
    if before is None:
        st.info("The 'before' snapshot could not be taken (the warehouse was busy), so only the new state is shown.")
        before = after
    b_ov, a_ov = before["overview"], after["overview"]
    b_t, a_t = before["tickets"], after["tickets"]

    def by_code(frame: pd.DataFrame, code: str) -> int:
        return int((frame["carrier_code"] == code).sum())

    ui.compare_row([
        ("Source rows (bronze)", n0(b_ov["bronze_rows"]), n0(a_ov["bronze_rows"]),
         delta_text(b_ov["bronze_rows"], a_ov["bronze_rows"])),
        ("Staging bookings", n0(b_ov["stg_bookings"]), n0(a_ov["stg_bookings"]),
         delta_text(b_ov["stg_bookings"], a_ov["stg_bookings"])),
        ("fact_ticket rows", n0(b_ov["fact_rows"]), n0(a_ov["fact_rows"]), delta_text(b_ov["fact_rows"], a_ov["fact_rows"])),
        ("Mainline tickets", n0(by_code(b_t, "DM")), n0(by_code(a_t, "DM")), delta_text(by_code(b_t, "DM"), by_code(a_t, "DM"))),
        ("Regional tickets", n0(by_code(b_t, "PX")), n0(by_code(a_t, "PX")), delta_text(by_code(b_t, "PX"), by_code(a_t, "PX"))),
        ("On-time %", pct(b_ov["on_time_pct"]), pct(a_ov["on_time_pct"]),
         delta_text(b_ov["on_time_pct"], a_ov["on_time_pct"], " pts", 1)),
    ])

    new = a_t[~a_t["ticket_nk"].isin(b_t["ticket_nk"])]
    gone = b_t[~b_t["ticket_nk"].isin(a_t["ticket_nk"])]
    stopped = stopped_by_rules(before, after)
    if len(stopped):
        st.markdown(ui.badge_html(f"{len(stopped)} new source ticket(s) stopped by a data-quality rule", "warn"),
                    unsafe_allow_html=True)
        st.caption("They reached the raw (bronze) copy, so the extract worked - then a cleansing rule in staging "
                   "kept them out of the star schema on purpose:")
        st.dataframe(stopped, hide_index=True, column_config={
            "ticket": "Source ticket", "rule": "Rule (etl_audit step)", "why": st.column_config.TextColumn("Why", width="large")})
    c1, c2 = st.columns([1, 1.25], gap="large")
    with c1, ui.card_container("wh_ba"):
        st.markdown("**Tickets per airline — before vs after**")
        st.altair_chart(before_after_chart(b_t, a_t))
    with c2:
        if len(new):
            st.markdown(f"**{len(new)} new ticket(s) loaded into the warehouse**")
            st.dataframe(new[["ticket_nk", "booking_reference", "carrier_name", "passenger", "flight_number",
                              "route", "flight_date", "cabin_name", "fare_bhd"]],
                         hide_index=True, column_config={
                             "ticket_nk": "Ticket", "booking_reference": "Booking ref", "carrier_name": "Airline",
                             "passenger": "Passenger", "flight_number": "Flight", "route": "Route",
                             "flight_date": "Flight date", "cabin_name": "Cabin",
                             "fare_bhd": st.column_config.NumberColumn("Fare (BHD)", format="%.3f")})
        elif len(stopped):
            st.info("No ticket was added to fact_ticket because the only new one broke a data-quality rule "
                    "(see above). For a +1, book a passenger on a flight they are not already on.")
        else:
            st.info("No new tickets this time - the warehouse already matched Supabase. For a visible change, "
                    "create a booking on page 1 (Simulate new booking) and press Sync now again.")
        if len(gone):
            st.caption(f"{len(gone)} ticket(s) left the warehouse because they no longer exist in the source "
                       "(full reload keeps deletes in step).")

    st.markdown("**On-time performance chart — before vs after**")
    p1, p2 = st.columns(2, gap="large")
    with p1, ui.card_container("wh_before"):
        st.caption(f"Before · read at {when(before['at'])}")
        st.altair_chart(on_time_chart(before["on_time"], height=240))
    with p2, ui.card_container("wh_after"):
        st.caption(f"After · read at {when(after['at'])}")
        st.altair_chart(on_time_chart(after["on_time"], height=240))
    if st.button("Hide sync result", key="wh_hide_result"):
        st.session_state.pop("wh_sync_result", None)
        st.rerun()


# ------------------------------------------------------------------------------------------
# Page
# ------------------------------------------------------------------------------------------
try:
    dbx.settings()
except dbx.DatabricksError as exc:
    ui.hero("Data Warehouse", "Databricks star schema built from both operational schemas.",
            eyebrow="Page 2 · Warehouse · Member 2")
    st.error(str(exc))
    st.stop()

overview = fetch(SQL_OVERVIEW)
ov = overview.iloc[0].to_dict() if overview is not None and len(overview) else {}
status_info = job_status()
last_run: dbx.RunInfo | None = status_info.get("last")
data_as_of = dbx.to_local(ov.get("last_etl_utc"))

ui.hero(
    "Data Warehouse",
    "Both operational schemas (mainline_carrier and regional_partner) cleaned, reconciled and modelled "
    "as one star schema in Databricks. Press Sync now to re-run the whole pipeline live.",
    eyebrow="Page 2 · Warehouse · Member 2",
    gold_chip="Flow 1 · PostgreSQL → Databricks",
    chips=["Unity Catalog · workspace.airline_gold", f"Job · {dbx.JOB_NAME}",
           f"Data as of {when(data_as_of)}" if data_as_of else "Data refresh time unknown"],
)

if ov:
    ui.kpi_row([
        ui.Kpi("Tickets in warehouse", n0(ov["fact_rows"]), f"fact_ticket rows · {n0(ov['revenue_tickets'])} earn revenue", "🎫"),
        ui.Kpi("Revenue", n0(ov["revenue_bhd"]), "refunded, void and cancelled excluded", "💰", unit="BHD"),
        ui.Kpi("On-time departures", pct(ov["on_time_pct"]), "left within 15 min of schedule", "⏱️", accent="teal"),
        ui.Kpi("Passengers", n0(ov["passengers"]), f"real people, merged from {n0(ov['passenger_records'])} source records",
               "👥", accent="teal"),
        ui.Kpi("Flights", n0(ov["flights"]), "mainline flights + regional routes", "✈️"),
    ])
    ui.pipeline([
        ("Source", "Supabase PostgreSQL", "mainline_carrier + regional_partner · read-only etl_reader role", "source"),
        ("Bronze", "Raw copy", f"{n0(ov['bronze_tables'])} tables · {n0(ov['bronze_rows'])} rows · text + source_system", "bronze"),
        ("Silver", "Staging", f"cleaned & typed · {n0(ov['stg_bookings'])} bookings · {n0(ov['stg_passengers'])} passengers", "silver"),
        ("Gold", "Star schema", f"fact_ticket ({n0(ov['fact_rows'])} rows) + 5 dimensions", "gold"),
        ("Serve", "This dashboard", "5 analytical views · Sync now · carrier filter", "source"),
    ])
else:
    st.warning("The warehouse tables could not be read just now. If a Sync is running, the gold tables are being "
               "rebuilt - wait about a minute and reload the page.")

# ---------- Sync now ----------
ui.section("Sync now", "Re-runs the Databricks Job airline_etl_flow1 (extract → staging → gold → analytics) through "
           "the Jobs API, then compares the warehouse before and after.", icon="🔄")
pending = st.session_state.get("wh_sync_pending")
left, right = st.columns([1.3, 1], gap="large")
with left:
    ui.note("Demo tip: create a booking on page 1 (Simulate new booking), then press Sync now. "
            "The new ticket appears below with the fact row counts and the charts before and after. "
            "A full run takes about 3 minutes.")
    st.write("")
    clicked = st.button("Sync now", type="primary", icon=":material/sync:", disabled=pending is not None,
                        help="Triggers the Databricks Job through its API and waits for it to finish")
with right:
    if last_run:
        ui.card("Refresh status", [
            ("Last run", f"{when(last_run.started)} · {RESULT_TEXT.get(last_run.result or '', last_run.result or '—')}"),
            ("Duration", duration(last_run.seconds)),
            ("Started by", TRIGGERS.get(last_run.trigger, last_run.trigger or "—")),
            ("Schedule", status_info.get("schedule", "—")),
            ("Strategy", "Full reload - rebuilds bronze, staging and gold"),
        ])
    elif status_info.get("error"):
        st.warning(f"Job status unavailable: {status_info['error']}")
    else:
        ui.card("Refresh status", [("Last run", "No finished run yet"), ("Schedule", status_info.get("schedule", "—"))])

sync_area = st.container()
if clicked and pending is None:
    st.session_state.pop("wh_sync_result", None)
    st.session_state.pop("wh_sync_error", None)
    with sync_area, st.spinner("Reading the warehouse before the sync…"):
        try:
            before_snapshot = take_snapshot()
        except dbx.DatabricksError:
            before_snapshot = None          # tables mid-rebuild by another run: sync anyway
        try:
            running = dbx.active_run()
            run_id = running.run_id if running else dbx.start_sync()
            pending = {"run_id": run_id, "before": before_snapshot, "attached": running is not None}
            st.session_state["wh_sync_pending"] = pending
        except dbx.DatabricksError as exc:
            st.session_state["wh_sync_error"] = str(exc)

if pending is None:
    if st.session_state.get("wh_sync_error"):
        with sync_area:
            st.error(st.session_state["wh_sync_error"])
    elif st.session_state.get("wh_sync_result"):
        with sync_area:
            render_sync_result(st.session_state["wh_sync_result"])

# ---------- On-time performance ----------
ui.section("On-time performance by airline", "Share of departed flights that left within 15 minutes of schedule, "
           "per month (view v_on_time_by_carrier_month, query Q1). Cancelled flights are counted separately.", icon="⏱️")
on_time = fetch(SQL_ON_TIME)
if on_time is not None and len(on_time):
    totals = on_time.groupby("carrier_name").agg(
        on_time=("on_time_flights", "sum"), departed=("departed_flights", "sum"),
        not_reported=("delay_not_reported", "sum"), cancelled=("cancelled_flights", "sum"))
    cards = []
    for name, code in (("Mainline carrier", "DM"), ("Regional partner", "PX")):
        if name in totals.index:
            r = totals.loc[name]
            reported = r["departed"] - r["not_reported"]
            share = 100 * r["on_time"] / reported if reported else None
            cards.append(ui.Kpi(f"{name} ({code})", pct(share),
                                f"{n0(r['on_time'])} of {n0(reported)} departures on time · {n0(r['cancelled'])} cancelled",
                                "🟡" if code == "DM" else "🔵", accent="gold" if code == "DM" else "teal"))
    ui.kpi_row(cards)
    with ui.card_container("wh_ontime"):
        st.altair_chart(on_time_chart(on_time))
    with st.expander("Show the numbers behind the chart"):
        st.dataframe(on_time, hide_index=True, column_config={
            "year_month": "Month", "carrier_name": "Airline", "departed_flights": "Departed",
            "on_time_flights": "On time", "on_time_pct": st.column_config.NumberColumn("On time %", format="%.1f"),
            "avg_delay_min": st.column_config.NumberColumn("Avg delay (min)", format="%.1f"),
            "cancelled_flights": "Cancelled", "delay_not_reported": "Delay not reported"})

# ---------- Carrier filter ----------
ui.section("Ticket volumes · carrier filter", "Revenue tickets per flight month (view v_ticket_volume_by_carrier_month, "
           "query Q4). Refunded, void and cancelled tickets are not counted.", icon="🎫")
volume = fetch(SQL_VOLUME)
if volume is not None and len(volume):
    choice = st.segmented_control("Carrier filter", list(FILTERS), default="Combined", key="wh_carrier") or "Combined"
    codes = FILTERS[choice]
    sel = volume[volume["carrier_code"].isin(codes)]
    if sel.empty:
        st.info("No revenue tickets for this selection yet.")
    else:
        by_month, _ = with_months(sel.groupby("year_month", as_index=False)["tickets"].sum())
        busiest = by_month.sort_values(["tickets", "year_month"], ascending=[False, True]).iloc[0]
        all_tickets = volume["tickets"].sum()
        if len(codes) > 1:
            share_dm = round(100 * volume.loc[volume["carrier_code"] == "DM", "tickets"].sum() / all_tickets)
            share = ui.Kpi("Split", f"{share_dm}% / {100 - share_dm}%", "mainline / regional", "📊", accent="teal")
        else:
            share = ui.Kpi("Share", f"{100 * sel['tickets'].sum() / all_tickets:.0f}%", "of all revenue tickets",
                           "📊", accent="teal")
        ui.kpi_row([
            ui.Kpi("Tickets", n0(sel["tickets"].sum()), choice.lower(), "🎫"),
            ui.Kpi("Revenue", n0(sel["revenue_bhd"].sum()), "from these tickets", "💰", unit="BHD"),
            ui.Kpi("Busiest month", busiest["month_label"], f"{n0(busiest['tickets'])} tickets", "📅", accent="teal"),
            share,
        ])
        with ui.card_container("wh_volume"):
            st.altair_chart(volume_chart(volume, codes))

# ---------- More analytical queries ----------
ui.section("More from the warehouse", "Three more analytical queries on the star schema (Q2, Q3 and Q5).", icon="📊")
tab_rev, tab_top, tab_fare = st.tabs(["💰 Revenue by route & cabin", "🏅 Top passengers", "🧾 Fare reconciliation"])
with tab_rev:
    rev = fetch(SQL_REVENUE)
    if rev is not None and len(rev):
        st.caption("Top 10 routes by revenue (view v_revenue_by_route_cabin). Hover a bar for details.")
        with ui.card_container("wh_revenue"):
            st.altair_chart(revenue_chart(rev))
        with st.expander("Every route and cabin"):
            st.dataframe(rev.drop(columns=["cabin_rank"]), hide_index=True, column_config={
                "carrier_name": "Airline", "route": "Route", "cabin_name": "Cabin", "tickets": "Tickets",
                "revenue_bhd": st.column_config.NumberColumn("Revenue (BHD)", format="%.3f"),
                "avg_fare_bhd": st.column_config.NumberColumn("Avg fare (BHD)", format="%.3f")})
with tab_top:
    top = fetch(SQL_TOP)
    if top is not None and len(top):
        st.caption("Most frequent travellers across BOTH airlines (view v_top_passengers). Possible only because "
                   "passengers from the two schemas were matched and merged into one dim_passenger.")
        st.dataframe(top, hide_index=True, column_config={
            "full_name": "Passenger", "source_systems": "Found in", "country_name": "Country",
            "loyalty_tier": "Loyalty tier",
            "trips": st.column_config.ProgressColumn("Trips", min_value=0, max_value=int(top["trips"].max()), format="%d"),
            "flights_flown": "Flown", "airlines_used": "Airlines used",
            "revenue_bhd": st.column_config.NumberColumn("Revenue (BHD)", format="%.3f")})
with tab_fare:
    fare = fetch(SQL_FARE)
    if fare is not None and len(fare):
        ok = int(fare.loc[fare["fare_check"] == "OK", "tickets"].sum())
        st.caption(f"{ok} of {int(fare['tickets'].sum())} fares match the shared fare model "
                   "(route base fare × cabin multiplier) - view v_fare_reconciliation.")
        st.markdown(" ".join([
            ui.badge_html("OK - matches the model", "good"),
            ui.badge_html("DRIFT - regional fare off by more than 0.5%", "warn"),
            ui.badge_html("OUT_OF_BAND - mainline fare outside 0.90-1.15 × model", "bad"),
            ui.badge_html("IMPUTED - missing fare rebuilt from the model", "info"),
        ]), unsafe_allow_html=True)
        st.write("")
        st.dataframe(fare, hide_index=True, column_config={
            "carrier_name": "Airline", "fare_check": "Check", "tickets": "Tickets",
            "fare_bhd": st.column_config.NumberColumn("Fares (BHD)", format="%.3f"),
            "expected_fare_bhd": st.column_config.NumberColumn("Model fares (BHD)", format="%.3f"),
            "variance_bhd": st.column_config.NumberColumn("Difference (BHD)", format="%.3f")})

# ---------- How it is built ----------
with st.expander("How this warehouse is built - grain, tables and refresh strategy"):
    a, b = st.columns(2, gap="large")
    with a:
        ui.card("Star schema", [
            ("Grain", "fact_ticket: one row per ticket = one passenger seat on one flight segment"),
            ("fact_ticket", f"{n0(ov.get('fact_rows'))} rows"),
            ("dim_passenger", f"{n0(ov.get('passengers'))} rows (both schemas merged)"),
            ("dim_flight", f"{n0(ov.get('flights'))} rows (airports folded in)"),
            ("dim_date", f"{n0(ov.get('calendar_days'))} rows (Bahrain weekend Fri-Sat)"),
            ("dim_carrier", f"{n0(ov.get('carriers'))} rows (DM mainline, PX regional)"),
            ("dim_cabin", f"{n0(ov.get('cabins'))} rows (Economy → First + Unknown)"),
        ])
    with b:
        ui.card("Refresh strategy", [
            ("On demand", "Sync now → Jobs API run-now → full reload of all layers"),
            ("Scheduled", status_info.get("schedule", "—")),
            ("Why full reload", "small source (hundreds of rows); keeps deletes and late fixes in step"),
            ("Safety", "Supabase is read with a read-only role inside a read-only transaction"),
            ("Code", "databricks/01_extract_bronze → 02_staging → 03_gold → 04_analytical_queries"),
        ])

if load_errors:
    with st.expander("⚠️ Some warehouse data could not be loaded (details)"):
        for err in dict.fromkeys(load_errors):
            st.code(err, language=None)

ui.footer()

# Follow a running sync last, so the whole page is already on screen while it runs.
if pending is not None:
    run_pending_sync(pending, sync_area)
