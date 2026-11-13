"""Overview dashboard: KPIs, global map, headline NASA trends, alerts and analysis history."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from analysis.trends import STATUS_LABEL, aggregate, run_trend
from backend import database as db
from backend.catalog import DATASETS
from backend.nasa_api import DataSourceError
from core import state
from core.config import COLORS, LATEST_FULL_YEAR, VARIABLES
from visualization import charts
from visualization.animations import (CATEGORY_COLORS, alert_row, badges, category_color, hero, kpi_card, loading)

hero("Earth system overview", "Live NASA observations, long-term trends and statistically tested change — in one place.",
     eyebrow="EarthScope AI · NASA Space Apps Challenge 2026")

# ---------------------------------------------------------------- live data (real NASA services)
events, events_err = pd.DataFrame(), None
try:
    with loading("Loading NASA EONET natural events…"):
        events = state.load_eonet(30, "open")
        db.store_alerts(events)
except Exception as e:
    events_err = str(e)

gis, gis_err = None, None
try:
    gis = state.load_gistemp()
except Exception as e:
    gis_err = str(e)

n_connected = sum(d["connected"] for d in DATASETS)
n_sig = db.count_significant_trends()
n_regions = db.regions_analysed()
latest = events["time"].max() if not events.empty else None

badges(("live" if not events_err else "stale", "Live NASA data" if not events_err else "NASA feed unreachable"),
       ("nasa", "GISTEMP · POWER · EONET · MODIS"))
st.write("")

# ---------------------------------------------------------------- KPI cards (each links to its page)
cols = st.columns(5)
kpis = [
    ("Datasets available", len(DATASETS), f"{n_connected} analysable in-app", "🗂️", "views/data_explorer.py", "Browse datasets", COLORS["primary"]),
    ("Active detections", int(len(events)), "open events · last 30 days (EONET)", "🔥", "views/live_monitoring.py", "Open live monitor", "#F97316"),
    ("Regions analysed", int(n_regions), "in your analysis history", "🗺️", "views/regional_comparison.py", "Compare regions", COLORS["secondary"]),
    ("Significant trends", int(n_sig), "identified by your analyses", "📈", "views/trend_analysis.py", "Run trend analysis", COLORS["positive"]),
    ("Latest NASA update", latest.strftime("%d %b %H:%M") if latest is not None else "—",
     "most recent event observation (UTC)", "🛰️", "views/live_monitoring.py", "See data freshness", "#A78BFA"),
]
for i, (c, (label, value, sub, icon, target, link, accent)) in enumerate(zip(cols, kpis)):
    with c:
        kpi_card(label, value, sub, icon, delay=i * 0.09, accent=accent)
        st.page_link(target, label=link, icon="➡️")

if n_regions == 0:
    st.caption("ℹ️ ‘Regions analysed’ and ‘Significant trends’ count your own analyses — they start at 0 and grow "
               "as you use Trend Analysis, Regional Comparison and the Opposite Trend Detector. Nothing here is sample data.")

# ---------------------------------------------------------------- globe + alerts
left, right = st.columns([3, 2], gap="large")
with left:
    st.subheader("Global Earth map")
    if events_err:
        st.warning(f"Live events unavailable: {events_err}")
    st.plotly_chart(charts.rotating_globe(events, CATEGORY_COLORS), width="stretch",
                    config={"displayModeBar": False, "scrollZoom": True})
    st.caption("Drag to spin, scroll to zoom, or press ▶ Rotate. Markers: open natural events from NASA EONET.")
with right:
    st.subheader("Recent environmental alerts")
    if events.empty:
        st.info("No live events could be loaded right now.")
    for i, (_, e) in enumerate(events.head(7).iterrows()):
        alert_row(e["title"], f"{e['category']} · {e['time'].strftime('%d %b %Y %H:%M UTC')} · "
                              f"{e['lat']:.1f}°, {e['lon']:.1f}° · {e['data_source']}",
                  category_color(e["category"]), delay=i * 0.06)
    st.page_link("views/live_monitoring.py", label="View all detections", icon="🔥")

# ---------------------------------------------------------------- headline charts
st.subheader("Global temperature")
if gis is not None:
    st.plotly_chart(charts.global_temp_chart(gis), width="stretch", config={"displayModeBar": False})
    ann = gis["value"].groupby(gis.index.year).agg(["mean", "count"])
    ann = ann[ann["count"] == 12]["mean"]
    gdf = pd.DataFrame({"value": gis["value"][gis.index.year >= 1980]})
    gres = run_trend(gdf[gdf.index.year <= ann.index.max()], "annual", "auto", 0.05)
    st.caption(f"NASA GISS GISTEMP v4 · latest complete year {ann.index.max()}: {ann.iloc[-1]:+.2f} °C · "
               f"1980–{ann.index.max()} Sen's slope {gres['sen_slope_per_decade']:+.2f} °C/decade "
               f"(Mann-Kendall p = {gres['p_value']:.2g}).")
    state.publish("overview", f"GISTEMP latest complete year {ann.index.max()} anomaly {ann.iloc[-1]:+.2f} °C; "
                              f"1980-{ann.index.max()} Sen slope {gres['sen_slope_per_decade']:+.3f} °C/decade, "
                              f"p={gres['p_value']:.3g}; open EONET events: {len(events)}")
else:
    st.warning(f"GISTEMP could not be loaded: {gis_err}")

region = st.session_state["g_region"]
c1, c2 = st.columns(2, gap="large")
for col, var, color in ((c1, "precipitation", COLORS["primary"]), (c2, "ndvi", COLORS["positive"])):
    with col:
        v = VARIABLES[var]
        st.subheader("Precipitation trend" if var == "precipitation" else "Vegetation monitoring")
        start = 1991 if var == "precipitation" else 2015
        try:
            with loading(f"Loading {v['label']} for {region}…"):
                df, meta = state.load_series(var, region, start, LATEST_FULL_YEAR, "point")
            res = run_trend(df, "annual", "auto", 0.05)
            st.plotly_chart(charts.trend_chart(df, res, v["label"], v["units"], region, "annual", show_ols=False,
                                               color=color), width="stretch", config={"displayModeBar": False})
            st.caption(f"{STATUS_LABEL[res['status']]}"
                       + (f" · Sen {res['sen_slope_per_decade']:+.3g} {v['units']}/decade, p = {res['p_value']:.3g}"
                          if res["status"] != "insufficient" else "") + f" · {meta['provider']}")
        except DataSourceError as e:
            st.warning(f"{v['label']} unavailable: {e}")
st.caption(f"Charts above use the globally selected region (**{region}**). Change it in Earth Explorer or Trend Analysis.")

# ---------------------------------------------------------------- history
st.subheader("Recent analysis history")
hist = db.analysis_history(8)
if hist.empty:
    st.info("No analyses yet. Run your first one in Trend Analysis.")
    st.page_link("views/trend_analysis.py", label="Start a trend analysis", icon="📈")
else:
    rows = []
    for _, h in hist.iterrows():
        r = json.loads(h["result_json"] or "{}")
        rows.append({"When (UTC)": h["created_at"][:16].replace("T", " "), "Type": h["analysis_type"],
                     "Variable": VARIABLES.get(h["variable"], {}).get("label", h["variable"]),
                     "Region": h["region"], "Period": h["period"],
                     "Result": STATUS_LABEL.get(r.get("status"), "—"),
                     "p-value": r.get("p_value"), "Sen slope / decade": r.get("sen_slope_per_decade")})
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True,
                 column_config={"p-value": st.column_config.NumberColumn(format="%.4f"),
                                "Sen slope / decade": st.column_config.NumberColumn(format="%.4g")})
