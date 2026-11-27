"""
dashboard/dbx_utils.py  (Fatema - Member 2)
Databricks helper used by page 2_Warehouse. Everything goes over Databricks' REST APIs with
`requests` (already installed with Streamlit), so no extra driver package is needed:
  * query_df()      - run a SELECT on the SQL warehouse   (SQL Statement Execution API 2.0)
  * start_sync()    - trigger the ETL Job airline_etl_flow1 (Jobs API 2.2 run-now)
  * wait_for_run()  - poll the run until it finishes, reporting each task's progress

Secrets (.streamlit/secrets.toml locally, or Streamlit Cloud -> Settings -> Secrets):
    [databricks]
    host      = "dbc-xxxxxxxx-xxxx.cloud.databricks.com"   # workspace URL, no https://
    http_path = "/sql/1.0/warehouses/xxxxxxxxxxxxxxxx"      # SQL warehouse -> Connection details
    token     = "dapi..."                                    # personal access token (scopes: sql, jobs)
    job_id    = 123456789012345                              # Jobs & Pipelines -> airline_etl_flow1
Environment variables DATABRICKS_HOST / _HTTP_PATH / _TOKEN / _JOB_ID work too (local runs).

The token is only sent to the workspace in an Authorization header; it is never shown on the page.
"""
from __future__ import annotations

import datetime as dt
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd
import requests
import streamlit as st

CATALOG = "workspace"
BRONZE = f"{CATALOG}.airline_bronze"
GOLD = f"{CATALOG}.airline_gold"
STAGING = f"{CATALOG}.airline_staging"
AUDIT = f"{STAGING}.etl_audit"
JOB_NAME = "airline_etl_flow1"
TASK_ORDER = ["extract_bronze", "staging", "gold", "analytics"]   # the 4 Job tasks, in run order

BAHRAIN = dt.timezone(dt.timedelta(hours=3), "Bahrain")            # UTC+3 all year (no daylight saving)
JOBS_API = "/api/2.2/jobs"
SQL_API = "/api/2.0/sql/statements"
TERMINAL_STATES = {"TERMINATED", "SKIPPED", "INTERNAL_ERROR"}
SQL_WAIT_LIMIT = 180   # seconds: a stopped serverless warehouse needs a little time to wake up


class DatabricksError(RuntimeError):
    """A readable error for the page (never contains the token)."""


# ------------------------------------------------------------------------------------------
# Settings
# ------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Settings:
    host: str
    http_path: str
    token: str
    job_id: int

    @property
    def warehouse_id(self) -> str:
        return self.http_path.rstrip("/").rsplit("/", 1)[-1]


def _read_secrets() -> tuple[dict, str]:
    """The [databricks] section of secrets.toml, plus a plain-English reason when it is missing."""
    try:
        return dict(st.secrets["databricks"]), ""
    except KeyError:
        return {}, ("there is no [databricks] section in .streamlit/secrets.toml - paste it into secrets.toml "
                    "(not secrets.toml.example), press Ctrl+S, then restart Streamlit")
    except Exception as exc:   # missing file or a typing mistake in the TOML (shown without any secret values)
        return {}, f".streamlit/secrets.toml could not be read ({exc.__class__.__name__}: {str(exc)[:200]})"


def settings() -> Settings:
    cfg, reason = _read_secrets()
    values = {
        "host": cfg.get("host") or os.getenv("DATABRICKS_HOST", ""),
        "http_path": cfg.get("http_path") or os.getenv("DATABRICKS_HTTP_PATH", ""),
        "token": cfg.get("token") or os.getenv("DATABRICKS_TOKEN", ""),
        "job_id": cfg.get("job_id") or os.getenv("DATABRICKS_JOB_ID", ""),
    }
    problems = [k for k, v in values.items() if not str(v).strip() or "<" in str(v) or "xxxx" in str(v)]
    if problems:
        if reason and len(problems) == len(values):
            raise DatabricksError(f"Databricks is not configured: {reason}.")
        raise DatabricksError(
            "Databricks is not configured: in the [databricks] section of .streamlit/secrets.toml these are "
            f"missing or still a placeholder: {', '.join(problems)}.")
    host = str(values["host"]).strip().removeprefix("https://").removeprefix("http://").strip("/")
    http_path = str(values["http_path"]).strip()
    if "/warehouses/" not in http_path:
        raise DatabricksError("[databricks] http_path must look like /sql/1.0/warehouses/<id> "
                              "(SQL Warehouses -> your warehouse -> Connection details).")
    try:
        job_id = int(str(values["job_id"]).strip())
    except ValueError as exc:
        raise DatabricksError("[databricks] job_id must be the number shown in Job details.") from exc
    return Settings(host, http_path, str(values["token"]).strip(), job_id)


