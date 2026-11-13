"""
NASA data access layer.

All network calls go through `_get()` which provides:
  * a disk cache (data/cache) so repeated analyses are instant and API limits are respected,
  * timeouts and retries with exponential back-off for 429 / 5xx responses,
  * clear exceptions (`DataSourceError`) the UI can show to the user.

Sources used (all real, public NASA services):
  * NASA POWER monthly/daily point API        https://power.larc.nasa.gov/
  * NASA GISS GISTEMP v4 global temperature    https://data.giss.nasa.gov/gistemp/
  * MODIS MOD13Q1 NDVI via ORNL DAAC           https://modis.ornl.gov/data/modis_webservice.html
  * NASA EONET natural event tracker           https://eonet.gsfc.nasa.gov/
  * NASA FIRMS active fires (needs MAP_KEY)    https://firms.modaps.eosdis.nasa.gov/api/
  * JPL CNEOS fireball (meteor) events         https://ssd-api.jpl.nasa.gov/doc/fireball.html
  * NASA GIBS imagery tiles                    https://gibs.earthdata.nasa.gov/
"""
from __future__ import annotations

import hashlib
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import httpx
import numpy as np
import pandas as pd

from core.config import CACHE_DIR, REGIONS, VARIABLES, settings

USER_AGENT = "EarthScopeAI/1.0 (NASA Space Apps Challenge research prototype)"


class DataSourceError(RuntimeError):
    """Raised when a NASA service cannot provide the requested data."""


# ---------------------------------------------------------------- HTTP + cache
def _cache_path(url: str, params: dict | None) -> "Path":
    key = url + "?" + json.dumps(params or {}, sort_keys=True)
    return CACHE_DIR / (hashlib.sha1(key.encode()).hexdigest() + ".cache")


def _get(url: str, params: dict | None = None, *, ttl_hours: float | None = None,
         as_json: bool = True, retries: int = 3, headers: dict | None = None):
    """GET with disk cache, timeout and retry. Returns parsed JSON or text."""
    cfg = settings()
    ttl = cfg["CACHE_HOURS"] if ttl_hours is None else ttl_hours
    path = _cache_path(url, params)
    if ttl > 0 and path.exists() and (time.time() - path.stat().st_mtime) < ttl * 3600:
        text = path.read_text(encoding="utf-8")
        return json.loads(text) if as_json else text

    last_err = None
    for attempt in range(retries):
        try:
            with httpx.Client(timeout=cfg["HTTP_TIMEOUT"], follow_redirects=True,
                              headers={"User-Agent": USER_AGENT, **(headers or {})}) as client:
                r = client.get(url, params=params)
            if r.status_code == 429 or r.status_code >= 500:
                last_err = DataSourceError(f"{url} returned HTTP {r.status_code} (rate limit or server issue)")
                time.sleep(1.5 * (2 ** attempt))
                continue
            if r.status_code >= 400:
                raise DataSourceError(f"{url} returned HTTP {r.status_code}: {r.text[:200]}")
            text = r.text
            data = json.loads(text) if as_json else text
            if ttl > 0:
                path.write_text(text, encoding="utf-8")
            return data
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last_err = DataSourceError(f"Network problem contacting {url.split('/')[2]}: {e}")
            time.sleep(1.0 * (2 ** attempt))
    # fall back to a stale cache rather than failing completely
    if path.exists():
        text = path.read_text(encoding="utf-8")
        return json.loads(text) if as_json else text
    raise last_err or DataSourceError(f"Could not reach {url}")


def cache_info() -> dict:
    files = list(CACHE_DIR.glob("*.cache"))
    return {"files": len(files), "size_mb": round(sum(f.stat().st_size for f in files) / 1e6, 2)}


def clear_cache() -> int:
    n = 0
    for f in CACHE_DIR.glob("*.cache"):
        f.unlink(missing_ok=True)
        n += 1
    return n


# ---------------------------------------------------------------- NASA POWER
POWER_MONTHLY = "https://power.larc.nasa.gov/api/temporal/monthly/point"
POWER_DAILY = "https://power.larc.nasa.gov/api/temporal/daily/point"


