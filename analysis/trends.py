"""
Trend analysis engine.

Implements, for a monthly or annual environmental time series:
  * Mann-Kendall trend test (original, seasonal, and serial-correlation–corrected variants),
  * Sen's slope estimator with a distribution-free confidence interval (Gilbert, 1987),
  * ordinary least squares linear trend (for comparison and plotting),
  * sample-size and missing-data reporting,
  * a classification that never treats "not significant" as "no change".

Method choice ("auto"):
  * monthly data  -> Seasonal Kendall test (Hirsch et al., 1982): compares each calendar
                     month only with the same month in other years, removing the seasonal cycle.
  * annual data   -> original Mann-Kendall test, switching to the Hamed & Rao (1998) variance
                     correction when significant lag-1 autocorrelation is detected.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pymannkendall as pmk
from scipy import stats

METHODS = {
    "auto": "Automatic (seasonal Kendall for monthly, MK / Hamed-Rao for annual)",
    "original": "Original Mann-Kendall",
    "seasonal": "Seasonal Kendall (Hirsch 1982)",
    "hamed_rao": "Hamed & Rao modified MK (autocorrelation-corrected)",
    "yue_wang": "Yue & Wang modified MK (effective sample size)",
    "tfpw": "Trend-free pre-whitening MK (Yue et al. 2002)",
}

MIN_ANNUAL = 10          # minimum valid annual values for a meaningful test
MIN_MONTHLY_YEARS = 5    # minimum years per calendar month for the seasonal test


# ---------------------------------------------------------------- data preparation
def aggregate(df: pd.DataFrame, aggregation: str = "annual", min_months: int = 10) -> pd.Series:
    """Return the series to analyse. Annual means require >= `min_months` valid months."""
    s = df["value"].astype(float)
    if aggregation != "annual":
        return s
    g = s.groupby(s.index.year)
    means, counts = g.mean(), g.count()
    means[counts < min_months] = np.nan
    means.index = pd.to_datetime([f"{y}-07-01" for y in means.index])
    means.index.name = "date"
    return means


def fractional_year(idx: pd.DatetimeIndex) -> np.ndarray:
    return (idx.year + (idx.dayofyear - 1) / 365.25).to_numpy(dtype=float)


# ---------------------------------------------------------------- core statistics
def _mk_s(x: np.ndarray) -> tuple[float, float, float]:
    """Mann-Kendall S, its variance (tie-corrected) and number of pairs, NaNs removed."""
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 2:
        return 0.0, 0.0, 0.0
    diff = np.sign(x[None, :] - x[:, None])
    s = float(np.triu(diff, 1).sum())
    _, counts = np.unique(x, return_counts=True)
    ties = counts[counts > 1]
    var = (n * (n - 1) * (2 * n + 5) - np.sum(ties * (ties - 1) * (2 * ties + 5))) / 18.0
    return s, float(var), n * (n - 1) / 2


def _z_from_s(s: float, var: float) -> float:
    if var <= 0:
        return 0.0
    if s > 0:
        return (s - 1) / math.sqrt(var)
    if s < 0:
        return (s + 1) / math.sqrt(var)
    return 0.0


def _pairwise_slopes(t: np.ndarray, x: np.ndarray) -> np.ndarray:
    ok = ~np.isnan(x)
    t, x = t[ok], x[ok]
    i, j = np.triu_indices(len(x), 1)
    dt = t[j] - t[i]
    keep = dt != 0
    return (x[j] - x[i])[keep] / dt[keep]


def sen_slope_ci(slopes: np.ndarray, var_s: float, alpha: float) -> tuple[float, float, float]:
    """Sen's slope (median of pairwise slopes) and its (1-alpha) confidence interval (Gilbert 1987)."""
    slopes = np.sort(slopes[~np.isnan(slopes)])
    N = len(slopes)
    if N == 0:
        return np.nan, np.nan, np.nan
    med = float(np.median(slopes))
    if var_s <= 0:
        return med, np.nan, np.nan
    c = stats.norm.ppf(1 - alpha / 2) * math.sqrt(var_s)
    m1 = int(round((N - c) / 2.0))
    m2 = int(round((N + c) / 2.0))
    lo = slopes[min(max(m1 - 1, 0), N - 1)]
    hi = slopes[min(max(m2, 0), N - 1)]
    return med, float(lo), float(hi)


def seasonal_kendall(series: pd.Series, period: int = 12) -> dict:
    """Seasonal Kendall test that tolerates missing months (each month tested separately, then summed)."""
    s_tot, var_tot, d_tot = 0.0, 0.0, 0.0
    slopes = []
    for m in range(1, period + 1):
        sub = series[series.index.month == m]
        x = sub.to_numpy(dtype=float)
        s, var, d = _mk_s(x)
        s_tot += s
        var_tot += var
        d_tot += d
        slopes.append(_pairwise_slopes(fractional_year(sub.index), x))
    z = _z_from_s(s_tot, var_tot)
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    return {"s": s_tot, "var_s": var_tot, "z": z, "p": p, "tau": s_tot / d_tot if d_tot else np.nan,
            "slopes": np.concatenate(slopes) if slopes else np.array([])}


