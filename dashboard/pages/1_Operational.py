"""
Page 1 - Operational database (PostgreSQL, both schemas)      Owner:(Abrar)

Brief requirements covered on this page
  * View into the operational database - BOTH schemas
  * Interactive element: two-schema comparison toggle
  * Interactive element: "simulate new booking" (writes to either schema;
    gives Member 2's Sync now button a visible before/after change)
"""
from __future__ import annotations

import random
import string
import time

import pandas as pd
import streamlit as st

from pg_utils import get_pg_conn, query_df, scalar

st.set_page_config(page_title="Operational DB", page_icon="✈️", layout="wide")
st.title("✈️ Operational database — PostgreSQL")
st.caption("Live view of the two structurally different operational schemas on Supabase: "
           "`mainline_carrier` (normalised) and `regional_partner` (denormalised).")

SCHEMA_TABLES = {
    "mainline_carrier": ["passenger", "flight", "booking", "ticket", "airport", "cabin_class"],
    "regional_partner": ["traveler", "route", "reservation", "fare_line"],
}
# Equivalent entities (used by the comparison view and by Member 2's reconciliation)
ENTITY_MAP = pd.DataFrame([
    ("Customer", "passenger", "traveler", "first_name + last_name vs one full_name; SERIAL vs text key 'TRV-0001'"),
    ("Flight",   "flight (+ airport)", "route", "airport-code FKs vs city names; actual times vs delay_minutes"),
    ("Booking",  "booking", "reservation", "SERIAL vs BIGINT key; class lives on ticket vs one travel_class text"),
    ("Ticket",   "ticket", "fare_line", "fare_paid from flight x cabin vs fare_amount copied from route"),
    ("Cabin",    "cabin_class", "— (none)", "lookup table vs free text 'Economy', 'ECONOMY', 'econ' ..."),
], columns=["Entity", "mainline_carrier", "regional_partner", "Structural difference"])


def to_float(df: pd.DataFrame) -> pd.DataFrame:
    """psycopg returns NUMERIC as Decimal; charts need float."""
    for c in df.columns:
        if df[c].dtype == object and len(df) and df[c].map(lambda v: v.__class__.__name__ == "Decimal").any():
            df[c] = df[c].astype(float)
    return df


def table_counts(schema: str) -> dict:
    return {t: scalar(f"SELECT count(*) FROM {schema}.{t}") for t in SCHEMA_TABLES[schema]}


# ---------------------------------------------------------------------------------------------
# Two-schema comparison toggle
# ---------------------------------------------------------------------------------------------
view = st.radio("Schema view", ["Mainline carrier", "Regional partner", "Compare both schemas"],
                horizontal=True, key="schema_view")

