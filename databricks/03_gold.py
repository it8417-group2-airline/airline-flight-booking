# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · Staging → Star schema  (Flow 1, step 3 of 3)
# MAGIC **Owner:** Fatema Alashiri (Member 2)
# MAGIC
# MAGIC Builds the analytical **star schema** in `workspace.airline_gold`:
# MAGIC
# MAGIC | Table | Grain / meaning | Merged from |
# MAGIC |---|---|---|
# MAGIC | **`fact_ticket`** | **one row per ticket = one passenger seat on one flight segment** | mainline `ticket` + regional `fare_line` |
# MAGIC | `dim_passenger` | one row per real person | `passenger` + `traveler` (duplicates merged) |
# MAGIC | `dim_flight` | one row per flight, airports folded in | `flight` + `route` + `airport` |
# MAGIC | `dim_date` | one row per calendar day | generated (Bahrain weekend = Fri + Sat) |
# MAGIC | `dim_carrier` | one row per airline | mainline / regional partner |
# MAGIC | `dim_cabin` | one row per cabin | mainline `cabin_class` + regional `travel_class` text |
# MAGIC
# MAGIC Booking attributes (reference, status, channel, payment) are kept on the fact as
# MAGIC **degenerate dimensions**, because a booking has no attributes of its own worth a dimension.
# MAGIC Primary and foreign keys are declared (informational in Unity Catalog), so Catalog Explorer
# MAGIC can draw the warehouse ERD. Every run rebuilds the tables (full reload, see refresh strategy).

# COMMAND ----------

# MAGIC %run ./_etl_common

# COMMAND ----------

run_id = current_run_id()
audit = Audit(run_id, "gold")
today = dt.date.today()

S = {name: read_table(f"{STAGING}.{name}") for name in
     ["stg_airport", "stg_cabin", "stg_passenger", "stg_flight", "stg_booking", "stg_ticket"]}
for name, frame in S.items():
    print(f"staging {name:<14} {len(frame):>4} rows")


def none_if_missing(value):
    return None if value is None or (not isinstance(value, str) and pd.isna(value)) else value


def as_date(value):
    value = none_if_missing(value)
    if value is None:
        return None
    return value.date() if isinstance(value, (dt.datetime, pd.Timestamp)) else value


def date_key(value):
    d = as_date(value)
    return int(d.strftime("%Y%m%d")) if d else None

# COMMAND ----------

# MAGIC %md
# MAGIC ## Dimensions

# COMMAND ----------

# ---- dim_carrier ---------------------------------------------------------------------
dim_carrier = pd.DataFrame([
    {"carrier_key": i, "carrier_code": code, "carrier_name": name, "carrier_type": kind, "source_system": system}
    for i, (system, (code, name, kind)) in enumerate(CARRIERS.items(), start=1)])
CARRIER_KEY = dict(zip(dim_carrier["carrier_code"], dim_carrier["carrier_key"]))
CARRIER_NAME = dict(zip(dim_carrier["carrier_code"], dim_carrier["carrier_name"]))

# ---- dim_cabin (+ an 'Unknown' member so no ticket is lost) -----------------------------
cabin_rows = [{"cabin_key": 0, "cabin_code": "U", "cabin_name": "Unknown", "fare_multiplier": None, "cabin_rank": 0}]
order = {"Y": 1, "W": 2, "J": 3, "F": 4}
for i, c in enumerate(sorted(S["stg_cabin"].to_dict("records"), key=lambda c: order.get(c["cabin_code"], 9)), start=1):
    cabin_rows.append({"cabin_key": i, "cabin_code": c["cabin_code"], "cabin_name": c["cabin_name"],
                       "fare_multiplier": none_if_missing(c["fare_multiplier"]), "cabin_rank": order.get(c["cabin_code"], 9)})
dim_cabin = pd.DataFrame(cabin_rows)
CABIN_KEY = dict(zip(dim_cabin["cabin_code"], dim_cabin["cabin_key"]))

