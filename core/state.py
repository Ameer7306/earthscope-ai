"""
Shared Streamlit session state and cached data loaders.

Pages publish what they display (selected region, results, detections) into
`st.session_state["ctx"]`, which the AI assistant reads to answer context-aware questions.
"""
from __future__ import annotations

import uuid

import pandas as pd
import streamlit as st

from backend import database as db
from backend import nasa_api
from core.config import (DEFAULT_ALPHA, DEFAULT_REGION, DEFAULT_START_YEAR, DEFAULT_VARIABLE,
                         LATEST_FULL_YEAR, REGIONS, VARIABLES)


def init_state() -> None:
    ss = st.session_state
    ss.setdefault("session_id", uuid.uuid4().hex[:12])
    ss.setdefault("g_region", DEFAULT_REGION)
    ss.setdefault("g_variable", DEFAULT_VARIABLE)
    ss.setdefault("g_years", (DEFAULT_START_YEAR, LATEST_FULL_YEAR))
    ss.setdefault("g_sampling", "point")
    ss.setdefault("g_alpha", DEFAULT_ALPHA)
    ss.setdefault("custom_regions", {})
    ss.setdefault("chat", [])
    ss.setdefault("ctx", {})
    ss.setdefault("animations", True)


def all_regions() -> dict:
    """Built-in regions + saved (database) regions + session custom points."""
    regions = dict(REGIONS)
    try:
        regions.update(db.saved_regions())
    except Exception:
        pass
    regions.update(st.session_state.get("custom_regions", {}))
    return regions


def region_names() -> list[str]:
    return list(all_regions().keys())


def variable_names() -> list[str]:
    return list(VARIABLES.keys())


def var_label(key: str) -> str:
    return VARIABLES[key]["label"]


def publish(key: str, value) -> None:
    """Make information available to the AI assistant (and other pages)."""
    st.session_state["ctx"][key] = value


def set_page(name: str) -> None:
    st.session_state["ctx"]["current_page"] = name


# ---------------------------------------------------------------- cached loaders
@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _load_series(variable: str, region: str, start: int, end: int, sampling: str,
                 lat: float, lon: float, bbox: tuple | None) -> tuple[pd.DataFrame, dict]:
    custom = {region: {"lat": lat, "lon": lon, "bbox": bbox}}
    df, meta = nasa_api.fetch_series(variable, region, start, end, sampling, custom=custom)
    try:
        db.store_observations(df, meta)
    except Exception:
        pass
    return df, meta


def load_series(variable: str, region: str, start: int, end: int, sampling: str = "point"):
    loc = all_regions()[region]
    bbox = tuple(loc["bbox"]) if loc.get("bbox") else None
    return _load_series(variable, region, int(start), int(end), sampling, float(loc["lat"]), float(loc["lon"]), bbox)


@st.cache_data(ttl=12 * 3600, show_spinner=False)
def load_gistemp() -> pd.DataFrame:
    return nasa_api.fetch_gistemp_global()


@st.cache_data(ttl=1800, show_spinner=False)
def load_eonet(days: int = 30, status: str = "open") -> pd.DataFrame:
    return nasa_api.fetch_eonet(days=days, status=status)


@st.cache_data(ttl=900, show_spinner=False)
def load_firms(key: str, source: str, area: str, days: int) -> pd.DataFrame:
    return nasa_api.fetch_firms(key, source, area, days)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def load_fireballs(limit: int = 30) -> pd.DataFrame:
    return nasa_api.fetch_fireballs(limit)


@st.cache_data(ttl=3 * 3600, show_spinner=False)
def load_daily(lat: float, lon: float, param: str, days: int = 60) -> pd.DataFrame:
    from datetime import date, timedelta
    end = date.today()
    return nasa_api.fetch_power_daily(lat, lon, [param], end - timedelta(days=days), end)
