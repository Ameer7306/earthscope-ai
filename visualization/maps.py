"""
Folium map builders: NASA GIBS satellite layers, event markers, region outlines and drawing tools.
"""
from __future__ import annotations

import html
from datetime import date

import folium
import pandas as pd
from folium.plugins import Draw, Fullscreen, MousePosition

from backend.nasa_api import GIBS_LAYERS, gibs_tile_url
from core.config import COLORS
from visualization.animations import category_color

GIBS_ATTR = "Imagery: NASA GIBS / ESDIS"


def base_map(center: tuple[float, float] = (20, 10), zoom: int = 2, base_layer: str = "Blue Marble (static)",
             overlay: str | None = None, day: date | None = None, overlay_opacity: float = 0.75) -> folium.Map:
    """World map with a NASA GIBS base layer and an optional GIBS data overlay."""
    m = folium.Map(location=center, zoom_start=zoom, tiles=None, min_zoom=1, max_zoom=9,
                   world_copy_jump=True, control_scale=True, prefer_canvas=True)
    url, _ = gibs_tile_url(base_layer, day)
    folium.TileLayer(tiles=url, attr=GIBS_ATTR, name=base_layer,
                     max_native_zoom=GIBS_LAYERS[base_layer]["level"], max_zoom=9).add_to(m)
    if overlay and overlay != base_layer:
        ourl, _ = gibs_tile_url(overlay, day)
        folium.TileLayer(tiles=ourl, attr=GIBS_ATTR, name=overlay, overlay=True, opacity=overlay_opacity,
                         max_native_zoom=GIBS_LAYERS[overlay]["level"], max_zoom=9).add_to(m)
    # country borders/labels reference layer from GIBS so places are recognisable on imagery
    folium.TileLayer(
        tiles="https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/Reference_Features_15m/default/"
              "GoogleMapsCompatible_Level13/{z}/{y}/{x}.png",
        attr=GIBS_ATTR, name="Borders", overlay=True, opacity=.8, max_native_zoom=13, max_zoom=9).add_to(m)
    Fullscreen(position="topleft").add_to(m)
    MousePosition(position="bottomleft", separator=" , ", prefix="Lat, Lon:", num_digits=3).add_to(m)
    return m


def add_events(m: folium.Map, events: pd.DataFrame, radius: int = 6, limit: int = 600) -> folium.Map:
    """Add environmental event markers coloured by category."""
    if events is None or events.empty:
        return m
    for _, e in events.head(limit).iterrows():
        c = category_color(e["category"])
        when = pd.Timestamp(e["time"]).strftime("%Y-%m-%d %H:%M UTC")
        popup = (f"<b>{html.escape(str(e['title']))}</b><br>{html.escape(str(e['category']))}<br>{when}"
                 f"<br>Source: {html.escape(str(e.get('data_source', '')))}")
        folium.CircleMarker(location=(e["lat"], e["lon"]), radius=radius, color=c, weight=1.5, fill=True,
                            fill_color=c, fill_opacity=.7, popup=folium.Popup(popup, max_width=260),
                            tooltip=html.escape(str(e["title"]))[:80]).add_to(m)
    return m


def add_fires(m: folium.Map, fires: pd.DataFrame, limit: int = 3000) -> folium.Map:
    """Add FIRMS active-fire pixels (brightest first)."""
    if fires is None or fires.empty:
        return m
    col = "frp" if "frp" in fires.columns else None
    sub = fires.sort_values(col, ascending=False).head(limit) if col else fires.head(limit)
    for _, f in sub.iterrows():
        frp = float(f[col]) if col else 0
        folium.CircleMarker(location=(f["lat"], f["lon"]), radius=2 + min(6, frp / 40), color="#F97316",
                            weight=0, fill=True, fill_color="#F97316" if frp < 100 else "#EF4444", fill_opacity=.75,
                            tooltip=f"FRP {frp:.0f} MW · {pd.Timestamp(f['time']).strftime('%Y-%m-%d %H:%M')} UTC").add_to(m)
    return m


def add_region(m: folium.Map, name: str, loc: dict, color: str = COLORS["primary"]) -> folium.Map:
    """Marker at the representative point and rectangle for the bounding box (if any)."""
    folium.Marker((loc["lat"], loc["lon"]), tooltip=f"{name} ({loc['lat']:.2f}, {loc['lon']:.2f})",
                  icon=folium.Icon(color="lightblue", icon="map-marker")).add_to(m)
    if loc.get("bbox"):
        s, w, n, e = loc["bbox"]
        folium.Rectangle([(s, w), (n, e)], color=color, weight=2, fill=True, fill_opacity=.06,
                         dash_array="6 6", tooltip=f"{name} analysis area").add_to(m)
    return m


def add_draw_tools(m: folium.Map) -> folium.Map:
    """Let the user drop a point or draw a rectangle to select a location/region."""
    Draw(export=False, position="topright",
         draw_options={"polyline": False, "polygon": False, "circle": False, "circlemarker": False,
                       "marker": True, "rectangle": {"shapeOptions": {"color": COLORS["secondary"]}}},
         edit_options={"edit": False, "remove": True}).add_to(m)
    return m


def finish(m: folium.Map) -> folium.Map:
    folium.LayerControl(position="topright", collapsed=True).add_to(m)
    return m
