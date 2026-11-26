# Databricks notebook source
# MAGIC %md
# MAGIC # _etl_common · shared settings, cleaning rules and table helpers
# MAGIC **Owner:** Fatema Alashiri (Member 2)
# MAGIC
# MAGIC Loaded at the top of `02_staging` and `03_gold` with `%run ./_etl_common`, so every
# MAGIC step uses the same names, the same cleaning rules and the same way of writing tables.
# MAGIC Nothing here reads or writes data on its own.

# COMMAND ----------

import datetime as dt
import re
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

import pandas as pd
from pyspark.sql import types as T

# ---- Unity Catalog locations -------------------------------------------------------
CATALOG = "workspace"
BRONZE = f"{CATALOG}.airline_bronze"
STAGING = f"{CATALOG}.airline_staging"
GOLD = f"{CATALOG}.airline_gold"
AUDIT_TABLE = f"{STAGING}.etl_audit"

# ---- Business rules ----------------------------------------------------------------
LOCAL_TZ = ZoneInfo("Asia/Bahrain")       # all warehouse times are Bahrain local time
USD_TO_BHD = Decimal("0.376")             # fixed peg: 1 USD = 0.376 BHD
ON_TIME_THRESHOLD_MIN = 15                # departed within 15 min of schedule = on time
REGIONAL_FARE_TOLERANCE = Decimal("0.005")   # regional fares are copied at sale time: must match
MAINLINE_FARE_BAND = (Decimal("0.90"), Decimal("1.15"))   # mainline dynamic pricing band
CABIN_INFERENCE_TOLERANCE = Decimal("0.05")  # infer a missing class only if the fare ratio is this close

CARRIERS = {   # source_system -> (carrier_code, carrier_name, carrier_type)
    "mainline": ("DM", "Mainline carrier", "Own flights"),
    "regional": ("PX", "Regional partner", "Partner airline"),
}

# COMMAND ----------

# ---- Lookup tables (left side = normalised source value) --------------------------
def _key(value):
    """Lower-case and keep letters/digits only: 'Kuwait City' -> 'kuwaitcity'."""
    return re.sub(r"[^a-z0-9]", "", str(value).lower())

# route.origin_city / destination_city -> IATA (from Member 1's notes in docs/schema_design.md)
CITY_TO_IATA = {
    "manama": "BAH", "bahrain": "BAH", "doha": "DOH", "dubai": "DXB",
    "kuwait": "KWI", "kuwaitcity": "KWI", "muscat": "MCT", "dammam": "DMM",
    "alula": "ULH", "salalah": "SLL", "shiraz": "SYZ", "taif": "TIF",
    "riyadh": "RUH", "jeddah": "JED", "london": "LHR", "paris": "CDG",
    "istanbul": "IST", "cairo": "CAI", "mumbai": "BOM",
}

# Airports the regional partner flies to that mainline_carrier.airport does not list
EXTRA_AIRPORTS = [
    ("DMM", "King Fahd International Airport", "Dammam", "SA"),
    ("ULH", "AlUla International Airport", "AlUla", "SA"),
    ("SLL", "Salalah International Airport", "Salalah", "OM"),
    ("SYZ", "Shiraz International Airport", "Shiraz", "IR"),
    ("TIF", "Taif International Airport", "Taif", "SA"),
]

COUNTRY_TO_ISO = {
    "bahrain": "BH", "kingdomofbahrain": "BH", "bh": "BH",
    "saudiarabia": "SA", "ksa": "SA", "sa": "SA",
    "unitedkingdom": "GB", "uk": "GB", "greatbritain": "GB", "gb": "GB",
    "india": "IN", "in": "IN", "oman": "OM", "om": "OM", "egypt": "EG", "eg": "EG",
    "kuwait": "KW", "kw": "KW", "qatar": "QA", "qa": "QA",
    "unitedarabemirates": "AE", "uae": "AE", "ae": "AE", "france": "FR", "fr": "FR",
    "turkey": "TR", "turkiye": "TR", "tr": "TR", "iran": "IR", "ir": "IR",
}
COUNTRY_NAMES = {
    "BH": "Bahrain", "SA": "Saudi Arabia", "GB": "United Kingdom", "IN": "India",
    "OM": "Oman", "EG": "Egypt", "KW": "Kuwait", "QA": "Qatar",
    "AE": "United Arab Emirates", "FR": "France", "TR": "Turkey", "IR": "Iran",
}