if view in ("Mainline carrier", "Regional partner"):
    schema = "mainline_carrier" if view == "Mainline carrier" else "regional_partner"
    counts = table_counts(schema)
    cols = st.columns(len(counts))
    for col, (t, n) in zip(cols, counts.items()):
        col.metric(t, n)

    tab_browse, tab_perf, tab_query = st.tabs(["Browse tables", "On-time performance", "Business query"])

    with tab_browse:
        c1, c2 = st.columns([1, 3])
        table = c1.selectbox("Table", SCHEMA_TABLES[schema], key=f"tbl_{schema}")
        limit = c1.slider("Rows", 10, 200, 50, step=10, key=f"lim_{schema}")
        structure = query_df("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position""", (schema, table))
        c1.dataframe(structure, hide_index=True, width="stretch", height=300)
        # table name comes from a fixed whitelist above, so the f-string is safe
        c2.dataframe(query_df(f"SELECT * FROM {schema}.{table} ORDER BY 1 DESC LIMIT %s", (limit,)),
                     hide_index=True, width="stretch", height=420)

    with tab_perf:
        if schema == "mainline_carrier":
            perf = to_float(query_df("SELECT * FROM mainline_carrier.v_on_time_performance_by_route ORDER BY route"))
            st.markdown("**View `mainline_carrier.v_on_time_performance_by_route`** — flight + airport + "
                        "ticket join, on time = departed ≤ 15 min late.")
            label = "route"
        else:
            perf = to_float(query_df("SELECT * FROM regional_partner.v_route_performance ORDER BY route_name"))
            st.markdown("**View `regional_partner.v_route_performance`** — same question on the denormalised "
                        "schema: no actual times, only `delay_minutes`, and messy city names cleaned on the fly.")
            label = "route_name"
        if not perf.empty:
            k1, k2, k3 = st.columns(3)
            k1.metric("Flights flown", int(perf["flights_flown"].sum()))
            k2.metric("On-time %", f"{100 * perf['on_time_flights'].sum() / max(perf['flights_flown'].sum(), 1):.1f}%")
            k3.metric("Avg delay (min)", f"{perf['avg_delay_min'].mean():.1f}")
            st.bar_chart(perf.set_index(label)["on_time_pct"], y_label="On-time %")
            st.dataframe(perf, hide_index=True, width="stretch")

    with tab_query:
        if schema == "mainline_carrier":
            st.markdown("**Recent bookings** — a 5-table join (booking → passenger, ticket → flight, cabin_class) "
                        "using the foreign keys of the normalised schema.")
            st.dataframe(query_df("""
                SELECT b.booking_reference, b.booking_status, b.booking_date,
                       p.first_name || ' ' || p.last_name AS passenger,
                       f.flight_number, f.origin_code || ' -> ' || f.destination_code AS route,
                       c.cabin_name, t.seat_number, t.fare_paid
                FROM mainline_carrier.booking b
                JOIN mainline_carrier.passenger   p ON p.passenger_id   = b.passenger_id
                JOIN mainline_carrier.ticket      t ON t.booking_id     = b.booking_id
                JOIN mainline_carrier.flight      f ON f.flight_id      = t.flight_id
                JOIN mainline_carrier.cabin_class c ON c.cabin_class_id = t.cabin_class_id
                ORDER BY b.booking_id DESC
                LIMIT 50"""), hide_index=True, width="stretch")
        else:
            st.markdown("**Revenue per cabin** — view `regional_partner.v_revenue_per_cabin`: `travel_class` is free "
                        "text, so it is normalised with `CASE`; USD lines are converted to BHD.")
            rev = to_float(query_df("SELECT * FROM regional_partner.v_revenue_per_cabin ORDER BY revenue_bhd DESC"))
            st.bar_chart(rev.set_index("cabin")["revenue_bhd"], y_label="Revenue (BHD)")
            st.dataframe(rev, hide_index=True, width="stretch")

else:
    # ------------------------------------------------------------------ comparison mode
    st.subheader("Same business, two different designs")
    st.dataframe(ENTITY_MAP, hide_index=True, width="stretch")

    m, r = table_counts("mainline_carrier"), table_counts("regional_partner")
    c1, c2 = st.columns(2)
    c1.markdown("**mainline_carrier** — 6 tables, 3NF")
    c1.dataframe(pd.DataFrame(m.items(), columns=["table", "rows"]), hide_index=True, width="stretch")
    c2.markdown("**regional_partner** — 4 tables, denormalised")
    c2.dataframe(pd.DataFrame(r.items(), columns=["table", "rows"]), hide_index=True, width="stretch")

    pair = st.selectbox("Compare the columns of an equivalent table pair",
                        ["passenger ↔ traveler", "flight ↔ route", "booking ↔ reservation", "ticket ↔ fare_line"])
    left, right = [p.strip() for p in pair.split("↔")]
    struct_sql = """SELECT column_name, data_type FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position"""
    s1, s2 = st.columns(2)
    s1.dataframe(query_df(struct_sql, ("mainline_carrier", left)), hide_index=True, width="stretch")
    s2.dataframe(query_df(struct_sql, ("regional_partner", right)), hide_index=True, width="stretch")

    st.subheader("Monthly ticket volume — mainline vs regional")
    vol = query_df("""
        SELECT month, carrier, count(*) AS tickets FROM (
          SELECT date_trunc('month', f.scheduled_departure)::date AS month, 'Mainline' AS carrier
          FROM mainline_carrier.ticket t JOIN mainline_carrier.flight f USING (flight_id)
          WHERE t.ticket_status <> 'REFUNDED'
          UNION ALL
          SELECT date_trunc('month', r.departure_date)::date, 'Regional'
          FROM regional_partner.fare_line fl JOIN regional_partner.route r USING (route_id)
          WHERE lower(coalesce(fl.line_status,'')) <> 'void') x
        GROUP BY 1, 2 ORDER BY 1""")
    if not vol.empty:
        st.bar_chart(vol.pivot(index="month", columns="carrier", values="tickets").fillna(0), stack=False)

    st.subheader("Customers who exist in both schemas")
    st.caption("Matched on lower(email) — these duplicates are merged into one dim_passenger row by the ETL.")
    st.dataframe(query_df("""
        SELECT p.passenger_id, p.first_name || ' ' || p.last_name AS mainline_name,
               t.traveler_code, t.full_name AS regional_name, lower(p.email) AS matched_email
        FROM mainline_carrier.passenger p
        JOIN regional_partner.traveler t ON lower(t.email_address) = lower(p.email)
        ORDER BY p.passenger_id"""), hide_index=True, width="stretch")

