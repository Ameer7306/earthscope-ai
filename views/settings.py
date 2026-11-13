"""Settings: API status, defaults, animation preference, saved regions, cache and database tools."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from backend import database as db
from backend import nasa_api
from core import controls, state
from core.config import ROOT, settings
from visualization.animations import badge, hero

hero("Settings", "Connections, preferences and data management.")
cfg = settings()

# ---------------------------------------------------------------- connections
st.subheader("Data connections")


def status_row(name: str, ok: bool, detail: str, needs_key: bool = False) -> None:
    b = badge("live", "Connected") if ok else badge("demo", "Demo mode" if needs_key else "Unavailable")
    st.markdown(f"<div class='es-card' style='padding:10px 16px'><b>{name}</b> &nbsp;{b}"
                f"<div class='muted'>{detail}</div></div>", unsafe_allow_html=True)


c1, c2 = st.columns(2)
with c1:
    status_row("NASA POWER", True, "Monthly & daily climate variables · no key required")
    status_row("NASA GISS GISTEMP", True, "Global temperature anomaly · no key required")
    status_row("MODIS NDVI (ORNL DAAC)", True, "MOD13Q1 250 m vegetation index · no key required")
    status_row("NASA GIBS imagery", True, "Satellite map layers · no key required")
with c2:
    status_row("NASA EONET", True, "Natural event tracker · no key required")
    status_row("NASA FIRMS active fires", bool(cfg["FIRMS_MAP_KEY"]),
               "Key configured" if cfg["FIRMS_MAP_KEY"] else "Set FIRMS_MAP_KEY in .env — free at firms.modaps.eosdis.nasa.gov/api/map_key", True)
    status_row("OpenAI (AI Assistant)", bool(cfg["OPENAI_API_KEY"]),
               f"Model: {cfg['OPENAI_MODEL']}" if cfg["OPENAI_API_KEY"] else "Set OPENAI_API_KEY in .env — offline explainer is used meanwhile", True)
    status_row("SQLite database", True, f"{cfg['DATABASE_PATH']}")

if st.button("Test NASA connections now"):
    tests = {
        "NASA POWER": lambda: nasa_api._get("https://power.larc.nasa.gov/api/temporal/monthly/point",
                                            {"parameters": "T2M", "community": "AG", "latitude": 0, "longitude": 0,
                                             "start": 2023, "end": 2023, "format": "JSON"}, ttl_hours=0),
        "NASA EONET": lambda: nasa_api._get("https://eonet.gsfc.nasa.gov/api/v3/events", {"limit": 1}, ttl_hours=0),
        "NASA GISTEMP": lambda: nasa_api._get(nasa_api.GISTEMP_CSV, as_json=False, ttl_hours=0),
    }
    for name, fn in tests.items():
        try:
            fn()
            st.success(f"{name}: reachable")
        except Exception as e:
            st.error(f"{name}: {e}")

with st.expander("How to add API keys (kept server-side, never sent to the browser)"):
    st.markdown(f"""
1. Copy `.env.example` to `.env` in `{ROOT}`.
2. Fill in the keys:
```
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
FIRMS_MAP_KEY=your_firms_map_key
```
3. Restart the app (`streamlit run app.py`).

Keys are read from environment variables or `.streamlit/secrets.toml`. For security they cannot be typed into this page.
""")

# ---------------------------------------------------------------- preferences
st.subheader("Preferences")
p1, p2 = st.columns(2)
with p1:
    anim = st.toggle("Interface animations", value=st.session_state["animations"],
                     help="Fade, slide and counter animations. They are also disabled automatically when your "
                          "operating system requests reduced motion.")
    if anim != st.session_state["animations"]:
        st.session_state["animations"] = anim
        st.rerun()
    st.caption("Default analysis settings (apply across all pages):")
    controls.region_select("Default region")
    controls.alpha_select()
with p2:
    controls.sampling_select()
    var = controls.variable_select("Default variable")
    controls.years_select(var, label="Default period")

# ---------------------------------------------------------------- saved regions
st.subheader("Saved regions")
with st.form("add_region", border=True):
    a, b, c, d = st.columns([2, 1, 1, 1])
    name = a.text_input("Name", max_chars=40, placeholder="e.g. Lake Chad")
    lat = b.number_input("Latitude", -90.0, 90.0, 13.0, format="%.3f")
    lon = c.number_input("Longitude", -180.0, 180.0, 14.0, format="%.3f")
    half = d.number_input("Box half-size (°, 0 = point)", 0.0, 20.0, 0.0, step=0.5)
    if st.form_submit_button("Save region"):
        if not name.strip():
            st.warning("Enter a name.")
        else:
            bbox = (max(-90, lat - half), lon - half, min(90, lat + half), lon + half) if half > 0 else None
            db.save_region(name.strip(), lat, lon, bbox)
            st.success(f"Saved “{name.strip()}”. It now appears in every region selector.")
saved = db.saved_regions()
if saved:
    st.dataframe(pd.DataFrame([{"Name": k, "Lat": v["lat"], "Lon": v["lon"],
                                "Box": "—" if not v["bbox"] else f"{v['bbox'][0]:.1f}…{v['bbox'][2]:.1f} lat, {v['bbox'][1]:.1f}…{v['bbox'][3]:.1f} lon"}
                               for k, v in saved.items()]), hide_index=True, width="stretch")
    r1, r2 = st.columns([3, 1])
    victim = r1.selectbox("Remove a saved region", list(saved), label_visibility="collapsed")
    if r2.button("Delete region", width="stretch"):
        db.delete_region(victim)
        if st.session_state["g_region"] == victim:
            st.session_state["g_region"] = "Qatar"
        st.rerun()
else:
    st.caption("No saved regions yet. Add one here or draw one in Earth Explorer.")

# ---------------------------------------------------------------- data management
st.subheader("Data management")
info = nasa_api.cache_info()
counts = db.table_counts()
m = st.columns(4)
m[0].metric("Cached NASA responses", info["files"], f"{info['size_mb']} MB", delta_color="off")
m[1].metric("Stored observations", counts["observations"])
m[2].metric("Analyses logged", counts["analysis_history"])
m[3].metric("Chat messages", counts["chat_sessions"])

b1, b2, b3 = st.columns(3)
if b1.button("Clear NASA download cache", width="stretch"):
    n = nasa_api.clear_cache()
    st.cache_data.clear()
    st.success(f"Removed {n} cached responses. Data will be downloaded fresh.")
if b2.button("Clear analysis history", width="stretch"):
    db.clear_history()
    st.session_state.pop("_logged", None)
    st.success("Analysis history cleared.")
if b3.button("Clear AI conversation", width="stretch"):
    st.session_state["chat"] = []
    st.success("Conversation cleared.")

with st.expander("Database tables"):
    st.dataframe(pd.DataFrame([{"Table": k, "Rows": v} for k, v in counts.items()]), hide_index=True,
                 width="stretch")
    st.caption("SQLite with portable SQL types — the schema in `backend/database.py` can be moved to PostgreSQL or "
               "Supabase by replacing the connection function.")

st.caption("EarthScope AI · built for the NASA Space Apps Challenge 2026 · data courtesy of NASA. "
           "This tool is a research prototype and not an official NASA product.")
state.publish("selection", st.session_state["ctx"].get("selection"))
