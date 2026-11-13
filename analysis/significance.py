"""
Significance testing helpers: separate *statistical* significance from *practical* importance.
"""
from __future__ import annotations

import numpy as np


def explain_p_value(p: float, alpha: float = 0.05) -> str:
    verdict = "below" if p < alpha else "not below"
    return (f"p = {p:.4f} is {verdict} the significance threshold α = {alpha}. "
            f"It means: *if there were truly no monotonic trend*, a trend at least this strong would appear "
            f"by chance about {p * 100:.1f}% of the time. It is **not** the probability that the trend is real, "
            "and it says nothing about how large or important the change is.")


def practical_importance(r: dict) -> dict:
    """Signal-to-noise: total change over the record compared with interannual variability."""
    if r.get("status") == "insufficient" or not r.get("std"):
        return {"ratio": None, "level": "unknown", "text": "Not enough data to judge practical importance."}
    ratio = abs(r["total_change"]) / r["std"] if r["std"] else np.nan
    rel = abs(r["total_change"]) / abs(r["mean"]) * 100 if r.get("mean") else np.nan
    if ratio >= 1.5:
        level = "large"
    elif ratio >= 0.5:
        level = "moderate"
    else:
        level = "small"
    text = (f"The estimated total change ({r['total_change']:+.3g}) is {ratio:.2f}× the typical year-to-year "
            f"standard deviation ({r['std']:.3g}) and ≈{rel:.1f}% of the long-term mean — a **{level}** change "
            "relative to natural variability. Whether that matters environmentally depends on the variable "
            "and the system (e.g. 1 °C of warming can matter a great deal for heat stress or crops).")
    return {"ratio": float(ratio), "relative_pct": float(rel), "level": level, "text": text}


def significance_table(r: dict) -> list[tuple[str, str]]:
    """Rows for a results table."""
    if r.get("status") == "insufficient":
        return [("Status", "Insufficient data"), ("Valid values", str(r["n_valid"])),
                ("Missing", f"{r['missing_pct']}%")]
    return [
        ("Test", r["method_label"]),
        ("Significance threshold (α)", f"{r['alpha']}"),
        ("Mann-Kendall S", f"{r['mk_s']:.0f}"),
        ("Z statistic", f"{r['mk_z']:.3f}"),
        ("Kendall's τ", f"{r['kendall_tau']:.3f}"),
        ("p-value", f"{r['p_value']:.4g}"),
        ("Result", "Significant" if r["significant"] else "Not significant"),
        ("Sen's slope", f"{r['sen_slope']:+.4g} per year ({r['sen_slope_per_decade']:+.4g} per decade)"),
        (f"Sen's slope {r['ci_level']}% CI", f"{r['sen_ci_low']:+.4g} to {r['sen_ci_high']:+.4g} per year"),
        ("OLS slope (comparison)", f"{r['ols_slope']:+.4g} per year (p = {r['ols_p']:.3g}, R² = {r['ols_r2']:.2f})"),
        ("Lag-1 autocorrelation", f"{r['lag1_autocorr']} ({'significant' if r['autocorr_significant'] else 'not significant'})"),
        ("Sample size", f"{r['n_valid']} valid of {r['n_total']} ({r['aggregation']})"),
        ("Missing data", f"{r['missing_pct']}%"),
        ("Period", f"{r['start']} → {r['end']}"),
    ]