# ---- dim_passenger ---------------------------------------------------------------------
def age_band(birth):
    birth = as_date(birth)
    if birth is None:
        return "Unknown"
    age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
    for limit, label in [(25, "Under 25"), (35, "25-34"), (45, "35-44"), (55, "45-54"), (65, "55-64")]:
        if age < limit:
            return label
    return "65+"


passengers = []
for p in S["stg_passenger"].to_dict("records"):
    passengers.append({
        "passenger_key": int(p["passenger_key"]),
        "full_name": none_if_missing(p["full_name"]) or "Unknown",
        "first_name": none_if_missing(p["first_name"]), "last_name": none_if_missing(p["last_name"]),
        "email": none_if_missing(p["email"]) or "Unknown",
        "birth_date": as_date(p["birth_date"]), "age_band": age_band(p["birth_date"]),
        "country_code": none_if_missing(p["country_code"]) or "??",
        "country_name": none_if_missing(p["country_name"]) or "Unknown",
        "frequent_flyer_no": none_if_missing(p["frequent_flyer_no"]),
        "loyalty_tier": none_if_missing(p["loyalty_tier"]) or "No tier",
        "source_systems": p["source_systems"],
        "mainline_passenger_ids": none_if_missing(p["mainline_passenger_ids"]),
        "regional_traveler_codes": none_if_missing(p["regional_traveler_codes"]),
        "records_merged": int(p["records_merged"]),
    })
dim_passenger = pd.DataFrame(passengers)

# ---- dim_flight (airport details folded in = denormalised) ---------------------------
def delay_band(f):
    if f["flight_status"] == "CANCELLED":
        return "Cancelled"
    if f["flight_status"] == "DIVERTED":
        return "Diverted"
    if not f["is_departed"]:
        return "Not departed"
    if none_if_missing(f["delay_minutes"]) is None:
        return "Not reported"
    d = int(f["delay_minutes"])
    return "On time (0-15 min)" if d <= 15 else ("16-60 min late" if d <= 60 else "Over 60 min late")


AIR = {a["airport_code"]: a for a in S["stg_airport"].to_dict("records")}
flights = sorted(S["stg_flight"].to_dict("records"), key=lambda f: (f["scheduled_departure"], f["flight_nk"]))
dim_flight_rows = []
for key, f in enumerate(flights, start=1):
    o, d = AIR.get(f["origin_code"], {}), AIR.get(f["destination_code"], {})
    sched = none_if_missing(f["scheduled_departure"])
    dim_flight_rows.append({
        "flight_key": key, "flight_nk": f["flight_nk"], "source_system": f["source_system"],
        "carrier_code": f["carrier_code"], "carrier_name": CARRIER_NAME[f["carrier_code"]],
        "flight_number": f["flight_number"],
        "route": f"{f['origin_code']} → {f['destination_code']}",
        "origin_code": f["origin_code"], "origin_city": o.get("city", "Unknown"), "origin_country": o.get("country_name", "Unknown"),
        "destination_code": f["destination_code"], "destination_city": d.get("city", "Unknown"),
        "destination_country": d.get("country_name", "Unknown"),
        "scheduled_departure": sched, "scheduled_arrival": none_if_missing(f["scheduled_arrival"]),
        "actual_departure": none_if_missing(f["actual_departure"]),
        "flight_date": as_date(sched), "flight_date_key": date_key(sched),
        "departure_hour": pd.Timestamp(sched).hour if sched is not None else None,
        "flight_status": f["flight_status"], "delay_minutes": none_if_missing(f["delay_minutes"]),
        "delay_band": delay_band(f), "is_departed": bool(f["is_departed"]),
        "is_on_time": none_if_missing(f["is_on_time"]),
        "aircraft_type": none_if_missing(f["aircraft_type"]) or "Unknown",
        "base_fare_bhd": none_if_missing(f["base_fare_bhd"]),
        "review_count": none_if_missing(f["review_count"]), "avg_rating": none_if_missing(f["avg_rating"]),
        "photo_like_total": none_if_missing(f["photo_like_total"]),
    })
