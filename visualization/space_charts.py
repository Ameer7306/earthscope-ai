"""
Plotly charts for the Space & Orbit Tracker: animated asteroid orbits, close-approach
timeline, meteor (fireball) globe and satellite ground tracks.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from backend import space_api
from core.config import COLORS

PLANET_COLORS = {"Mercury": "#A8A29E", "Venus": "#FCD34D", "Earth": "#38BDF8", "Mars": "#F87171", "Jupiter": "#FDBA74"}
_BTN = dict(bgcolor="rgba(18,36,58,.9)", bordercolor="rgba(56,189,248,.5)", font=dict(color=COLORS["text"]))


def orbit_animation(el: dict, span_days: int = 120, frames: int = 61) -> go.Figure:
    """Top-down view of the inner solar system with the asteroid and planets moving along their orbits."""
    limit = max(1.7, min(el["Q"], 6.0) * 1.08)
    planets = [p for p in space_api.PLANETS if space_api.PLANETS[p][0] <= limit * 1.02]
    fig = go.Figure()
    for p in planets:
        xyz = space_api.orbit_path(space_api.planet_elements(p))
        fig.add_trace(go.Scatter(x=xyz[0], y=xyz[1], mode="lines", name=f"{p} orbit", hoverinfo="skip",
                                 line=dict(color=PLANET_COLORS[p], width=1.6 if p == "Earth" else 1,
                                           dash=None if p == "Earth" else "dot"), opacity=.9 if p == "Earth" else .55))
    axyz = space_api.orbit_path(el)
    fig.add_trace(go.Scatter(x=axyz[0], y=axyz[1], mode="lines", name=f"{el['name']} orbit", hoverinfo="skip",
                             line=dict(color="#FB923C", width=2)))
    fig.add_trace(go.Scatter(x=[0], y=[0], mode="markers+text", text=["Sun"], textposition="top center",
                             marker=dict(size=16, color="#FDE047", line=dict(width=0)), name="Sun", hoverinfo="skip",
                             textfont=dict(color="#FDE047", size=11)))

    jd0 = space_api.julian_now()
    names = planets + [el["name"]]
    colors = [PLANET_COLORS[p] for p in planets] + ["#FB923C"]
    sizes = [9 if p != "Earth" else 12 for p in planets] + [11]

    def bodies(jd: float) -> go.Scatter:
        pts = [space_api.position_at(space_api.planet_elements(p), jd) for p in planets] + [space_api.position_at(el, jd)]
        return go.Scatter(x=[p[0] for p in pts], y=[p[1] for p in pts], mode="markers+text", text=names,
                          textposition="top right", textfont=dict(size=10, color=COLORS["text"]),
                          marker=dict(size=sizes, color=colors, line=dict(width=1, color=COLORS["bg"])),
                          name="Positions", hovertemplate="%{text}<br>x %{x:.2f} AU, y %{y:.2f} AU<extra></extra>")

    fig.add_trace(bodies(jd0))
    moving = len(fig.data) - 1
    offsets = np.linspace(-span_days, span_days, frames)
    today = datetime.now(timezone.utc)
    fig.frames = [go.Frame(data=[bodies(jd0 + d)], traces=[moving], name=f"{d:+.0f}") for d in offsets]
    steps = [dict(method="animate", label=(today + timedelta(days=float(d))).strftime("%d %b"),
                  args=[[f"{d:+.0f}"], dict(mode="immediate", frame=dict(duration=0, redraw=False), transition=dict(duration=0))])
             for d in offsets]
    fig.update_layout(
        template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(4,10,20,.75)", height=560,
        margin=dict(l=10, r=10, t=10, b=10), font=dict(color=COLORS["text"]), showlegend=False,
        # constrain="domain" keeps a 1:1 aspect by shrinking the plot area, never by changing the range
        # (without it Plotly widens the range on every resize and the orbits shrink to a dot).
        xaxis=dict(range=[-limit, limit], autorange=False, visible=False, scaleanchor="y", scaleratio=1,
                   constrain="domain", fixedrange=True),
        yaxis=dict(range=[-limit, limit], autorange=False, visible=False, constrain="domain", fixedrange=True),
        updatemenus=[dict(type="buttons", showactive=False, x=0.01, y=0.99, xanchor="left", yanchor="top", **_BTN,
                          buttons=[dict(label="▶ Play", method="animate",
                                        args=[None, dict(frame=dict(duration=80, redraw=False), fromcurrent=True,
                                                         transition=dict(duration=60, easing="linear"))]),
                                   dict(label="❚❚ Pause", method="animate",
                                        args=[[None], dict(mode="immediate", frame=dict(duration=0, redraw=False))])])],
        sliders=[dict(active=frames // 2, steps=steps, x=0.08, len=0.9, y=0.02, pad=dict(t=0, b=0),
                      currentvalue=dict(prefix="Date: ", font=dict(size=12, color=COLORS["muted"])),
                      font=dict(size=9, color=COLORS["muted"]), bgcolor="rgba(56,189,248,.25)",
                      bordercolor="rgba(0,0,0,0)", tickcolor="rgba(0,0,0,0)")],
        annotations=[dict(text="Top-down view of the ecliptic plane · distances in AU", x=0.99, y=0.99, xref="paper",
                          yref="paper", showarrow=False, xanchor="right", font=dict(size=10, color=COLORS["muted"]))],
    )
    return fig


def approach_timeline(df: pd.DataFrame) -> go.Figure:
    """Close approaches: date vs miss distance (lunar distances, log scale); bubble = estimated size."""
    size = df["size_max_m"].fillna(10).clip(lower=1)
    fig = go.Figure(go.Scatter(
        x=df["date"], y=df["dist_lunar"], mode="markers", text=df["object"],
        customdata=np.stack([df["velocity_kps"], size], axis=-1),
        marker=dict(size=np.clip(6 + 5 * np.log10(size), 5, 30), color=df["velocity_kps"], colorscale="Turbo",
                    colorbar=dict(title="km/s", thickness=10), line=dict(width=1, color=COLORS["bg"]), opacity=.85),
        hovertemplate="<b>%{text}</b><br>%{x|%d %b %Y %H:%M} UTC<br>%{y:.2f} lunar distances"
                      "<br>%{customdata[0]:.1f} km/s · up to ~%{customdata[1]:.0f} m<extra></extra>"))
    fig.add_hline(y=1, line=dict(color="#FDE047", dash="dash", width=1), annotation_text="Moon's distance",
                  annotation_font_color="#FDE047", annotation_position="top left")
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(13,27,42,.55)",
                      height=400, margin=dict(l=55, r=10, t=20, b=40), font=dict(color=COLORS["text"]),
                      yaxis=dict(type="log", title="Miss distance (lunar distances)", gridcolor="rgba(148,163,184,.12)"),
                      xaxis=dict(gridcolor="rgba(148,163,184,.12)"), transition=dict(duration=500))
    return fig


def _globe_layout(fig: go.Figure, lon: float = 20, lat: float = 15, height: int = 520) -> go.Figure:
    fig.update_geos(projection_type="orthographic", projection_rotation=dict(lon=lon, lat=lat),
                    showland=True, landcolor="#16324F", showocean=True, oceancolor="#0A1E33", showcountries=True,
                    countrycolor="rgba(148,163,184,.35)", coastlinecolor="rgba(125,211,252,.55)", showlakes=False,
                    bgcolor="rgba(0,0,0,0)", framecolor="rgba(56,189,248,.35)")
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", height=height,
                      margin=dict(l=0, r=0, t=10, b=0), font=dict(color=COLORS["text"]),
                      legend=dict(orientation="h", y=-0.02, bgcolor="rgba(0,0,0,0)"))
    return fig


def fireball_globe(df: pd.DataFrame) -> go.Figure:
    """Meteor fireballs on a rotating globe; marker size and colour show impact energy."""
    kt = df["impact_kt"].fillna(0.05)
    fig = go.Figure(go.Scattergeo(
        lon=df["lon"], lat=df["lat"], mode="markers", text=df["time"].dt.strftime("%Y-%m-%d %H:%M UTC"),
        customdata=np.stack([kt, df["altitude_km"].fillna(-1), df["velocity_kps"].fillna(-1)], axis=-1),
        marker=dict(size=np.clip(7 + 6 * np.log10(kt + 0.02) + 6, 5, 34), color=np.log10(kt + 0.01),
                    colorscale="YlOrRd", line=dict(width=1, color="rgba(7,17,31,.8)"), opacity=.85,
                    colorbar=dict(title="log₁₀ kt", thickness=10)),
        hovertemplate="<b>%{text}</b><br>%{lat:.1f}°, %{lon:.1f}°<br>Impact energy %{customdata[0]:.2f} kt TNT"
                      "<br>Altitude %{customdata[1]:.1f} km · %{customdata[2]:.1f} km/s<extra></extra>", name="Fireballs"))
    fig.frames = [go.Frame(layout=dict(geo=dict(projection_rotation=dict(lon=lon, lat=15)))) for lon in range(20, 381, 6)]
    fig.update_layout(updatemenus=[dict(type="buttons", showactive=False, x=0.02, y=0.98, xanchor="left", yanchor="top",
                                        **_BTN, buttons=[
            dict(label="▶ Rotate", method="animate", args=[None, dict(frame=dict(duration=90, redraw=True), fromcurrent=True,
                                                                     transition=dict(duration=0), mode="immediate")]),
            dict(label="❚❚", method="animate", args=[[None], dict(frame=dict(duration=0, redraw=False), mode="immediate")])])])
    return _globe_layout(fig)


def fireballs_per_year(df: pd.DataFrame) -> go.Figure:
    counts = df.groupby(df["time"].dt.year).size()
    fig = go.Figure(go.Bar(x=counts.index, y=counts.values, marker_color="#FB923C"))
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(13,27,42,.55)",
                      height=260, margin=dict(l=45, r=10, t=30, b=30), font=dict(color=COLORS["text"]),
                      title=dict(text="Fireballs per year (in the loaded sample)", font=dict(size=13)),
                      yaxis=dict(gridcolor="rgba(148,163,184,.12)"))
    return fig


def satellite_globe(positions: pd.DataFrame, track: pd.DataFrame | None, selected: str | None) -> go.Figure:
    """Live satellite positions with the selected satellite's ground track."""
    fig = go.Figure()
    if track is not None and not track.empty:
        past, future = track[track["minutes"] <= 0], track[track["minutes"] >= 0]
        fig.add_trace(go.Scattergeo(lon=past["lon"], lat=past["lat"], mode="lines", name="Past track",
                                    line=dict(color="rgba(253,224,71,.45)", width=1.5), hoverinfo="skip"))
        fig.add_trace(go.Scattergeo(lon=future["lon"], lat=future["lat"], mode="lines", name="Upcoming track",
                                    line=dict(color="#FDE047", width=2.2), hoverinfo="skip"))
    others = positions[positions["name"] != selected]
    fig.add_trace(go.Scattergeo(lon=others["lon"], lat=others["lat"], mode="markers", text=others["name"],
                                customdata=others["altitude_km"], name="Satellites",
                                marker=dict(size=6, color=COLORS["primary"], line=dict(width=1, color=COLORS["bg"])),
                                hovertemplate="<b>%{text}</b><br>%{lat:.2f}°, %{lon:.2f}°<br>%{customdata:.0f} km<extra></extra>"))
    sel = positions[positions["name"] == selected]
    lon0, lat0 = 20.0, 15.0
    if not sel.empty:
        lon0, lat0 = float(sel["lon"].iloc[0]), float(np.clip(sel["lat"].iloc[0], -60, 60))
        fig.add_trace(go.Scattergeo(lon=sel["lon"], lat=sel["lat"], mode="markers+text", text=sel["name"],
                                    textposition="top center", textfont=dict(color="#FDE047", size=12), name=selected,
                                    marker=dict(size=14, color="#FDE047", symbol="diamond",
                                                line=dict(width=1.5, color=COLORS["bg"])),
                                    hovertemplate="<b>%{text}</b><br>%{lat:.2f}°, %{lon:.2f}°<extra></extra>"))
    fig = _globe_layout(fig, lon0, lat0, 540)
    fig.update_layout(uirevision="satellites", showlegend=False)
    return fig