def fetch_power_monthly(lat: float, lon: float, params: list[str], start: int, end: int) -> pd.DataFrame:
    """Monthly means from NASA POWER for one point. Returns a DataFrame indexed by month start."""
    data = _get(POWER_MONTHLY, {
        "parameters": ",".join(params), "community": "AG",
        "latitude": round(lat, 3), "longitude": round(lon, 3),
        "start": start, "end": end, "format": "JSON",
    })
    try:
        p = data["properties"]["parameter"]
    except (KeyError, TypeError):
        raise DataSourceError(f"NASA POWER returned no data: {str(data)[:200]}")
    frames = {}
    for name, series in p.items():
        rows = {k: v for k, v in series.items() if not k.endswith("13")}   # drop annual summaries
        s = pd.Series(rows, dtype=float)
        s.index = pd.to_datetime(s.index, format="%Y%m")
        frames[name] = s.replace(-999.0, np.nan)
    return pd.DataFrame(frames).sort_index()


def fetch_power_daily(lat: float, lon: float, params: list[str], start: date, end: date) -> pd.DataFrame:
    """Daily values from NASA POWER (near-real-time, typically 2-7 days latency)."""
    data = _get(POWER_DAILY, {
        "parameters": ",".join(params), "community": "AG",
        "latitude": round(lat, 3), "longitude": round(lon, 3),
        "start": start.strftime("%Y%m%d"), "end": end.strftime("%Y%m%d"), "format": "JSON",
    }, ttl_hours=3)
    p = data.get("properties", {}).get("parameter", {})
    frames = {}
    for name, series in p.items():
        s = pd.Series(series, dtype=float)
        s.index = pd.to_datetime(s.index, format="%Y%m%d")
        frames[name] = s.replace(-999.0, np.nan)
    return pd.DataFrame(frames).sort_index()


# ---------------------------------------------------------------- MODIS NDVI (ORNL DAAC)
ORNL_SUBSET = "https://modis.ornl.gov/rst/api/v1/MOD13Q1/subset"
_NDVI_DOYS = list(range(1, 366, 16))   # MOD13Q1 composite start days


def fetch_modis_ndvi(lat: float, lon: float, start_year: int, end_year: int) -> pd.DataFrame:
    """16-day MODIS NDVI for a single 250 m pixel, aggregated to monthly means.

    The ORNL service accepts at most 10 composites per request, so each year is
    split into three requests which are run in parallel and cached on disk.
    """
    start_year = max(2000, start_year)
    chunks = []
    for y in range(start_year, end_year + 1):
        for i in range(0, len(_NDVI_DOYS), 9):
            d = _NDVI_DOYS[i:i + 9]
            if y == 2000 and d[-1] < 49:   # MODIS Terra NDVI starts Feb 2000
                continue
            chunks.append((f"A{y}{max(d[0], 49 if y == 2000 else d[0]):03d}", f"A{y}{d[-1]:03d}", y))

    def one(c):
        past = c[2] < date.today().year
        try:
            return _get(ORNL_SUBSET, {
                "latitude": lat, "longitude": lon, "band": "250m_16_days_NDVI",
                "startDate": c[0], "endDate": c[1], "kmAboveBelow": 0, "kmLeftRight": 0,
            }, ttl_hours=24 * 365 if past else 24, headers={"Accept": "application/json"})
        except DataSourceError:
            return None

    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(one, chunks))
    rows = []
    for res in results:
        if not res:
            continue
        for item in res.get("subset", []):
            v = item["data"][0] if item.get("data") else None
            if v is None or v <= -2000:      # fill value -3000
                continue
            rows.append((pd.to_datetime(item["calendar_date"]), v * 0.0001))
    if not rows:
        raise DataSourceError("MODIS NDVI service returned no valid observations for this location.")
    s = pd.Series(dict(rows)).sort_index()
    monthly = s.resample("MS").mean()
    return pd.DataFrame({"250m_16_days_NDVI": monthly})


# ---------------------------------------------------------------- unified series access
def resolve_location(region: str, custom: dict | None = None) -> dict:
    """Look up a region by name (built-in or custom/saved)."""
    if custom and region in custom:
        return custom[region]
    if region in REGIONS:
        return REGIONS[region]
    raise DataSourceError(f"Unknown region '{region}'")


