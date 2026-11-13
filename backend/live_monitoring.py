"""
Live monitoring service: combines near-real-time NASA feeds into one detection list.

Used by the FastAPI backend (`/live/detections`). The Streamlit page calls the same
`nasa_api` functions through cached loaders. Nothing here fabricates events: when a
source is not configured or unreachable it is reported in `sources` with its status.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from backend import nasa_api
from core.config import settings


def collect_detections(days: int = 30, include_fireballs: bool = False, fire_limit: int = 200) -> dict:
    """Return {'detections': [...], 'sources': {...}, 'mode': 'LIVE'|'DEMO', 'refreshed': iso}."""
    cfg = settings()
    sources, frames = {}, []

    try:
        ev = nasa_api.fetch_eonet(days=days)
        frames.append(ev)
        sources["NASA EONET"] = {"status": "ok", "count": int(len(ev))}
    except Exception as e:
        sources["NASA EONET"] = {"status": "error", "detail": str(e)}

    if cfg["FIRMS_MAP_KEY"]:
        try:
            f = nasa_api.fetch_firms(cfg["FIRMS_MAP_KEY"])
            top = f.sort_values("frp", ascending=False).head(fire_limit) if "frp" in f else f.head(fire_limit)
            frames.append(pd.DataFrame({
                "id": ["FIRMS-" + str(i) for i in top.index], "title": "Active fire (FRP " + top["frp"].round(0).astype(str) + " MW)",
                "category": "Active fire", "lat": top["lat"], "lon": top["lon"], "time": top["time"],
                "magnitude": top["frp"], "magnitude_unit": "MW", "source": "VIIRS S-NPP",
                "link": "https://firms.modaps.eosdis.nasa.gov/map/", "data_source": "NASA FIRMS"}))
            sources["NASA FIRMS"] = {"status": "ok", "count": int(len(f))}
        except Exception as e:
            sources["NASA FIRMS"] = {"status": "error", "detail": str(e)}
    else:
        sources["NASA FIRMS"] = {"status": "not_configured", "detail": "Set FIRMS_MAP_KEY to enable fire pixels"}

    if include_fireballs:
        try:
            fb = nasa_api.fetch_fireballs(20)
            frames.append(fb)
            sources["JPL CNEOS"] = {"status": "ok", "count": int(len(fb))}
        except Exception as e:
            sources["JPL CNEOS"] = {"status": "error", "detail": str(e)}

    frames = [f for f in frames if f is not None and not f.empty]
    df = pd.concat(frames, ignore_index=True).sort_values("time", ascending=False) if frames else pd.DataFrame()
    records = []
    for _, r in df.iterrows():
        records.append({"id": r["id"], "title": r["title"], "category": r["category"], "lat": float(r["lat"]),
                        "lon": float(r["lon"]), "observed_at": pd.Timestamp(r["time"]).isoformat(),
                        "data_source": r["data_source"], "link": r.get("link")})
    all_ok = all(s["status"] == "ok" for s in sources.values())
    return {"mode": "LIVE" if all_ok else "DEMO" if not records else "PARTIAL",
            "refreshed": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "data_quality": "near-real-time (preliminary, subject to revision)",
            "sources": sources, "count": len(records), "detections": records}
