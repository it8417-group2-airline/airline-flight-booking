# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Bronze → Staging  (Flow 1, step 2 of 3)
# MAGIC **Owner:** Fatema Alashiri (Member 2)
# MAGIC
# MAGIC Turns the raw, text-only bronze copies of **two differently designed booking systems**
# MAGIC into **typed, cleansed and reconciled** staging tables in `workspace.airline_staging`.
# MAGIC
# MAGIC | Staging table | Built from | What happens |
# MAGIC |---|---|---|
# MAGIC | `stg_airport` | mainline `airport` + the regional city list | cities mapped to IATA codes; 5 regional-only airports added |
# MAGIC | `stg_cabin` | mainline `cabin_class` | the one cabin model both systems are mapped to |
# MAGIC | `stg_passenger` | `passenger` + `traveler` | names, e-mails, 4 birth-date formats and countries cleaned; duplicates **within** and **across** schemas merged into one person |
# MAGIC | `stg_passenger_xref` | both | every source id → its merged `passenger_key` (shows each merge) |
# MAGIC | `stg_flight` | `flight` + `route` | route → flight; one status set; Bahrain local time; overnight arrivals fixed; delay and on-time flag |
# MAGIC | `stg_booking` | `booking` + `reservation` | reservation → booking; statuses, channels and payment methods unified |
# MAGIC | `stg_ticket` | `ticket` + `fare_line` | travel_class text → cabin model; USD → BHD; exact copies and double bookings removed; **fare_line reconciled against the ticket fare model** |
# MAGIC | `etl_column_exclusions` | — | every dropped source column with a one-line reason |
# MAGIC
# MAGIC Every step writes **before/after row counts** to `etl_audit`. Re-running gives the same result.

# COMMAND ----------

# MAGIC %run ./_etl_common

# COMMAND ----------

run_id = current_run_id()
audit = Audit(run_id, "staging")
print("Transforming extract run:", run_id)

B = {name: read_table(f"{BRONZE}.{name}") for name in [
    "mainline_airport", "mainline_cabin_class", "mainline_passenger", "mainline_flight",
    "mainline_booking", "mainline_ticket",
    "regional_traveler", "regional_route", "regional_reservation", "regional_fare_line"]}