def lag1_autocorrelation(t: np.ndarray, x: np.ndarray) -> float:
    """Lag-1 autocorrelation of the linearly detrended series."""
    ok = ~np.isnan(x)
    if ok.sum() < 4:
        return np.nan
    t, x = t[ok], x[ok]
    resid = x - np.polyval(np.polyfit(t, x, 1), t)
    return float(pd.Series(resid).autocorr(lag=1))


# ---------------------------------------------------------------- main entry point
def run_trend(df: pd.DataFrame, aggregation: str = "annual", method: str = "auto",
              alpha: float = 0.05) -> dict:
    """Run the full trend analysis and return a JSON-serialisable result dictionary."""
    series = aggregate(df, aggregation)
    t = fractional_year(series.index)
    x = series.to_numpy(dtype=float)
    n_total = len(x)
    n_valid = int(np.sum(~np.isnan(x)))
    missing_pct = 100.0 * (n_total - n_valid) / n_total if n_total else 100.0
    years = sorted(set(series.dropna().index.year))
    unit_time = "year"

    base = {
        "aggregation": aggregation, "alpha": alpha, "n_total": n_total, "n_valid": n_valid,
        "n_missing": n_total - n_valid, "missing_pct": round(missing_pct, 1),
        "start": str(series.index.min().date()) if n_total else None,
        "end": str(series.index.max().date()) if n_total else None,
        "years": len(years),
    }

    # --- sufficiency checks
    insufficient = (aggregation == "annual" and n_valid < MIN_ANNUAL) or \
                   (aggregation != "annual" and len(years) < MIN_MONTHLY_YEARS) or missing_pct > 50
    if insufficient:
        return {**base, "status": "insufficient", "significant": False, "method": None,
                "message": (f"Only {n_valid} valid values ({len(years)} years, {missing_pct:.0f}% missing). "
                            f"At least {MIN_ANNUAL} annual values or {MIN_MONTHLY_YEARS} years of monthly data "
                            "with ≤50% missing are needed.")}

    r1 = lag1_autocorrelation(t, x)
    r1_sig = bool(not np.isnan(r1) and abs(r1) > 1.96 / math.sqrt(n_valid))

    if method == "auto":
        method = "seasonal" if aggregation != "annual" else ("hamed_rao" if r1_sig else "original")

    if method == "seasonal":
        if aggregation == "annual":
            method = "original"            # seasonal test needs monthly data
        else:
            sk = seasonal_kendall(series)
            s, var_s, z, p, tau, slopes = sk["s"], sk["var_s"], sk["z"], sk["p"], sk["tau"], sk["slopes"]

    if method != "seasonal":
        xv = x[~np.isnan(x)]
        fn = {"original": pmk.original_test, "hamed_rao": pmk.hamed_rao_modification_test,
              "yue_wang": pmk.yue_wang_modification_test,
              "tfpw": pmk.trend_free_pre_whitening_modification_test}[method]
        res = fn(xv, alpha=alpha)
        s, var_s, z, p, tau = float(res.s), float(res.var_s), float(res.z), float(res.p), float(res.Tau)
        slopes = _pairwise_slopes(t, x)

    slope, ci_lo, ci_hi = sen_slope_ci(slopes, var_s, alpha)

    # --- OLS for comparison
    ok = ~np.isnan(x)
    lr = stats.linregress(t[ok], x[ok])
    tcrit = stats.t.ppf(1 - alpha / 2, ok.sum() - 2)
    span_years = float(t[ok].max() - t[ok].min())

    significant = bool(p < alpha)
    if significant:
        status = "increasing" if z > 0 else "decreasing"
    else:
        status = "no_significant_trend"

    # Sen intercept so the trend line passes through the median point
    intercept = float(np.nanmedian(x) - slope * np.nanmedian(t[ok]))

    return {
        **base,
        "status": status, "significant": significant, "method": method, "method_label": METHODS[method],
        "mk_s": s, "mk_var_s": var_s, "mk_z": round(z, 4), "kendall_tau": round(tau, 4),
        "p_value": float(p),
        "sen_slope": slope, "sen_slope_per_decade": slope * 10, "sen_ci_low": ci_lo, "sen_ci_high": ci_hi,
        "sen_intercept": intercept, "slope_unit": f"per {unit_time}",
        "ci_level": round(100 * (1 - alpha)),
        "total_change": slope * span_years, "span_years": round(span_years, 1),
        "ols_slope": float(lr.slope), "ols_p": float(lr.pvalue), "ols_r2": float(lr.rvalue ** 2),
        "ols_intercept": float(lr.intercept),
        "ols_ci_low": float(lr.slope - tcrit * lr.stderr), "ols_ci_high": float(lr.slope + tcrit * lr.stderr),
        "lag1_autocorr": None if np.isnan(r1) else round(r1, 3), "autocorr_significant": r1_sig,
        "mean": float(np.nanmean(x)), "std": float(np.nanstd(x, ddof=1)),
    }


