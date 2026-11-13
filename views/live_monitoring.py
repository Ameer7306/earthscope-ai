"""Live Earth Monitoring: near-real-time NASA detections, fires, rainfall and satellite layers."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from backend import database as db
from backend.nasa_api import DataSourceError
from core import controls, state
from core.config import settings
from visualization import charts, maps
from visualization.animations import badges, category_color, hero, kpi_card, loading

hero("Live Earth Monitoring", "Near-real-time environmental detections from NASA services — refreshed on demand, "
                              "never simulated.")

cfg = settings()
firms_key = cfg["FIRMS_MAP_KEY"]

top = st.columns([1.1, 1.1, 1.3, 1.2, 0.9])
days = top[0].selectbox("Time window", [7, 14, 30, 60], index=2, format_func=lambda d: f"Last {d} days")
status = top[1].selectbox("Event status", ["open", "all"], format_func=lambda s: "Active (open)" if s == "open" else "Open + closed")
layer = top[2].selectbox("Satellite layer", ["True colour – VIIRS SNPP", "True colour – MODIS Terra",
                                             "Precipitation rate – GPM IMERG", "Aerosol optical depth – MODIS",
                                             "Land surface temp – MODIS (day)"])
include_fb = top[3].toggle("Include meteor fireballs (JPL)", value=False)
with top[4]:
    st.write("")
    if st.button("🔄 Refresh", width="stretch", type="primary"):
        state.load_eonet.clear()
        state.load_firms.clear()
        state.load_daily.clear()
        st.session_state["live_refreshed"] = datetime.now(timezone.utc)
        st.rerun()

st.session_state.setdefault("live_refreshed", datetime.now(timezone.utc))

# ---------------------------------------------------------------- load real data
events, err = pd.DataFrame(), None
try:
    with loading("Contacting NASA EONET…"):
        events = state.load_eonet(days, status)
        db.store_alerts(events)
except Exception as e:
    err = str(e)

fires, firms_err = pd.DataFrame(), None
if firms_key:
    try:
        with loading("Loading NASA FIRMS active fires (VIIRS, last 24 h)…"):
            fires = state.load_firms(firms_key, "VIIRS_SNPP_NRT", "world", 1)
    except Exception as e:
        firms_err = str(e)

if include_fb:
    try:
        fb = state.load_fireballs(30)
        fb = fb[fb["time"] >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=365)]
        events = pd.concat([events, fb], ignore_index=True).sort_values("time", ascending=False)
    except Exception as e:
        st.warning(f"Fireball data unavailable: {e}")

# ---------------------------------------------------------------- freshness + mode
now = pd.Timestamp.now(tz="UTC")
latest = events["time"].max() if not events.empty else None
age_h = (now - latest).total_seconds() / 3600 if latest is not None else None
fresh = ("live", f"Fresh · latest observation {age_h:.0f} h ago") if age_h is not None and age_h <= 48 else \
        ("stale", f"Latest observation {age_h / 24:.0f} days ago" if age_h is not None else "No data")
b = [fresh, ("nasa", "Near-real-time (NRT) data")]
b.append(("live", "FIRMS connected") if firms_key and not firms_err else ("demo", "DEMO MODE · FIRMS key not configured"))
badges(*b)
st.caption(f"Last refreshed {st.session_state['live_refreshed'].strftime('%Y-%m-%d %H:%M:%S UTC')} · "
           "events cached 30 min, fires 15 min, with automatic retry on rate limits.")

if err:
    st.error(f"NASA EONET could not be reached: {err}. No events are shown rather than inventing any.")
if not firms_key:
    st.info("**DEMO MODE for active-fire pixels.** NASA FIRMS needs a free MAP_KEY "
            "(https://firms.modaps.eosdis.nasa.gov/api/map_key/). Add `FIRMS_MAP_KEY` to `.env` to plot individual "
            "VIIRS fire detections. Until then, fires shown here are the real wildfire *events* tracked by NASA EONET.")
elif firms_err:
    st.warning(f"FIRMS error: {firms_err}")

# ---------------------------------------------------------------- KPIs
wild = events[events["category"] == "Wildfires"] if not events.empty else events
storms = events[events["category"] == "Severe Storms"] if not events.empty else events
k = st.columns(5)
with k[0]:
    kpi_card("Detections", int(len(events)), f"last {days} days", "📡")
with k[1]:
    kpi_card("Wildfire events", int(len(wild)), "NASA EONET", "🔥", 0.08, "#F97316")
with k[2]:
    kpi_card("Severe storms", int(len(storms)), "NASA EONET", "🌀", 0.16, "#38BDF8")
with k[3]:
    kpi_card("Fire pixels (24 h)", int(len(fires)) if firms_key and not firms_err else "—",
             "NASA FIRMS VIIRS" if firms_key else "needs FIRMS key", "🛰️", 0.24, "#EF4444")
with k[4]:
    kpi_card("Categories", int(events["category"].nunique()) if not events.empty else 0, "event types", "🏷️", 0.32, "#14B8A6")

# ---------------------------------------------------------------- map
cats = sorted(events["category"].unique()) if not events.empty else []
chosen = st.multiselect("Event categories", cats, default=cats)
shown = events[events["category"].isin(chosen)] if cats else events

tab_map, tab_list, tab_rain = st.tabs(["🗺️ Detection map", "📋 Detection list", "🌧️ Rainfall monitoring"])
with tab_map:
    img_day = date.today() - timedelta(days=1)
    m = maps.base_map((15, 10), 2, "Blue Marble (static)", layer, img_day, 0.85)
    maps.add_fires(m, fires)
    maps.add_events(m, shown)
    maps.finish(m)
    st_folium(m, height=540, use_container_width=True, key="live_map", returned_objects=[])
    legend = " ".join(f'<span style="color:{category_color(c)}">●</span> {c}' for c in chosen)
    st.markdown(f"<div style='font-size:.85rem;color:#94A3B8'>{legend}</div>", unsafe_allow_html=True)
    st.caption(f"Satellite layer: {layer} for {img_day.isoformat()} (NASA GIBS, near-real-time).")

with tab_list:
    if shown.empty:
        st.info("No detections for this selection.")
    else:
        tbl = shown.copy()
        tbl["Observed (UTC)"] = tbl["time"].dt.strftime("%Y-%m-%d %H:%M")
        tbl["Age"] = ((now - tbl["time"]).dt.total_seconds() / 3600).apply(lambda h: f"{h:.0f} h" if h < 72 else f"{h / 24:.0f} d")
        tbl = tbl.rename(columns={"title": "Event", "category": "Category", "lat": "Lat", "lon": "Lon",
                                  "data_source": "Data source", "source": "Reported by", "link": "Details"})
        st.dataframe(tbl[["Observed (UTC)", "Age", "Category", "Event", "Lat", "Lon", "Data source", "Reported by", "Details"]],
                     width="stretch", hide_index=True, height=440,
                     column_config={"Details": st.column_config.LinkColumn(display_text="Open ↗"),
                                    "Lat": st.column_config.NumberColumn(format="%.2f"),
                                    "Lon": st.column_config.NumberColumn(format="%.2f")})
        st.download_button("Download detections (CSV)", tbl.drop(columns=["time"]).to_csv(index=False).encode("utf-8"),
                           "earthscope_detections.csv", "text/csv")
    if firms_key and not fires.empty:
        st.markdown("**Brightest FIRMS fire pixels (last 24 h)**")
        cols = [c for c in ["time", "lat", "lon", "frp", "bright_ti4", "confidence", "daynight"] if c in fires.columns]
        st.dataframe(fires.sort_values("frp", ascending=False).head(50)[cols], width="stretch", hide_index=True)

rain_summary = None
with tab_rain:
    rc1, rc2 = st.columns([1, 2.4])
    with rc1:
        region = controls.region_select("Rainfall location")
        loc = state.all_regions()[region]
        st.caption("Daily precipitation from NASA POWER (MERRA-2 / IMERG based). Latency is typically 2–7 days; "
                   "the newest days are near-real-time estimates that are later revised.")
    with rc2:
        try:
            with loading(f"Loading daily rainfall for {region}…"):
                daily = state.load_daily(loc["lat"], loc["lon"], "PRECTOTCORR", 60)
            s = daily["PRECTOTCORR"].dropna()
            if s.empty:
                st.info("No recent daily rainfall values are available yet for this point.")
            else:
                r = st.columns(4)
                r[0].metric("Latest day", f"{s.iloc[-1]:.1f} mm", s.index[-1].strftime("%d %b"), delta_color="off")
                r[1].metric("Last 7 days", f"{s.iloc[-7:].sum():.1f} mm")
                r[2].metric("Last 30 days", f"{s.iloc[-30:].sum():.1f} mm")
                r[3].metric("Wettest day", f"{s.max():.1f} mm", s.idxmax().strftime("%d %b"), delta_color="off")
                st.plotly_chart(charts.daily_bars(s, f"Daily precipitation — {region}", "mm/day"), width="stretch")
                lag = (date.today() - s.index[-1].date()).days
                badges(("live" if lag <= 7 else "stale", f"Data through {s.index[-1].date()} ({lag} days behind today)"),
                       ("nasa", "NASA POWER · NRT"))
                rain_summary = (f"{region}: latest {s.iloc[-1]:.1f} mm on {s.index[-1].date()}, 7-day total "
                                f"{s.iloc[-7:].sum():.1f} mm, 30-day total {s.iloc[-30:].sum():.1f} mm (NASA POWER daily)")
        except DataSourceError as e:
            st.warning(f"Rainfall data unavailable: {e}")
    st.caption("For a global view, choose “Precipitation rate – GPM IMERG” as the satellite layer on the Detection map.")

with st.expander("Near-real-time vs research-quality data"):
    st.markdown("""