for name, frame in B.items():
    print(f"bronze {name:<24} {len(frame):>4} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1 · Column exclusion
# MAGIC At least two columns per source table are left out of the warehouse, each for a stated reason.
# MAGIC The two named in Appendix I (`flight.crew_manifest_ref`, `reservation.checkin_kiosk_code`) are included.

# COMMAND ----------

EXCLUDED_COLUMNS = [
    ("mainline_carrier.airport", "timezone_name", "Not needed: every time is converted to Bahrain local time in staging."),
    ("mainline_carrier.airport", "terminal_count", "Physical airport detail with no use in any booking or punctuality analysis."),
    ("mainline_carrier.cabin_class", "lounge_access_code", "Operational benefit code, mostly NULL; no report filters or measures on it."),
    ("mainline_carrier.cabin_class", "display_colour", "Presentation colour for an old screen, not business data."),
    ("mainline_carrier.passenger", "phone", "Personal data not needed for analysis (data minimisation)."),
    ("mainline_carrier.passenger", "passport_scan_ref", "Sensitive identity-document reference; must not be copied into a warehouse."),
    ("mainline_carrier.flight", "crew_manifest_ref", "Crew-operations reference (named in Appendix I); not part of booking analytics."),
    ("mainline_carrier.flight", "gate_code", "Changes every day and is often NULL; no analytical value."),
    ("mainline_carrier.flight", "notes", "Free-text disruption notes belong to the pgvector semantic search, not to warehouse queries."),
    ("mainline_carrier.booking", "session_ip", "IP address is personal/technical data with no analytical use."),
    ("mainline_carrier.booking", "agent_remarks", "Unstructured agent free text that can hold personal information."),
    ("mainline_carrier.ticket", "baggage_tag_ref", "Baggage-handling reference, mostly NULL; baggage lives in MongoDB baggage_events."),
    ("mainline_carrier.ticket", "issued_terminal_id", "Point-of-sale terminal id; technical detail with no reporting use."),
    ("regional_partner.traveler", "mobile_no", "Personal data not needed for analysis (data minimisation)."),
    ("regional_partner.traveler", "sms_opt_in", "Marketing-consent flag; no warehouse question uses it."),
    ("regional_partner.route", "aircraft_reg", "Tail number changes per rotation; analysis is by flight and route, not airframe."),
    ("regional_partner.route", "ops_remark", "Free-text operations remark; unstructured."),
    ("regional_partner.reservation", "checkin_kiosk_code", "Check-in kiosk used (named in Appendix I); operational and often NULL."),
    ("regional_partner.reservation", "agent_terminal", "Sales terminal id; technical detail with no reporting use."),
    ("regional_partner.fare_line", "promo_code", "Marketing promo code, often NULL; not a reporting dimension in this model."),
    ("regional_partner.fare_line", "legacy_fare_basis", "Fare-basis code from the old system, replaced by the shared cabin model."),
]

bronze_columns = {f"{sys_schema}.{table}": set(B[f"{prefix}_{table}"].columns)
                  for prefix, sys_schema in [("mainline", "mainline_carrier"), ("regional", "regional_partner")]
                  for table in ["airport", "cabin_class", "passenger", "flight", "booking", "ticket",
                                "traveler", "route", "reservation", "fare_line"]
                  if f"{prefix}_{table}" in B}
exclusions = pd.DataFrame(EXCLUDED_COLUMNS, columns=["source_table", "column_name", "reason"])
exclusions["found_in_bronze"] = [col in bronze_columns.get(tbl, set())
                                 for tbl, col in zip(exclusions["source_table"], exclusions["column_name"])]
per_table = exclusions.groupby("source_table").size()
assert per_table.min() >= 2 and len(per_table) == 10, "Every source table must drop at least 2 columns"
assert exclusions["found_in_bronze"].all(), exclusions[~exclusions["found_in_bronze"]]
EXCLUDED_NAMES = set(exclusions["column_name"])

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2 · Reference data: airports and cabins

# COMMAND ----------

def country_iso(value):
    text = clean_text(value)
    if text is None:
        return None
    return COUNTRY_TO_ISO.get(_key(text)) or (text.upper() if re.fullmatch(r"[A-Za-z]{2}", text) else None)


airports = []
for r in B["mainline_airport"].to_dict("records"):
    cc = clean_text(r["country_code"]).upper()
    airports.append({"airport_code": clean_text(r["airport_code"]).upper(), "airport_name": clean_text(r["airport_name"]),
                     "city": clean_text(r["city"]), "country_code": cc, "country_name": COUNTRY_NAMES.get(cc, cc),
                     "is_hub": bool(to_bool(r["is_hub"])), "source": "mainline_carrier.airport"})
n_mainline_airports = len(airports)
known_codes = {a["airport_code"] for a in airports}
for code, name, city, cc in EXTRA_AIRPORTS:
    if code not in known_codes:
        airports.append({"airport_code": code, "airport_name": name, "city": city, "country_code": cc,
                         "country_name": COUNTRY_NAMES.get(cc, cc), "is_hub": False,
                         "source": "regional city list (docs/schema_design.md)"})
stg_airport = pd.DataFrame(airports)
AIRPORT = {a["airport_code"]: a for a in airports}
audit.log("stg_airport", "load mainline airports", n_mainline_airports, n_mainline_airports)
audit.log("stg_airport", "add regional-only airports", n_mainline_airports, len(stg_airport),
          "added " + ", ".join(sorted(set(stg_airport["airport_code"]) - known_codes)))

cabins = []
for r in B["mainline_cabin_class"].to_dict("records"):
    cabins.append({"cabin_code": clean_text(r["cabin_code"]).upper(), "cabin_name": clean_text(r["cabin_name"]),
                   "fare_multiplier": to_decimal(r["fare_multiplier"], 2),
                   "source_cabin_class_id": to_int(r["cabin_class_id"])})
stg_cabin = pd.DataFrame(cabins)
CABIN_BY_ID = {c["source_cabin_class_id"]: c["cabin_code"] for c in cabins}
MULTIPLIER = {c["cabin_code"]: c["fare_multiplier"] for c in cabins}
audit.log("stg_cabin", "load cabin model", len(stg_cabin), len(stg_cabin), "Y / W / J / F")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3 · Passengers: clean, then merge duplicates within and across the two schemas
# MAGIC Match rule: the same lower-cased e-mail = the same person (fallback: same name **and** birth date).
# MAGIC Survivorship: mainline values win over regional ones; within a system the oldest record wins.

# COMMAND ----------

people, birth_formats = [], {}
for r in B["mainline_passenger"].to_dict("records"):
    pid = to_int(r["passenger_id"])
    dob = parse_iso_date(r["date_of_birth"])
    people.append({
        "source_system": "mainline", "source_passenger_id": str(pid), "_order": (0, pid, ""),
        "first_name": title_name(r["first_name"]), "last_name": title_name(r["last_name"]),
        "email": norm_email(r["email"]), "birth_date": dob,
        "country_code": country_iso(r["nationality"]), "country_source": "mainline nationality",
        "frequent_flyer_no": clean_text(r["frequent_flyer_no"]), "loyalty_tier": None,
        "source_updated_at": parse_utc_to_local(r["updated_at"]),
    })
for r in B["regional_traveler"].to_dict("records"):
    code = clean_text(r["traveler_code"]).upper()
    first, last = split_full_name(r["full_name"])
    dob, fmt = parse_birth_date(r["birth_date_text"])
    birth_formats[fmt] = birth_formats.get(fmt, 0) + 1
    people.append({
        "source_system": "regional", "source_passenger_id": code, "_order": (1, 0, code),
        "first_name": first, "last_name": last, "email": norm_email(r["email_address"]), "birth_date": dob,
        "country_code": country_iso(r["country"]), "country_source": "regional country",
        "frequent_flyer_no": None, "loyalty_tier": title_name(r["loyalty_tier"]),
        "source_updated_at": parse_naive_utc(r["last_modified"]),
    })


def match_key(p):
    if p["email"]:
        return "email:" + p["email"], "same e-mail"
    if p["first_name"] and p["birth_date"]:
        return f"name+dob:{p['first_name']} {p['last_name'] or ''}|{p['birth_date']}".lower(), "same name and birth date"
    return f"single:{p['source_system']}:{p['source_passenger_id']}", "no match key"


for p in people:
    p["_key"], p["_rule"] = match_key(p)
people.sort(key=lambda p: p["_order"])

n_ml = sum(p["source_system"] == "mainline" for p in people)
n_rg = len(people) - n_ml
ml_keys = {p["_key"] for p in people if p["source_system"] == "mainline"}
rg_keys = {p["_key"] for p in people if p["source_system"] == "regional"}
all_keys = ml_keys | rg_keys
audit.log("stg_passenger", "combine passenger + traveler", len(people), len(people),
          f"{n_ml} mainline passengers + {n_rg} regional travelers")
audit.log("stg_passenger", "merge duplicates in mainline", len(people), len(ml_keys) + n_rg,
          "same person entered twice in passenger (matched on lower(email))")
audit.log("stg_passenger", "merge duplicates in regional", len(ml_keys) + n_rg, len(ml_keys) + len(rg_keys),
          "same person entered twice in traveler (matched on lower(email))")
audit.log("stg_passenger", "merge people in both schemas", len(ml_keys) + len(rg_keys), len(all_keys),
          f"{len(ml_keys & rg_keys)} people exist in both systems")
audit.log("stg_passenger", "parse birth_date_text", n_rg, n_rg,
          "formats: " + ", ".join(f"{k}={v}" for k, v in sorted(birth_formats.items())))

groups = {}
for p in people:
    groups.setdefault(p["_key"], []).append(p)

golden, xref = [], []
for passenger_key, members in enumerate(groups.values(), start=1):
    first, last = first_value(m["first_name"] for m in members), first_value(m["last_name"] for m in members)
    country = first_value(m["country_code"] for m in members)
    country_src = next((m["country_source"] for m in members if m["country_code"]), None)
    systems = sorted({m["source_system"] for m in members})
    golden.append({
        "passenger_key": passenger_key,
        "full_name": " ".join(x for x in [first, last] if x) or None,
        "first_name": first, "last_name": last,
        "email": first_value(m["email"] for m in members),
        "birth_date": first_value(m["birth_date"] for m in members),
        "country_code": country, "country_name": COUNTRY_NAMES.get(country, country) if country else None,
        "country_source": country_src,
        "frequent_flyer_no": first_value(m["frequent_flyer_no"] for m in members),
        "loyalty_tier": first_value(m["loyalty_tier"] for m in members),
        "source_systems": " + ".join(systems),
        "mainline_passenger_ids": ", ".join(m["source_passenger_id"] for m in members if m["source_system"] == "mainline") or None,
        "regional_traveler_codes": ", ".join(m["source_passenger_id"] for m in members if m["source_system"] == "regional") or None,
        "records_merged": len(members),
        "match_rule": members[0]["_rule"],
        "source_updated_at": max((m["source_updated_at"] for m in members if m["source_updated_at"]), default=None),
    })
    for i, m in enumerate(members):
        xref.append({"source_system": m["source_system"], "source_passenger_id": m["source_passenger_id"],
                     "passenger_key": passenger_key, "is_survivor": i == 0,
                     "match_rule": m["_rule"] if len(members) > 1 else "unique"})

stg_passenger = pd.DataFrame(golden)
stg_passenger_xref = pd.DataFrame(xref)
PASSENGER_KEY = {(x["source_system"], x["source_passenger_id"]): x["passenger_key"] for x in xref}
missing = {c: int(stg_passenger[c].isna().sum()) for c in ["email", "birth_date", "country_code"]}
audit.log("stg_passenger", "NULL check (kept, shown as Unknown in gold)", len(stg_passenger), len(stg_passenger),
          ", ".join(f"{k} missing={v}" for k, v in missing.items()))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4 · Flights: `route` (regional) becomes `flight`
# MAGIC One status set, Bahrain local time, IATA codes from city names, overnight arrivals moved to
# MAGIC the next day, delay in minutes (early = 0) and an on-time flag (≤ 15 min).

# COMMAND ----------

flights, unmapped_cities, overnight_fixed, delay_not_reported = [], set(), 0, 0


def on_time_flag(status, delay):
    if status == "DIVERTED":
        return False
    if status in DEPARTED_STATUSES and delay is not None:
        return delay <= ON_TIME_THRESHOLD_MIN
    return None


for r in B["mainline_flight"].to_dict("records"):
    fid = to_int(r["flight_id"])
    status = lookup(r["flight_status"], FLIGHT_STATUS, "UNKNOWN")
    sched_dep, sched_arr = parse_utc_to_local(r["scheduled_departure"]), parse_utc_to_local(r["scheduled_arrival"])
    act_dep, act_arr = parse_utc_to_local(r["actual_departure"]), parse_utc_to_local(r["actual_arrival"])
    delay = max(0, round((act_dep - sched_dep).total_seconds() / 60)) if act_dep and sched_dep else None
    origin, dest = clean_text(r["origin_code"]).upper(), clean_text(r["destination_code"]).upper()
    flights.append({
        "flight_nk": f"mainline:{fid}", "source_system": "mainline", "source_flight_id": str(fid),
        "carrier_code": CARRIERS["mainline"][0], "flight_number": clean_text(r["flight_number"]).upper(),
        "origin_code": origin, "destination_code": dest,
        "scheduled_departure": sched_dep, "scheduled_arrival": sched_arr,
        "actual_departure": act_dep, "actual_arrival": act_arr,
        "flight_status": status, "delay_minutes": delay,
        "is_departed": status in DEPARTED_STATUSES, "is_on_time": on_time_flag(status, delay),
        "aircraft_type": clean_text(r["aircraft_type"]), "base_fare_bhd": to_decimal(r["base_fare"]),
        "review_count": to_int(r["review_count"]), "avg_rating": to_decimal(r["avg_rating"], 2),
        "photo_like_total": to_int(r["photo_like_total"]),
        "source_updated_at": parse_utc_to_local(r["updated_at"]),
    })

for r in B["regional_route"].to_dict("records"):
    rid = to_int(r["route_id"])
    status = lookup(r["route_status"], FLIGHT_STATUS, "UNKNOWN")
    dep_date = parse_iso_date(r["departure_date"])
    dep_t, arr_t = dt.time.fromisoformat(clean_text(r["departure_time"])), dt.time.fromisoformat(clean_text(r["arrival_time"]))
    sched_dep, sched_arr = dt.datetime.combine(dep_date, dep_t), dt.datetime.combine(dep_date, arr_t)
    if arr_t < dep_t:                      # TIME-only columns: an overnight flight lands the next day
        sched_arr += dt.timedelta(days=1)
        overnight_fixed += 1
    departed = status in DEPARTED_STATUSES
    delay = to_int(r["delay_minutes"]) if departed else None
    if departed and delay is None:
        delay_not_reported += 1
    act_dep = sched_dep + dt.timedelta(minutes=delay) if departed and delay is not None else None
    act_arr = sched_arr + dt.timedelta(minutes=delay) if departed and delay is not None else None
    codes = []
    for city in (r["origin_city"], r["destination_city"]):
        code = lookup(city, CITY_TO_IATA)
        if code is None:
            unmapped_cities.add(clean_text(city))
            code = "UNK"
        codes.append(code)
    flights.append({
        "flight_nk": f"regional:{rid}", "source_system": "regional", "source_flight_id": str(rid),
        "carrier_code": CARRIERS["regional"][0], "flight_number": clean_text(r["route_code"]).upper(),
        "origin_code": codes[0], "destination_code": codes[1],
        "scheduled_departure": sched_dep, "scheduled_arrival": sched_arr,
        "actual_departure": act_dep, "actual_arrival": act_arr,
        "flight_status": status, "delay_minutes": delay,
        "is_departed": departed, "is_on_time": on_time_flag(status, delay),
        "aircraft_type": None, "base_fare_bhd": to_decimal(r["fare_amount"]),
        "review_count": None, "avg_rating": None, "photo_like_total": None,
        "source_updated_at": parse_naive_utc(r["last_modified"]),
    })

stg_flight = pd.DataFrame(flights)
FLIGHT = {f["flight_nk"]: f for f in flights}
n_ml_f = len(B["mainline_flight"])
audit.log("stg_flight", "combine flight + route", len(stg_flight), len(stg_flight),
          f"{n_ml_f} mainline flights + {len(stg_flight) - n_ml_f} regional routes")
audit.log("stg_flight", "normalise route cities to IATA", len(stg_flight), len(stg_flight),
          "unmapped cities: " + (", ".join(sorted(unmapped_cities)) if unmapped_cities else "none"))
audit.log("stg_flight", "fix overnight arrivals", len(stg_flight), len(stg_flight),
          f"{overnight_fixed} regional arrivals moved to the next day")
audit.log("stg_flight", "flag missing delays", len(stg_flight), len(stg_flight),
          f"{delay_not_reported} departed regional flights have no delay reported (excluded from on-time %)")
statuses = stg_flight["flight_status"].value_counts().to_dict()
audit.log("stg_flight", "unify flight status", len(stg_flight), len(stg_flight),
          ", ".join(f"{k}={v}" for k, v in sorted(statuses.items())))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5 · Bookings: `reservation` (regional) becomes `booking`

# COMMAND ----------

bookings, travel_class_raw = [], {}
for r in B["mainline_booking"].to_dict("records"):
    bid = to_int(r["booking_id"])
    bookings.append({
        "booking_nk": f"mainline:{bid}", "source_system": "mainline", "source_booking_id": str(bid),
        "booking_reference": clean_text(r["booking_reference"]).upper(),
        "passenger_key": PASSENGER_KEY.get(("mainline", str(to_int(r["passenger_id"])))),
        "booking_ts": parse_utc_to_local(r["booking_date"]),
        "booking_status": lookup(r["booking_status"], BOOKING_STATUS, "UNKNOWN"),
        "booking_channel": lookup(r["booking_channel"], CHANNEL, "OTHER"),
        "payment_method": (clean_text(r["payment_method"]) or "UNKNOWN").upper(),
        "source_updated_at": parse_utc_to_local(r["updated_at"]),
    })
for r in B["regional_reservation"].to_dict("records"):
    res_no = to_int(r["reservation_no"])
    travel_class_raw[res_no] = clean_text(r["travel_class"])
    bookings.append({
        "booking_nk": f"regional:{res_no}", "source_system": "regional", "source_booking_id": str(res_no),
        "booking_reference": clean_text(r["pnr"]).upper(),
        "passenger_key": PASSENGER_KEY.get(("regional", clean_text(r["traveler_code"]).upper())),
        "booking_ts": parse_local_timestamp(r["reserved_at"]),
        "booking_status": lookup(r["reservation_status"], BOOKING_STATUS, "UNKNOWN"),
        "booking_channel": lookup(r["sales_channel"], CHANNEL, "OTHER"),
        "payment_method": "UNKNOWN",        # the regional system does not record it
        "source_updated_at": parse_naive_utc(r["last_modified"]),
    })
stg_booking = pd.DataFrame(bookings)
n_all = len(stg_booking)
audit.log("stg_booking", "combine booking + reservation", n_all, n_all,
          f"{len(B['mainline_booking'])} mainline bookings + {len(B['regional_reservation'])} regional reservations")
no_passenger = stg_booking["passenger_key"].isna()
stg_booking = stg_booking[~no_passenger].reset_index(drop=True)
audit.log("stg_booking", "remove bookings without a passenger", n_all, len(stg_booking), "orphan check")
null_payment = int((stg_booking["payment_method"] == "UNKNOWN").sum())
audit.log("stg_booking", "unify status, channel, payment", len(stg_booking), len(stg_booking),
          f"payment_method NULL/not recorded -> UNKNOWN for {null_payment} bookings")
BOOKING = {b["booking_nk"]: b for b in stg_booking.to_dict("records")}

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6 · Tickets: `fare_line` (regional) becomes `ticket`
# MAGIC * `travel_class` free text → mainline cabin code; a missing class is inferred only when the fare
# MAGIC   matches a cabin factor within 5 %.
# MAGIC * USD fares × 0.376 → BHD. A missing fare is rebuilt as route fare × cabin factor (flagged).
# MAGIC * **Reconciliation:** every fare is compared with the mainline ticket fare model
# MAGIC   (base fare × cabin multiplier). Regional lines are copied at sale time, so they must match
# MAGIC   (±0.5 %); mainline tickets may vary 0.90–1.15 by design (dynamic pricing).
# MAGIC * Exact duplicate rows and double bookings (same person, same flight, two live tickets) are removed.

# COMMAND ----------

def fare_check(fare, expected, system, imputed):
    if imputed:
        return "IMPUTED", None
    if fare is None or expected in (None, 0):
        return "UNVERIFIABLE", None
    ratio = fare / expected
    variance = (ratio - 1) * 100
    if system == "regional":
        ok = abs(ratio - 1) <= REGIONAL_FARE_TOLERANCE
    else:
        ok = MAINLINE_FARE_BAND[0] <= ratio <= MAINLINE_FARE_BAND[1]
    return ("OK" if ok else ("DRIFT" if system == "regional" else "OUT_OF_BAND")), variance


def infer_cabin(fare_bhd, base_fare):
    """Nearest cabin factor to fare / base fare, only if within the tolerance."""
    if fare_bhd is None or not base_fare:
        return None
    ratio = fare_bhd / base_fare
    code, factor = min(((c, m) for c, m in MULTIPLIER.items() if c in {"Y", "W", "J"}),
                       key=lambda cm: abs(ratio - cm[1]))
    return code if abs(ratio - factor) / factor <= CABIN_INFERENCE_TOLERANCE else None


tickets = []
for r in B["mainline_ticket"].to_dict("records"):
    tid = to_int(r["ticket_id"])
    flight_nk = f"mainline:{to_int(r['flight_id'])}"
    cabin = CABIN_BY_ID.get(to_int(r["cabin_class_id"]), "U")
    fare = to_decimal(r["fare_paid"])
    base = FLIGHT.get(flight_nk, {}).get("base_fare_bhd")
    expected = round3(base * MULTIPLIER[cabin]) if base is not None and cabin in MULTIPLIER else None
    check, variance = fare_check(fare, expected, "mainline", False)
    tickets.append({
        "ticket_nk": f"mainline:{tid}", "source_system": "mainline", "source_ticket_id": str(tid),
        "ticket_number": clean_text(r["ticket_number"]), "booking_nk": f"mainline:{to_int(r['booking_id'])}",
        "flight_nk": flight_nk, "cabin_code": cabin, "cabin_source": "cabin_class_id",
        "travel_class_raw": None, "seat": (clean_text(r["seat_number"]) or "").upper() or None,
        "ticket_status": lookup(r["ticket_status"], TICKET_STATUS, "UNKNOWN"),
        "original_currency": "BHD", "original_fare_amount": fare, "fare_bhd": fare, "tax_bhd": None,
        "expected_fare_bhd": expected, "fare_variance_pct": variance, "fare_check": check,
        "fare_imputed": False, "currency_converted": False,
        "source_updated_at": parse_utc_to_local(r["updated_at"]),
        "_dedupe_key": tuple(clean_text(r[c]) for c in ["booking_id", "flight_id", "seat_number", "fare_paid"]),
    })

for r in B["regional_fare_line"].to_dict("records"):
    lid, res_no = to_int(r["fare_line_id"]), to_int(r["reservation_no"])
    flight_nk = f"regional:{to_int(r['route_id'])}"
    base = FLIGHT.get(flight_nk, {}).get("base_fare_bhd")
    currency = (clean_text(r["currency"]) or "BHD").upper()
    rate = USD_TO_BHD if currency == "USD" else Decimal(1)
    raw_fare, raw_tax = to_decimal(r["fare_amount"]), to_decimal(r["tax_amount"])
    fare = round3(raw_fare * rate) if raw_fare is not None else None
    tax = round3(raw_tax * rate) if raw_tax is not None else None
    raw_class = travel_class_raw.get(res_no)
    cabin, source = lookup(raw_class, CLASS_TO_CABIN), "travel_class text"
    if cabin is None:
        cabin, source = infer_cabin(fare, base), "inferred from fare"
    if cabin is None:
        cabin, source = "U", "unknown"
    expected = round3(base * MULTIPLIER[cabin]) if base is not None and cabin in MULTIPLIER else None
    imputed = fare is None and expected is not None
    if imputed:
        fare = expected
    check, variance = fare_check(fare, expected, "regional", imputed)
    tickets.append({
        "ticket_nk": f"regional:{lid}", "source_system": "regional", "source_ticket_id": str(lid),
        "ticket_number": None, "booking_nk": f"regional:{res_no}", "flight_nk": flight_nk,
        "cabin_code": cabin, "cabin_source": source, "travel_class_raw": raw_class,
        "seat": (clean_text(r["seat_label"]) or "").upper() or None,
        "ticket_status": lookup(r["line_status"], TICKET_STATUS, "UNKNOWN"),
        "original_currency": currency, "original_fare_amount": raw_fare, "fare_bhd": fare, "tax_bhd": tax,
        "expected_fare_bhd": expected, "fare_variance_pct": variance, "fare_check": check,
        "fare_imputed": imputed, "currency_converted": currency != "BHD",
        "source_updated_at": parse_naive_utc(r["last_modified"]),
        "_dedupe_key": tuple(clean_text(r[c]) for c in ["reservation_no", "route_id", "fare_amount", "tax_amount",
                                                         "currency", "seat_label", "line_status"]),
    })

n_ml_t = len(B["mainline_ticket"])
audit.log("stg_ticket", "combine ticket + fare_line", len(tickets), len(tickets),
          f"{n_ml_t} mainline tickets + {len(tickets) - n_ml_t} regional fare lines")

# a) exact duplicate rows (same values in every business column) - keep the first
seen, kept, exact_dupes = set(), [], []
for t in sorted(tickets, key=lambda t: (t["source_system"], int(t["source_ticket_id"]))):
    key = (t["source_system"],) + t["_dedupe_key"]
    if key in seen:
        exact_dupes.append(t["ticket_nk"])
    else:
        seen.add(key)
        kept.append(t)
audit.log("stg_ticket", "remove exact duplicate rows", len(tickets), len(kept),
          "removed " + (", ".join(exact_dupes) if exact_dupes else "none"))
tickets = kept

# b) orphans: a ticket must point to a known booking and flight
before = len(tickets)
tickets = [t for t in tickets if t["booking_nk"] in BOOKING and t["flight_nk"] in FLIGHT]
audit.log("stg_ticket", "remove tickets without booking/flight", before, len(tickets), "orphan check")

# c) double bookings: one live seat per (merged) passenger per flight - keep the earliest booking
for t in tickets:
    b = BOOKING[t["booking_nk"]]
    t["passenger_key"], t["booking_reference"], t["_booked"] = b["passenger_key"], b["booking_reference"], b["booking_ts"]
live = [t for t in tickets if t["ticket_status"] not in NON_REVENUE_TICKETS]
by_seat = {}
for t in sorted(live, key=lambda t: (t["_booked"] or dt.datetime.max, t["source_system"], int(t["source_ticket_id"]))):
    by_seat.setdefault((t["passenger_key"], t["flight_nk"]), []).append(t)
double = {t["ticket_nk"] for group in by_seat.values() if len(group) > 1 for t in group[1:]}
before = len(tickets)
tickets = [t for t in tickets if t["ticket_nk"] not in double]
audit.log("stg_ticket", "remove double bookings", before, len(tickets),
          "removed " + (", ".join(sorted(double)) if double else "none") + " (same passenger, same flight)")

stg_ticket = pd.DataFrame(tickets).drop(columns=["_dedupe_key", "_booked"])
fare_summary = stg_ticket.groupby(["source_system", "fare_check"]).size().to_dict()
audit.log("stg_ticket", "reconcile fares with ticket model", len(stg_ticket), len(stg_ticket),
          ", ".join(f"{s}/{c}={n}" for (s, c), n in sorted(fare_summary.items())))
cabin_summary = stg_ticket[stg_ticket["source_system"] == "regional"]["cabin_source"].value_counts().to_dict()
audit.log("stg_ticket", "map travel_class to cabin model", len(stg_ticket), len(stg_ticket),
          ", ".join(f"{k}={v}" for k, v in sorted(cabin_summary.items())))
converted = int(stg_ticket["currency_converted"].sum())
audit.log("stg_ticket", "convert USD fares to BHD", len(stg_ticket), len(stg_ticket),
          f"{converted} regional lines converted at {USD_TO_BHD}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7 · Write the typed staging tables

# COMMAND ----------

S, L, I, Bo, D, TS = T.StringType(), T.LongType(), T.IntegerType(), T.BooleanType(), T.DateType(), T.TimestampNTZType()
DEC = lambda p, s: T.DecimalType(p, s)  # noqa: E731

STAGING_TABLES = {
    "stg_airport": (stg_airport, "Airports of both systems (IATA), incl. 5 regional-only airports", [
        ("airport_code", S, False, "IATA code"), ("airport_name", S, True, "Airport name"),
        ("city", S, True, "City"), ("country_code", S, True, "ISO country code"),
        ("country_name", S, True, "Country"), ("is_hub", Bo, True, "Mainline hub airport"),
        ("source", S, True, "Where the row comes from")]),
    "stg_cabin": (stg_cabin, "Shared cabin model (mainline cabin_class) that regional travel_class is mapped to", [
        ("cabin_code", S, False, "Y / W / J / F"), ("cabin_name", S, True, "Cabin name"),
        ("fare_multiplier", DEC(4, 2), True, "Fare = base fare x multiplier"),
        ("source_cabin_class_id", I, True, "mainline cabin_class_id")]),
    "stg_passenger": (stg_passenger, "One row per real person after merging duplicates within and across schemas", [
        ("passenger_key", L, False, "Merged person id"), ("full_name", S, True, "First + last name, title case"),
        ("first_name", S, True, "First name"), ("last_name", S, True, "Last name"),
        ("email", S, True, "Lower-cased e-mail"), ("birth_date", D, True, "Birth date (4 text formats parsed)"),
        ("country_code", S, True, "ISO country code"), ("country_name", S, True, "Country"),
        ("country_source", S, True, "mainline nationality or regional country"),
        ("frequent_flyer_no", S, True, "Mainline frequent-flyer number"),
        ("loyalty_tier", S, True, "Regional loyalty tier"),
        ("source_systems", S, True, "mainline / regional / mainline + regional"),
        ("mainline_passenger_ids", S, True, "Merged mainline passenger_id values"),
        ("regional_traveler_codes", S, True, "Merged regional traveler_code values"),
        ("records_merged", I, True, "Source records merged into this person"),
        ("match_rule", S, True, "How the records were matched"),
        ("source_updated_at", TS, True, "Latest source change (watermark)")]),
    "stg_passenger_xref": (stg_passenger_xref, "Every source passenger/traveler id and the merged passenger it belongs to", [
        ("source_system", S, False, "mainline / regional"), ("source_passenger_id", S, False, "passenger_id or traveler_code"),
        ("passenger_key", L, False, "Merged person id"), ("is_survivor", Bo, True, "Record whose values won"),
        ("match_rule", S, True, "unique / same e-mail / same name and birth date")]),
    "stg_flight": (stg_flight, "Mainline flights and regional routes as one flight table (Bahrain local time)", [
        ("flight_nk", S, False, "source_system:source id"), ("source_system", S, False, "mainline / regional"),
        ("source_flight_id", S, False, "flight_id or route_id"), ("carrier_code", S, False, "DM / PX"),
        ("flight_number", S, True, "Flight number / route code"), ("origin_code", S, True, "Origin IATA"),
        ("destination_code", S, True, "Destination IATA"),
        ("scheduled_departure", TS, True, "Bahrain local time"), ("scheduled_arrival", TS, True, "Bahrain local time"),
        ("actual_departure", TS, True, "Bahrain local time"), ("actual_arrival", TS, True, "Bahrain local time"),
        ("flight_status", S, True, "SCHEDULED / LANDED / DELAYED / CANCELLED / DIVERTED"),
        ("delay_minutes", I, True, "Departure delay, early = 0"), ("is_departed", Bo, True, "Has departed"),
        ("is_on_time", Bo, True, "Departed within 15 min (NULL = not departed or not reported)"),
        ("aircraft_type", S, True, "Aircraft type (mainline only)"),
        ("base_fare_bhd", DEC(10, 3), True, "Economy base fare in BHD"),
        ("review_count", I, True, "Synced from MongoDB (Flow 4)"), ("avg_rating", DEC(3, 2), True, "Synced from MongoDB (Flow 4)"),
        ("photo_like_total", I, True, "Synced from MongoDB (Flow 4)"),
        ("source_updated_at", TS, True, "Source change time (watermark)")]),
    "stg_booking": (stg_booking, "Mainline bookings and regional reservations as one booking table", [
        ("booking_nk", S, False, "source_system:source id"), ("source_system", S, False, "mainline / regional"),
        ("source_booking_id", S, False, "booking_id or reservation_no"), ("booking_reference", S, True, "PNR"),
        ("passenger_key", L, False, "Merged person id"), ("booking_ts", TS, True, "Bahrain local time"),
        ("booking_status", S, True, "CONFIRMED / COMPLETED / CANCELLED"),
        ("booking_channel", S, True, "WEB / APP / AGENT / CALL_CENTRE"),
        ("payment_method", S, True, "UNKNOWN when NULL or not recorded"),
        ("source_updated_at", TS, True, "Source change time (watermark)")]),
    "stg_ticket": (stg_ticket, "One row per seat per flight segment, fares in BHD, reconciled with the ticket fare model", [
        ("ticket_nk", S, False, "source_system:source id"), ("source_system", S, False, "mainline / regional"),
        ("source_ticket_id", S, False, "ticket_id or fare_line_id"), ("ticket_number", S, True, "Mainline ticket number"),
        ("booking_nk", S, False, "Booking"), ("flight_nk", S, False, "Flight"),
        ("cabin_code", S, False, "Y / W / J / F / U"), ("cabin_source", S, True, "How the cabin was found"),
        ("travel_class_raw", S, True, "Regional free text as entered"), ("seat", S, True, "Seat"),
        ("ticket_status", S, True, "ISSUED / USED / REFUNDED / VOID"),
        ("original_currency", S, True, "Currency in the source"), ("original_fare_amount", DEC(10, 3), True, "Fare as in the source"),
        ("fare_bhd", DEC(10, 3), True, "Fare in BHD (revenue measure)"), ("tax_bhd", DEC(10, 3), True, "Tax in BHD (regional only)"),
        ("expected_fare_bhd", DEC(10, 3), True, "Base fare x cabin multiplier"),
        ("fare_variance_pct", DEC(8, 2), True, "(fare / expected - 1) x 100"),
        ("fare_check", S, True, "OK / DRIFT / OUT_OF_BAND / IMPUTED / UNVERIFIABLE"),
        ("fare_imputed", Bo, True, "Fare was missing and rebuilt"), ("currency_converted", Bo, True, "USD converted to BHD"),
        ("source_updated_at", TS, True, "Source change time (watermark)"),
        ("passenger_key", L, False, "Merged person id"), ("booking_reference", S, True, "PNR")]),
    "etl_column_exclusions": (exclusions, "Source columns left out of the warehouse, with the reason for each", [
        ("source_table", S, False, "schema.table"), ("column_name", S, False, "Dropped column"),
        ("reason", S, False, "Why it is not needed"), ("found_in_bronze", Bo, True, "Column existed in the extract")]),
}

for table, (frame, comment, columns) in STAGING_TABLES.items():
    leaked = EXCLUDED_NAMES & set(frame.columns) - {"column_name"}
    assert not leaked, f"{table} still contains excluded columns {leaked}"
    n = write_table(frame, f"{STAGING}.{table}", columns, comment)
    print(f"wrote {STAGING}.{table:<24} {n:>4} rows")

audit.save()

# COMMAND ----------

summary = spark.table(AUDIT_TABLE).where(f"run_id = '{run_id}' AND layer IN ('bronze', 'staging')") \
               .select("layer", "table_name", "step", "rows_before", "rows_after", "rows_removed", "note") \
               .orderBy("layer", "table_name", "step")
display(summary)