# Free-text travel_class -> mainline cabin model (cabin_class.cabin_code)
CLASS_TO_CABIN = {
    "economy": "Y", "econ": "Y", "eco": "Y", "y": "Y", "economyclass": "Y",
    "premiumeconomy": "W", "premecon": "W", "premium": "W", "w": "W",
    "business": "J", "businessclass": "J", "j": "J", "c": "J",
    "first": "F", "firstclass": "F", "f": "F",
}

FLIGHT_STATUS = {   # both systems -> one set of statuses
    "scheduled": "SCHEDULED", "landed": "LANDED", "operated": "LANDED",
    "delayed": "DELAYED", "cancelled": "CANCELLED", "canceled": "CANCELLED",
    "diverted": "DIVERTED",
}
BOOKING_STATUS = {
    "confirmed": "CONFIRMED", "completed": "COMPLETED", "flown": "COMPLETED",
    "cancelled": "CANCELLED", "canceled": "CANCELLED", "cxl": "CANCELLED",
}
TICKET_STATUS = {
    "issued": "ISSUED", "active": "ISSUED", "used": "USED",
    "refunded": "REFUNDED", "void": "VOID",
}
CHANNEL = {
    "web": "WEB", "website": "WEB", "app": "APP", "mobile": "APP",
    "agent": "AGENT", "travelagent": "AGENT",
    "callcentre": "CALL_CENTRE", "callcenter": "CALL_CENTRE",
}
DEPARTED_STATUSES = {"LANDED", "DELAYED", "DIVERTED"}
NON_REVENUE_TICKETS = {"REFUNDED", "VOID"}

# COMMAND ----------

# ---- Value cleaning functions (one value in, one clean value out) ------------------
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def clean_text(value):
    """Trim, collapse spaces; NULL / NaN / '' -> None."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def to_int(value):
    text = clean_text(value)
    return int(text) if text is not None else None


def to_decimal(value, places=3):
    text = clean_text(value)
    if text is None:
        return None
    return Decimal(text).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def round3(value):
    return None if value is None else Decimal(value).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def to_bool(value):
    text = clean_text(value)
    if text is None:
        return None
    return text.lower() in {"true", "t", "yes", "y", "1"}


def title_name(value):
    """'AHMED AL-KHALIFA' / 'ahmed al-khalifa' -> 'Ahmed Al-Khalifa'."""
    text = clean_text(value)
    return text.title() if text else None


def norm_email(value):
    text = clean_text(value)
    if not text or "@" not in text:
        return None
    return text.lower()


def split_full_name(value):
    """'Ahmed Al-Khalifa' -> ('Ahmed', 'Al-Khalifa'); one word -> (word, None)."""
    name = title_name(value)
    if not name:
        return None, None
    first, _, last = name.partition(" ")
    return first, (last or None)


def lookup(value, mapping, default=None):
    text = clean_text(value)
    return mapping.get(_key(text), default) if text else default


def parse_utc_to_local(value):
    """Postgres timestamptz text in UTC ('2026-09-01 23:45:00+00') -> naive Bahrain local time."""
    text = clean_text(value)
    if text is None:
        return None
    text = re.sub(r"([+-]\d{2})$", r"\1:00", text)   # '+00' -> '+00:00' for fromisoformat
    moment = dt.datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment.astimezone(LOCAL_TZ).replace(tzinfo=None, microsecond=0)


def parse_local_timestamp(value):
    """Regional TIMESTAMP text (already Bahrain local) -> naive datetime."""
    text = clean_text(value)
    return dt.datetime.fromisoformat(text).replace(microsecond=0) if text else None


def parse_naive_utc(value):
    """Regional last_modified (TIMESTAMP stored in UTC) -> naive Bahrain local time."""
    text = clean_text(value)
    if text is None:
        return None
    moment = dt.datetime.fromisoformat(text).replace(tzinfo=dt.timezone.utc)
    return moment.astimezone(LOCAL_TZ).replace(tzinfo=None, microsecond=0)


def parse_iso_date(value):
    text = clean_text(value)
    return dt.date.fromisoformat(text) if text else None


def parse_birth_date(value):
    """The 4 planted text formats -> (date, format_name). Unknown or impossible -> (None, reason)."""
    text = clean_text(value)
    if text is None:
        return None, "missing"
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            parsed, fmt = dt.date.fromisoformat(text), "YYYY-MM-DD"
        elif re.fullmatch(r"\d{2}/\d{2}/\d{4}", text):
            d, m, y = (int(p) for p in text.split("/"))
            parsed, fmt = dt.date(y, m, d), "DD/MM/YYYY"
        elif re.fullmatch(r"\d{2}-\d{2}-\d{4}", text):
            m, d, y = (int(p) for p in text.split("-"))
            parsed, fmt = dt.date(y, m, d), "MM-DD-YYYY"
        elif re.fullmatch(r"[A-Za-z]{3} \d{1,2} \d{4}", text):
            mon, d, y = text.split(" ")
            parsed, fmt = dt.date(int(y), _MONTHS[mon.lower()], int(d)), "Mon DD YYYY"
        else:
            return None, "unrecognised"
    except (ValueError, KeyError):
        return None, "invalid"
    if not dt.date(1900, 1, 1) <= parsed <= dt.date.today():
        return None, "out of range"
    return parsed, fmt


def first_value(values):
    """First non-missing value in order (survivorship rule for merged records)."""
    for value in values:
        if value is not None and not (isinstance(value, float) and pd.isna(value)):
            return value
    return None

# COMMAND ----------

# ---- Spark table helpers -----------------------------------------------------------
def read_table(name):
    """Unity Catalog table -> pandas DataFrame (the data is small, so pandas keeps rules readable)."""
    return spark.table(name).toPandas()


def _python_value(value, data_type):
    """Convert one pandas value to the plain Python type Spark expects for that column."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(data_type, T.StringType):
        return str(value)
    if isinstance(data_type, (T.LongType, T.IntegerType)):
        return int(value)
    if isinstance(data_type, T.DoubleType):
        return float(value)
    if isinstance(data_type, T.DecimalType):
        return Decimal(str(value)).quantize(Decimal(1).scaleb(-data_type.scale), rounding=ROUND_HALF_UP)
    if isinstance(data_type, T.BooleanType):
        return bool(value)
    if isinstance(data_type, T.DateType):
        return value.date() if isinstance(value, dt.datetime) else value
    if isinstance(data_type, (T.TimestampNTZType, T.TimestampType)):
        return pd.Timestamp(value).to_pydatetime()
    return value