# ------------------------------------------------------------------------------------------
# One HTTP helper for both APIs
# ------------------------------------------------------------------------------------------
def _hint(path: str, status: int) -> str:
    scope = "sql" if path.startswith("/api/2.0/sql") else "jobs"
    return {
        400: "the request was rejected - check job_id / http_path",
        401: "the token is wrong or expired - create a new one",
        403: f"the token needs the '{scope}' scope (Read + Write) and permission on it",
        404: "not found - check host, job_id and http_path",
        429: "too many requests - wait a moment",
    }.get(status, "")


def _api(method: str, path: str, *, params: dict | None = None, payload: dict | None = None) -> dict:
    s = settings()
    try:
        resp = requests.request(method, f"https://{s.host}{path}",
                                headers={"Authorization": f"Bearer {s.token}"},
                                params=params, json=payload, timeout=60)
    except requests.RequestException as exc:
        raise DatabricksError(f"Could not reach Databricks ({exc.__class__.__name__}). "
                              "Check the host in secrets.toml and your internet connection.") from exc
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("message", "")
        except ValueError:
            detail = resp.text[:200]
        hint = _hint(path, resp.status_code)
        raise DatabricksError(f"Databricks API {path} failed with HTTP {resp.status_code}"
                              f"{' - ' + hint if hint else ''}. {detail}".strip())
    return resp.json() if resp.content else {}


# ------------------------------------------------------------------------------------------
# SQL warehouse (Statement Execution API)
# ------------------------------------------------------------------------------------------
def _typed(values: pd.Series, type_name: str) -> pd.Series:
    """JSON_ARRAY results arrive as text; give each column its real type."""
    t = (type_name or "STRING").upper()
    if t in ("BYTE", "SHORT", "INT", "LONG", "DECIMAL", "DOUBLE", "FLOAT"):
        return pd.to_numeric(values)
    if t == "BOOLEAN":
        return values.map({"true": True, "false": False})
    if t == "DATE":
        return values.map(lambda v: dt.date.fromisoformat(v[:10]) if isinstance(v, str) else None)
    if t.startswith("TIMESTAMP"):
        return pd.to_datetime(values, errors="coerce")
    return values


def query_df(statement: str) -> pd.DataFrame:
    """Run one SELECT on the SQL warehouse and return a typed DataFrame.
    Waits (up to 3 minutes) if the serverless warehouse has auto-stopped and is waking up."""
    s = settings()
    resp = _api("POST", SQL_API, payload={
        "warehouse_id": s.warehouse_id, "statement": statement, "wait_timeout": "30s",
        "on_wait_timeout": "CONTINUE", "format": "JSON_ARRAY", "disposition": "INLINE"})
    deadline = time.monotonic() + SQL_WAIT_LIMIT
    while (resp.get("status") or {}).get("state") in ("PENDING", "RUNNING"):
        if time.monotonic() > deadline:
            raise DatabricksError("The SQL warehouse did not answer within 3 minutes - is it running?")
        time.sleep(2)
        resp = _api("GET", f"{SQL_API}/{resp['statement_id']}")
    status = resp.get("status") or {}
    if status.get("state") != "SUCCEEDED":
        error = status.get("error") or {}
        raise DatabricksError(f"SQL warehouse query {status.get('state', 'failed').lower()}: "
                              f"{error.get('message', 'no details')[:400]}")
    columns = ((resp.get("manifest") or {}).get("schema") or {}).get("columns") or []
    result = resp.get("result") or {}
    rows = list(result.get("data_array") or [])
    next_link = result.get("next_chunk_internal_link")
    while next_link:                                   # large results come in chunks
        chunk = _api("GET", next_link)
        rows += chunk.get("data_array") or []
        next_link = chunk.get("next_chunk_internal_link")
    df = pd.DataFrame(rows, columns=[c["name"] for c in columns])
    for c in columns:
        df[c["name"]] = _typed(df[c["name"]], c.get("type_name", "STRING"))
    return df


# ------------------------------------------------------------------------------------------
# Jobs API
# ------------------------------------------------------------------------------------------
@dataclass
class TaskInfo:
    key: str
    life_cycle: str
    result: str | None
    seconds: float | None


@dataclass
class RunInfo:
    run_id: int
    life_cycle: str                  # QUEUED / PENDING / RUNNING / TERMINATING / TERMINATED ...
    result: str | None               # SUCCESS / FAILED / CANCELED / TIMEDOUT ... (None while running)
    message: str
    url: str
    trigger: str                     # ONE_TIME (Run now / Sync now) / PERIODIC (schedule) / RETRY
    started: dt.datetime | None
    ended: dt.datetime | None
    seconds: float | None
    tasks: list[TaskInfo] = field(default_factory=list)

    @property
    def done(self) -> bool:
        return self.life_cycle in TERMINAL_STATES

    @property
    def succeeded(self) -> bool:
        return self.done and self.result == "SUCCESS"


