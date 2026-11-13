"""
EarthScope AI Assistant.

Two modes:
  * LIVE  – OpenAI Chat Completions (key from OPENAI_API_KEY env var / Streamlit secrets; never sent
            to the browser). The model receives the system prompt + the application context.
  * DEMO  – when no key is configured, a deterministic offline explainer answers from the same
            application context (real computed results) and a small built-in knowledge base.
            It is clearly labelled and never invents numbers.
"""
from __future__ import annotations

import re
from typing import Iterator

from ai.context import build_context
from ai.prompts import SYSTEM_PROMPT
from analysis.significance import explain_p_value
from analysis.trends import STATUS_LABEL
from core.config import settings

MAX_HISTORY = 12   # messages of conversation memory sent to the model


def is_live() -> bool:
    return bool(settings()["OPENAI_API_KEY"])


def mode_label() -> str:
    return f"OpenAI · {settings()['OPENAI_MODEL']}" if is_live() else "DEMO MODE · offline explainer"


# ---------------------------------------------------------------- OpenAI
def _openai_stream(history: list[dict], ctx: dict) -> Iterator[str]:
    from openai import OpenAI
    cfg = settings()
    client = OpenAI(api_key=cfg["OPENAI_API_KEY"], timeout=60)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": "APPLICATION CONTEXT (authoritative data):\n" + build_context(ctx)},
        *[{"role": m["role"], "content": m["content"]} for m in history[-MAX_HISTORY:]],
    ]
    stream = client.chat.completions.create(model=cfg["OPENAI_MODEL"], messages=messages,
                                            temperature=0.2, stream=True)
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


def stream_reply(history: list[dict], ctx: dict) -> Iterator[str]:
    """Yield the assistant's reply in chunks. Errors are reported as readable text, not exceptions."""
    if not is_live():
        text = offline_answer(history[-1]["content"], ctx)
        for part in re.split(r"(\s+)", text):      # word-by-word for a typing effect
            yield part
        return
    try:
        yield from _openai_stream(history, ctx)
    except Exception as e:  # network, auth, rate limit, bad model name…
        name = type(e).__name__
        hint = {"AuthenticationError": "The OpenAI API key was rejected. Check OPENAI_API_KEY.",
                "RateLimitError": "OpenAI rate limit or quota reached. Try again shortly.",
                "APIConnectionError": "Could not reach OpenAI. Check your internet connection.",
                "NotFoundError": "The configured OPENAI_MODEL was not found for this key."}.get(name, str(e)[:200])
        yield f"⚠️ The AI service returned an error ({name}). {hint}\n\n"
        yield "Answering with the offline explainer instead:\n\n" + offline_answer(history[-1]["content"], ctx)


# ---------------------------------------------------------------- offline explainer
def _describe(name: str, r: dict, units: str) -> str:
    if r["status"] == "insufficient":
        return f"**{name}** — insufficient data. {r.get('message', '')}"
    base = (f"**{name}** — {STATUS_LABEL[r['status']]} ({r['method_label']}): p = {r['p_value']:.4g}, "
            f"Sen's slope {r['sen_slope_per_decade']:+.3g} {units}/decade "
            f"({r['ci_level']}% CI {r['sen_ci_low'] * 10:+.3g} to {r['sen_ci_high'] * 10:+.3g}), "
            f"n = {r['n_valid']} {r['aggregation']} values, {r['missing_pct']}% missing, "
            f"{r['start'][:4]}–{r['end'][:4]}.")
    if not r["significant"]:
        base += " This is not evidence of no change — only that a trend could not be distinguished from variability."
    return base