dim_flight = pd.DataFrame(dim_flight_rows)
FLIGHT = {f["flight_nk"]: f for f in dim_flight_rows}

# COMMAND ----------

# MAGIC %md
# MAGIC ## Fact: `fact_ticket`

# COMMAND ----------

BOOK = {b["booking_nk"]: b for b in S["stg_booking"].to_dict("records")}
tickets = sorted(S["stg_ticket"].to_dict("records"),
                 key=lambda t: (FLIGHT[t["flight_nk"]]["scheduled_departure"], t["ticket_nk"]))
fact_rows, skipped = [], 0
for key, t in enumerate(tickets, start=1):
    f, b = FLIGHT.get(t["flight_nk"]), BOOK.get(t["booking_nk"])
    if f is None or b is None:
        skipped += 1
        continue
    fare = none_if_missing(t["fare_bhd"])
    expected = none_if_missing(t["expected_fare_bhd"])
    is_revenue = t["ticket_status"] not in NON_REVENUE_TICKETS and b["booking_status"] != "CANCELLED" and fare is not None
    fact_rows.append({
        "ticket_key": key, "ticket_nk": t["ticket_nk"], "source_system": t["source_system"],
        "passenger_key": int(t["passenger_key"]), "flight_key": f["flight_key"],
        "carrier_key": CARRIER_KEY[f["carrier_code"]], "cabin_key": CABIN_KEY.get(t["cabin_code"], 0),
        "booking_date_key": date_key(b["booking_ts"]), "flight_date_key": f["flight_date_key"],
        "booking_reference": none_if_missing(t["booking_reference"]),
        "booking_status": b["booking_status"], "booking_channel": b["booking_channel"],
        "payment_method": b["payment_method"], "ticket_status": t["ticket_status"],
        "seat": none_if_missing(t["seat"]),
        "fare_bhd": fare, "tax_bhd": none_if_missing(t["tax_bhd"]), "expected_fare_bhd": expected,
        "fare_variance_bhd": round3(fare - expected) if fare is not None and expected is not None else None,
        "fare_check": t["fare_check"], "is_fare_imputed": bool(t["fare_imputed"]),
        "is_revenue": bool(is_revenue), "revenue_bhd": fare if is_revenue else Decimal("0.000"),
        "ticket_count": 1,
    })
fact_ticket = pd.DataFrame(fact_rows)

# ---- dim_date: every day from the first to the last month used by the facts ----------
used = [as_date(b["booking_ts"]) for b in BOOK.values()] + [f["flight_date"] for f in dim_flight_rows]
used = [d for d in used if d]
start, end = min(used).replace(day=1), max(used)
end = (end.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)   # month end
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
dates, d = [], start
while d <= end:
    dates.append({"date_key": int(d.strftime("%Y%m%d")), "full_date": d, "year": d.year,
                  "quarter": (d.month - 1) // 3 + 1, "month": d.month, "month_name": MONTHS[d.month - 1],
                  "year_month": d.strftime("%Y-%m"), "day": d.day, "day_of_week": d.isoweekday(),
                  "day_name": DAYS[d.isoweekday() - 1], "is_weekend": d.isoweekday() in (5, 6)})
    d += dt.timedelta(days=1)
dim_date = pd.DataFrame(dates)

