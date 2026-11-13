"""Opposite Trend Detector: do two regions show statistically significant trends in opposite directions?"""
from __future__ import annotations

import streamlit as st

from analysis.regional import classify_pair, explain_pair
from analysis.trends import STATUS_LABEL
from core import controls, state
from core.config import COLORS, VARIABLES
from visualization import charts
from visualization.animations import badges, hero, result_card

hero("Opposite Trend Detector", "Compare two regions and find out whether they are genuinely moving in opposite "
                                "directions — or whether it only looks that way.")

st.session_state.setdefault("opp_a", "Qatar")
st.session_state.setdefault("opp_b", "India")

c1, c2, c3 = st.columns([1, 1, 1.3])
with c1:
    region_a = controls.region_select("Region A", key="opp_a")
with c2:
    region_b = controls.region_select("Region B", key="opp_b")
with c3:
    variable = controls.variable_select()
c4, c5, c6, c7 = st.columns([2, 1, 1, 1])
with c4:
    years = controls.years_select(variable, label="Time period (same for both regions)")
with c5:
    aggregation = st.selectbox("Aggregation", ["annual", "monthly"], format_func=str.capitalize)
with c6:
    sampling = controls.sampling_select()
with c7:
    alpha = controls.alpha_select()

if region_a == region_b:
    st.warning("Choose two different regions.")
    st.stop()

v = VARIABLES[variable]
df_a, meta_a = controls.get_series(variable, region_a, years, sampling)
df_b, meta_b = controls.get_series(variable, region_b, years, sampling)
res_a = controls.analyse(df_a, variable, region_a, years, aggregation, "auto", alpha, kind="opposite")
res_b = controls.analyse(df_b, variable, region_b, years, aggregation, "auto", alpha, kind="opposite")
pair = classify_pair(res_a, res_b)

badges(("nasa", meta_a["provider"]), ("final", f"{years[0]}–{years[1]} · {aggregation}"), ("live", "Real NASA data"))
st.write("")

# ---------------------------------------------------------------- verdict
verdict_color = {"opposite": COLORS["warning"], "both_increasing": COLORS["positive"],
                 "both_decreasing": COLORS["negative"]}.get(pair["category"], COLORS["muted"])
icon = {"opposite": "🔀", "both_increasing": "⬆️⬆️", "both_decreasing": "⬇️⬇️", "one_significant": "◐",
        "neither": "○", "insufficient": "⚠️"}[pair["category"]]
st.markdown(
    f"""<div class="es-result" style="border-color:{verdict_color};box-shadow:inset 4px 0 0 {verdict_color}">
    <div style="color:#94A3B8;font-size:.78rem;text-transform:uppercase;letter-spacing:1px">Detector verdict</div>
    <div class="big" style="color:{verdict_color}">{icon} {pair['label']}</div></div>""", unsafe_allow_html=True)
st.write("")

# ---------------------------------------------------------------- side-by-side
ca, cb = st.columns(2, gap="large")
for col, name, df, res, color in ((ca, region_a, df_a, res_a, COLORS["primary"]), (cb, region_b, df_b, res_b, COLORS["secondary"])):
    with col:
        if res["status"] == "insufficient":
            result_card("insufficient", f"{name}: insufficient data", "—", res["message"])
        else:
            result_card(res["status"], f"{name}: {STATUS_LABEL[res['status']]}",
                        f"{res['sen_slope_per_decade']:+.3g} {v['units']} / decade",
                        f"p = {res['p_value']:.4g} · {'significant' if res['significant'] else 'not significant'} at α = {alpha}")
        st.plotly_chart(charts.trend_chart(df, res, v["label"], v["units"], name, aggregation, show_ols=False, color=color),
                        width="stretch")

# ---------------------------------------------------------------- numbers
if pair["category"] != "insufficient":
    st.subheader("Comparison of trend statistics")
    rows = {
        "Statistic": ["Trend direction", "Sen's slope (per year)", "Sen's slope (per decade)",
                      f"{res_a['ci_level']}% confidence interval (per decade)", "p-value", f"Significant at α = {alpha}",
                      "Test used", "Sample size", "Missing data"],
        region_a: [STATUS_LABEL[res_a["status"]], f"{res_a['sen_slope']:+.4g}", f"{res_a['sen_slope_per_decade']:+.4g}",
                   f"{res_a['sen_ci_low'] * 10:+.3g} to {res_a['sen_ci_high'] * 10:+.3g}", f"{res_a['p_value']:.4g}",
                   "Yes" if res_a["significant"] else "No", res_a["method_label"], str(res_a["n_valid"]), f"{res_a['missing_pct']}%"],
        region_b: [STATUS_LABEL[res_b["status"]], f"{res_b['sen_slope']:+.4g}", f"{res_b['sen_slope_per_decade']:+.4g}",
                   f"{res_b['sen_ci_low'] * 10:+.3g} to {res_b['sen_ci_high'] * 10:+.3g}", f"{res_b['p_value']:.4g}",
                   "Yes" if res_b["significant"] else "No", res_b["method_label"], str(res_b["n_valid"]), f"{res_b['missing_pct']}%"],
    }
    st.table(rows)
    d = st.columns(3)
    d[0].metric("Difference in trend rates (A − B)", f"{pair['slope_difference_per_decade']:+.3g} {v['units']}/decade")
    if "difference_p" in pair:
        d[1].metric("Approx. p-value of difference", f"{pair['difference_p']:.3g}",
                    help="z-test on the two Sen's slopes using standard errors derived from their confidence intervals; assumes independent regions.")
        d[2].metric("Slopes differ significantly?", "Yes" if pair["difference_p"] < alpha else "No")

st.subheader("Scientific explanation")
explanation = explain_pair(res_a, res_b, region_a, region_b, v["label"], v["units"], pair)
st.markdown(explanation)
st.caption("Rule applied: an “opposite trend” is reported only when both regions are individually significant and "
           "their directions differ. Different signs with a non-significant slope are not treated as opposite.")

state.publish("selection", {"region": f"{region_a} vs {region_b}", "variable": variable, "start": years[0],
                            "end": years[1], "sampling": sampling, "aggregation": aggregation})
state.publish("opposite", {"label": v["label"], "units": v["units"], "period": f"{years[0]}–{years[1]}",
                           "region_a": region_a, "region_b": region_b, "result_a": res_a, "result_b": res_b, "pair": pair})
st.session_state["last_comparison"] = {
    "rows": [(k, f"{a}  |  {b}") for k, a, b in zip(rows["Statistic"], rows[region_a], rows[region_b])]
    if pair["category"] != "insufficient" else [("Status", pair["label"])],
    "text": f"{region_a} vs {region_b}: {pair['label']}.", "regions": (region_a, region_b), "variable": variable}
