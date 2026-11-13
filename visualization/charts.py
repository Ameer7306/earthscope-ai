"""
Plotly chart builders using the EarthScope dark theme.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from analysis.trends import aggregate, fractional_year
from core.config import COLORS

GRID = "rgba(148,163,184,.12)"


def _layout(fig: go.Figure, title: str = "", height: int = 380, ytitle: str = "") -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=COLORS["text"]), x=0.01, xanchor="left"),
        template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(13,27,42,.55)",
        font=dict(color=COLORS["text"], family="Inter, system-ui, Segoe UI, sans-serif", size=12),
        margin=dict(l=55, r=20, t=50 if title else 20, b=40), height=height,
        hovermode="x unified", legend=dict(orientation="h", y=-0.18, x=0, bgcolor="rgba(0,0,0,0)"),
        transition=dict(duration=600, easing="cubic-in-out"),      # smooth transitions on update
        xaxis=dict(gridcolor=GRID, zeroline=False), yaxis=dict(gridcolor=GRID, zeroline=False, title=ytitle),
    )
    return fig


def trend_chart(df: pd.DataFrame, result: dict, label: str, units: str, region: str,
                aggregation: str = "annual", show_ols: bool = True, color: str = COLORS["primary"]) -> go.Figure:
    """Time series with Sen's slope line, its confidence band and an optional OLS line."""
    s = aggregate(df, aggregation)
    fig = go.Figure()
    if aggregation != "annual":
        fig.add_trace(go.Scatter(x=s.index, y=s.values, mode="lines", name=f"Monthly {label}",
                                 line=dict(color=color, width=1.2), opacity=.75))
        roll = s.rolling(12, min_periods=9, center=True).mean()
        fig.add_trace(go.Scatter(x=roll.index, y=roll.values, mode="lines", name="12-month running mean",
                                 line=dict(color=COLORS["secondary"], width=2.4)))
    else:
        fig.add_trace(go.Scatter(x=s.index, y=s.values, mode="lines+markers", name=f"Annual mean",
                                 line=dict(color=color, width=2.2, shape="spline", smoothing=.4),
                                 marker=dict(size=6, line=dict(width=1, color=COLORS["bg"]))))
    if result.get("status") not in (None, "insufficient"):
        t = fractional_year(s.index)
        tmed = float(np.nanmedian(t[~np.isnan(s.values)]))
        ymed = float(np.nanmedian(s.values))
        tc = COLORS["positive"] if result["sen_slope"] >= 0 else COLORS["negative"]
        if not result["significant"]:
            tc = COLORS["muted"]
        lo = ymed + result["sen_ci_low"] * (t - tmed)
        hi = ymed + result["sen_ci_high"] * (t - tmed)
        if not (np.isnan(lo).any() or np.isnan(hi).any()):
            fig.add_trace(go.Scatter(x=list(s.index) + list(s.index[::-1]), y=list(hi) + list(lo[::-1]),
                                     fill="toself", fillcolor="rgba(148,163,184,.13)", line=dict(width=0),
                                     hoverinfo="skip", name=f"Sen slope {result['ci_level']}% CI"))
        fig.add_trace(go.Scatter(x=s.index, y=ymed + result["sen_slope"] * (t - tmed), mode="lines",
                                 name=f"Sen's slope ({result['sen_slope_per_decade']:+.3g} {units}/decade)",
                                 line=dict(color=tc, width=2.6, dash="dash")))
        if show_ols:
            fig.add_trace(go.Scatter(x=s.index, y=result["ols_intercept"] + result["ols_slope"] * t, mode="lines",
                                     name="Linear (OLS)", line=dict(color=COLORS["warning"], width=1.4, dash="dot")))
    return _layout(fig, f"{label} — {region}", ytitle=units)


def anomaly_bars(annual: pd.DataFrame, units: str, title: str = "Annual anomaly") -> go.Figure:
    colors = [COLORS["negative"] if v >= 0 else COLORS["primary"] for v in annual["anomaly"].fillna(0)]
    fig = go.Figure(go.Bar(x=annual["year"], y=annual["anomaly"], marker_color=colors, name="Anomaly"))
    b = annual.attrs.get("baseline")
    return _layout(fig, f"{title} (vs {b[0]}–{b[1]} mean)" if b else title, height=300, ytitle=units)


def change_bars(annual: pd.DataFrame, units: str) -> go.Figure:
    v = annual["change_vs_prev"]
    colors = [COLORS["positive"] if x >= 0 else COLORS["negative"] for x in v.fillna(0)]
    fig = go.Figure(go.Bar(x=annual["year"], y=v, marker_color=colors, name="Year-on-year change"))
    return _layout(fig, "Year-on-year change", height=300, ytitle=units)


def seasonal_cycle(df: pd.DataFrame, units: str, split_year: int) -> go.Figure:
    """Mean seasonal cycle for the early vs recent half of the record."""
    s = df["value"]
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    early = s[s.index.year < split_year].groupby(s[s.index.year < split_year].index.month).mean()
    late = s[s.index.year >= split_year].groupby(s[s.index.year >= split_year].index.month).mean()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=months, y=early.reindex(range(1, 13)).values, name=f"Before {split_year}",
                             mode="lines+markers", line=dict(color=COLORS["muted"], width=2)))
    fig.add_trace(go.Scatter(x=months, y=late.reindex(range(1, 13)).values, name=f"{split_year} onwards",
                             mode="lines+markers", line=dict(color=COLORS["primary"], width=2.5)))
    return _layout(fig, "Seasonal cycle: early vs recent", height=300, ytitle=units)


