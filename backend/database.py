"""
SQLite persistence layer.

The schema uses portable SQL types (TEXT/INTEGER/REAL, ISO timestamps, JSON stored as
TEXT) so it can be migrated to PostgreSQL / Supabase by swapping the connection
function. All queries use parameter binding.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from core.config import settings

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    category TEXT, variable TEXT, mission TEXT, source TEXT,
    spatial_resolution TEXT, temporal_resolution TEXT, coverage TEXT,
    update_frequency TEXT, doc_url TEXT, connected INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    variable TEXT NOT NULL, region TEXT NOT NULL, sampling TEXT NOT NULL,
    obs_date TEXT NOT NULL, value REAL, source TEXT,
    retrieved_at TEXT NOT NULL,
    UNIQUE(variable, region, sampling, obs_date)
);
CREATE TABLE IF NOT EXISTS analysis_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, analysis_type TEXT NOT NULL, variable TEXT, region TEXT,
    period TEXT, result_json TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS saved_regions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, name TEXT UNIQUE NOT NULL,
    lat REAL NOT NULL, lon REAL NOT NULL,
    south REAL, west REAL, north REAL, east REAL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS detection_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id TEXT UNIQUE, category TEXT, title TEXT,
    lat REAL, lon REAL, observed_at TEXT, source TEXT, link TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
    page TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS generated_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT, variable TEXT, region TEXT, period TEXT,
    formats TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_obs ON observations(variable, region, sampling);
CREATE INDEX IF NOT EXISTS idx_hist ON analysis_history(created_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_path() -> Path:
    p = Path(settings()["DATABASE_PATH"])
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@contextmanager
def connect():
    with _lock:
        con = sqlite3.connect(db_path(), check_same_thread=False)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()


def init_db() -> None:
    """Create tables, a default local user and seed the dataset catalogue."""
    from backend.catalog import DATASETS
    with connect() as con:
        con.executescript(SCHEMA)
        con.execute("INSERT OR IGNORE INTO users(username, created_at) VALUES (?, ?)", ("local", _now()))
        for d in DATASETS:
            con.execute(
                """INSERT OR IGNORE INTO datasets(name, category, variable, mission, source, spatial_resolution,
                   temporal_resolution, coverage, update_frequency, doc_url, connected)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (d["name"], d["category"], d["variable"], d["mission"], d["source"], d["spatial"],
                 d["temporal"], d["coverage"], d["update"], d["doc"], int(d["connected"])))


# ---------------------------------------------------------------- observations
def store_observations(df: pd.DataFrame, meta: dict) -> int:
    rows = [(meta["variable"], meta["region"], meta["sampling"], idx.strftime("%Y-%m-%d"),
             None if pd.isna(v) else float(v), meta["provider"], meta["retrieved"])
            for idx, v in df["value"].items()]
    with connect() as con:
        con.executemany(
            """INSERT INTO observations(variable, region, sampling, obs_date, value, source, retrieved_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(variable, region, sampling, obs_date) DO UPDATE SET
               value=excluded.value, retrieved_at=excluded.retrieved_at""", rows)
    return len(rows)


# ---------------------------------------------------------------- analysis history
def log_analysis(kind: str, variable: str, region: str, period: str, result: dict) -> None:
    with connect() as con:
        con.execute(
            "INSERT INTO analysis_history(user_id, analysis_type, variable, region, period, result_json, created_at)"
            " VALUES (1,?,?,?,?,?,?)", (kind, variable, region, period, json.dumps(result, default=str), _now()))


def analysis_history(limit: int = 20) -> pd.DataFrame:
    with connect() as con:
        return pd.read_sql_query(
            "SELECT id, analysis_type, variable, region, period, result_json, created_at "
            "FROM analysis_history ORDER BY id DESC LIMIT ?", con, params=(limit,))


