"""
Space tracking data: near-Earth asteroids, close approaches, meteor fireballs and
Earth-orbiting satellites.

Sources (all real, public):
  * NASA NeoWs (api.nasa.gov)            - asteroids approaching Earth, orbital elements
  * JPL SBDB Close-Approach Data API     - upcoming close approaches of small bodies
  * JPL CNEOS Fireball API               - meteors (bolides) detected in the atmosphere
  * CelesTrak GP data (NORAD elements)   - satellite orbits, propagated with SGP4 in Python

NASA_API_KEY is optional; without it the shared DEMO_KEY is used (about 30 requests/hour).
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sgp4.api import Satrec, jday

from backend.nasa_api import DataSourceError, _get
from core.config import env

AU_KM = 149_597_870.7
LUNAR_KM = 384_400.0
EARTH_RADIUS_KM = 6378.137


def _api_key() -> str:
    return env("NASA_API_KEY", "DEMO_KEY") or "DEMO_KEY"


def using_demo_key() -> bool:
    return _api_key() == "DEMO_KEY"


# ---------------------------------------------------------------- near-Earth asteroids (NeoWs)
def fetch_neo_feed(days: int = 7) -> pd.DataFrame:
    """Asteroids making a close approach to Earth in the next `days` days (max 7)."""
    days = max(1, min(7, days))
    start = date.today()
    data = _get("https://api.nasa.gov/neo/rest/v1/feed", {
        "start_date": start.isoformat(), "end_date": (start + timedelta(days=days - 1)).isoformat(),
        "api_key": _api_key()}, ttl_hours=3)
    rows = []
    for objs in data.get("near_earth_objects", {}).values():
        for o in objs:
            ca = o["close_approach_data"][0]
            dia = o["estimated_diameter"]["meters"]
            rows.append({
                "id": o["id"], "name": o["name"][1:-1] if o["name"].startswith("(") else o["name"],
                "approach": pd.to_datetime(ca.get("epoch_date_close_approach"), unit="ms", utc=True),
                "hazardous": bool(o["is_potentially_hazardous_asteroid"]),
                "diameter_min_m": dia["estimated_diameter_min"], "diameter_max_m": dia["estimated_diameter_max"],
                "velocity_kps": float(ca["relative_velocity"]["kilometers_per_second"]),
                "miss_km": float(ca["miss_distance"]["kilometers"]),
                "miss_lunar": float(ca["miss_distance"]["lunar"]),
                "magnitude_h": o["absolute_magnitude_h"], "url": o["nasa_jpl_url"],
            })
    if not rows:
        raise DataSourceError("NASA NeoWs returned no asteroids for this period.")
    return pd.DataFrame(rows).sort_values("approach").reset_index(drop=True)


def fetch_neo_orbit(neo_id: str) -> dict:
    """Keplerian orbital elements of one asteroid from NeoWs."""
    o = _get(f"https://api.nasa.gov/neo/rest/v1/neo/{neo_id}", {"api_key": _api_key()}, ttl_hours=24 * 7)
    od = o.get("orbital_data") or {}
    try:
        return {
            "name": o.get("name", neo_id),
            "a": float(od["semi_major_axis"]), "e": float(od["eccentricity"]),
            "i": float(od["inclination"]), "node": float(od["ascending_node_longitude"]),
            "peri": float(od["perihelion_argument"]), "M0": float(od["mean_anomaly"]),
            "epoch_jd": float(od["epoch_osculation"]), "period_days": float(od["orbital_period"]),
            "q": float(od["perihelion_distance"]), "Q": float(od["aphelion_distance"]),
            "orbit_class": (od.get("orbit_class") or {}).get("orbit_class_type", ""),
            "orbit_class_description": (od.get("orbit_class") or {}).get("orbit_class_description", ""),
        }
    except (KeyError, TypeError, ValueError) as e:
        raise DataSourceError(f"Orbital elements unavailable for object {neo_id}: {e}")


# ---------------------------------------------------------------- orbit geometry (heliocentric, ecliptic plane)
def julian_now() -> float:
    return datetime.now(timezone.utc).timestamp() / 86400.0 + 2440587.5


def _kepler(M: float, e: float) -> float:
    """Solve Kepler's equation M = E - e sin E for the eccentric anomaly E (Newton iteration)."""
    E = M if e < 0.8 else math.pi
    for _ in range(50):
        d = (E - e * math.sin(E) - M) / (1 - e * math.cos(E))
        E -= d
        if abs(d) < 1e-12:
            break
    return E


