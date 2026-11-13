"""
Regional comparison and opposite-trend detection.

An "opposite trend" is only reported when BOTH regions show a statistically significant
trend AND the directions differ. Every other combination is labelled explicitly.
"""
from __future__ import annotations

import math

from scipy import stats

PAIR_CATEGORIES = {
    "opposite": "Opposite statistically significant trends",
    "both_increasing": "Both increasing (significant)",
    "both_decreasing": "Both decreasing (significant)",
    "one_significant": "One significant, one non-significant",
    "neither": "Neither statistically significant",
    "insufficient": "Insufficient data in at least one region",
}


def _se_from_ci(r: dict) -> float | None:
    """Approximate standard error of Sen's slope from its confidence interval."""
    lo, hi = r.get("sen_ci_low"), r.get("sen_ci_high")
    if lo is None or hi is None or any(map(lambda v: v != v, [lo, hi])):
        return None
    z = stats.norm.ppf(1 - r["alpha"] / 2)
    return (hi - lo) / (2 * z) if hi > lo else None


def classify_pair(a: dict, b: dict) -> dict:
    """Classify the relationship between two regional trend results."""
    if a["status"] == "insufficient" or b["status"] == "insufficient":
        cat = "insufficient"
    elif a["significant"] and b["significant"]:
        if a["status"] != b["status"]:
            cat = "opposite"
        else:
            cat = "both_increasing" if a["status"] == "increasing" else "both_decreasing"
    elif a["significant"] or b["significant"]:
        cat = "one_significant"
    else:
        cat = "neither"

    out = {"category": cat, "label": PAIR_CATEGORIES[cat]}
    if cat != "insufficient":
        diff = a["sen_slope"] - b["sen_slope"]
        out["slope_difference"] = diff
        out["slope_difference_per_decade"] = diff * 10
        se_a, se_b = _se_from_ci(a), _se_from_ci(b)
        if se_a and se_b:
            z = diff / math.sqrt(se_a ** 2 + se_b ** 2)
            out["difference_z"] = z
            out["difference_p"] = float(2 * (1 - stats.norm.cdf(abs(z))))
    return out


def explain_pair(a: dict, b: dict, name_a: str, name_b: str, label: str, units: str, pair: dict) -> str:
    def desc(r, n):
        if r["status"] == "insufficient":
            return f"{n}: insufficient data"
        state = {"increasing": "significant increase", "decreasing": "significant decrease",
                 "no_significant_trend": "no significant trend"}[r["status"]]
        return f"{n}: {state} (Sen {r['sen_slope_per_decade']:+.3g} {units}/decade, p = {r['p_value']:.3g})"

    lines = [f"- {desc(a, name_a)}", f"- {desc(b, name_b)}"]
    cat = pair["category"]
    if cat == "opposite":
        concl = (f"**{name_a} and {name_b} show opposite, statistically significant trends** in {label.lower()}. "
                 "Possible drivers include different climate regimes (e.g. monsoon vs arid), land-use change, "
                 "irrigation, urbanisation or circulation shifts — the statistics alone cannot identify the cause.")
    elif cat == "one_significant":
        concl = ("Only one region has a statistically significant trend. This is **not** evidence that the trends "
                 "are opposite or different in sign; the other region's trend may simply be undetectable at this "
                 "record length and variability.")
    elif cat == "neither":
        concl = "Neither region shows a statistically significant trend, so no opposite-trend conclusion can be drawn."
    elif cat == "insufficient":
        concl = "At least one region lacks enough valid data for a reliable test."
    else:
        concl = f"Both regions change in the same direction ({PAIR_CATEGORIES[cat].lower()})."
    if "difference_p" in pair:
        concl += (f"\n\nDifference in Sen's slopes: {pair['slope_difference_per_decade']:+.3g} {units}/decade "
                  f"(approximate z-test p = {pair['difference_p']:.3g}; assumes independent regions).")
    return "\n".join(lines) + "\n\n" + concl
