"""
Smoke tests for the Space & Orbit Tracker (live NASA / JPL / CelesTrak data).

Run from the project folder:   venv\\Scripts\\python tests\\test_space.py
"""
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import space_api  # noqa: E402
from visualization import space_charts  # noqa: E402


def test_asteroids():
    neos = space_api.fetch_neo_feed(7)
    assert len(neos) > 0 and (neos["miss_km"] > 0).all()
    closest = neos.loc[neos["miss_lunar"].idxmin()]
    el = space_api.fetch_neo_orbit(str(closest["id"]))
    assert 0 <= el["e"] < 1 and el["a"] > 0
    # geometry check: at its close approach the asteroid must be near Earth
    jd = closest["approach"].timestamp() / 86400.0 + 2440587.5
    d_au = np.linalg.norm(space_api.position_at(el, jd) - space_api.position_at(space_api.planet_elements("Earth"), jd))
    print(f"asteroids: {len(neos)} this week, {int(neos['hazardous'].sum())} PHA; closest {closest['name']} "
          f"{closest['miss_lunar']:.2f} LD; model distance at approach {d_au:.3f} AU (reported {closest['miss_km'] / space_api.AU_KM:.3f})")
    assert d_au < 0.08, d_au        # mean-element Earth + two-body asteroid: agreement to a few 0.01 AU
    fig = space_charts.orbit_animation({**el, "name": closest["name"]})
    assert len(fig.frames) == 61


def test_earth_position():
    # Earth must be ~1 AU from the Sun and near ecliptic longitude 100 deg + 0.9856 deg/day from J2000
    p = space_api.position_at(space_api.planet_elements("Earth"), 2451545.0)
    assert abs(np.linalg.norm(p) - 0.983) < 0.01, np.linalg.norm(p)       # early January = near perihelion
    lon = math.degrees(math.atan2(p[1], p[0])) % 360
    assert abs(lon - 100.4) < 1.5, lon
    print(f"earth position OK (r={np.linalg.norm(p):.4f} AU, lon={lon:.1f} deg at J2000)")


def test_close_approaches_and_fireballs():
    ca = space_api.fetch_close_approaches(60, 0.05)
    assert len(ca) > 0 and (ca["dist_au"] <= 0.05).all()
    space_charts.approach_timeline(ca)
    fb = space_api.fetch_fireball_events(100)
    assert len(fb) == 100 and fb["lat"].between(-90, 90).all() and fb["lon"].between(-180, 180).all()
    space_charts.fireball_globe(fb)
    space_charts.fireballs_per_year(fb)
    print(f"close approaches: {len(ca)}; fireballs: {len(fb)}, latest {fb['time'].max():%Y-%m-%d}")


def test_satellites():
    tles = space_api.fetch_tles("stations")
    iss = next(t for t in tles if t["name"].startswith("ISS"))
    now = datetime.now(timezone.utc)
    s = space_api.satellite_state(iss, now)
    assert 370 < s["altitude_km"] < 460, s["altitude_km"]
    assert 7.5 < s["speed_kps"] < 7.8 and abs(s["lat"]) <= 51.8 and 90 < s["period_min"] < 94
    pos = space_api.satellite_positions(tles, now)
    track = space_api.ground_track(iss, now)
    assert len(track) > 200 and track["lat"].abs().max() <= 51.9
    space_charts.satellite_globe(pos, track, iss["name"])
    print(f"satellites: {len(pos)} tracked; ISS at {s['lat']:.2f}, {s['lon']:.2f}, {s['altitude_km']:.0f} km, "
          f"{s['speed_kps']:.2f} km/s, period {s['period_min']:.1f} min")
    # independent check against a public ISS position service
    try:
        import httpx
        r = httpx.get("https://api.wheretheiss.at/v1/satellites/25544", timeout=15).json()
        dlat, dlon = abs(r["latitude"] - s["lat"]), abs((r["longitude"] - s["lon"] + 180) % 360 - 180)
        print(f"  cross-check vs wheretheiss.at: dlat {dlat:.2f} deg, dlon {dlon:.2f} deg, dalt {abs(r['altitude'] - s['altitude_km']):.1f} km")
        assert dlat < 1.5 and dlon < 1.5
    except (httpx.HTTPError, KeyError, ValueError) as e:
        print("  cross-check skipped:", type(e).__name__)


if __name__ == "__main__":
    test_earth_position()
    test_asteroids()
    test_close_approaches_and_fireballs()
    test_satellites()
    print("space tracker OK")