# ---------------------------------------------------------------- supporting tables
def annual_table(df: pd.DataFrame, baseline: tuple[int, int] | None = None) -> pd.DataFrame:
    """Annual mean, change from previous year and anomaly relative to a baseline period."""
    ann = aggregate(df, "annual")
    out = pd.DataFrame({"year": ann.index.year, "annual_mean": ann.values})
    out["change_vs_prev"] = out["annual_mean"].diff()
    if baseline is None:
        baseline = (int(out["year"].min()), int(min(out["year"].min() + 29, out["year"].max())))
    ref = out[(out["year"] >= baseline[0]) & (out["year"] <= baseline[1])]["annual_mean"].mean()
    out["anomaly"] = out["annual_mean"] - ref
    out.attrs["baseline"] = baseline
    return out


def period_comparison(df: pd.DataFrame, window: int = 10) -> dict:
    """Compare the first and last `window` years (mean difference + Mann-Whitney U test)."""
    ann = aggregate(df, "annual").dropna()
    if len(ann) < 2 * window:
        window = max(3, len(ann) // 2)
    first, last = ann.iloc[:window], ann.iloc[-window:]
    if len(first) < 3 or len(last) < 3:
        return {}
    u = stats.mannwhitneyu(first, last, alternative="two-sided")
    return {
        "window": window,
        "first_period": f"{first.index.year.min()}–{first.index.year.max()}", "first_mean": float(first.mean()),
        "last_period": f"{last.index.year.min()}–{last.index.year.max()}", "last_mean": float(last.mean()),
        "difference": float(last.mean() - first.mean()), "mannwhitney_p": float(u.pvalue),
    }


# ---------------------------------------------------------------- interpretation
STATUS_LABEL = {
    "increasing": "Increasing trend",
    "decreasing": "Decreasing trend",
    "no_significant_trend": "No statistically significant trend detected",
    "insufficient": "Insufficient data",
}


def fmt_p(p: float) -> str:
    """Readable p-value: very small values are shown as '< 0.0001' instead of 0.0000."""
    return "< 0.0001" if p < 1e-4 else f"{p:.4f}"


def interpret(r: dict, label: str, units: str, region: str) -> str:
    """Plain-language interpretation with appropriate scientific caution."""
    if r["status"] == "insufficient":
        return f"**Insufficient data.** {r['message']} No conclusion about a trend can be drawn."
    alpha = r["alpha"]
    slope_dec = r["sen_slope_per_decade"]
    ci = f"{r['ci_level']}% CI {r['sen_ci_low'] * 10:+.3g} to {r['sen_ci_high'] * 10:+.3g} {units}/decade"
    period = f"{r['start'][:4]}–{r['end'][:4]}"
    if r["significant"]:
        direction = "increased" if r["status"] == "increasing" else "decreased"
        txt = (f"**{label} in {region} has {direction} over {period}.** The {r['method_label']} gives "
               f"p {'= ' if r['p_value'] >= 1e-4 else ''}{fmt_p(r['p_value'])} (below α = {alpha}), and Sen's slope is **{slope_dec:+.3g} {units} per decade** "
               f"({ci}), about {r['total_change']:+.3g} {units} across the {r['span_years']:.0f}-year record.")
    else:
        txt = (f"**No statistically significant trend was detected** for {label.lower()} in {region} over {period} "
               f"(p = {r['p_value']:.3f} ≥ α = {alpha}; Sen's slope {slope_dec:+.3g} {units}/decade, {ci}). "
               "This does **not** prove the variable is unchanged: the change may be too small relative to "
               "year-to-year variability, or the record too short, for the test to detect it.")
    if r.get("autocorr_significant") and r["method"] == "original":
        txt += " ⚠️ Significant lag-1 autocorrelation was found; consider the Hamed-Rao corrected test."
    if r["missing_pct"] > 10:
        txt += f" ⚠️ {r['missing_pct']:.0f}% of values are missing, which reduces reliability."
    return txt


METHODOLOGY = """
**Mann-Kendall (MK) test** — a non-parametric, rank-based test for a monotonic trend. It counts how often
later values exceed earlier ones (statistic *S*). It makes no assumption of normality or linearity and is robust
to outliers. H₀: no monotonic trend. A p-value below α (default 0.05) rejects H₀.

**Seasonal Kendall test** — for monthly data the MK statistic is computed separately for each calendar month
(January vs January, …) and summed, so the seasonal cycle cannot create a false trend.

**Serial correlation** — positive autocorrelation inflates false-positive rates. For annual data the lag-1
autocorrelation of the detrended series is tested; if significant, the **Hamed & Rao (1998)** variance
correction is used automatically. Yue-Wang and trend-free pre-whitening variants are also available.

**Sen's slope** — the median of all pairwise slopes (Δvalue / Δtime), a robust estimate of the rate of change.
Its confidence interval follows Gilbert (1987) using the MK variance.

**Limitations** — results describe a single NASA POWER grid cell (≈50 km) or a 3×3 sample of cells, not a full
area average; reanalysis data (MERRA-2) are model-assimilated estimates, not direct measurements; MK detects
monotonic trends only (not step changes or cycles); statistical significance is not the same as practical or
environmental importance; and a non-significant result is not evidence of no change.
"""
