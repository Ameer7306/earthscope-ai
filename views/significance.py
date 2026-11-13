"""Significance Testing: a focused statistical test bench with robustness checks."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from analysis.significance import explain_p_value, practical_importance, significance_table
from analysis.trends import METHODS, STATUS_LABEL, interpret, run_trend
from core import controls, state
from core.config import VARIABLES
from visualization import charts
from visualization.animations import badges, hero, result_card

hero("Significance Testing", "Is the trend statistically significant — and is it large enough to matter? "
                             "Two different questions, answered separately.")

c1, c2, c3 = st.columns([1.2, 1.5, 1.3])
with c1:
    region = controls.region_select()
    alpha = controls.alpha_select()
with c2:
    variable = controls.variable_select("Dataset / variable")
    years = controls.years_select(variable)
with c3:
    aggregation = st.radio("Aggregation", ["annual", "monthly"], horizontal=True, format_func=str.capitalize)
    method = st.selectbox("Mann-Kendall variant", list(METHODS), format_func=METHODS.get)

v = VARIABLES[variable]
sampling = st.session_state["g_sampling"]
df, meta = controls.get_series(variable, region, years, sampling)
result = controls.analyse(df, variable, region, years, aggregation, method, alpha, kind="significance")
st.caption(f"Dataset: {meta['source']} · sampling: {sampling}")
badges(("nasa", meta["provider"]), ("live", "Real NASA data"))
st.write("")

if result["status"] == "insufficient":
    result_card("insufficient", "Insufficient data", "—", result["message"])
    st.stop()

# ---------------------------------------------------------------- two separate verdicts
prac = practical_importance(result)
a, b = st.columns(2, gap="large")
with a:
    st.markdown("#### 1 · Statistical significance")
    result_card(result["status"], "Significant" if result["significant"] else "Not significant",
                f"p = {result['p_value']:.4g}", f"threshold α = {alpha} · Z = {result['mk_z']:.2f} · τ = {result['kendall_tau']:.2f}")
    st.markdown(explain_p_value(result["p_value"], alpha))
with b:
    st.markdown("#### 2 · Practical importance")
    lvl = prac["level"]
    result_card("increasing" if result["sen_slope"] > 0 else "decreasing" if lvl != "small" else "no_significant_trend",
                f"{lvl.capitalize()} change relative to variability",
                f"{result['total_change']:+.3g} {v['units']} in {result['span_years']:.0f} yr",
                f"= {prac['ratio']:.2f} × interannual standard deviation")
    st.markdown(prac["text"])

st.plotly_chart(charts.trend_chart(df, result, v["label"], v["units"], region, aggregation), width="stretch")

t1, t2, t3, t4 = st.tabs(["Test results", "Robustness across methods", "Sensitivity to α and period", "Interpretation"])
with t1:
    rows = significance_table(result)
    st.table({"Statistic": [r[0] for r in rows], "Value": [r[1] for r in rows]})
with t2:
    st.caption("If the conclusion changes with the test variant, treat the result as fragile.")
    comp = []
    for key, label in METHODS.items():
        if key == "auto" or (key == "seasonal" and aggregation == "annual"):
            continue
        try:
            r = run_trend(df, aggregation, key, alpha)
            comp.append({"Method": label, "p-value": r["p_value"], "Z": r["mk_z"],
                         "Sen's slope / decade": r["sen_slope_per_decade"], "Significant": r["significant"],
                         "Conclusion": STATUS_LABEL[r["status"]]})
        except Exception as e:
            comp.append({"Method": label, "Conclusion": f"Not applicable ({type(e).__name__})"})
    cdf = pd.DataFrame(comp)
    st.dataframe(cdf, width="stretch", hide_index=True,
                 column_config={"p-value": st.column_config.NumberColumn(format="%.4f"),
                                "Sen's slope / decade": st.column_config.NumberColumn(format="%+.3g")})
    agree = cdf["Significant"].dropna().nunique() == 1 if "Significant" in cdf else False
    (st.success if agree else st.warning)(
        "All variants agree on significance — the conclusion is robust to the choice of test." if agree else
        "Variants disagree on significance — serial correlation or seasonality affects this result; report it cautiously.")
with t3:
    s1, s2 = st.columns(2)
    with s1:
        st.markdown("**Significance thresholds**")
        st.dataframe(pd.DataFrame([{"α": a_, "Confidence": f"{(1 - a_) * 100:.0f}%",
                                    "Significant?": "Yes" if result["p_value"] < a_ else "No"}
                                   for a_ in (0.10, 0.05, 0.01, 0.001)]), hide_index=True, width="stretch")
    with s2:
        st.markdown("**Different start years** (same end year)")
        sens = []
        for start in range(years[0], years[1] - 9, max(1, (years[1] - years[0]) // 6)):
            sub = df[df.index.year >= start]
            r = run_trend(sub, aggregation, method, alpha)
            if r["status"] != "insufficient":
                sens.append({"Period": f"{start}–{years[1]}", "p-value": r["p_value"],
                             "Sen / decade": r["sen_slope_per_decade"], "Significant?": "Yes" if r["significant"] else "No"})
        st.dataframe(pd.DataFrame(sens), hide_index=True, width="stretch",
                     column_config={"p-value": st.column_config.NumberColumn(format="%.4f"),
                                    "Sen / decade": st.column_config.NumberColumn(format="%+.3g")})
    st.caption("Trends that are significant only for particular start years are sensitive to the chosen period.")
with t4:
    st.markdown(interpret(result, v["label"], v["units"], region))
    st.markdown("""
- **Statistical significance** answers: *could this pattern plausibly be chance?*
- **Practical importance** answers: *is the change big enough to matter for people or ecosystems?*
- A significant trend can be tiny; an important change can be non-significant in a short or noisy record.
- “Not significant” means *not detected*, never *proven absent*.
""")

state.publish("selection", {"region": region, "variable": variable, "start": years[0], "end": years[1],
                            "sampling": sampling, "aggregation": aggregation})
state.publish("significance", {"region": region, "label": v["label"], "units": v["units"], "result": result,
                               "practical": prac})
st.session_state["last_analysis"] = {"df": df, "meta": meta, "result": result, "aggregation": aggregation}