# ---------------------------------------------------------------------------------------------
# Simulate new booking (writes to either schema)
# ---------------------------------------------------------------------------------------------
st.divider()
st.header("🧾 Simulate a new booking")
st.caption("Inserts a real booking in one transaction. Afterwards press **Sync now** on the Warehouse page "
           "to see it arrive in Databricks (before/after).")

target = st.radio("Write to", ["mainline_carrier", "regional_partner"], horizontal=True, key="sim_target")


def new_pnr() -> str:
    return "".join(random.choices("ABCDEFGHJKLMNPQRSTUVWXYZ23456789", k=6))


def free_seat(flight_id: int, cabin_id: int) -> str:
    taken = set(query_df("SELECT seat_number FROM mainline_carrier.ticket WHERE flight_id = %s",
                         (flight_id,))["seat_number"].dropna()) if flight_id else set()
    rows = range(1, 10) if cabin_id >= 3 else range(10, 39)
    for row in rows:
        for letter in "ACDF" if cabin_id >= 3 else "ABCDEF":
            if f"{row}{letter}" not in taken:
                return f"{row}{letter}"
    return None


if target == "mainline_carrier":
    pax = query_df("SELECT passenger_id, first_name || ' ' || last_name || ' (#' || passenger_id || ')' AS label "
                   "FROM mainline_carrier.passenger ORDER BY first_name, last_name")
    flights = query_df("""
        SELECT f.flight_id, f.base_fare,
               f.flight_number || '  ' || f.origin_code || '→' || f.destination_code || '  ' ||
               to_char(f.scheduled_departure, 'DD Mon HH24:MI') AS label
        FROM mainline_carrier.flight f
        WHERE f.flight_status = 'SCHEDULED' AND f.scheduled_departure > now()
        ORDER BY f.scheduled_departure""")
    cabins = query_df("SELECT cabin_class_id, cabin_name, fare_multiplier FROM mainline_carrier.cabin_class ORDER BY 1")

    if flights.empty:
        st.warning("No future SCHEDULED flights left in mainline_carrier.flight — add one to simulate bookings.")
    else:
        with st.form("mainline_booking"):
            c1, c2, c3 = st.columns(3)
            p_label = c1.selectbox("Passenger", pax["label"])
            f_label = c2.selectbox("Flight", flights["label"])
            c_label = c3.selectbox("Cabin", cabins["cabin_name"])
            channel = c1.selectbox("Channel", ["WEB", "APP", "AGENT"])
            payment = c2.selectbox("Payment", ["CARD", "BENEFITPAY", "APPLE_PAY", "MILES"])
            submitted = st.form_submit_button("Create booking", type="primary")

        if submitted:
            pid = int(pax.loc[pax["label"] == p_label, "passenger_id"].iloc[0])
            fl = flights.loc[flights["label"] == f_label].iloc[0]
            cab = cabins.loc[cabins["cabin_name"] == c_label].iloc[0]
            fare = round(float(fl["base_fare"]) * float(cab["fare_multiplier"]), 3)
            seat = free_seat(int(fl["flight_id"]), int(cab["cabin_class_id"]))
            before = table_counts("mainline_carrier")
            conn = get_pg_conn()
            with conn.transaction():          # booking + ticket succeed or fail together
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO mainline_carrier.booking
                              (booking_reference, passenger_id, booking_channel, payment_method, booking_status)
                        VALUES (%s, %s, %s, %s, 'CONFIRMED') RETURNING booking_id, booking_reference""",
                                (new_pnr(), pid, channel, payment))
                    booking_id, ref = cur.fetchone()
                    cur.execute("""
                        INSERT INTO mainline_carrier.ticket
                              (ticket_number, booking_id, flight_id, cabin_class_id, seat_number, fare_paid)
                        VALUES (%s, %s, %s, %s, %s, %s) RETURNING ticket_id""",
                                ("607-" + str(int(time.time() * 1000))[-10:], booking_id, int(fl["flight_id"]),
                                 int(cab["cabin_class_id"]), seat, fare))
            after = table_counts("mainline_carrier")
            st.session_state["last_booking"] = {
                "schema": "mainline_carrier", "ref": ref, "before": before, "after": after,
                "rows": query_df("""SELECT b.booking_reference, b.booking_status, p.first_name || ' ' || p.last_name AS passenger,
                                           f.flight_number, t.seat_number, t.fare_paid, b.booking_date
                                    FROM mainline_carrier.booking b
                                    JOIN mainline_carrier.passenger p USING (passenger_id)
                                    JOIN mainline_carrier.ticket t USING (booking_id)
                                    JOIN mainline_carrier.flight f USING (flight_id)
                                    WHERE b.booking_id = %s""", (booking_id,))}

else:
    travelers = query_df("SELECT traveler_code, full_name || ' (' || traveler_code || ')' AS label "
                         "FROM regional_partner.traveler ORDER BY full_name")
    routes = query_df("""
        SELECT route_id, fare_amount,
               route_code || '  ' || origin_city || '→' || destination_city || '  ' ||
               to_char(departure_date, 'DD Mon') || ' ' || to_char(departure_time, 'HH24:MI') AS label
        FROM regional_partner.route
        WHERE departure_date >= CURRENT_DATE
        ORDER BY departure_date, departure_time""")
    if routes.empty:
        st.warning("No future routes in regional_partner.route — add one to simulate reservations.")
    else:
        with st.form("regional_booking"):
            c1, c2, c3 = st.columns(3)
            t_label = c1.selectbox("Traveler", travelers["label"])
            r_label = c2.selectbox("Route", routes["label"])
            t_class = c3.selectbox("travel_class (free text)", ["Economy", "Premium Economy", "Business"])
            channel = c1.selectbox("Sales channel", ["Website", "Mobile", "Call Centre", "Travel Agent"])
            submitted = st.form_submit_button("Create reservation", type="primary")

        if submitted:
            tcode = travelers.loc[travelers["label"] == t_label, "traveler_code"].iloc[0]
            rt = routes.loc[routes["label"] == r_label].iloc[0]
            mult = {"Economy": 1.0, "Premium Economy": 1.45, "Business": 2.6}[t_class]
            fare = round(float(rt["fare_amount"]) * mult, 3)   # DENORMALISED copy of the route fare
            before = table_counts("regional_partner")
            conn = get_pg_conn()
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO regional_partner.reservation
                              (reservation_no, pnr, traveler_code, travel_class, reservation_status, sales_channel)
                        SELECT coalesce(max(reservation_no), 900000000) + 1, %s, %s, %s, 'Confirmed', %s
                        FROM regional_partner.reservation
                        RETURNING reservation_no, pnr""", (new_pnr(), tcode, t_class, channel))
                    res_no, ref = cur.fetchone()
                    cur.execute("""
                        INSERT INTO regional_partner.fare_line
                              (reservation_no, route_id, fare_amount, tax_amount, currency, line_status)
                        VALUES (%s, %s, %s, %s, 'BHD', 'active')""",
                                (res_no, int(rt["route_id"]), fare, round(fare * 0.1, 3)))
            after = table_counts("regional_partner")
            st.session_state["last_booking"] = {
                "schema": "regional_partner", "ref": ref, "before": before, "after": after,
                "rows": query_df("""SELECT r.reservation_no, r.pnr, t.full_name, r.travel_class, rt.route_code,
                                           f.fare_amount, f.currency, r.reserved_at
                                    FROM regional_partner.reservation r
                                    JOIN regional_partner.traveler t USING (traveler_code)
                                    JOIN regional_partner.fare_line f USING (reservation_no)
                                    JOIN regional_partner.route rt USING (route_id)
                                    WHERE r.reservation_no = %s""", (res_no,))}

last = st.session_state.get("last_booking")
if last:
    st.success(f"Booking **{last['ref']}** written to `{last['schema']}`.")
    ba = pd.DataFrame({"before": last["before"], "after": last["after"]})
    ba["change"] = ba["after"] - ba["before"]
    c1, c2 = st.columns([1, 2])
    c1.markdown("**Row counts before / after**")
    c1.dataframe(ba, width="stretch")
    c2.markdown("**New row(s)**")
    c2.dataframe(last["rows"], hide_index=True, width="stretch")