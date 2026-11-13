"""
Reusable selection widgets. Selections are stored in session state under g_* keys so every page
(and the AI assistant) shares the same region / variable / period.
"""
from __future__ import annotations

import streamlit as st

from analysis.trends import run_trend
from backend import database as db
from backend.nasa_api import DataSourceError
from core import state
from core.config import LATEST_FULL_YEAR, VARIABLES
from visualization.animations import loading


def region_select(label: str = "Region", key: str = "g_region", container=st) -> str:
    names = state.region_names()
    current = st.session_state.get(key, names[0])
    idx = names.index(current) if current in names else 0
    choice = container.selectbox(label, names, index=idx, help="Type to search countries, areas, cities and saved regions")
    st.session_state[key] = choice
    return choice


def variable_select(label: str = "Environmental variable", container=st) -> str:
    keys = state.variable_names()
    cur = st.session_state.get("g_variable", keys[0])
    choice = container.selectbox(label, keys, index=keys.index(cur) if cur in keys else 0,
                                 format_func=lambda k: f"{VARIABLES[k]['label']}  ·  {VARIABLES[k]['category']}")
    st.session_state["g_variable"] = choice
    return choice


def years_select(variable: str, container=st, label: str = "Time period") -> tuple[int, int]:
    lo = VARIABLES[variable]["start"]
    cur = st.session_state.get("g_years", (1991, LATEST_FULL_YEAR))
    cur = (max(lo, min(cur[0], LATEST_FULL_YEAR - 1)), min(LATEST_FULL_YEAR, cur[1]))
    if cur[1] <= cur[0]:
        cur = (lo, LATEST_FULL_YEAR)
    yrs = container.slider(label, lo, LATEST_FULL_YEAR, cur)
    st.session_state["g_years"] = yrs
    return yrs


def sampling_select(container=st) -> str:
    opts = {"point": "Representative point (fast)", "area": "Area mean · 3×3 grid (slower)"}
    cur = st.session_state.get("g_sampling", "point")
    choice = container.selectbox("Spatial sampling", list(opts), index=list(opts).index(cur),
                                 format_func=opts.get,
                                 help="Point = the grid cell at the region's capital/centre. Area = mean of 9 grid "
                                      "cells spread across the region's bounding box (cities and custom points use point).")
    st.session_state["g_sampling"] = choice
    return choice


def alpha_select(container=st) -> float:
    opts = [0.01, 0.05, 0.10]
    cur = st.session_state.get("g_alpha", 0.05)
    a = container.selectbox("Significance threshold (α)", opts, index=opts.index(cur) if cur in opts else 1)
    st.session_state["g_alpha"] = a
    return a


def get_series(variable: str, region: str, years: tuple[int, int], sampling: str):
    """Load a series with an animated loader; show a friendly error and stop the page on failure."""
    msg = "Downloading from NASA…" if VARIABLES[variable]["source"] == "power" else \
        "Downloading MODIS NDVI composites (first load can take ~30 s)…"
    try:
        with loading(f"{msg}  {VARIABLES[variable]['label']} · {region}"):
            return state.load_series(variable, region, years[0], years[1], sampling)
    except DataSourceError as e:
        st.error(f"NASA data could not be loaded: {e}")
        st.info("Check your internet connection and try again. No demo values are substituted for analysis.")
        st.stop()
    except Exception as e:  # unexpected parsing problems etc.
        st.error(f"Unexpected error while loading data: {type(e).__name__}: {e}")
        st.stop()


def analyse(df, variable: str, region: str, years, aggregation: str, method: str, alpha: float,
            kind: str = "trend") -> dict:
    """Run the trend engine and record the analysis once per unique configuration."""
    result = run_trend(df, aggregation, method, alpha)
    sig = (kind, variable, region, years, aggregation, method, alpha, st.session_state.get("g_sampling"))
    logged = st.session_state.setdefault("_logged", set())
    if sig not in logged:
        logged.add(sig)
        try:
            db.log_analysis(kind, variable, region, f"{years[0]}–{years[1]}", {
                k: result.get(k) for k in ("status", "significant", "p_value", "sen_slope_per_decade", "method",
                                           "aggregation", "n_valid", "missing_pct", "alpha")})
        except Exception:
            pass
    return result
