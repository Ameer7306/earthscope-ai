"""Reports: generate downloadable scientific reports (PDF, CSV, Excel)."""
from __future__ import annotations

import re

import streamlit as st

from analysis.trends import STATUS_LABEL, interpret
from backend import database as db
from core import controls, state
from core.config import VARIABLES
from reports import generator
from visualization import charts
from visualization.animations import badges, hero, loading, result_card

hero("Reports", "Turn an analysis into a shareable scientific report with methodology, results, chart and limitations.")

last = st.session_state.get("last_analysis")
source = st.radio("Report content", ["Use my latest analysis", "Configure a new analysis"], horizontal=True,
                  index=0 if last else 1, disabled=not last,
                  help="Run a Trend Analysis or Significance Test first to reuse it here.")

if source == "Use my latest analysis" and last:
    df, meta, result, aggregation = last["df"], last["meta"], last["result"], last["aggregation"]
else:
    c1, c2, c3 = st.columns([1.2, 1.5, 1])
    with c1:
        region = controls.region_select()
    with c2:
        variable = controls.variable_select()
        years = controls.years_select(variable)
    with c3:
        aggregation = st.radio("Aggregation", ["annual", "monthly"], format_func=str.capitalize)
        alpha = controls.alpha_select()
    sampling = st.session_state["g_sampling"]
    df, meta = controls.get_series(variable, region, years, sampling)
    result = controls.analyse(df, variable, region, years, aggregation, "auto", alpha, kind="report")

v = VARIABLES[meta["variable"]]
region = meta["region"]
period = f"{meta['start']}–{meta['end']}"

st.divider()
left, right = st.columns([1.1, 1.6], gap="large")
with left:
    st.markdown("#### Report details")
    title = st.text_input("Project title", f"{v['label']} trends in {region}, {period}", max_chars=120)
    author = st.text_input("Author / team (optional)", "", max_chars=80)
    notes = st.text_area("Author notes (optional)", "", height=110, max_chars=2000,
                         placeholder="Context, hypotheses or next steps to include in the report…")
    cmp_ = st.session_state.get("last_comparison")
    include_cmp = st.checkbox("Include latest Opposite Trend comparison", value=False, disabled=not cmp_,
                              help="Available after you use the Opposite Trend Detector.")
with right:
    st.markdown("#### Preview")
    badges(("nasa", meta["provider"]), ("final", f"{period} · {aggregation}"))
    if result["status"] == "insufficient":
        result_card("insufficient", "Insufficient data", "—", result["message"])
    else:
        result_card(result["status"], STATUS_LABEL[result["status"]],
                    f"{result['sen_slope_per_decade']:+.3g} {v['units']} / decade",
                    f"p = {result['p_value']:.4g} · {result['method_label']}")
    st.plotly_chart(charts.trend_chart(df, result, v["label"], v["units"], region, aggregation), width="stretch")
    st.markdown(interpret(result, v["label"], v["units"], region))

st.divider()
st.markdown("#### Download")
slug = re.sub(r"[^a-z0-9]+", "_", f"{meta['variable']}_{region}_{period}".lower()).strip("_")


@st.cache_data(show_spinner=False)
def _pdf(title, author, notes, key, _df, _meta, _result, aggregation, _cmp):
    return generator.build_pdf(title, author, _df, _meta, _result, aggregation, notes, _cmp)


key = (meta["variable"], region, period, meta["sampling"], aggregation, result.get("p_value"), result.get("alpha"))
try:
    with loading("Building PDF report…"):
        pdf = _pdf(title, author, notes, key, df, meta, result, aggregation, cmp_ if include_cmp else None)
    csv = generator.build_csv(df, meta)
    xlsx = generator.build_excel(df, meta, result)
except Exception as e:
    st.error(f"Report generation failed: {type(e).__name__}: {e}")
    st.stop()


def _log(fmt: str) -> None:
    db.log_report(title, v["label"], region, period, fmt)


d1, d2, d3 = st.columns(3)
d1.download_button("📄 Scientific report (PDF)", pdf, f"earthscope_report_{slug}.pdf", "application/pdf",
                   width="stretch", type="primary", on_click=_log, args=("PDF",))
d2.download_button("🧾 Data (CSV)", csv, f"earthscope_data_{slug}.csv", "text/csv", width="stretch",
                   on_click=_log, args=("CSV",))
d3.download_button("📊 Workbook (Excel)", xlsx, f"earthscope_{slug}.xlsx",
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch",
                   on_click=_log, args=("Excel",))
st.caption(f"PDF {len(pdf) / 1024:.0f} KB · includes study definition, result, chart, Mann-Kendall statistics, Sen's "
           "slope and CI, methodology, data quality, limitations and annual values. Excel has monthly, annual, "
           "results and metadata sheets.")

hist = db.list_reports(10)
if not hist.empty:
    st.markdown("#### Generated reports")
    st.dataframe(hist.rename(columns={"title": "Title", "variable": "Variable", "region": "Region",
                                      "period": "Period", "formats": "Format", "created_at": "Created (UTC)"}),
                 width="stretch", hide_index=True)

state.publish("selection", {"region": region, "variable": meta["variable"], "start": meta["start"],
                            "end": meta["end"], "sampling": meta["sampling"], "aggregation": aggregation})
