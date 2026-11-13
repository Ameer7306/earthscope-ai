"""
Anomaly detection: deviations from a monthly climatology (baseline) and extreme-month flags.
"""
from __future__ import annotations

import pandas as pd


def climatology(df: pd.DataFrame, baseline: tuple[int, int]) -> pd.DataFrame:
    """Per-calendar-month mean and std over the baseline period."""
    s = df["value"]
    base = s[(s.index.year >= baseline[0]) & (s.index.year <= baseline[1])]
    return base.groupby(base.index.month).agg(["mean", "std"])


def monthly_anomalies(df: pd.DataFrame, baseline: tuple[int, int] | None = None) -> pd.DataFrame:
    """Return value, anomaly and standardised anomaly (z) for each month."""
    s = df["value"]
    if baseline is None:
        y0 = int(s.dropna().index.year.min())
        baseline = (y0, min(y0 + 29, int(s.dropna().index.year.max())))
    clim = climatology(df, baseline)
    m = s.index.month
    mean = clim["mean"].reindex(m).to_numpy()
    std = clim["std"].reindex(m).to_numpy()
    out = pd.DataFrame({"value": s.values, "anomaly": s.values - mean,
                        "z": (s.values - mean) / std}, index=s.index)
    out.attrs["baseline"] = baseline
    return out


def detect_extremes(df: pd.DataFrame, z_threshold: float = 2.0, recent_months: int = 24,
                    baseline: tuple[int, int] | None = None) -> pd.DataFrame:
    """Months in the recent window whose standardised anomaly exceeds the threshold."""
    an = monthly_anomalies(df, baseline).dropna()
    recent = an.iloc[-recent_months:]
    ext = recent[recent["z"].abs() >= z_threshold].copy()
    ext["kind"] = ext["z"].apply(lambda z: "unusually high" if z > 0 else "unusually low")
    return ext
