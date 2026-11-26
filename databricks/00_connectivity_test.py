# Databricks notebook source
# MAGIC %md
# MAGIC # 00 · Connectivity test (evidence for the report)
# MAGIC **Owner:** Fatema Alashiri (Member 2)
# MAGIC
# MAGIC Databricks Free Edition limits outbound internet access, so before building the
# MAGIC extract we checked that the workspace can reach Supabase, and that the ETL login
# MAGIC (`etl_reader`, created with `sql/postgres/11_read_only_role.sql`) is **read-only**.
# MAGIC
# MAGIC Result on 26 Nov 2026: Supabase reachable; 96 flights, 142 bookings, 44 routes,
# MAGIC 81 reservations read; `UPDATE` refused with *permission denied for table flight*.

# COMMAND ----------

# 1. Can serverless compute open a TCP connection to the Supabase session pooler?
import socket

host, port = "aws-1-ap-northeast-1.pooler.supabase.com", 5432
try:
    socket.create_connection((host, port), timeout=10).close()
    print(f"REACHABLE: Databricks can connect to {host}:{port}")
except Exception as e:
    print(f"BLOCKED: {type(e).__name__}: {e}")

# COMMAND ----------

# MAGIC %pip install "psycopg[binary]>=3.2,<4" --quiet

# COMMAND ----------

# 2. Read with the etl_reader login (stored in the Databricks secret scope "airline"),
#    then prove it cannot write. The UPDATE has WHERE false, so it would change nothing
#    even if it were allowed.
import psycopg

url = dbutils.secrets.get("airline", "supabase_url")
with psycopg.connect(url, connect_timeout=10) as conn:
    for schema, table in [("mainline_carrier", "flight"), ("mainline_carrier", "booking"),
                          ("regional_partner", "route"), ("regional_partner", "reservation")]:
        n = conn.execute(f"SELECT count(*) FROM {schema}.{table}").fetchone()[0]
        print(f"{schema}.{table}: {n} rows")
    try:
        conn.execute("UPDATE mainline_carrier.flight SET notes = notes WHERE false")
        print("WARNING: this login can write!")
    except psycopg.errors.InsufficientPrivilege as e:
        conn.rollback()
        print("READ-ONLY confirmed:", str(e).strip())
