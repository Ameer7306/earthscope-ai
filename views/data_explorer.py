"""Data Explorer: searchable NASA dataset catalogue with filters."""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from backend.catalog import CATEGORIES, DATASETS
from core import state
from visualization.animations import badge, hero

hero("Data Explorer", "Discover NASA Earth observation datasets across the atmosphere, land and water.")
state.publish("selection", st.session_state["ctx"].get("selection"))

df = pd.DataFrame(DATASETS)

f1, f2, f3, f4 = st.columns([2.2, 1.4, 1.6, 1.2])
query = f1.text_input("Search", placeholder="e.g. NDVI, MODIS, soil moisture, GRACE…")
cats = f2.multiselect("Category", CATEGORIES, default=CATEGORIES)
variables = f3.multiselect("Variable", sorted(df["variable"].unique()))
only = f4.selectbox("Availability", ["All datasets", "Analysable in app", "Catalogue only"])

view = df[df["category"].isin(cats)]
if variables:
    view = view[view["variable"].isin(variables)]
if only == "Analysable in app":
    view = view[view["connected"]]
elif only == "Catalogue only":
    view = view[~view["connected"]]
if query.strip():
    q = query.lower().strip()
    text = (view["name"] + " " + view["variable"] + " " + view["mission"] + " " + view["source"]).str.lower()
    view = view[text.str.contains(q, regex=False)]

m1, m2, m3, m4 = st.columns(4)
m1.metric("Datasets shown", len(view))
m2.metric("Analysable in app", int(view["connected"].sum()))
m3.metric("Missions / models", view["mission"].nunique())
m4.metric("Categories", view["category"].nunique())

tab_cards, tab_table = st.tabs(["Cards", "Table"])

with tab_cards:
    if view.empty:
        st.info("No datasets match these filters.")
    for cat in CATEGORIES:
        sub = view[view["category"] == cat]
        if sub.empty:
            continue
        st.markdown(f"### {'🌫️' if cat == 'Atmosphere' else '🌱' if cat == 'Land' else '💧'} {cat}")
        cols = st.columns(2)
        for i, (_, d) in enumerate(sub.iterrows()):
            with cols[i % 2]:
                status = badge("live", "Analysable in app") if d["connected"] else badge("nasa", "Catalogue")
                note = f"<br><i>{html.escape(d['note'])}</i>" if isinstance(d.get("note"), str) else ""
                st.markdown(
                    f"""<div class="es-card" style="animation-delay:{i * 0.05:.2f}s">
                    <h4>{html.escape(d['name'])}</h4>{status}
                    <div class="muted" style="margin-top:8px">
                    <b>Variable:</b> {html.escape(d['variable'])}<br>
                    <b>NASA mission / model:</b> {html.escape(d['mission'])}<br>
                    <b>Data source:</b> {html.escape(d['source'])}<br>
                    <b>Spatial resolution:</b> {html.escape(d['spatial'])} · <b>Temporal:</b> {html.escape(d['temporal'])}<br>
                    <b>Coverage:</b> {html.escape(d['coverage'])} · <b>Updates:</b> {html.escape(d['update'])}{note}<br>
                    <a href="{html.escape(d['doc'])}" target="_blank" rel="noopener" style="color:#38BDF8">Dataset documentation ↗</a>
                    </div></div>""", unsafe_allow_html=True)
                app_var = d.get("app_variable")
                if d["connected"] and isinstance(app_var, str) and app_var != "global":
                    if st.button("Analyse this dataset", key=f"an_{i}_{cat}", width="stretch"):
                        st.session_state["g_variable"] = app_var
                        st.switch_page("views/trend_analysis.py")

with tab_table:
    table = view.rename(columns={
        "name": "Dataset", "category": "Category", "variable": "Variable", "mission": "NASA mission / model",
        "source": "Data source", "spatial": "Spatial resolution", "temporal": "Temporal resolution",
        "coverage": "Coverage period", "update": "Update frequency", "doc": "Documentation", "connected": "In app"})
    st.dataframe(table[["Dataset", "Category", "Variable", "NASA mission / model", "Data source", "Spatial resolution",
                        "Temporal resolution", "Coverage period", "Update frequency", "In app", "Documentation"]],
                 width="stretch", hide_index=True,
                 column_config={"Documentation": st.column_config.LinkColumn(display_text="Open ↗")})
    st.download_button("Download catalogue (CSV)", table.to_csv(index=False).encode("utf-8"),
                       "earthscope_datasets.csv", "text/csv")

st.caption("“Analysable in app” datasets are fetched live from NASA POWER, NASA GISS or the ORNL DAAC MODIS service. "
           "Catalogue-only datasets need an Earthdata Login and gridded processing; they are listed for discovery.")
