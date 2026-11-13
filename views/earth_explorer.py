"""Earth Explorer: interactive global map with NASA GIBS satellite layers and location selection."""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st
from streamlit_folium import st_folium

from backend import database as db
from backend.nasa_api import GIBS_LAYERS, DataSourceError, gibs_tile_url
from core import controls, state
from core.config import COLORS, LATEST_FULL_YEAR, VARIABLES
from visualization import charts, maps
from visualization.animations import badges, hero, loading

hero("Earth Explorer", "Pan and zoom NASA satellite imagery, search places or coordinates, and pick a point or "
                       "region to analyse.")

# Which GIBS overlay best illustrates each variable
VAR_LAYER = {
    "precipitation": "Precipitation rate – GPM IMERG", "ndvi": "Vegetation NDVI – MODIS 8-day",
    "surface_temperature": "Land surface temp – MODIS (day)", "air_temperature": "Land surface temp – MODIS (day)",
    "max_temperature": "Land surface temp – MODIS (day)",
}

ctl, mp = st.columns([1, 2.6], gap="large")

with ctl:
    st.markdown("#### Find a place")
    mode = st.radio("Search by", ["Country / city", "Latitude & longitude"], horizontal=True, label_visibility="collapsed")
    if mode == "Country / city":
        region = controls.region_select("Search countries, areas and cities")
    else:
        with st.form("coord_form", border=False):
            c1, c2 = st.columns(2)
            lat = c1.number_input("Latitude", -90.0, 90.0, 25.29, step=0.1, format="%.3f")
            lon = c2.number_input("Longitude", -180.0, 180.0, 51.53, step=0.1, format="%.3f")
            go = st.form_submit_button("Go to coordinates", width="stretch")
        if go:
            name = f"Point {lat:.2f}, {lon:.2f}"
            st.session_state["custom_regions"][name] = {"lat": lat, "lon": lon, "bbox": None, "type": "custom"}
            st.session_state["g_region"] = name
            st.rerun()
        region = st.session_state["g_region"]
    loc = state.all_regions()[region]

    st.markdown("#### Data & layers")
    variable = controls.variable_select()
    base = st.selectbox("Base map", ["Blue Marble (static)", "True colour – MODIS Terra", "True colour – VIIRS SNPP",
                                     "Night lights – VIIRS Black Marble"])
    overlays = ["None"] + [k for k in GIBS_LAYERS if k not in ("Blue Marble (static)", "Night lights – VIIRS Black Marble")]
    suggested = VAR_LAYER.get(variable, "None")
    overlay = st.selectbox("Satellite observation layer", overlays, index=overlays.index(suggested),
                           help="Daily NASA GIBS imagery. The layer suggested for the selected variable is pre-selected.")
    day = st.date_input("Observation date", date.today() - timedelta(days=2), min_value=date(2000, 3, 1),
                        max_value=date.today(), help="Date of the satellite imagery (most layers lag 1–2 days).")
    opacity = st.slider("Layer opacity", 0.2, 1.0, 0.75, 0.05)
    years = controls.years_select(variable, label="Date range for the time series")

with mp:
    badges(("nasa", "NASA GIBS imagery"), ("live", f"Imagery date {day.isoformat()}"))
    zoom = 3 if loc.get("bbox") else 6
    m = maps.base_map((loc["lat"], loc["lon"]), zoom, base, None if overlay == "None" else overlay, day, opacity)
    maps.add_region(m, region, loc)
    maps.add_draw_tools(m)
    maps.finish(m)
    out = st_folium(m, height=560, use_container_width=True, key="explorer_map",
                    returned_objects=["last_clicked", "last_active_drawing"])
    st.caption("Click anywhere to select a point · use the ▢ tool (top-right) to draw a region · ⛶ for fullscreen.")

# ---------------------------------------------------------------- selections from the map
clicked = (out or {}).get("last_clicked")
drawing = (out or {}).get("last_active_drawing")