def orbit_xyz(a: float, e: float, i: float, node: float, peri: float, nu: np.ndarray) -> np.ndarray:
    """Heliocentric ecliptic coordinates (AU) for true anomalies `nu` (radians); angles in degrees."""
    i, node, peri = map(math.radians, (i, node, peri))
    r = a * (1 - e * e) / (1 + e * np.cos(nu))
    u = peri + nu
    x = r * (np.cos(node) * np.cos(u) - np.sin(node) * np.sin(u) * np.cos(i))
    y = r * (np.sin(node) * np.cos(u) + np.cos(node) * np.sin(u) * np.cos(i))
    z = r * (np.sin(u) * np.sin(i))
    return np.vstack([x, y, z])


def orbit_path(el: dict, n: int = 361) -> np.ndarray:
    return orbit_xyz(el["a"], el["e"], el["i"], el["node"], el["peri"], np.linspace(0, 2 * np.pi, n))


def position_at(el: dict, jd: float) -> np.ndarray:
    """Position of the body on its orbit at Julian date `jd`."""
    n = 2 * math.pi / el["period_days"]
    M = (math.radians(el["M0"]) + n * (jd - el["epoch_jd"])) % (2 * math.pi)
    E = _kepler(M, el["e"])
    nu = 2 * math.atan2(math.sqrt(1 + el["e"]) * math.sin(E / 2), math.sqrt(1 - el["e"]) * math.cos(E / 2))
    return orbit_xyz(el["a"], el["e"], el["i"], el["node"], el["peri"], np.array([nu]))[:, 0]


# J2000 mean elements (a AU, e, i°, node°, longitude of perihelion°, mean longitude°, period days)
PLANETS = {
    "Mercury": (0.3871, 0.2056, 7.005, 48.331, 77.456, 252.251, 87.969),
    "Venus": (0.7233, 0.0068, 3.395, 76.680, 131.533, 181.980, 224.701),
    "Earth": (1.0000, 0.0167, 0.000, 0.0, 102.947, 100.464, 365.256),
    "Mars": (1.5237, 0.0934, 1.850, 49.558, 336.060, 355.453, 686.980),
    "Jupiter": (5.2026, 0.0485, 1.303, 100.464, 14.331, 34.404, 4332.59),
}


def planet_elements(name: str) -> dict:
    a, e, i, node, lperi, L, period = PLANETS[name]
    return {"a": a, "e": e, "i": i, "node": node, "peri": (lperi - node) % 360, "M0": (L - lperi) % 360,
            "epoch_jd": 2451545.0, "period_days": period, "name": name}