def sample_points(loc: dict, sampling: str) -> list[tuple[float, float]]:
    """Representative point, or a 3×3 grid across the bounding box for 'area' sampling."""
    if sampling == "area" and loc.get("bbox"):
        s, w, n, e = loc["bbox"]
        lats = np.linspace(s, n, 5)[1:4]
        lons = np.linspace(w, e, 5)[1:4]
        return [(float(a), float(o)) for a in lats for o in lons]
    return [(loc["lat"], loc["lon"])]


def fetch_series(variable: str, region: str, start: int, end: int, sampling: str = "point",
                 custom: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """Return (DataFrame[date, value], metadata) for a variable at a region.

    Area sampling averages a 3×3 grid of points inside the region's bounding box.
    """
    var = VARIABLES[variable]
    loc = resolve_location(region, custom)
    start = max(start, var["start"])
    if end < start:
        raise DataSourceError(f"{var['label']} is only available from {var['start']}.")
    pts = sample_points(loc, sampling)

    def one(pt):
        if var["source"] == "power":
            return fetch_power_monthly(pt[0], pt[1], [var["param"]], start, end)[var["param"]]
        return fetch_modis_ndvi(pt[0], pt[1], start, end)[var["param"]]

    with ThreadPoolExecutor(max_workers=min(5, len(pts))) as ex:
        parts = list(ex.map(one, pts))
    df = pd.concat(parts, axis=1).mean(axis=1, skipna=True).to_frame("value")
    df.index.name = "date"
    df = df.loc[f"{start}-01-01":f"{end}-12-31"]
    # ensure a regular monthly index so missing months are visible
    full = pd.date_range(f"{start}-01-01", f"{end}-12-01", freq="MS")
    df = df.reindex(full)
    df.index.name = "date"
    meta = {
        "variable": variable, "label": var["label"], "units": var["units"],
        "region": region, "lat": loc["lat"], "lon": loc["lon"], "sampling": sampling,
        "n_points": len(pts), "start": start, "end": end,
        "source": var["dataset"], "provider": "NASA POWER" if var["source"] == "power" else "MODIS / ORNL DAAC",
        "demo": False, "retrieved": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return df, meta


# ---------------------------------------------------------------- GISTEMP global temperature
GISTEMP_CSV = "https://data.giss.nasa.gov/gistemp/tabledata_v4/GLB.Ts+dSST.csv"


def fetch_gistemp_global() -> pd.DataFrame:
    """Global land-ocean temperature anomaly (°C vs 1951-1980), monthly."""
    text = _get(GISTEMP_CSV, as_json=False, ttl_hours=24)
    df = pd.read_csv(io.StringIO(text), skiprows=1, na_values=["***", "****"])
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    long = df.melt(id_vars="Year", value_vars=months, var_name="m", value_name="value")
    long["date"] = pd.to_datetime(long["Year"].astype(str) + "-" + long["m"], format="%Y-%b")
    out = long.set_index("date")[["value"]].sort_index().astype(float)
    return out.dropna()


# ---------------------------------------------------------------- EONET natural events
EONET = "https://eonet.gsfc.nasa.gov/api/v3/events"


def fetch_eonet(days: int = 30, status: str = "open", limit: int = 300, category: str | None = None) -> pd.DataFrame:
    """Natural events (wildfires, storms, volcanoes, floods...) curated by NASA EONET."""
    params = {"status": status, "days": days, "limit": limit}
    if category:
        params["category"] = category
    data = _get(EONET, params, ttl_hours=0.5)
    rows = []
    for ev in data.get("events", []):
        geo = ev.get("geometry") or []
        if not geo:
            continue
        g = geo[-1]                                # most recent position
        coords = g.get("coordinates")
        if g.get("type") == "Polygon":
            ring = np.array(coords[0])
            lon, lat = float(ring[:, 0].mean()), float(ring[:, 1].mean())
        else:
            lon, lat = float(coords[0]), float(coords[1])
        cats = ev.get("categories") or [{}]
        src = ev.get("sources") or [{}]
        rows.append({
            "id": ev["id"], "title": ev["title"], "category": cats[0].get("title", "Event"),
            "lat": lat, "lon": lon, "time": pd.to_datetime(g.get("date"), utc=True),
            "magnitude": g.get("magnitudeValue"), "magnitude_unit": g.get("magnitudeUnit"),
            "source": src[0].get("id", "EONET"), "link": src[0].get("url") or ev.get("link"),
            "data_source": "NASA EONET",
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("time", ascending=False).reset_index(drop=True)
    return df


# ---------------------------------------------------------------- FIRMS active fires
def fetch_firms(map_key: str, source: str = "VIIRS_SNPP_NRT", area: str = "world", days: int = 1) -> pd.DataFrame:
    """NASA FIRMS active fire detections (requires a free MAP_KEY)."""
    if not map_key:
        raise DataSourceError("FIRMS_MAP_KEY is not configured.")
    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{map_key}/{source}/{area}/{max(1, min(10, days))}"
    text = _get(url, as_json=False, ttl_hours=0.25)
    if text.lower().startswith("invalid") or "error" in text[:100].lower():
        raise DataSourceError(f"FIRMS rejected the request: {text[:150]}")
    df = pd.read_csv(io.StringIO(text))
    if df.empty:
        return df
    df["time"] = pd.to_datetime(df["acq_date"] + " " + df["acq_time"].astype(str).str.zfill(4),
                                format="%Y-%m-%d %H%M", utc=True)
    df = df.rename(columns={"latitude": "lat", "longitude": "lon"})
    return df.sort_values("time", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------- JPL fireballs (meteors)
def fetch_fireballs(limit: int = 50) -> pd.DataFrame:
    """Bright meteors (bolides) detected by US government sensors, via JPL CNEOS."""
    data = _get("https://ssd-api.jpl.nasa.gov/fireball.api", {"limit": limit, "req-loc": "true"}, ttl_hours=6)
    f = data.get("fields", [])
    rows = []
    for r in data.get("data", []):
        d = dict(zip(f, r))
        lat = float(d["lat"]) * (-1 if d["lat-dir"] == "S" else 1)
        lon = float(d["lon"]) * (-1 if d["lon-dir"] == "W" else 1)
        rows.append({
            "id": "FB-" + d["date"].replace(" ", "T"), "title": f"Fireball – {float(d['impact-e']):.2f} kt TNT",
            "category": "Fireball (meteor)", "lat": lat, "lon": lon,
            "time": pd.to_datetime(d["date"], utc=True),
            "magnitude": float(d["impact-e"]), "magnitude_unit": "kt TNT",
            "source": "JPL CNEOS", "link": "https://cneos.jpl.nasa.gov/fireballs/", "data_source": "JPL CNEOS",
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- GIBS imagery layers
GIBS_LAYERS = {
    "Blue Marble (static)": {"id": "BlueMarble_ShadedRelief_Bathymetry", "ext": "jpeg", "level": 8, "lag": None},
    "True colour – MODIS Terra": {"id": "MODIS_Terra_CorrectedReflectance_TrueColor", "ext": "jpg", "level": 9, "lag": 1},
    "True colour – VIIRS SNPP": {"id": "VIIRS_SNPP_CorrectedReflectance_TrueColor", "ext": "jpg", "level": 9, "lag": 1},
    "Precipitation rate – GPM IMERG": {"id": "IMERG_Precipitation_Rate", "ext": "png", "level": 6, "lag": 1},
    "Land surface temp – MODIS (day)": {"id": "MODIS_Terra_Land_Surface_Temp_Day", "ext": "png", "level": 7, "lag": 2},
    "Vegetation NDVI – MODIS 8-day": {"id": "MODIS_Terra_NDVI_8Day", "ext": "png", "level": 9, "lag": 10},
    "Aerosol optical depth – MODIS": {"id": "MODIS_Combined_Value_Added_AOD", "ext": "png", "level": 6, "lag": 1},
    "Night lights – VIIRS Black Marble": {"id": "VIIRS_Black_Marble", "ext": "png", "level": 8, "lag": None, "fixed": "2016-01-01"},
}


def gibs_tile_url(layer_name: str, day: date | None = None) -> tuple[str, str]:
    """Return (tile URL template, date string) for a GIBS layer in Web Mercator."""
    lay = GIBS_LAYERS[layer_name]
    if lay.get("fixed"):
        d = lay["fixed"]
    elif lay["lag"] is None:
        d = ""
    else:
        d = (day or (date.today() - timedelta(days=lay["lag"]))).isoformat()
    time_part = f"{d}/" if d else ""
    url = (f"https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/{lay['id']}/default/{time_part}"
           f"GoogleMapsCompatible_Level{lay['level']}/{{z}}/{{y}}/{{x}}.{lay['ext']}")
    return url, d or "static"