def make_schema(columns):
    """columns: list of (name, spark_type, nullable, comment)."""
    return T.StructType([T.StructField(name, dtype, nullable, metadata={"comment": comment})
                         for name, dtype, nullable, comment in columns])


def to_rows(pdf, schema):
    missing = [f.name for f in schema.fields if f.name not in pdf.columns]
    if missing:
        raise ValueError(f"DataFrame is missing columns {missing}")
    records = pdf[[f.name for f in schema.fields]].to_dict("records")
    return [tuple(_python_value(rec[f.name], f.dataType) for f in schema.fields) for rec in records]


def write_table(pdf, table, columns, comment):
    """Replace a Delta table with the pandas DataFrame, using an explicit typed schema."""
    schema = make_schema(columns)
    rows = to_rows(pdf, schema)
    (spark.createDataFrame(rows, schema)
          .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table))
    spark.sql(f"COMMENT ON TABLE {table} IS '{comment.replace(chr(39), chr(39) * 2)}'")
    return len(rows)


AUDIT_SCHEMA = T.StructType([
    T.StructField("run_id", T.StringType()), T.StructField("run_ts", T.TimestampType()),
    T.StructField("layer", T.StringType()), T.StructField("table_name", T.StringType()),
    T.StructField("step", T.StringType()), T.StructField("rows_before", T.LongType()),
    T.StructField("rows_after", T.LongType()), T.StructField("rows_removed", T.LongType()),
    T.StructField("note", T.StringType()),
])


class Audit:
    """Collects before/after row counts and appends them to etl_audit in one write."""

    def __init__(self, run_id, layer):
        self.run_id, self.layer = run_id, layer
        self.run_ts = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        self.rows = []
        self.seq = 0

    def log(self, table, step, before, after, note=""):
        self.seq += 1
        step = f"{self.seq:02d} {step}"          # numbered so the audit always sorts in run order
        self.rows.append((self.run_id, self.run_ts, self.layer, table, step,
                          int(before), int(after), int(before) - int(after), note))
        print(f"[{self.layer}] {table:<20} {step:<46} {before:>5} -> {after:<5} {note}")

    def save(self):
        if self.rows:
            spark.createDataFrame(self.rows, AUDIT_SCHEMA).write.mode("append").saveAsTable(AUDIT_TABLE)


def current_run_id():
    """The run_id stamped on bronze by 01_extract_bronze: staging and gold describe that extract."""
    row = spark.table(f"{BRONZE}.mainline_flight").select("_run_id").limit(1).collect()
    return row[0][0] if row else "no-extract"