KB = {
    "mann": ("**Mann-Kendall test** — a non-parametric test for a monotonic (consistently upward or downward) "
             "trend. It compares every pair of observations: +1 if the later one is higher, −1 if lower. The sum "
             "is *S*; a large |S| relative to its expected variance gives a Z score and p-value. It needs no "
             "normality assumption and resists outliers. Limits: it assumes independent observations (so "
             "EarthScope uses the seasonal version for monthly data and the Hamed-Rao correction when annual "
             "data are autocorrelated), and it detects monotonic trends only — not cycles or sudden shifts."),
    "sen": ("**Sen's slope** — the median of the slopes between all pairs of points. It estimates the rate of "
            "change (e.g. °C per decade) and is far less sensitive to outliers than a least-squares line. "
            "EarthScope reports it with a confidence interval derived from the Mann-Kendall variance."),
    "ndvi": ("For **NDVI**, use **MODIS MOD13Q1** (Terra, 250 m, 16-day composites, 2000–present) — it is "
             "connected in this app through the ORNL DAAC service. For 2012-onwards continuity consider VIIRS "
             "VNP13; for field-scale work use Harmonized Landsat Sentinel-2 (HLS, 30 m). NDVI saturates in dense "
             "canopy (EVI helps there) and is affected by cloud and snow."),
    "report": ("To prepare a scientific report: 1) run a Trend Analysis for your variable/region, 2) open "
               "**Reports**, 3) choose the title, then download the PDF (with chart, methodology, results, "
               "limitations) plus CSV/Excel data. State the dataset, period, test used, α, p-value, Sen's slope "
               "with CI, sample size and missing data — and separate statistical from practical significance."),
    "seasonal": ("**Seasonality** — monthly climate data have a strong annual cycle. The Seasonal Kendall test "
                 "compares January with January, February with February, etc., so the cycle cannot masquerade "
                 "as a trend."),
    "autocorr": ("**Serial correlation** — when one year resembles the previous one, the effective sample size "
                 "is smaller than n and the plain Mann-Kendall test finds too many 'significant' trends. The "
                 "Hamed-Rao and Yue-Wang modifications correct the variance; pre-whitening removes lag-1 "
                 "correlation first."),
    "significan": ("**Statistical vs practical significance** — statistical significance (p < α) says a trend "
                   "is unlikely to be chance. Practical significance asks whether its size matters. A tiny "
                   "trend can be significant in a long record, and an important change can be non-significant "
                   "in a short, noisy one."),
}