s1, s2, s3 = st.columns(3)
with s1:
    st.markdown("##### Selected location")
    st.metric(region, f"{loc['lat']:.3f}°, {loc['lon']:.3f}°")
    if loc.get("bbox"):
        s, w, n, e = loc["bbox"]
        st.caption(f"Region box: {s:.1f}°…{n:.1f}° lat, {w:.1f}°…{e:.1f}° lon")
with s2:
    st.markdown("##### Clicked point")
    if clicked:
        st.metric("Coordinates", f"{clicked['lat']:.3f}°, {clicked['lng']:.3f}°")
        if st.button("Analyse this point", width="stretch"):
            name = f"Point {clicked['lat']:.2f}, {clicked['lng']:.2f}"
            st.session_state["custom_regions"][name] = {"lat": clicked["lat"], "lon": clicked["lng"], "bbox": None, "type": "custom"}
            st.session_state["g_region"] = name
            st.rerun()
    else:
        st.caption("Click the map to pick a geographical point.")
with s3:
    st.markdown("##### Drawn region")
    if drawing and drawing.get("geometry", {}).get("type") == "Polygon":
        ring = drawing["geometry"]["coordinates"][0]
        lons, lats = [p[0] for p in ring], [p[1] for p in ring]
        bbox = (min(lats), min(lons), max(lats), max(lons))
        st.caption(f"{bbox[0]:.2f}°…{bbox[2]:.2f}° lat, {bbox[1]:.2f}°…{bbox[3]:.2f}° lon")
        rname = st.text_input("Name this region", "My region", max_chars=40)
        if st.button("Save & select region", width="stretch") and rname.strip():
            db.save_region(rname.strip(), (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2, bbox)
            st.session_state["g_region"] = rname.strip()
            st.session_state["g_sampling"] = "area"
            st.rerun()
    elif drawing and drawing.get("geometry", {}).get("type") == "Point":
        lon_, lat_ = drawing["geometry"]["coordinates"]
        st.caption(f"Marker at {lat_:.3f}°, {lon_:.3f}°")
        if st.button("Analyse marker", width="stretch"):
            name = f"Point {lat_:.2f}, {lon_:.2f}"
            st.session_state["custom_regions"][name] = {"lat": lat_, "lon": lon_, "bbox": None, "type": "custom"}
            st.session_state["g_region"] = name
            st.rerun()
    else:
        st.caption("Draw a rectangle on the map to define a region; saved regions appear in every region list.")

# ---------------------------------------------------------------- observations at the selection
st.divider()
v = VARIABLES[variable]
st.subheader(f"{v['label']} at {region}")
try:
    with loading(f"Loading {v['label']} for {region}…"):
        df, meta = state.load_series(variable, region, years[0], years[1], "point")
    s = df["value"].dropna()
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Latest month", f"{s.iloc[-1]:.3g} {v['units']}", s.index[-1].strftime("%b %Y"), delta_color="off")
    k2.metric("Period mean", f"{s.mean():.3g} {v['units']}")
    k3.metric("Minimum", f"{s.min():.3g}", s.idxmin().strftime("%b %Y"), delta_color="off")
    k4.metric("Maximum", f"{s.max():.3g}", s.idxmax().strftime("%b %Y"), delta_color="off")
    st.plotly_chart(charts.simple_line(df["value"], f"Monthly {v['label']} — {region}", v["units"]),
                    width="stretch")
    st.caption(f"Source: {meta['source']} · {meta['provider']}")
    state.publish("selection", {"region": region, "variable": variable, "start": years[0], "end": years[1],
                                "sampling": "point"})
    st.page_link("views/trend_analysis.py", label=f"Test this series for a trend", icon="📈")
except DataSourceError as e:
    st.error(f"Could not load data: {e}")

if overlay != "None":
    _, d = gibs_tile_url(overlay, day)
    st.caption(f"Map layer: **{overlay}** (GIBS id `{GIBS_LAYERS[overlay]['id']}`, date {d}). Imagery is "
               "near-real-time and for visual context; trends use the calibrated time series above.")