audit.log("dim_carrier", "build", len(dim_carrier), len(dim_carrier), "DM mainline, PX regional partner")
audit.log("dim_cabin", "build", len(S["stg_cabin"]), len(dim_cabin), "4 cabins + Unknown member")
audit.log("dim_passenger", "build", len(S["stg_passenger"]), len(dim_passenger), "NULL text shown as Unknown")
audit.log("dim_flight", "build (airports folded in)", len(S["stg_flight"]), len(dim_flight), "flight + route + airport")
audit.log("dim_date", "generate calendar", 0, len(dim_date), f"{start} to {end}")
audit.log("fact_ticket", "build", len(S["stg_ticket"]), len(fact_ticket),
          f"grain: one row per ticket per flight segment; {skipped} skipped (no booking/flight)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write the star schema (tables, keys, comments)

# COMMAND ----------

S_, L, I, Bo, D, TS = T.StringType(), T.LongType(), T.IntegerType(), T.BooleanType(), T.DateType(), T.TimestampNTZType()
DEC = lambda p, s: T.DecimalType(p, s)  # noqa: E731

GOLD_TABLES = {
    "dim_date": (dim_date, "Calendar dimension, one row per day (Bahrain weekend = Friday and Saturday)", "date_key", [
        ("date_key", I, False, "yyyymmdd"), ("full_date", D, False, "Date"), ("year", I, False, "Year"),
        ("quarter", I, False, "1-4"), ("month", I, False, "1-12"), ("month_name", S_, False, "January..."),
        ("year_month", S_, False, "yyyy-mm"), ("day", I, False, "Day of month"),
        ("day_of_week", I, False, "1 = Monday ... 7 = Sunday"), ("day_name", S_, False, "Monday..."),
        ("is_weekend", Bo, False, "Friday or Saturday")]),
    "dim_carrier": (dim_carrier, "Airline dimension: mainline carrier and regional partner", "carrier_key", [
        ("carrier_key", I, False, "Surrogate key"), ("carrier_code", S_, False, "DM / PX"),
        ("carrier_name", S_, False, "Airline"), ("carrier_type", S_, False, "Own flights / Partner airline"),
        ("source_system", S_, False, "mainline / regional")]),
    "dim_cabin": (dim_cabin, "Cabin dimension: mainline cabin model; regional travel_class text mapped onto it", "cabin_key", [
        ("cabin_key", I, False, "Surrogate key (0 = Unknown)"), ("cabin_code", S_, False, "Y / W / J / F / U"),
        ("cabin_name", S_, False, "Cabin"), ("fare_multiplier", DEC(4, 2), True, "Fare = base fare x multiplier"),
        ("cabin_rank", I, False, "Sort order, Economy first")]),
    "dim_passenger": (dim_passenger, "Passenger dimension: one row per real person across both systems", "passenger_key", [
        ("passenger_key", L, False, "Merged person key"), ("full_name", S_, False, "Name"),
        ("first_name", S_, True, "First name"), ("last_name", S_, True, "Last name"),
        ("email", S_, False, "E-mail or Unknown"), ("birth_date", D, True, "Birth date"),
        ("age_band", S_, False, "Age group today"), ("country_code", S_, False, "ISO code or ??"),
        ("country_name", S_, False, "Country or Unknown"), ("frequent_flyer_no", S_, True, "Mainline FF number"),
        ("loyalty_tier", S_, False, "Regional tier or No tier"),
        ("source_systems", S_, False, "mainline / regional / mainline + regional"),
        ("mainline_passenger_ids", S_, True, "Merged mainline ids"), ("regional_traveler_codes", S_, True, "Merged regional codes"),
        ("records_merged", I, False, "Source records merged")]),
    "dim_flight": (dim_flight, "Flight dimension: mainline flights + regional routes, airport details folded in", "flight_key", [
        ("flight_key", L, False, "Surrogate key"), ("flight_nk", S_, False, "source_system:source id"),
        ("source_system", S_, False, "mainline / regional"), ("carrier_code", S_, False, "DM / PX"),
        ("carrier_name", S_, False, "Airline"), ("flight_number", S_, True, "Flight number / route code"),
        ("route", S_, False, "Origin → destination"),
        ("origin_code", S_, False, "IATA"), ("origin_city", S_, False, "City"), ("origin_country", S_, False, "Country"),
        ("destination_code", S_, False, "IATA"), ("destination_city", S_, False, "City"),
        ("destination_country", S_, False, "Country"),
        ("scheduled_departure", TS, True, "Bahrain local time"), ("scheduled_arrival", TS, True, "Bahrain local time"),
        ("actual_departure", TS, True, "Bahrain local time"), ("flight_date", D, True, "Local departure date"),
        ("flight_date_key", I, True, "FK to dim_date"), ("departure_hour", I, True, "0-23"),
        ("flight_status", S_, False, "SCHEDULED / LANDED / DELAYED / CANCELLED / DIVERTED"),
        ("delay_minutes", I, True, "Departure delay, early = 0"), ("delay_band", S_, False, "Punctuality group"),
        ("is_departed", Bo, False, "Has departed"), ("is_on_time", Bo, True, "Within 15 min; NULL = not departed / not reported"),
        ("aircraft_type", S_, False, "Aircraft or Unknown"), ("base_fare_bhd", DEC(10, 3), True, "Economy base fare"),
        ("review_count", I, True, "From MongoDB (Flow 4)"), ("avg_rating", DEC(3, 2), True, "From MongoDB (Flow 4)"),
        ("photo_like_total", I, True, "From MongoDB (Flow 4)")]),
    "fact_ticket": (fact_ticket, "Ticket fact: one row per ticket = one passenger seat on one flight segment", "ticket_key", [
        ("ticket_key", L, False, "Surrogate key"), ("ticket_nk", S_, False, "source_system:source id"),
        ("source_system", S_, False, "mainline / regional"),
        ("passenger_key", L, False, "FK dim_passenger"), ("flight_key", L, False, "FK dim_flight"),
        ("carrier_key", I, False, "FK dim_carrier"), ("cabin_key", I, False, "FK dim_cabin"),
        ("booking_date_key", I, True, "FK dim_date (booking day)"), ("flight_date_key", I, True, "FK dim_date (flight day)"),
        ("booking_reference", S_, True, "PNR (degenerate dimension)"), ("booking_status", S_, False, "CONFIRMED / COMPLETED / CANCELLED"),
        ("booking_channel", S_, False, "WEB / APP / AGENT / CALL_CENTRE"), ("payment_method", S_, False, "Payment method or UNKNOWN"),
        ("ticket_status", S_, False, "ISSUED / USED / REFUNDED / VOID"), ("seat", S_, True, "Seat"),
        ("fare_bhd", DEC(10, 3), True, "Fare paid in BHD"), ("tax_bhd", DEC(10, 3), True, "Tax in BHD (regional only)"),
        ("expected_fare_bhd", DEC(10, 3), True, "Base fare x cabin multiplier"),
        ("fare_variance_bhd", DEC(10, 3), True, "fare - expected"),
        ("fare_check", S_, False, "OK / DRIFT / OUT_OF_BAND / IMPUTED / UNVERIFIABLE"),
        ("is_fare_imputed", Bo, False, "Missing fare rebuilt from route fare x cabin"),
        ("is_revenue", Bo, False, "Counts as revenue (not refunded/void/cancelled)"),
        ("revenue_bhd", DEC(10, 3), False, "fare_bhd when is_revenue, else 0"),
        ("ticket_count", I, False, "Always 1 (for counting)")]),
}

SQL_TYPE = {T.StringType: "STRING", T.LongType: "BIGINT", T.IntegerType: "INT", T.BooleanType: "BOOLEAN",
            T.DateType: "DATE", T.TimestampNTZType: "TIMESTAMP_NTZ", T.DoubleType: "DOUBLE"}


def sql_type(t):
    return f"DECIMAL({t.precision},{t.scale})" if isinstance(t, T.DecimalType) else SQL_TYPE[type(t)]


def q(text):
    return text.replace("'", "''")


# 1) drop in dependency order (fact first, it references the dimensions)
for table in ["fact_ticket", "dim_flight", "dim_passenger", "dim_date", "dim_carrier", "dim_cabin"]:
    spark.sql(f"DROP TABLE IF EXISTS {GOLD}.{table}")

# 2) create each table from its column list, then load it
for table, (frame, comment, _pk, columns) in GOLD_TABLES.items():
    cols = ",\n".join(f"  {n} {sql_type(t)}{'' if null else ' NOT NULL'} COMMENT '{q(c)}'" for n, t, null, c in columns)
    spark.sql(f"CREATE TABLE {GOLD}.{table} (\n{cols}\n) COMMENT '{q(comment)}' "
              "TBLPROPERTIES ('delta.feature.timestampNtz' = 'supported')")
    schema = make_schema(columns)
    spark.createDataFrame(to_rows(frame, schema), schema).write.insertInto(f"{GOLD}.{table}", overwrite=True)
    print(f"wrote {GOLD}.{table:<14} {len(frame):>4} rows")

# 3) informational primary / foreign keys (lets Catalog Explorer draw the ERD)
constraints = [f"ALTER TABLE {GOLD}.{t} ADD CONSTRAINT {t}_pk PRIMARY KEY ({pk})" for t, (_, _, pk, _) in GOLD_TABLES.items()]
for fk_col, dim, dim_key in [("passenger_key", "dim_passenger", "passenger_key"), ("flight_key", "dim_flight", "flight_key"),
                             ("carrier_key", "dim_carrier", "carrier_key"), ("cabin_key", "dim_cabin", "cabin_key"),
                             ("booking_date_key", "dim_date", "date_key"), ("flight_date_key", "dim_date", "date_key")]:
    constraints.append(f"ALTER TABLE {GOLD}.fact_ticket ADD CONSTRAINT fact_ticket_{fk_col}_fk "
                       f"FOREIGN KEY ({fk_col}) REFERENCES {GOLD}.{dim} ({dim_key})")
failed = []
for statement in constraints:
    try:
        spark.sql(statement)
    except Exception as e:      # keys are documentation only; the data is already loaded
        failed.append(f"{statement.split('CONSTRAINT ')[1].split()[0]}: {str(e).splitlines()[0][:120]}")
print(f"keys declared: {len(constraints) - len(failed)} of {len(constraints)}")
for f in failed:
    print("  could not declare", f)

audit.save()

# COMMAND ----------

# Integrity checks: every fact row must find its dimension rows
checks = {
    "fact rows": len(fact_ticket),
    "unknown passenger": int((~fact_ticket["passenger_key"].isin(dim_passenger["passenger_key"])).sum()),
    "unknown flight": int((~fact_ticket["flight_key"].isin(dim_flight["flight_key"])).sum()),
    "unknown cabin (key 0)": int((fact_ticket["cabin_key"] == 0).sum()),
    "booking date outside dim_date": int((~fact_ticket["booking_date_key"].isin(dim_date["date_key"])).sum()),
    "flight date outside dim_date": int((~fact_ticket["flight_date_key"].isin(dim_date["date_key"])).sum()),
    "duplicate ticket_nk": int(fact_ticket["ticket_nk"].duplicated().sum()),
}
for name, value in checks.items():
    print(f"{name:<32} {value}")
assert all(v == 0 for k, v in checks.items() if k not in ("fact rows", "unknown cabin (key 0)")), checks

display(spark.sql(f"""
    SELECT c.carrier_name, count(*) AS tickets, sum(f.revenue_bhd) AS revenue_bhd,
           count(DISTINCT f.passenger_key) AS passengers, count(DISTINCT f.flight_key) AS flights
    FROM {GOLD}.fact_ticket f JOIN {GOLD}.dim_carrier c ON c.carrier_key = f.carrier_key
    GROUP BY c.carrier_name ORDER BY c.carrier_name"""))