# ---------------------------------------------------------------- close approaches (JPL SBDB)
def fetch_close_approaches(days: int = 60, dist_au: float = 0.05) -> pd.DataFrame:
    """All known small bodies passing within `dist_au` of Earth in the next `days` days."""
    data = _get("https://ssd-api.jpl.nasa.gov/cad.api", {
        "date-min": "now", "date-max": f"+{max(1, min(365, days))}", "dist-max": str(dist_au),
        "sort": "date", "fullname": "true"}, ttl_hours=6)
    fields = data.get("fields", [])
    rows = []
    for r in data.get("data", []) or []:
        d = dict(zip(fields, r))
        h = float(d["h"]) if d.get("h") else None
        dist = float(d["dist"])
        rows.append({
            "object": (d.get("fullname") or d["des"]).strip(),
            "date": pd.to_datetime(d["cd"], format="%Y-%b-%d %H:%M", utc=True),
            "dist_lunar": dist * AU_KM / LUNAR_KM, "dist_km": dist * AU_KM, "dist_au": dist,
            "velocity_kps": float(d["v_rel"]), "magnitude_h": h,
            # diameter from absolute magnitude H for albedo 0.25 (bright) to 0.05 (dark)
            "size_min_m": None if h is None else 1329 / math.sqrt(0.25) * 10 ** (-h / 5) * 1000,
            "size_max_m": None if h is None else 1329 / math.sqrt(0.05) * 10 ** (-h / 5) * 1000,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- meteors (fireballs)
def fetch_fireball_events(limit: int = 300) -> pd.DataFrame:
    """Fireball (bolide) events with location, energy, altitude and speed from JPL CNEOS."""
    data = _get("https://ssd-api.jpl.nasa.gov/fireball.api", {"limit": max(1, min(1000, limit)), "req-loc": "true"},
                ttl_hours=6)
    fields = data.get("fields", [])
    rows = []
    for r in data.get("data", []) or []:
        d = dict(zip(fields, r))
        rows.append({
            "time": pd.to_datetime(d["date"], utc=True),
            "lat": float(d["lat"]) * (-1 if d["lat-dir"] == "S" else 1),
            "lon": float(d["lon"]) * (-1 if d["lon-dir"] == "W" else 1),
            "impact_kt": float(d["impact-e"]) if d.get("impact-e") else np.nan,
            "radiated_e10j": float(d["energy"]) if d.get("energy") else np.nan,
            "altitude_km": float(d["alt"]) if d.get("alt") else np.nan,
            "velocity_kps": float(d["vel"]) if d.get("vel") else np.nan,
        })
    if not rows:
        raise DataSourceError("JPL CNEOS returned no fireball events.")
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- satellites (CelesTrak + SGP4)
SAT_GROUPS = {
    "stations": "Space stations (ISS, Tiangong)", "science": "Earth & space science",
    "weather": "Weather satellites", "resource": "Earth resources (Landsat, Terra, Aqua…)",
    "visual": "100 brightest", "gps-ops": "GPS constellation", "geo": "Geostationary",
}


def fetch_tles(group: str = "stations", limit: int = 300) -> list[dict]:
    """Two-line element sets for a CelesTrak satellite group."""
    if group not in SAT_GROUPS:
        group = "stations"
    text = _get("https://celestrak.org/NORAD/elements/gp.php", {"GROUP": group, "FORMAT": "tle"},
                as_json=False, ttl_hours=6)
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    sats = []
    for k in range(0, len(lines) - 2, 3):
        if lines[k + 1].startswith("1 ") and lines[k + 2].startswith("2 "):
            sats.append({"name": lines[k].strip(), "tle1": lines[k + 1], "tle2": lines[k + 2]})
    if not sats:
        raise DataSourceError(f"CelesTrak returned no orbital elements for group '{group}'.")
    return sats[:limit]


def _gmst(jd_ut1: float) -> float:
    """Greenwich mean sidereal time in radians (IAU 1982 model)."""
    t = (jd_ut1 - 2451545.0) / 36525.0
    sec = 67310.54841 + (876600 * 3600 + 8640184.812866) * t + 0.093104 * t * t - 6.2e-6 * t ** 3
    return math.radians((sec % 86400.0) / 240.0) % (2 * math.pi)


def _teme_to_geodetic(r: tuple, jd: float) -> tuple[float, float, float]:
    """TEME position (km) -> geodetic latitude, longitude (degrees) and altitude (km), WGS-84."""
    g = _gmst(jd)
    x = r[0] * math.cos(g) + r[1] * math.sin(g)
    y = -r[0] * math.sin(g) + r[1] * math.cos(g)
    z = r[2]
    lon = math.degrees(math.atan2(y, x))
    f = 1 / 298.257223563
    e2 = f * (2 - f)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1 - e2))
    for _ in range(6):
        n = EARTH_RADIUS_KM / math.sqrt(1 - e2 * math.sin(lat) ** 2)
        lat = math.atan2(z + e2 * n * math.sin(lat), p)
    n = EARTH_RADIUS_KM / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    alt = p / math.cos(lat) - n if abs(math.cos(lat)) > 1e-9 else abs(z) - n * (1 - e2)
    return math.degrees(lat), lon, alt


def satellite_state(sat: dict, when: datetime | None = None) -> dict | None:
    """Current sub-satellite point, altitude and speed from SGP4 propagation."""
    when = when or datetime.now(timezone.utc)
    rec = Satrec.twoline2rv(sat["tle1"], sat["tle2"])
    jd, fr = jday(when.year, when.month, when.day, when.hour, when.minute, when.second + when.microsecond / 1e6)
    err, r, v = rec.sgp4(jd, fr)
    if err != 0:
        return None
    lat, lon, alt = _teme_to_geodetic(r, jd + fr)
    period_min = 2 * math.pi / rec.no_kozai
    return {"name": sat["name"], "norad_id": rec.satnum, "lat": lat, "lon": lon, "altitude_km": alt,
            "speed_kps": math.sqrt(sum(c * c for c in v)), "period_min": period_min,
            "inclination_deg": math.degrees(rec.inclo), "eccentricity": rec.ecco,
            "orbits_per_day": 1440.0 / period_min}


def satellite_positions(sats: list[dict], when: datetime | None = None) -> pd.DataFrame:
    rows = [s for s in (satellite_state(x, when) for x in sats) if s]
    return pd.DataFrame(rows)


def ground_track(sat: dict, when: datetime | None = None, orbits: float = 1.5, steps: int = 240) -> pd.DataFrame:
    """Sub-satellite track from half an orbit ago to `orbits` ahead."""
    when = when or datetime.now(timezone.utc)
    rec = Satrec.twoline2rv(sat["tle1"], sat["tle2"])
    period_min = 2 * math.pi / rec.no_kozai
    rows = []
    for m in np.linspace(-0.5 * period_min, orbits * period_min, steps):
        t = when + timedelta(minutes=float(m))
        jd, fr = jday(t.year, t.month, t.day, t.hour, t.minute, t.second + t.microsecond / 1e6)
        err, r, _ = rec.sgp4(jd, fr)
        if err == 0:
            lat, lon, alt = _teme_to_geodetic(r, jd + fr)
            rows.append({"time": t, "lat": lat, "lon": lon, "altitude_km": alt, "minutes": float(m)})
    return pd.DataFrame(rows)