def count_significant_trends() -> int:
    """Count distinct (variable, region) analyses whose result was statistically significant."""
    df = analysis_history(1000)
    seen = set()
    for _, r in df.iterrows():
        try:
            res = json.loads(r["result_json"])
        except Exception:
            continue
        if res.get("significant"):
            seen.add((r["variable"], r["region"]))
    return len(seen)


def regions_analysed() -> int:
    with connect() as con:
        return con.execute("SELECT COUNT(DISTINCT region) FROM analysis_history").fetchone()[0]


def clear_history() -> None:
    with connect() as con:
        con.execute("DELETE FROM analysis_history")


# ---------------------------------------------------------------- saved regions
def save_region(name: str, lat: float, lon: float, bbox: tuple | None = None) -> None:
    s, w, n, e = bbox if bbox else (None, None, None, None)
    with connect() as con:
        con.execute(
            """INSERT INTO saved_regions(user_id, name, lat, lon, south, west, north, east, created_at)
               VALUES (1,?,?,?,?,?,?,?,?)
               ON CONFLICT(name) DO UPDATE SET lat=excluded.lat, lon=excluded.lon, south=excluded.south,
               west=excluded.west, north=excluded.north, east=excluded.east""",
            (name, lat, lon, s, w, n, e, _now()))


def saved_regions() -> dict:
    with connect() as con:
        rows = con.execute("SELECT * FROM saved_regions ORDER BY name").fetchall()
    out = {}
    for r in rows:
        bbox = (r["south"], r["west"], r["north"], r["east"]) if r["south"] is not None else None
        out[r["name"]] = {"lat": r["lat"], "lon": r["lon"], "bbox": bbox, "type": "saved"}
    return out


def delete_region(name: str) -> None:
    with connect() as con:
        con.execute("DELETE FROM saved_regions WHERE name = ?", (name,))


# ---------------------------------------------------------------- alerts
def store_alerts(events: pd.DataFrame) -> int:
    if events is None or events.empty:
        return 0
    rows = [(str(e["id"]), e["category"], e["title"], float(e["lat"]), float(e["lon"]),
             pd.Timestamp(e["time"]).isoformat(), e["data_source"], e.get("link"), _now())
            for _, e in events.iterrows()]
    with connect() as con:
        con.executemany(
            """INSERT OR IGNORE INTO detection_alerts(external_id, category, title, lat, lon, observed_at,
               source, link, created_at) VALUES (?,?,?,?,?,?,?,?,?)""", rows)
    return len(rows)


def recent_alerts(limit: int = 10) -> pd.DataFrame:
    with connect() as con:
        return pd.read_sql_query(
            "SELECT category, title, lat, lon, observed_at, source, link FROM detection_alerts "
            "ORDER BY observed_at DESC LIMIT ?", con, params=(limit,))


def count_alerts() -> int:
    with connect() as con:
        return con.execute("SELECT COUNT(*) FROM detection_alerts").fetchone()[0]


# ---------------------------------------------------------------- chat + reports
def save_chat(session_id: str, role: str, content: str, page: str) -> None:
    with connect() as con:
        con.execute("INSERT INTO chat_sessions(session_id, role, content, page, created_at) VALUES (?,?,?,?,?)",
                    (session_id, role, content, page, _now()))


def log_report(title: str, variable: str, region: str, period: str, formats: str) -> None:
    with connect() as con:
        con.execute("INSERT INTO generated_reports(title, variable, region, period, formats, created_at)"
                    " VALUES (?,?,?,?,?,?)", (title, variable, region, period, formats, _now()))


def list_reports(limit: int = 20) -> pd.DataFrame:
    with connect() as con:
        return pd.read_sql_query("SELECT title, variable, region, period, formats, created_at "
                                 "FROM generated_reports ORDER BY id DESC LIMIT ?", con, params=(limit,))


def table_counts() -> dict:
    tables = ["users", "datasets", "observations", "analysis_history", "saved_regions",
              "detection_alerts", "chat_sessions", "generated_reports"]
    with connect() as con:
        return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
