# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Extract → Bronze  (Flow 1, step 1 of 3)
# MAGIC **Owner:** Fatema Alashiri (Member 2)
# MAGIC
# MAGIC Copies **every table of both PostgreSQL schemas** on Supabase into Delta tables in
# MAGIC `workspace.airline_bronze`, exactly as they are in the source:
# MAGIC
# MAGIC | Rule | Why |
# MAGIC |---|---|
# MAGIC | Every column is stored as `STRING` (Postgres `::text`) | Bronze is **raw and untyped**: no value is changed or lost; typing happens in staging |
# MAGIC | Tables are discovered from `information_schema` | New source tables are picked up without code changes |
# MAGIC | Each row is tagged `source_system` = `mainline` / `regional` | Lineage: staging knows which operational system a row came from |
# MAGIC | `_run_id`, `_extracted_at`, `source_table` are added | Every bronze row can be traced to one ETL run |
# MAGIC | Full reload (overwrite) on every run | Small tables, so a full copy is simple and always consistent (see refresh strategy) |
# MAGIC
# MAGIC **Security:** connects with the read-only login `etl_reader` (secret `airline/supabase_url`)
# MAGIC in a read-only transaction, so this notebook cannot change the operational data.
# MAGIC
# MAGIC **Audit:** writes one row per table to `workspace.airline_staging.etl_audit`
# MAGIC (source row count vs bronze row count).

# COMMAND ----------

# MAGIC %pip install "psycopg[binary]>=3.2,<4" --quiet

# COMMAND ----------

import datetime as dt
import uuid

import psycopg
from psycopg import sql
from pyspark.sql import functions as F
from pyspark.sql import types as T

CATALOG = "workspace"
BRONZE = f"{CATALOG}.airline_bronze"
STAGING = f"{CATALOG}.airline_staging"
AUDIT_TABLE = f"{STAGING}.etl_audit"

# Source schema -> source_system tag (and bronze table prefix)
SOURCES = {"mainline_carrier": "mainline", "regional_partner": "regional"}

# One id for the whole job run; the next tasks read it back via task values.
run_ts = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
run_id = run_ts.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
try:
    dbutils.jobs.taskValues.set(key="run_id", value=run_id)
except Exception:
    pass  # running interactively, outside a job
print("run_id:", run_id)

# COMMAND ----------

# Audit table shared by all ETL steps (created once, then appended to).
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {AUDIT_TABLE} (
  run_id       STRING    COMMENT 'ETL run identifier',
  run_ts       TIMESTAMP COMMENT 'When the run started (UTC)',
  layer        STRING    COMMENT 'bronze / staging / gold',
  table_name   STRING    COMMENT 'Table the counts refer to',
  step         STRING    COMMENT 'What was done (extract, dedupe, ...)',
  rows_before  BIGINT    COMMENT 'Rows before the step',
  rows_after   BIGINT    COMMENT 'Rows after the step',
  rows_removed BIGINT    COMMENT 'rows_before - rows_after',
  note         STRING    COMMENT 'Human-readable explanation'
) COMMENT 'Before/after row counts for every ETL step (Flow 1 audit trail)'
""")

AUDIT_SCHEMA = T.StructType([
    T.StructField("run_id", T.StringType()),
    T.StructField("run_ts", T.TimestampType()),
    T.StructField("layer", T.StringType()),
    T.StructField("table_name", T.StringType()),
    T.StructField("step", T.StringType()),
    T.StructField("rows_before", T.LongType()),
    T.StructField("rows_after", T.LongType()),
    T.StructField("rows_removed", T.LongType()),
    T.StructField("note", T.StringType()),
])

# COMMAND ----------

def list_tables(conn, schema):
    rows = conn.execute(
        """SELECT table_name FROM information_schema.tables
           WHERE table_schema = %s AND table_type = 'BASE TABLE'
           ORDER BY table_name""", (schema,)).fetchall()
    return [r[0] for r in rows]


def list_columns(conn, schema, table):
    rows = conn.execute(
        """SELECT column_name FROM information_schema.columns
           WHERE table_schema = %s AND table_name = %s
           ORDER BY ordinal_position""", (schema, table)).fetchall()
    return [r[0] for r in rows]


def read_as_text(conn, schema, table, columns):
    """SELECT col::text AS col, ... so every value arrives exactly as Postgres prints it."""
    query = sql.SQL("SELECT {cols} FROM {sch}.{tbl}").format(
        cols=sql.SQL(", ").join(
            sql.SQL("{c}::text AS {c}").format(c=sql.Identifier(c)) for c in columns),
        sch=sql.Identifier(schema),
        tbl=sql.Identifier(table),
    )
    return conn.execute(query).fetchall()

# COMMAND ----------

url = dbutils.secrets.get("airline", "supabase_url")
audit_rows, summary = [], []

with psycopg.connect(url, connect_timeout=15) as conn:
    conn.read_only = True                       # extra safety on top of the read-only login
    conn.execute("SET TIME ZONE 'UTC'")         # timestamptz values printed in UTC (+00)
    conn.execute("SET statement_timeout = '60s'")

    for source_schema, source_system in SOURCES.items():
        tables = list_tables(conn, source_schema)
        print(f"{source_schema}: {len(tables)} tables -> {tables}")

        for table in tables:
            columns = list_columns(conn, source_schema, table)
            rows = read_as_text(conn, source_schema, table, columns)

            raw_schema = T.StructType([T.StructField(c, T.StringType(), True) for c in columns])
            df = (spark.createDataFrame(rows, raw_schema)
                  .withColumn("source_system", F.lit(source_system))
                  .withColumn("source_table", F.lit(f"{source_schema}.{table}"))
                  .withColumn("_run_id", F.lit(run_id))
                  .withColumn("_extracted_at", F.lit(run_ts)))

            target = f"{BRONZE}.{source_system}_{table}"
            (df.write.mode("overwrite")
               .option("overwriteSchema", "true")
               .saveAsTable(target))

            bronze_count = spark.table(target).count()
            status = "OK" if bronze_count == len(rows) else "MISMATCH"
            summary.append((target, len(rows), bronze_count, len(columns), status))
            audit_rows.append((run_id, run_ts, "bronze", target, "extract",
                               len(rows), bronze_count, len(rows) - bronze_count,
                               f"{len(columns)} source columns copied as STRING from {source_schema}.{table}"))

spark.createDataFrame(audit_rows, AUDIT_SCHEMA).write.mode("append").saveAsTable(AUDIT_TABLE)

# COMMAND ----------

result = spark.createDataFrame(
    summary, "bronze_table STRING, source_rows LONG, bronze_rows LONG, columns INT, status STRING")
display(result.orderBy("bronze_table"))

mismatches = [s for s in summary if s[4] != "OK"]
if mismatches:
    raise RuntimeError(f"Row-count mismatch between source and bronze: {mismatches}")
print(f"Extract complete: {len(summary)} tables, {sum(s[2] for s in summary)} rows, run_id {run_id}")
