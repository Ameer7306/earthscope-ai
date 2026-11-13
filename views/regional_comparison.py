"""Regional Comparison: the same variable and period across several regions."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from analysis.trends import STATUS_LABEL, aggregate
from core import controls, state
from core.config import VARIABLES
from visualization import charts
from visualization.animations import badges, hero

hero("Regional Comparison", "Compare how one environmental variable is changing across up to eight regions, "
                            "using identical methods and periods.")

names = state.region_names()
c1, c2 = st.columns([2, 1.4])
with c1:
    default = [r for r in st.session_state.get("cmp_regions", ["Qatar", "India", "Kenya", "United Kingdom", "Brazil"]) if r in names]
    regions = st.multiselect("Regions (2–8)", names, default=default, max_selections=8)
    st.session_state["cmp_regions"] = regions
with c2:
    variable = controls.variable_select()
c3, c4, c5 = st.columns([2, 1, 1])
with c3:
    years = controls.years_select(variable)
with c4:
    sampling = controls.sampling_select()
with c5:
    alpha = controls.alpha_select()

if len(regions) < 2:
    st.info("Select at least two regions to compare.")
    st.stop()

v = VARIABLES[variable]
results, series, rows = {}, {}, []
progress = st.progress(0.0, text="Loading NASA data…")
for i, reg in enumerate(regions):
    progress.progress(i / len(regions), text=f"Loading {reg}…")
    df, meta = controls.get_series(variable, reg, years, sampling)
    res = controls.analyse(df, variable, reg, years, "annual", "auto", alpha, kind="comparison")
    results[reg], series[reg] = res, aggregate(df, "annual")
    if res["status"] == "insufficient":
        rows.append({"region": reg, "Result": STATUS_LABEL[res["status"]], "significant": False,
                     "slope_dec": float("nan"), "ci_lo_dec": float("nan"), "ci_hi_dec": float("nan")})
    else:
        rows.append({"region": reg, "Result": STATUS_LABEL[res["status"]], "significant": res["significant"],
                     "slope_dec": res["sen_slope_per_decade"], "ci_lo_dec": res["sen_ci_low"] * 10,
                     "ci_hi_dec": res["sen_ci_high"] * 10, "p": res["p_value"], "mean": res["mean"],
                     "n": res["n_valid"], "missing": res["missing_pct"], "method": res["method_label"]})
progress.empty()
table = pd.DataFrame(rows)

badges(("nasa", meta["provider"]), ("final", f"{years[0]}–{years[1]} · annual means"), ("live", "Real NASA data"))
st.write("")

valid = table.dropna(subset=["slope_dec"])
m = st.columns(4)
m[0].metric("Regions compared", len(regions))
m[1].metric("Significant increases", int(((valid["slope_dec"] > 0) & valid["significant"]).sum()))
m[2].metric("Significant decreases", int(((valid["slope_dec"] < 0) & valid["significant"]).sum()))
m[3].metric("No significant trend", int((~valid["significant"]).sum()))

normalise = st.toggle("Show as anomaly from each region's own mean", value=variable in ("air_temperature", "max_temperature", "surface_temperature"),
                      help="Makes regions with very different absolute values comparable.")
st.plotly_chart(charts.multi_region_chart(series, v["label"], v["units"], normalise), width="stretch")
if not valid.empty:
    st.plotly_chart(charts.slope_bar(valid, v["units"]), width="stretch")

show = table.rename(columns={"region": "Region", "slope_dec": f"Sen's slope ({v['units']}/decade)",
                             "ci_lo_dec": "CI low", "ci_hi_dec": "CI high", "p": "p-value", "mean": "Mean",
                             "n": "n (years)", "missing": "Missing %", "method": "Test", "significant": "Significant"})
st.dataframe(show, width="stretch", hide_index=True,
             column_config={"p-value": st.column_config.NumberColumn(format="%.4f"),
                            f"Sen's slope ({v['units']}/decade)": st.column_config.NumberColumn(format="%+.3g"),
                            "CI low": st.column_config.NumberColumn(format="%+.3g"),
                            "CI high": st.column_config.NumberColumn(format="%+.3g"),
                            "Mean": st.column_config.NumberColumn(format="%.3g")})
st.download_button("Download comparison (CSV)", show.to_csv(index=False).encode("utf-8"),
                   f"earthscope_comparison_{variable}.csv", "text/csv")

st.caption("Grey bars are not statistically significant: their direction should not be interpreted as a real "
           "increase or decrease, nor as proof of no change. Testing many regions at once raises the chance of at "
           f"least one false positive (≈{100 * (1 - (1 - alpha) ** len(regions)):.0f}% for {len(regions)} independent "
           f"tests at α = {alpha}).")

state.publish("selection", {"region": ", ".join(regions), "variable": variable, "start": years[0], "end": years[1],
                            "sampling": sampling, "aggregation": "annual"})
state.publish("comparison", {"label": v["label"], "units": v["units"], "period": f"{years[0]}–{years[1]}",
                             "results": results})
