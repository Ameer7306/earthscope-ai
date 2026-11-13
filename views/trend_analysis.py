"""Trend Analysis: Mann-Kendall test, Sen's slope, confidence interval and data-quality reporting."""
from __future__ import annotations

import streamlit as st

from ai.context import annual_pairs
from analysis.anomalies import detect_extremes
from analysis.significance import practical_importance, significance_table
from analysis.trends import (METHODOLOGY, METHODS, STATUS_LABEL, aggregate, annual_table, fmt_p, interpret,
                             period_comparison)
from core import controls, state
from core.config import VARIABLES
from visualization import charts
from visualization.animations import badges, hero, result_card

hero("Trend Analysis", "Test whether an environmental variable is really changing — with a robust rank-based test "
                       "and an honest account of uncertainty.")

c1, c2, c3 = st.columns([1.3, 1.5, 1.2])
with c1:
    region = controls.region_select()
    sampling = controls.sampling_select()
with c2:
    variable = controls.variable_select()
    years = controls.years_select(variable)
with c3:
    aggregation = st.radio("Aggregation", ["annual", "monthly"], horizontal=True,
                           format_func=str.capitalize,
                           help="Annual means remove the seasonal cycle. Monthly uses the Seasonal Kendall test.")
    with st.popover("Advanced options", width="stretch"):
        method = st.selectbox("Trend test", list(METHODS), format_func=METHODS.get)
        alpha = controls.alpha_select()
        show_ols = st.checkbox("Show linear (OLS) line", True)

v = VARIABLES[variable]
df, meta = controls.get_series(variable, region, years, sampling)
result = controls.analyse(df, variable, region, years, aggregation, method, alpha)

badges(("nasa", meta["provider"]), ("final", f"{meta['start']}–{meta['end']} · {aggregation}"),
       ("live", "Real NASA data"))
st.write("")

# ---------------------------------------------------------------- headline result
r1, r2 = st.columns([1.25, 2])
with r1:
    if result["status"] == "insufficient":
        result_card("insufficient", "Insufficient data", "—", result["message"])
    else:
        result_card(result["status"], STATUS_LABEL[result["status"]],
                    f"{result['sen_slope_per_decade']:+.3g} {v['units']} / decade",
                    f"p = {result['p_value']:.4g} · α = {alpha} · {result['method_label']}")
with r2:
    st.markdown(interpret(result, v["label"], v["units"], region))

if result["status"] != "insufficient":
    k = st.columns(6)
    k[0].metric("p-value", fmt_p(result["p_value"]))
    k[1].metric("Sen's slope / yr", f"{result['sen_slope']:+.3g}")
    k[2].metric(f"{result['ci_level']}% CI low", f"{result['sen_ci_low']:+.3g}")
    k[3].metric(f"{result['ci_level']}% CI high", f"{result['sen_ci_high']:+.3g}")
    k[4].metric("Sample size", f"{result['n_valid']} / {result['n_total']}", help="Valid values out of all time steps in the period")
    k[5].metric("Missing data", f"{result['missing_pct']}%")

# ---------------------------------------------------------------- charts
st.plotly_chart(charts.trend_chart(df, result, v["label"], v["units"], region, aggregation, show_ols),
                width="stretch")

ann = annual_table(df)
pc = period_comparison(df)
t1, t2, t3, t4, t5 = st.tabs(["Annual changes", "Anomalies", "Historical comparison", "Statistics", "Methodology & limits"])
with t1:
    st.plotly_chart(charts.change_bars(ann, v["units"]), width="stretch")
    st.dataframe(ann.rename(columns={"year": "Year", "annual_mean": f"Annual mean ({v['units']})",
                                     "change_vs_prev": "Change vs previous year", "anomaly": "Anomaly"}),
                 width="stretch", hide_index=True, height=260)
with t2:
    st.plotly_chart(charts.anomaly_bars(ann, v["units"]), width="stretch")
    ext = detect_extremes(df)
    if ext.empty:
        st.caption("No month in the last 24 months is more than 2 standard deviations from its baseline climatology.")
    else:
        st.markdown("**Unusual recent months** (|z| ≥ 2 relative to the baseline climatology)")
        show = ext.reset_index().rename(columns={"date": "Month", "value": f"Value ({v['units']})",
                                                 "anomaly": "Anomaly", "z": "Std. anomaly (z)", "kind": "Type"})
        show["Month"] = show["Month"].dt.strftime("%b %Y")
        st.dataframe(show, width="stretch", hide_index=True)
with t3:
    if pc:
        a, b, c = st.columns(3)
        a.metric(f"Mean {pc['first_period']}", f"{pc['first_mean']:.3g} {v['units']}")
        b.metric(f"Mean {pc['last_period']}", f"{pc['last_mean']:.3g} {v['units']}", f"{pc['difference']:+.3g}")
        c.metric("Mann-Whitney U p-value", f"{pc['mannwhitney_p']:.3g}",
                 help="Tests whether the two periods' annual values differ in distribution.")
    mid = (years[0] + years[1]) // 2
    st.plotly_chart(charts.seasonal_cycle(df, v["units"], mid), width="stretch")
with t4:
    st.table({"Statistic": [a for a, _ in significance_table(result)], "Value": [b for _, b in significance_table(result)]})
    if result["status"] != "insufficient":
        st.markdown("**Practical importance** — " + practical_importance(result)["text"])
with t5:
    st.markdown(METHODOLOGY)
    st.caption(f"Data: {meta['source']}. Sampling: {meta['n_points']} grid cell(s). Retrieved {meta['retrieved']}.")

# ---------------------------------------------------------------- share with assistant / reports
state.publish("selection", {"region": region, "variable": variable, "start": years[0], "end": years[1],
                            "sampling": sampling, "aggregation": aggregation})
state.publish("trend", {"region": region, "label": v["label"], "units": v["units"], "result": result,
                        "annual_values": annual_pairs(aggregate(df, "annual")), "period_comparison": pc})
st.session_state["last_analysis"] = {"df": df, "meta": meta, "result": result, "aggregation": aggregation}

b1, b2, b3 = st.columns(3)
b1.page_link("views/reports.py", label="Generate a report from this analysis", icon="📄")
b2.page_link("views/opposite_trend.py", label="Compare with another region", icon="🔀")
b3.page_link("views/ai_assistant.py", label="Ask the AI to explain this", icon="🤖")
