"""
Builds the text context handed to the assistant from what the application is currently showing.

Pages call `core.state.publish(...)` with their selections and results; this module turns that
dictionary into a compact, factual briefing. Only real application data goes in here.
"""
from __future__ import annotations

import pandas as pd

from backend.catalog import DATASETS
from core.config import VARIABLES


def _fmt_trend(name: str, r: dict, units: str) -> str:
    if not r:
        return f"- {name}: no result"
    if r.get("status") == "insufficient":
        return f"- {name}: INSUFFICIENT DATA ({r.get('message', '')})"
    return (f"- {name}: status={r['status']}, significant={r['significant']} (alpha={r['alpha']}), "
            f"method={r['method_label']}, p={r['p_value']:.4g}, Z={r['mk_z']}, tau={r['kendall_tau']}, "
            f"Sen slope={r['sen_slope']:+.4g} {units}/year ({r['sen_slope_per_decade']:+.4g}/decade), "
            f"{r['ci_level']}% CI [{r['sen_ci_low']:+.4g}, {r['sen_ci_high']:+.4g}] per year, "
            f"total change≈{r['total_change']:+.4g} {units} over {r['span_years']} years, "
            f"n={r['n_valid']}/{r['n_total']} ({r['aggregation']}), missing={r['missing_pct']}%, "
            f"mean={r['mean']:.4g}, std={r['std']:.4g}, lag1 autocorr={r['lag1_autocorr']}, "
            f"period {r['start']}..{r['end']}")


def build_context(ctx: dict) -> str:
    """Return a plain-text description of the current application state."""
    lines = []
    lines.append(f"Current page: {ctx.get('current_page', 'unknown')}")
    sel = ctx.get("selection")
    if sel:
        v = VARIABLES.get(sel.get("variable"), {})
        lines.append(f"Selected region: {sel.get('region')} | variable: {v.get('label', sel.get('variable'))} "
                     f"({v.get('units', '')}) | period: {sel.get('start')}–{sel.get('end')} | "
                     f"sampling: {sel.get('sampling')} | aggregation: {sel.get('aggregation', 'n/a')}")
        lines.append(f"Data source for selection: {v.get('dataset', 'n/a')}")

    tr = ctx.get("trend")
    if tr:
        lines.append("\nTREND ANALYSIS RESULT (computed in app):")
        lines.append(_fmt_trend(f"{tr['label']} in {tr['region']}", tr["result"], tr["units"]))
        if tr.get("annual_values"):
            lines.append("Annual means shown in chart (year: value): " +
                         ", ".join(f"{y}: {v:.3g}" for y, v in tr["annual_values"]))
        if tr.get("period_comparison"):
            pc = tr["period_comparison"]
            lines.append(f"Period comparison: {pc['first_period']} mean={pc['first_mean']:.4g}, "
                         f"{pc['last_period']} mean={pc['last_mean']:.4g}, difference={pc['difference']:+.4g}, "
                         f"Mann-Whitney p={pc['mannwhitney_p']:.3g}")

    opp = ctx.get("opposite")
    if opp:
        lines.append(f"\nOPPOSITE TREND DETECTOR ({opp['label']}, {opp['units']}, {opp['period']}):")
        lines.append(_fmt_trend(opp["region_a"], opp["result_a"], opp["units"]))
        lines.append(_fmt_trend(opp["region_b"], opp["result_b"], opp["units"]))
        lines.append(f"Classification: {opp['pair']['label']}")
        if "slope_difference_per_decade" in opp["pair"]:
            lines.append(f"Slope difference (A−B): {opp['pair']['slope_difference_per_decade']:+.4g} per decade"
                         + (f", approx p={opp['pair']['difference_p']:.3g}" if "difference_p" in opp["pair"] else ""))

    comp = ctx.get("comparison")
    if comp:
        lines.append(f"\nREGIONAL COMPARISON ({comp['label']}, {comp['units']}, {comp['period']}):")
        for name, r in comp["results"].items():
            lines.append(_fmt_trend(name, r, comp["units"]))

    sig = ctx.get("significance")
    if sig:
        lines.append(f"\nSIGNIFICANCE TEST ({sig['label']} in {sig['region']}):")
        lines.append(_fmt_trend("result", sig["result"], sig["units"]))
        if sig.get("practical"):
            lines.append(f"Practical importance: {sig['practical'].get('text', '')}")

    live = ctx.get("live")
    if live:
        lines.append(f"\nLIVE MONITORING (mode: {live.get('mode')}, refreshed {live.get('refreshed')}):")
        lines.append(f"Open natural events from NASA EONET: {live.get('n_events')} "
                     f"(by category: {live.get('by_category')})")
        if live.get("latest_fire"):
            lines.append(f"Latest fire detection: {live['latest_fire']}")
        if live.get("firms_summary"):
            lines.append(f"FIRMS: {live['firms_summary']}")
        for e in live.get("latest", [])[:8]:
            lines.append(f"- {e}")
        if live.get("rain"):
            lines.append(f"Rainfall monitor: {live['rain']}")

    space = ctx.get("space")
    if space:
        lines.append("\nSPACE & ORBIT TRACKER (NASA NeoWs, JPL SBDB/CNEOS, CelesTrak):")
        for k, v in space.items():
            lines.append(f"- {k}: {v}")

    ov = ctx.get("overview")
    if ov:
        lines.append(f"\nOVERVIEW: {ov}")

    if not (tr or opp or comp or sig or live):
        lines.append("\nNo analysis results have been computed in this session yet.")

    connected = [d for d in DATASETS if d["connected"]]
    lines.append("\nDATASET CATALOGUE (name | variable | mission | resolution | coverage | connected in app):")
    for d in DATASETS:
        lines.append(f"- {d['name']} | {d['variable']} | {d['mission']} | {d['spatial']}, {d['temporal']} | "
                     f"{d['coverage']} | {'yes' if d['connected'] else 'no'}")
    lines.append(f"({len(connected)} of {len(DATASETS)} datasets can be analysed directly in the app.)")
    return "\n".join(lines)


def annual_pairs(series: pd.Series) -> list[tuple[int, float]]:
    """Helper for pages: compact (year, value) list for the context."""
    s = series.dropna()
    return [(int(i.year), float(v)) for i, v in s.items()]
