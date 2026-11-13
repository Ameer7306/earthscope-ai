"""
Smoke tests for the data layer and analysis engine (uses live NASA services).

Run from the project folder:   venv\\Scripts\\python tests\\test_core.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.anomalies import detect_extremes  # noqa: E402
from analysis.regional import classify_pair  # noqa: E402
from analysis.significance import practical_importance  # noqa: E402
from analysis.trends import METHODS, annual_table, interpret, period_comparison, run_trend  # noqa: E402
from backend import database as db  # noqa: E402
from backend import nasa_api  # noqa: E402


def synthetic(slope: float, noise: float, years: int = 30, seed: int = 1, seasonal: float = 5.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("1995-01-01", periods=years * 12, freq="MS")
    t = np.arange(len(idx)) / 12
    val = 20 + slope * t + seasonal * np.sin(2 * np.pi * idx.month / 12) + rng.normal(0, noise, len(idx))
    return pd.DataFrame({"value": val}, index=idx)


def test_statistics():
    up, down, flat = synthetic(0.05, 0.3), synthetic(-0.05, 0.3), synthetic(0.0, 0.3, seed=7)
    for agg in ("annual", "monthly"):
        r = run_trend(up, agg)
        assert r["status"] == "increasing", r
        assert abs(r["sen_slope"] - 0.05) < 0.02, r["sen_slope"]
        assert r["sen_ci_low"] < r["sen_slope"] < r["sen_ci_high"]
        assert run_trend(down, agg)["status"] == "decreasing"
        assert run_trend(flat, agg)["status"] == "no_significant_trend"
    for m in METHODS:
        assert run_trend(up, "annual", m)["status"] == "increasing", m
    assert run_trend(up.iloc[:48], "annual")["status"] == "insufficient"
    gappy = up.copy()
    gappy.iloc[::2] = np.nan
    assert run_trend(gappy, "annual")["status"] == "insufficient"       # every year < 10 valid months
    r_up, r_down, r_flat = run_trend(up), run_trend(down), run_trend(flat)
    assert classify_pair(r_up, r_down)["category"] == "opposite"
    assert classify_pair(r_up, r_up)["category"] == "both_increasing"
    assert classify_pair(r_down, r_down)["category"] == "both_decreasing"
    assert classify_pair(r_up, r_flat)["category"] == "one_significant"
    assert classify_pair(r_flat, r_flat)["category"] == "neither"
    assert classify_pair(r_up, run_trend(up.iloc[:48]))["category"] == "insufficient"
    assert "does **not** prove" in interpret(r_flat, "Test", "u", "X")
    assert practical_importance(r_up)["level"] in ("small", "moderate", "large")
    assert len(annual_table(up)) == 30 and period_comparison(up)["difference"] > 0
    detect_extremes(up)
    print("statistics OK")


def test_nasa():
    df, meta = nasa_api.fetch_series("air_temperature", "Qatar", 1991, 2025)
    assert len(df) == 35 * 12 and df["value"].notna().mean() > 0.95, df["value"].notna().mean()
    r = run_trend(df, "annual")
    print(f"Qatar T2M: {r['status']} {r['sen_slope_per_decade']:+.3f} °C/decade p={r['p_value']:.4g} [{r['method']}]")
    df2, _ = nasa_api.fetch_series("precipitation", "India", 1991, 2025, sampling="area")
    r2 = run_trend(df2, "annual")
    print(f"India precip (area): {r2['status']} {r2['sen_slope_per_decade']:+.3f} mm/day/decade p={r2['p_value']:.3g}")
    ndvi, _ = nasa_api.fetch_series("ndvi", "India", 2022, 2025)
    assert ndvi["value"].notna().sum() >= 40 and 0 < ndvi["value"].mean() < 1
    print(f"India NDVI mean {ndvi['value'].mean():.3f} ({ndvi['value'].notna().sum()} months)")
    g = nasa_api.fetch_gistemp_global()
    assert g.index.min().year == 1880 and len(g) > 1700
    ev = nasa_api.fetch_eonet(30)
    print(f"GISTEMP rows {len(g)}, EONET open events {len(ev)}: {ev['category'].value_counts().to_dict()}")
    assert {"lat", "lon", "time", "category", "title"} <= set(ev.columns)
    fb = nasa_api.fetch_fireballs(5)
    assert len(fb) == 5
    d = nasa_api.fetch_power_daily(25.29, 51.53, ["PRECTOTCORR"], pd.Timestamp.today().date() - pd.Timedelta(days=30),
                                   pd.Timestamp.today().date())
    print(f"daily rain rows {len(d)} valid {d['PRECTOTCORR'].notna().sum()}")
    db.init_db()
    db.store_observations(df, meta)
    db.store_alerts(ev)
    print("db:", db.table_counts())
    print("NASA data layer OK")


if __name__ == "__main__":
    test_statistics()
    test_nasa()