def multi_region_chart(series: dict[str, pd.Series], label: str, units: str, normalise: bool = False) -> go.Figure:
    palette = [COLORS["primary"], COLORS["secondary"], "#F59E0B", "#A78BFA", "#F472B6", "#22C55E", "#FB7185", "#60A5FA"]
    fig = go.Figure()
    for i, (name, s) in enumerate(series.items()):
        y = s - s.mean() if normalise else s
        fig.add_trace(go.Scatter(x=s.index.year, y=y.values, mode="lines+markers", name=name,
                                 line=dict(color=palette[i % len(palette)], width=2), marker=dict(size=4)))
    return _layout(fig, f"{label} — annual {'anomaly from own mean' if normalise else 'mean'}", ytitle=units)


def slope_bar(rows: pd.DataFrame, units: str) -> go.Figure:
    """Sen's slope per decade by region with CI error bars; faded bars are non-significant."""
    rows = rows.sort_values("slope_dec")
    colors = [(COLORS["positive"] if v >= 0 else COLORS["negative"]) if sig else "rgba(148,163,184,.55)"
              for v, sig in zip(rows["slope_dec"], rows["significant"])]
    fig = go.Figure(go.Bar(
        x=rows["slope_dec"], y=rows["region"], orientation="h", marker_color=colors,
        error_x=dict(type="data", symmetric=False, array=rows["ci_hi_dec"] - rows["slope_dec"],
                     arrayminus=rows["slope_dec"] - rows["ci_lo_dec"], color="rgba(248,250,252,.6)", thickness=1.2),
        hovertemplate="%{y}: %{x:+.3g} " + units + "/decade<extra></extra>"))
    fig.add_vline(x=0, line_color="rgba(248,250,252,.4)")
    fig = _layout(fig, "Sen's slope per decade (grey = not statistically significant)",
                  height=max(280, 46 * len(rows) + 90), ytitle="")
    fig.update_layout(hovermode="closest", xaxis_title=f"{units} per decade")
    return fig


def global_temp_chart(gis: pd.DataFrame) -> go.Figure:
    ann = gis["value"].groupby(gis.index.year).agg(["mean", "count"])
    ann = ann[ann["count"] == 12]["mean"]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=ann.index, y=ann.values, name="Annual anomaly",
                         marker=dict(color=ann.values, colorscale="RdBu_r", cmid=0, cmin=-1.3, cmax=1.3)))
    fig.add_trace(go.Scatter(x=ann.index, y=ann.rolling(10, center=True, min_periods=5).mean().values,
                             name="10-year mean", line=dict(color=COLORS["text"], width=2)))
    return _layout(fig, "Global temperature anomaly (NASA GISTEMP v4, vs 1951–1980)", height=340, ytitle="°C")


def simple_line(s: pd.Series, title: str, units: str, color: str = COLORS["primary"], fill: bool = True,
                height: int = 300) -> go.Figure:
    fig = go.Figure(go.Scatter(x=s.index, y=s.values, mode="lines", line=dict(color=color, width=2),
                               fill="tozeroy" if fill else None,
                               fillcolor="rgba(56,189,248,.10)" if fill else None, name=title))
    return _layout(fig, title, height=height, ytitle=units)


def daily_bars(s: pd.Series, title: str, units: str) -> go.Figure:
    fig = go.Figure(go.Bar(x=s.index, y=s.values, marker_color=COLORS["primary"], name=title))
    return _layout(fig, title, height=300, ytitle=units)


def rotating_globe(events: pd.DataFrame, color_map: dict, height: int = 470) -> go.Figure:
    """Orthographic globe with event markers and a play button that rotates the Earth."""
    fig = go.Figure()
    if events is not None and not events.empty:
        for cat, grp in events.groupby("category"):
            fig.add_trace(go.Scattergeo(
                lon=grp["lon"], lat=grp["lat"], text=grp["title"], name=cat, mode="markers",
                marker=dict(size=8, color=color_map.get(cat, COLORS["primary"]), opacity=.9,
                            line=dict(width=1, color="rgba(7,17,31,.9)")),
                hovertemplate="<b>%{text}</b><br>%{lat:.2f}°, %{lon:.2f}°<extra>" + cat + "</extra>"))
    fig.update_geos(projection_type="orthographic", projection_rotation=dict(lon=30, lat=15),
                    showland=True, landcolor="#16324F", showocean=True, oceancolor="#0A1E33",
                    showcountries=True, countrycolor="rgba(148,163,184,.35)", coastlinecolor="rgba(125,211,252,.55)",
                    showlakes=False, bgcolor="rgba(0,0,0,0)", framecolor="rgba(56,189,248,.35)")
    frames = [go.Frame(layout=dict(geo=dict(projection_rotation=dict(lon=lon, lat=15)))) for lon in range(30, 391, 6)]
    fig.frames = frames
    fig.update_layout(
        template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", height=height, margin=dict(l=0, r=0, t=10, b=0),
        legend=dict(orientation="h", y=-0.02, bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
        font=dict(color=COLORS["text"]),
        updatemenus=[dict(type="buttons", showactive=False, x=0.02, y=0.98, xanchor="left", yanchor="top",
                          bgcolor="rgba(18,36,58,.9)", bordercolor="rgba(56,189,248,.5)",
                          font=dict(color=COLORS["text"]),
                          buttons=[dict(label="▶ Rotate", method="animate",
                                        args=[None, dict(frame=dict(duration=90, redraw=True), fromcurrent=True,
                                                         transition=dict(duration=0), mode="immediate")]),
                                   dict(label="❚❚", method="animate",
                                        args=[[None], dict(frame=dict(duration=0, redraw=False), mode="immediate")])])])
    return fig
