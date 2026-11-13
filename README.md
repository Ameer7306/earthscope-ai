# 🌍 EarthScope AI

**Discover. Analyse. Understand. Protect.**

A Python research dashboard for the NASA Space Apps Challenge 2026. It explores NASA Earth observation
data, monitors live environmental events, tests long-term trends for statistical significance, compares
regions, and explains the results with an integrated AI assistant.

Built with Streamlit, FastAPI, Pandas, SciPy, pymannkendall, Plotly, Folium and ReportLab.

---

## Quick start (Windows)

**Easiest:** double-click `Start EarthScope.bat` in this folder. It sets everything up on first run and
opens the app in your browser.

**Manual:** open a terminal *in this folder* first (put the path in quotes if it contains spaces):

```
cd "path\to\earthscope-ai"
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

The app opens at http://localhost:8501. **No API keys are required** for the core features.

macOS / Linux: use `source venv/bin/activate` instead of `venv\Scripts\activate`.

### Optional keys

Copy `.env.example` to `.env` and fill in:

| Key | Enables | Without it |
|---|---|---|
| `OPENAI_API_KEY` (+ `OPENAI_MODEL`) | Full conversational AI assistant | **DEMO MODE**: built-in offline explainer that answers from the app's computed results |
| `FIRMS_MAP_KEY` ([free](https://firms.modaps.eosdis.nasa.gov/api/map_key/)) | Individual VIIRS active-fire pixels | **DEMO MODE** badge; wildfire *events* from NASA EONET are still real |

Keys are read server-side from environment variables or `.streamlit/secrets.toml` and are never sent to the browser.

### Optional FastAPI service

```
uvicorn backend.main:app --reload --port 8001
```

Docs at http://localhost:8001/docs. Endpoints: `/health`, `/variables`, `/regions`, `/datasets`, `/series`,
`/trend`, `/compare`, `/live/detections`, `/history`.
(Note: the command needs `backend.main:app`, not just `backend.main`.)

---

## Pages

| Page | What it does |
|---|---|
| **Overview** | Animated KPI cards (each links to its page), rotating globe of open NASA EONET events, GISTEMP global temperature, precipitation and NDVI trend charts, alerts, analysis history |
| **Earth Explorer** | NASA GIBS satellite map: search countries/cities or lat/lon, click a point, draw and save a region, switch layers and dates, view the series at the selection |
| **Data Explorer** | Searchable catalogue of 20 NASA datasets (atmosphere / land / water) with mission, resolution, coverage, update frequency and documentation links |
| **Trend Analysis** | Mann-Kendall test, Sen's slope with confidence interval, p-value, OLS comparison, annual changes, anomalies, period comparison, sample size and missing data |
| **Regional Comparison** | Same variable and period across 2–8 regions, with a slope chart and multiple-testing warning |
| **Opposite Trend Detector** | Two regions side by side; classifies both increasing / both decreasing / opposite / one significant / neither |
| **Significance Testing** | Separate statistical vs practical significance, robustness across test variants, sensitivity to α and start year |
| **Live Earth Monitoring** | Near-real-time events, FIRMS fires, daily rainfall, GIBS layers, freshness indicator, refresh button |
| **Space & Orbit Tracker** | Near-Earth asteroids with animated orbits (NASA NeoWs), upcoming close approaches (JPL SBDB), meteor fireballs on a globe (JPL CNEOS), and live satellite positions and ground tracks (CelesTrak elements + SGP4) |
| **AI Science Assistant** | Context-aware chat (also available as a panel in the sidebar on every page) |
| **Reports** | PDF report (chart, methodology, results, limitations) plus CSV and Excel exports |
| **Settings** | Connection status, animation toggle, defaults, saved regions, cache and database tools |

## Data sources (all real, fetched live)

| Source | Used for | Key |
|---|---|---|
| [NASA POWER](https://power.larc.nasa.gov/) | Temperature, humidity, precipitation, soil wetness, solar radiation, wind (monthly 1981–present, daily) | none |
| [NASA GISS GISTEMP v4](https://data.giss.nasa.gov/gistemp/) | Global temperature anomaly | none |
| [MODIS MOD13Q1 via ORNL DAAC](https://modis.ornl.gov/data/modis_webservice.html) | NDVI (250 m, 2000–present) | none |
| [NASA EONET](https://eonet.gsfc.nasa.gov/) | Live natural events (wildfires, storms, volcanoes, ice…) | none |
| [NASA GIBS](https://www.earthdata.nasa.gov/eosdis/science-system-description/eosdis-components/gibs) | Satellite imagery layers (true colour, IMERG rain rate, LST, NDVI, aerosols) | none |
| [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/api/) | Active fire pixels | `FIRMS_MAP_KEY` |
| [JPL CNEOS](https://cneos.jpl.nasa.gov/fireballs/) | Meteor fireball detections | none |
| [NASA NeoWs](https://api.nasa.gov/) | Near-Earth asteroids and their orbits | optional `NASA_API_KEY` (shared `DEMO_KEY` otherwise, ≈30 requests/hour) |
| [JPL SBDB Close-Approach API](https://ssd-api.jpl.nasa.gov/doc/cad.html) | Upcoming close approaches | none |
| [CelesTrak](https://celestrak.org/) (not NASA) | Satellite orbital elements, propagated with SGP4 | none |

Responses are cached on disk (`data/cache`), with timeouts, retries and back-off on rate limits.
The app never substitutes invented values: if a source is down you get an error message, and anything
not connected is labelled **DEMO MODE**.

## Statistical methods

- **Mann-Kendall** trend test (original), **Seasonal Kendall** for monthly data, and **Hamed-Rao**,
  **Yue-Wang** and **trend-free pre-whitening** variants for serially correlated data.
- "Auto" mode uses Seasonal Kendall for monthly data; for annual data it tests lag-1 autocorrelation
  and switches to Hamed-Rao when it is significant.
- **Sen's slope** with a distribution-free confidence interval (Gilbert 1987).
- Results are classified as increasing, decreasing, **no statistically significant trend detected**, or
  **insufficient data** (fewer than 10 annual values, fewer than 5 years of monthly data, or >50% missing).
- A non-significant result is never reported as "no change".
- An opposite trend is reported only when both regions are individually significant with different directions.

### Limitations

- Point sampling uses one ~50 km reanalysis grid cell; "area" sampling averages a 3×3 grid of cells over
  the region's bounding box. Neither is a true area-weighted regional mean.
- NDVI uses a single 250 m MODIS pixel at the selected point.
- MERRA-2 values are model-assimilated estimates, not direct measurements.
- Trends do not identify causes.

## Project structure

```
earthscope-ai/
├── app.py                  Streamlit entry point, navigation, sidebar assistant
├── requirements.txt  .env.example  README.md
├── views/                  the 12 pages (not named "pages/": Streamlit auto-runs that folder and would skip app.py)
├── core/                   config (variables, regions, colours), session state, shared controls
├── backend/                nasa_api.py, live_monitoring.py, database.py, catalog.py, main.py (FastAPI)
├── analysis/               trends.py, significance.py, regional.py, anomalies.py
├── ai/                     assistant.py, prompts.py, context.py
├── visualization/          charts.py, maps.py, animations.py
├── reports/                generator.py (PDF, CSV, Excel)
├── assets/                 styles.css (theme + animations), logo.png
└── data/                   earthscope.db (SQLite), cache/
```

## Animations

Fade-in and slide-up reveals (including scroll-driven reveals in Chromium/Edge), staggered KPI cards with
animated counters, hover effects, page transitions, an animated aurora/star background, a rotating globe
and loading indicators. All motion is disabled when the operating system requests reduced motion, or with
the toggle in Settings.

## Database

SQLite (`data/earthscope.db`) with tables: `users`, `datasets`, `observations`, `analysis_history`,
`saved_regions`, `detection_alerts`, `chat_sessions`, `generated_reports`. Types are portable, so the schema
can move to PostgreSQL or Supabase by replacing `connect()` in `backend/database.py`.

---

Data courtesy of NASA. EarthScope AI is a research prototype and not an official NASA product.