| | Near-real-time (shown on this page) | Research-quality (used for trends) |
|---|---|---|
| **Latency** | minutes to a few days | weeks to months |
| **Examples** | FIRMS fire pixels, GIBS imagery, IMERG Early/Late, LANCE products, EONET events | IMERG Final, MERRA-2, MOD13Q1, GISTEMP |
| **Calibration** | preliminary; may be revised or reprocessed | fully calibrated and quality-controlled |
| **Use for** | situational awareness, monitoring | long-term trend and significance analysis |
""")

# ---------------------------------------------------------------- context for the assistant
latest_fire = None
if firms_key and not fires.empty:
    f0 = fires.iloc[0]
    latest_fire = (f"FIRMS VIIRS pixel at {f0['lat']:.2f}, {f0['lon']:.2f}, {f0['time']:%Y-%m-%d %H:%M} UTC, "
                   f"FRP {f0.get('frp', float('nan'))} MW")
elif not wild.empty:
    w0 = wild.iloc[0]
    latest_fire = (f"{w0['title']} — {w0['time']:%Y-%m-%d %H:%M} UTC at {w0['lat']:.2f}, {w0['lon']:.2f} "
                   f"(NASA EONET wildfire event, source {w0['source']})")
state.publish("live", {
    "mode": "LIVE (EONET + FIRMS)" if firms_key and not firms_err else "LIVE EONET; FIRMS in DEMO MODE (no key)",
    "refreshed": st.session_state["live_refreshed"].strftime("%Y-%m-%d %H:%M UTC"),
    "n_events": int(len(events)),
    "by_category": events["category"].value_counts().to_dict() if not events.empty else {},
    "latest_fire": latest_fire,
    "firms_summary": f"{len(fires)} VIIRS fire pixels in last 24 h" if firms_key and not firms_err else None,
    "latest": [f"{e['time']:%Y-%m-%d %H:%M} UTC | {e['category']} | {e['title']} | {e['lat']:.2f}, {e['lon']:.2f} | {e['data_source']}"
               for _, e in events.head(8).iterrows()],
    "rain": rain_summary,
})