def offline_answer(question: str, ctx: dict) -> str:
    q = question.lower()
    parts: list[str] = []
    tr, opp, comp, sig, live = (ctx.get(k) for k in ("trend", "opposite", "comparison", "significance", "live"))

    # p-value questions
    m = re.search(r"p[- ]?value(?: of)?\s*(?:=|is)?\s*(0?\.\d+)", q)
    if m:
        parts.append(explain_p_value(float(m.group(1)), (tr or sig or {}).get("result", {}).get("alpha", 0.05)
                                     if (tr or sig) else 0.05))
    elif "p-value" in q or "p value" in q:
        parts.append("A **p-value** is the probability of seeing a trend at least as strong as the observed one "
                     "*if there were really no trend*. Below α (default 0.05) the result is called statistically "
                     "significant. It is not the probability that the trend is real, and it does not measure size.")

    for key, text in KB.items():
        if key in q or (key == "mann" and "kendall" in q):
            parts.append(text)

    # live monitoring
    if any(w in q for w in ("fire", "wildfire", "detection", "event", "live", "latest", "rain", "storm")):
        if live:
            if live.get("latest_fire"):
                parts.append(f"**Latest fire detection:** {live['latest_fire']}")
            parts.append(f"Live monitoring ({live.get('mode')}): {live.get('n_events')} open events from NASA EONET "
                         f"— {live.get('by_category')}. Refreshed {live.get('refreshed')}.")
            if live.get("latest"):
                parts.append("Most recent:\n" + "\n".join(f"- {e}" for e in live["latest"][:5]))
            if live.get("rain") and "rain" in q:
                parts.append(f"Rainfall: {live['rain']}")
        else:
            parts.append("I don't have live detections in this session yet. Open **Live Earth Monitoring** "
                         "(and press Refresh) so I can read the latest NASA EONET / FIRMS data.")

    # asteroids, meteors, satellites
    if any(w in q for w in ("asteroid", "meteor", "fireball", "satellite", "orbit", "space station", "near-earth", "close approach")):
        space = ctx.get("space")
        if space:
            parts.append("**Space & Orbit Tracker (live NASA/JPL data):**\n" +
                         "\n".join(f"- {k.replace('_', ' ').capitalize()}: {v}" for k, v in space.items()))
        else:
            parts.append("I don't have space-tracking data in this session yet. Open **Space & Orbit Tracker** "
                         "to load asteroids, close approaches, meteor fireballs and satellite orbits.")

    # opposite trends / comparison
    if any(w in q for w in ("opposite", "two regions", "both regions", "compare", "comparison", "differ")):
        if opp:
            parts.append(f"Opposite Trend Detector — {opp['label']} ({opp['period']}): **{opp['pair']['label']}**.")
            parts.append(_describe(opp["region_a"], opp["result_a"], opp["units"]))
            parts.append(_describe(opp["region_b"], opp["result_b"], opp["units"]))
            if opp["pair"]["category"] == "opposite":
                parts.append("Why might they differ? *Hypotheses, not conclusions:* different climate regimes, "
                             "monsoon or circulation changes, irrigation and land-use change, urban growth, or "
                             "aerosol changes. Testing these needs additional datasets.")
        elif comp:
            parts.append(f"Regional comparison — {comp['label']} ({comp['period']}):")
            parts += [_describe(n, r, comp["units"]) for n, r in comp["results"].items()]
        else:
            parts.append("No two-region comparison has been run yet. Open **Opposite Trend Detector**, pick "
                         "Region A and Region B, and I can explain the result.")

    # explain the current graph / result / named region
    wants_result = any(w in q for w in ("graph", "chart", "trend", "happening", "result", "temperature",
                                        "explain this", "what does", "interpret", "summary", "summar"))
    if wants_result and not parts:
        named = None
        for src in (tr, sig):
            if src and src["region"].lower() in q:
                named = src
        src = named or tr or sig
        asked_region = re.search(r"\bin ([a-z ]+?)(?:\?|$|\.)", q)
        if src:
            if asked_region and src["region"].lower() not in q and asked_region.group(1).strip() not in ("this", "the chart"):
                parts.append(f"I only have results for **{src['region']}** right now, not "
                             f"'{asked_region.group(1).strip().title()}'. Select that region in Trend Analysis "
                             "and I'll explain it. Current result:")
            parts.append(_describe(f"{src['label']} in {src['region']}", src["result"], src["units"]))
            r = src["result"]
            if r["status"] != "insufficient":
                parts.append(f"How to read the chart: the solid line is the observed series; the dashed line is "
                             f"Sen's slope; the shaded band is its {r['ci_level']}% confidence range. The mean "
                             f"over the period is {r['mean']:.3g} {src['units']} with a year-to-year standard "
                             f"deviation of {r['std']:.3g}.")
            if src is tr and tr.get("period_comparison"):
                pc = tr["period_comparison"]
                parts.append(f"Comparing periods: {pc['first_period']} averaged {pc['first_mean']:.3g}, "
                             f"{pc['last_period']} averaged {pc['last_mean']:.3g} "
                             f"({pc['difference']:+.3g} {src['units']}).")
        elif opp:
            parts.append(_describe(opp["region_a"], opp["result_a"], opp["units"]))
            parts.append(_describe(opp["region_b"], opp["result_b"], opp["units"]))
        else:
            parts.append("There is no analysis result in this session yet, so I can't describe a graph without "
                         "inventing numbers. Open **Trend Analysis**, choose a region and variable, then ask again.")

    if "dataset" in q and "ndvi" not in q:
        from backend.catalog import DATASETS
        hits = [d for d in DATASETS if any(w in d["variable"].lower() or w in d["name"].lower()
                                           for w in re.findall(r"[a-z0-9]{4,}", q))]
        if hits:
            parts.append("Relevant NASA datasets:\n" + "\n".join(
                f"- **{d['name']}** — {d['mission']}, {d['spatial']}, {d['temporal']}, {d['coverage']}"
                f"{' (connected in app)' if d['connected'] else ''}" for d in hits[:5]))
        else:
            parts.append("Open **Data Explorer** to browse datasets by category (Atmosphere, Land, Water).")

    if not parts:
        parts.append("I'm running in **demo mode** (no OpenAI key), so I can explain the app's computed results, "
                     "p-values, the Mann-Kendall test, Sen's slope, seasonality, dataset choices and live "
                     "detections. Try one of the suggested questions, or add `OPENAI_API_KEY` in Settings/.env "
                     "for free-form answers.")
    footer = "\n\n_Offline explainer (DEMO MODE) — answers use only results computed in this app._"
    return "\n\n".join(parts) + footer
