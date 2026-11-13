"""Space & Orbit Tracker: near-Earth asteroids, close approaches, meteor fireballs and live satellite orbits."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from backend import space_api
from backend.nasa_api import DataSourceError
from core import state
from visualization import space_charts
from visualization.animations import badges, hero, kpi_card, loading

hero("Space & Orbit Tracker", "Asteroids approaching Earth, meteors hitting the atmosphere and satellites in "
                              "Earth orbit — tracked with live NASA / JPL data.")


# ---------------------------------------------------------------- cached loaders
@st.cache_data(ttl=3 * 3600, show_spinner=False)
def load_neos(days: int) -> pd.DataFrame:
    return space_api.fetch_neo_feed(days)


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def load_orbit(neo_id: str) -> dict:
    return space_api.fetch_neo_orbit(neo_id)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def load_approaches(days: int, dist: float) -> pd.DataFrame:
    return space_api.fetch_close_approaches(days, dist)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def load_fireballs(limit: int) -> pd.DataFrame:
    return space_api.fetch_fireball_events(limit)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def load_tles(group: str) -> list[dict]:
    return space_api.fetch_tles(group)


badges(("live", "Live NASA / JPL data"), ("nasa", "NeoWs · SBDB · CNEOS · CelesTrak"),
       ("demo", "NASA DEMO_KEY (≈30 requests/hour)") if space_api.using_demo_key() else ("live", "NASA API key set"))
st.write("")

tab_neo, tab_ca, tab_fb, tab_sat = st.tabs(["☄️ Near-Earth asteroids", "🎯 Close approaches",
                                            "🌠 Meteors (fireballs)", "🛰️ Earth orbit (satellites)"])
summary: dict = {}

# ================================================================ asteroids
with tab_neo:
    try:
        with loading("Loading asteroid approaches from NASA NeoWs…"):
            neos = load_neos(7)
    except Exception as e:
        neos = None
        st.error(f"NASA NeoWs is unavailable: {e}")
        if space_api.using_demo_key():
            st.info("The shared DEMO_KEY may be rate-limited. Get a free key at https://api.nasa.gov and set "
                    "`NASA_API_KEY` in `.env`.")
    if neos is not None:
        closest = neos.loc[neos["miss_lunar"].idxmin()]
        largest = neos.loc[neos["diameter_max_m"].idxmax()]
        k = st.columns(4)
        with k[0]:
            kpi_card("Asteroids this week", int(len(neos)), "passing Earth in the next 7 days", "☄️")
        with k[1]:
            kpi_card("Potentially hazardous", int(neos["hazardous"].sum()), "PHA classification (size + orbit)", "⚠️", 0.08, "#EF4444")
        with k[2]:
            kpi_card("Closest flyby", f"{closest['miss_lunar']:.1f} LD", closest["name"], "🎯", 0.16, "#14B8A6")
        with k[3]:
            kpi_card("Largest object", f"~{largest['diameter_max_m']:.0f} m", largest["name"], "🪨", 0.24, "#F59E0B")
        st.caption("LD = lunar distance (384,400 km). “Potentially hazardous” is an orbit/size class, not a prediction of impact.")

        left, right = st.columns([1.15, 1.5], gap="large")
        with left:
            only_pha = st.toggle("Potentially hazardous only", False)
            view = neos[neos["hazardous"]] if only_pha else neos
            if view.empty:
                st.info("No potentially hazardous asteroids in this window.")
                view = neos
            table = pd.DataFrame({
                "Name": view["name"], "Closest approach (UTC)": view["approach"].dt.strftime("%d %b %H:%M"),
                "Miss (LD)": view["miss_lunar"], "Speed (km/s)": view["velocity_kps"],
                "Diameter (m)": view["diameter_min_m"].round().astype(int).astype(str) + "–" + view["diameter_max_m"].round().astype(int).astype(str),
                "Hazardous": view["hazardous"].map({True: "⚠️ Yes", False: "No"})})
            st.dataframe(table, hide_index=True, width="stretch", height=430,
                         column_config={"Miss (LD)": st.column_config.NumberColumn(format="%.2f"),
                                        "Speed (km/s)": st.column_config.NumberColumn(format="%.1f")})
        with right:
            names = view["name"].tolist()
            default = names.index(closest["name"]) if closest["name"] in names else 0
            pick = st.selectbox("Show the orbit of", names, index=default)
            row = view[view["name"] == pick].iloc[0]
            try:
                with loading(f"Loading orbital elements for {pick}…"):
                    el = load_orbit(str(row["id"]))
                el = {**el, "name": pick}
                st.plotly_chart(space_charts.orbit_animation(el), width="stretch", config={"displayModeBar": False})
                o = st.columns(4)
                o[0].metric("Orbit class", el["orbit_class"] or "—", help=el["orbit_class_description"])
                o[1].metric("Orbital period", f"{el['period_days'] / 365.25:.2f} yr")
                o[2].metric("Eccentricity", f"{el['e']:.3f}")
                o[3].metric("Inclination", f"{el['i']:.1f}°")
                st.caption(f"Perihelion {el['q']:.3f} AU · aphelion {el['Q']:.3f} AU · closest approach "
                           f"{row['approach']:%d %b %Y %H:%M} UTC at {row['miss_km']:,.0f} km · "
                           f"[JPL Small-Body Database]({row['url']}). Press ▶ Play to animate ±120 days. "
                           "Planet positions use mean J2000 elements (approximate).")
            except DataSourceError as e:
                st.warning(f"Orbit could not be loaded: {e}")
        summary["asteroids"] = (f"{len(neos)} asteroids pass Earth in the next 7 days, {int(neos['hazardous'].sum())} "
                                f"potentially hazardous; closest {closest['name']} at {closest['miss_lunar']:.2f} LD "
                                f"({closest['miss_km']:,.0f} km) on {closest['approach']:%Y-%m-%d %H:%M} UTC")

# ================================================================ close approaches
with tab_ca:
    c1, c2 = st.columns(2)
    days = c1.selectbox("Look ahead", [30, 60, 180, 365], index=1, format_func=lambda d: f"{d} days")
    dist = c2.selectbox("Closer than", [0.0026, 0.01, 0.05, 0.1], index=2,
                        format_func=lambda d: {0.0026: "1 lunar distance", 0.01: "≈4 lunar distances",
                                               0.05: "0.05 AU (≈19 LD)", 0.1: "0.1 AU (≈39 LD)"}[d])
    try:
        with loading("Loading close approaches from JPL…"):
            ca = load_approaches(days, dist)
        if ca.empty:
            st.info("No known objects pass that close in this window.")
        else:
            m = st.columns(4)
            near = ca.loc[ca["dist_lunar"].idxmin()]
            m[0].metric("Approaches", len(ca))
            m[1].metric("Inside the Moon's orbit", int((ca["dist_lunar"] < 1).sum()))
            m[2].metric("Closest", f"{near['dist_lunar']:.2f} LD", near["object"], delta_color="off")
            m[3].metric("Fastest", f"{ca['velocity_kps'].max():.1f} km/s")
            st.plotly_chart(space_charts.approach_timeline(ca), width="stretch")
            show = pd.DataFrame({
                "Object": ca["object"], "Date (UTC)": ca["date"].dt.strftime("%Y-%m-%d %H:%M"),
                "Distance (LD)": ca["dist_lunar"], "Distance (km)": ca["dist_km"].round().astype("int64"),
                "Speed (km/s)": ca["velocity_kps"], "H (mag)": ca["magnitude_h"],
                "Est. size (m)": ca.apply(lambda r: "—" if pd.isna(r["size_min_m"]) else f"{r['size_min_m']:.0f}–{r['size_max_m']:.0f}", axis=1)})
            st.dataframe(show, hide_index=True, width="stretch", height=380,
                         column_config={"Distance (LD)": st.column_config.NumberColumn(format="%.2f"),
                                        "Speed (km/s)": st.column_config.NumberColumn(format="%.1f"),
                                        "Distance (km)": st.column_config.NumberColumn(format="localized")})
            st.download_button("Download close approaches (CSV)", show.to_csv(index=False).encode("utf-8"),
                               "earthscope_close_approaches.csv", "text/csv")
            st.caption("Source: JPL SBDB Close-Approach Data API. Sizes are estimated from absolute magnitude H "
                       "assuming albedo 0.25–0.05, so they are uncertain by roughly a factor of two.")
            summary["close_approaches"] = (f"{len(ca)} approaches within {dist} AU in next {days} days; closest "
                                           f"{near['object']} at {near['dist_lunar']:.2f} LD on {near['date']:%Y-%m-%d}")
    except Exception as e:
        st.error(f"JPL close-approach data unavailable: {e}")

# ================================================================ meteors
with tab_fb:
    limit = st.select_slider("Most recent fireball events", [50, 100, 200, 300, 500, 1000], value=300)
    try:
        with loading("Loading fireball events from JPL CNEOS…"):
            fb = load_fireballs(limit)
        big = fb.loc[fb["impact_kt"].idxmax()]
        m = st.columns(4)
        m[0].metric("Events loaded", len(fb), f"{fb['time'].min():%Y} – {fb['time'].max():%Y}", delta_color="off")
        m[1].metric("Latest fireball", f"{fb['time'].max():%d %b %Y}")
        m[2].metric("Most energetic", f"{big['impact_kt']:.1f} kt", f"{big['time']:%d %b %Y}", delta_color="off")
        m[3].metric("Median speed", f"{fb['velocity_kps'].median():.1f} km/s")
        g, s = st.columns([1.6, 1], gap="large")
        with g:
            st.plotly_chart(space_charts.fireball_globe(fb), width="stretch", config={"displayModeBar": False, "scrollZoom": True})
            st.caption("Drag to spin or press ▶ Rotate. Marker size and colour show impact energy (kilotons of TNT).")
        with s:
            st.plotly_chart(space_charts.fireballs_per_year(fb), width="stretch", config={"displayModeBar": False})
            latest = fb.iloc[0]
            st.markdown(f"**Most recent event** — {latest['time']:%Y-%m-%d %H:%M} UTC at "
                        f"{abs(latest['lat']):.1f}°{'N' if latest['lat'] >= 0 else 'S'}, "
                        f"{abs(latest['lon']):.1f}°{'E' if latest['lon'] >= 0 else 'W'} · "
                        f"{latest['impact_kt']:.2f} kt TNT"
                        + ("" if pd.isna(latest["altitude_km"]) else f" · {latest['altitude_km']:.0f} km altitude"))
            st.caption("Fireballs are exceptionally bright meteors detected by US Government sensors and published "
                       "by NASA/JPL CNEOS. Reporting is not real-time (days to weeks) and not every event has "
                       "altitude or velocity.")
        tbl = pd.DataFrame({"Date (UTC)": fb["time"].dt.strftime("%Y-%m-%d %H:%M"), "Lat": fb["lat"], "Lon": fb["lon"],
                            "Impact energy (kt)": fb["impact_kt"], "Altitude (km)": fb["altitude_km"],
                            "Speed (km/s)": fb["velocity_kps"], "Radiated (10¹⁰ J)": fb["radiated_e10j"]})
        st.dataframe(tbl, hide_index=True, width="stretch", height=300)
        st.download_button("Download fireballs (CSV)", tbl.to_csv(index=False).encode("utf-8"),
                           "earthscope_fireballs.csv", "text/csv")
        summary["meteors"] = (f"{len(fb)} fireballs loaded; latest {fb['time'].max():%Y-%m-%d %H:%M} UTC; most energetic "
                              f"{big['impact_kt']:.1f} kt on {big['time']:%Y-%m-%d}")
    except Exception as e:
        st.error(f"JPL fireball data unavailable: {e}")

# ================================================================ satellites
with tab_sat:
    s1, s2, s3 = st.columns([1.3, 1.5, 1])
    group = s1.selectbox("Satellite group", list(space_api.SAT_GROUPS), format_func=space_api.SAT_GROUPS.get)
    try:
        with loading("Loading orbital elements from CelesTrak…"):
            tles = load_tles(group)
    except Exception as e:
        tles = None
        st.error(f"Satellite orbital elements unavailable: {e}")
    if tles:
        sat_names = [t["name"] for t in tles]
        default = next((i for i, n in enumerate(sat_names) if n.startswith("ISS")), 0)
        chosen = s2.selectbox("Track satellite", sat_names, index=default)
        live = s3.toggle("Live updates (5 s)", True, help="Recomputes positions with the SGP4 orbit model every 5 seconds.")
        sat = tles[sat_names.index(chosen)]

        @st.fragment(run_every=5 if live else None)
        def live_view() -> None:
            now = datetime.now(timezone.utc)
            pos = space_api.satellite_positions(tles, now)
            cur = pos[pos["name"] == chosen]
            if cur.empty:
                st.warning("This satellite's orbit could not be propagated (elements may be out of date).")
                return
            c = cur.iloc[0]
            m = st.columns(5)
            m[0].metric("Latitude", f"{c['lat']:.2f}°")
            m[1].metric("Longitude", f"{c['lon']:.2f}°")
            m[2].metric("Altitude", f"{c['altitude_km']:,.0f} km")
            m[3].metric("Speed", f"{c['speed_kps']:.2f} km/s")
            m[4].metric("Orbital period", f"{c['period_min']:.1f} min")
            track = space_api.ground_track(sat, now)
            st.plotly_chart(space_charts.satellite_globe(pos, track, chosen), width="stretch",
                            config={"displayModeBar": False}, key="sat_globe")
            st.caption(f"{len(pos)} satellites · positions at {now:%H:%M:%S} UTC · {chosen}: NORAD {int(c['norad_id'])}, "
                       f"inclination {c['inclination_deg']:.1f}°, {c['orbits_per_day']:.2f} orbits/day. "
                       "Yellow line: ground track (faint = past half orbit, bright = next 1.5 orbits).")

        live_view()
        st.caption("Orbits come from NORAD two-line elements published by CelesTrak (not a NASA service) and are "
                   "propagated in Python with the SGP4 model; accuracy is typically within a few kilometres for "
                   "elements less than a few days old.")
        summary["satellites"] = f"{len(tles)} satellites in group '{space_api.SAT_GROUPS[group]}', tracking {chosen}"

state.publish("space", summary)