def _ms_to_local(ms) -> dt.datetime | None:
    return dt.datetime.fromtimestamp(ms / 1000, tz=BAHRAIN) if ms else None


def _seconds(start_ms, end_ms) -> float | None:
    if not start_ms:
        return None
    end_ms = end_ms or time.time() * 1000
    return max(0.0, (end_ms - start_ms) / 1000)


def summarize(run: dict) -> RunInfo:
    state = run.get("state") or {}
    tasks = []
    for t in run.get("tasks") or []:
        t_state = t.get("state") or {}
        tasks.append(TaskInfo(t.get("task_key", "?"), t_state.get("life_cycle_state", "PENDING"),
                              t_state.get("result_state"), _seconds(t.get("start_time"), t.get("end_time"))))
    tasks.sort(key=lambda t: TASK_ORDER.index(t.key) if t.key in TASK_ORDER else len(TASK_ORDER))
    return RunInfo(
        run_id=int(run.get("run_id", 0)),
        life_cycle=state.get("life_cycle_state", "PENDING"),
        result=state.get("result_state"),
        message=state.get("state_message", ""),
        url=run.get("run_page_url", ""),
        trigger=run.get("trigger", ""),
        started=_ms_to_local(run.get("start_time")),
        ended=_ms_to_local(run.get("end_time")),
        seconds=_seconds(run.get("start_time"), run.get("end_time")),
        tasks=tasks,
    )


def start_sync() -> int:
    """Trigger the ETL Job (Jobs API run-now) and return the new run id."""
    return int(_api("POST", f"{JOBS_API}/run-now", payload={"job_id": settings().job_id})["run_id"])


def get_run(run_id: int) -> RunInfo:
    return summarize(_api("GET", f"{JOBS_API}/runs/get", params={"run_id": run_id}))


def _runs(**filters) -> list[dict]:
    params = {"job_id": settings().job_id, "limit": 1, **filters}
    return _api("GET", f"{JOBS_API}/runs/list", params=params).get("runs") or []


def active_run() -> RunInfo | None:
    """A run of the Job that is still queued/running (e.g. started by a teammate), if any."""
    runs = _runs(active_only="true")
    return summarize(runs[0]) if runs else None


def last_finished_run() -> RunInfo | None:
    runs = _runs(completed_only="true")
    return summarize(runs[0]) if runs else None


def job_schedule() -> str:
    """Human-readable schedule of the Job, e.g. 'Daily at 03:30 (Asia/Bahrain)', or 'On demand only'."""
    job = _api("GET", f"{JOBS_API}/get", params={"job_id": settings().job_id})
    schedule = (job.get("settings") or {}).get("schedule")
    if not schedule:
        return "On demand only (no schedule yet)"
    paused = " - paused" if schedule.get("pause_status") == "PAUSED" else ""
    tz = schedule.get("timezone_id", "UTC")
    parts = str(schedule.get("quartz_cron_expression", "")).split()
    if len(parts) >= 6 and parts[1].isdigit() and parts[2].isdigit() and parts[3] in ("*", "?") \
            and parts[4] == "*" and parts[5] in ("*", "?"):
        return f"Daily at {int(parts[2]):02d}:{int(parts[1]):02d} ({tz}){paused}"
    return f"Cron {schedule.get('quartz_cron_expression')} ({tz}){paused}"


def wait_for_run(run_id: int, on_update: Callable[[RunInfo], None] | None = None,
                 poll_seconds: float = 5, timeout_seconds: float = 1200) -> RunInfo:
    """Poll the run until it reaches a final state; call on_update(RunInfo) after every poll."""
    deadline = time.monotonic() + timeout_seconds
    failures = 0
    while True:
        try:
            info = get_run(run_id)
            failures = 0
        except DatabricksError:
            failures += 1          # a network blip should not abort a 3-minute sync
            if failures >= 4:
                raise
            time.sleep(poll_seconds)
            continue
        if on_update:
            on_update(info)
        if info.done:
            return info
        if time.monotonic() > deadline:
            raise DatabricksError(f"The run is still going after {timeout_seconds // 60:.0f} minutes - "
                                  f"open it in Databricks: {info.url}")
        time.sleep(poll_seconds)


def to_local(value) -> dt.datetime | None:
    """A TIMESTAMP from the warehouse (UTC) as Bahrain time."""
    if value is None:
        return None
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert(BAHRAIN).to_pydatetime()
