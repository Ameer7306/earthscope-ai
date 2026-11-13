"""
Central configuration: colours, environment settings, environmental variables and regions.

Everything that other modules need to agree on lives here so pages, the FastAPI
backend and the AI assistant all describe data the same way.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # python-dotenv is optional at runtime
    pass

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

APP_NAME = "EarthScope AI"
TAGLINE = "Discover. Analyse. Understand. Protect."

# ---------- theme ----------
COLORS = {
    "bg": "#07111F",
    "bg2": "#0D1B2A",
    "card": "#12243A",
    "primary": "#38BDF8",
    "secondary": "#14B8A6",
    "positive": "#22C55E",
    "negative": "#EF4444",
    "text": "#F8FAFC",
    "muted": "#94A3B8",
    "warning": "#F59E0B",
}


# ---------- environment ----------
def env(name: str, default: str = "") -> str:
    """Read a setting from the environment, falling back to Streamlit secrets if available."""
    val = os.environ.get(name)
    if val:
        return val
    try:
        import streamlit as st  # imported lazily so the FastAPI backend doesn't need it
        return str(st.secrets.get(name, default))
    except Exception:
        return default


def settings() -> dict:
    return {
        "OPENAI_API_KEY": env("OPENAI_API_KEY"),
        "OPENAI_MODEL": env("OPENAI_MODEL", "gpt-4o-mini"),
        "FIRMS_MAP_KEY": env("FIRMS_MAP_KEY"),
        "DATABASE_PATH": env("DATABASE_PATH", str(DATA_DIR / "earthscope.db")),
        "CACHE_HOURS": float(env("CACHE_HOURS", "24") or 24),
        "HTTP_TIMEOUT": float(env("HTTP_TIMEOUT", "45") or 45),
    }


# ---------- environmental variables available for analysis ----------
# source "power"  -> NASA POWER monthly point API (MERRA-2 / GEOS / IMERG based), 1981-present
# source "modis"  -> MODIS MOD13Q1 NDVI via ORNL DAAC web service, 2000-present
VARIABLES: dict[str, dict] = {
    "air_temperature": {
        "label": "Air temperature (2 m)", "units": "°C", "category": "Atmosphere",
        "source": "power", "param": "T2M", "start": 1981,
        "dataset": "NASA POWER – MERRA-2 2 m air temperature",
    },
    "max_temperature": {
        "label": "Maximum air temperature (2 m)", "units": "°C", "category": "Atmosphere",
        "source": "power", "param": "T2M_MAX", "start": 1981,
        "dataset": "NASA POWER – MERRA-2 daily maximum temperature",
    },
    "humidity": {
        "label": "Relative humidity (2 m)", "units": "%", "category": "Atmosphere",
        "source": "power", "param": "RH2M", "start": 1981,
        "dataset": "NASA POWER – MERRA-2 relative humidity",
    },
    "surface_temperature": {
        "label": "Land/earth skin temperature", "units": "°C", "category": "Land",
        "source": "power", "param": "TS", "start": 1981,
        "dataset": "NASA POWER – MERRA-2 earth skin temperature",
    },
    "ndvi": {
        "label": "Vegetation index (NDVI)", "units": "NDVI", "category": "Land",
        "source": "modis", "param": "250m_16_days_NDVI", "start": 2000,
        "dataset": "MODIS Terra MOD13Q1 16-day NDVI (250 m) via ORNL DAAC",
    },
    "soil_moisture": {
        "label": "Surface soil wetness", "units": "fraction (0–1)", "category": "Land",
        "source": "power", "param": "GWETTOP", "start": 1981,
        "dataset": "NASA POWER – MERRA-2 surface soil wetness",
    },
    "root_soil_moisture": {
        "label": "Root-zone soil wetness", "units": "fraction (0–1)", "category": "Land",
        "source": "power", "param": "GWETROOT", "start": 1981,
        "dataset": "NASA POWER – MERRA-2 root-zone soil wetness",
    },
    "precipitation": {
        "label": "Precipitation", "units": "mm/day", "category": "Water",
        "source": "power", "param": "PRECTOTCORR", "start": 1981,
        "dataset": "NASA POWER – bias-corrected precipitation (MERRA-2 / GPM IMERG)",
    },
    "solar_radiation": {
        "label": "Surface solar radiation", "units": "MJ/m²/day", "category": "Atmosphere",
        "source": "power", "param": "ALLSKY_SFC_SW_DWN", "start": 1984,
        "dataset": "NASA POWER – CERES / GEWEX all-sky shortwave irradiance",
    },
    "wind_speed": {
        "label": "Wind speed (2 m)", "units": "m/s", "category": "Atmosphere",
        "source": "power", "param": "WS2M", "start": 1981,
        "dataset": "NASA POWER – MERRA-2 wind speed",
    },
}

# ---------- regions ----------
# lat/lon = representative point (capital or population centre);
# bbox = (south, west, north, east) used for the 3×3 "area mean" sampling mode.
REGIONS: dict[str, dict] = {
    "Qatar": {"lat": 25.29, "lon": 51.53, "bbox": (24.5, 50.75, 26.2, 51.65), "type": "country"},
    "India": {"lat": 28.61, "lon": 77.21, "bbox": (8.0, 68.0, 34.0, 89.0), "type": "country"},
    "United Arab Emirates": {"lat": 24.45, "lon": 54.38, "bbox": (22.6, 51.5, 26.1, 56.4), "type": "country"},
    "Saudi Arabia": {"lat": 24.71, "lon": 46.68, "bbox": (16.4, 36.5, 32.2, 55.7), "type": "country"},
    "Egypt": {"lat": 30.04, "lon": 31.24, "bbox": (22.0, 25.0, 31.6, 35.0), "type": "country"},
    "Kenya": {"lat": -1.29, "lon": 36.82, "bbox": (-4.7, 33.9, 5.0, 41.9), "type": "country"},
    "Nigeria": {"lat": 9.08, "lon": 7.40, "bbox": (4.3, 2.7, 13.9, 14.7), "type": "country"},
    "South Africa": {"lat": -25.75, "lon": 28.19, "bbox": (-34.8, 16.5, -22.1, 32.9), "type": "country"},
    "Ethiopia": {"lat": 9.03, "lon": 38.74, "bbox": (3.4, 33.0, 14.9, 48.0), "type": "country"},
    "Morocco": {"lat": 34.02, "lon": -6.84, "bbox": (27.7, -13.2, 35.9, -1.0), "type": "country"},
    "United Kingdom": {"lat": 51.51, "lon": -0.13, "bbox": (50.0, -5.7, 58.6, 1.8), "type": "country"},
    "France": {"lat": 48.86, "lon": 2.35, "bbox": (42.3, -4.8, 51.1, 8.2), "type": "country"},
    "Germany": {"lat": 52.52, "lon": 13.40, "bbox": (47.3, 5.9, 55.1, 15.0), "type": "country"},
    "Spain": {"lat": 40.42, "lon": -3.70, "bbox": (36.0, -9.3, 43.8, 3.3), "type": "country"},
    "Italy": {"lat": 41.90, "lon": 12.50, "bbox": (37.9, 7.6, 46.5, 18.5), "type": "country"},
    "Norway": {"lat": 59.91, "lon": 10.75, "bbox": (58.0, 5.0, 70.5, 30.0), "type": "country"},
    "Russia": {"lat": 55.76, "lon": 37.62, "bbox": (45.0, 30.0, 70.0, 140.0), "type": "country"},
    "China": {"lat": 39.90, "lon": 116.41, "bbox": (21.0, 75.0, 50.0, 125.0), "type": "country"},
    "Japan": {"lat": 35.68, "lon": 139.69, "bbox": (31.0, 130.0, 44.0, 145.0), "type": "country"},
    "Indonesia": {"lat": -6.21, "lon": 106.85, "bbox": (-8.5, 95.0, 5.5, 140.0), "type": "country"},
    "Pakistan": {"lat": 33.68, "lon": 73.05, "bbox": (24.5, 61.0, 36.5, 75.5), "type": "country"},
    "Bangladesh": {"lat": 23.81, "lon": 90.41, "bbox": (20.7, 88.0, 26.6, 92.7), "type": "country"},
    "Australia": {"lat": -33.87, "lon": 151.21, "bbox": (-39.0, 114.0, -12.0, 153.0), "type": "country"},
    "New Zealand": {"lat": -41.29, "lon": 174.78, "bbox": (-46.6, 166.5, -34.4, 178.6), "type": "country"},
    "United States": {"lat": 38.90, "lon": -77.04, "bbox": (25.0, -124.0, 49.0, -67.0), "type": "country"},
    "Canada": {"lat": 45.42, "lon": -75.70, "bbox": (43.0, -130.0, 60.0, -60.0), "type": "country"},
    "Mexico": {"lat": 19.43, "lon": -99.13, "bbox": (15.0, -115.0, 32.0, -87.0), "type": "country"},
    "Brazil": {"lat": -15.79, "lon": -47.88, "bbox": (-30.0, -73.0, 4.0, -35.0), "type": "country"},
    "Argentina": {"lat": -34.60, "lon": -58.38, "bbox": (-50.0, -72.0, -22.0, -54.0), "type": "country"},
    "Peru": {"lat": -12.05, "lon": -77.04, "bbox": (-18.3, -81.3, -0.1, -68.7), "type": "country"},
    "Amazon Basin": {"lat": -3.47, "lon": -62.21, "bbox": (-12.0, -75.0, 2.0, -50.0), "type": "area"},
    "Sahel": {"lat": 14.5, "lon": 0.0, "bbox": (11.0, -15.0, 18.0, 30.0), "type": "area"},
    "Greenland": {"lat": 64.18, "lon": -51.72, "bbox": (60.0, -55.0, 80.0, -20.0), "type": "area"},
    "Siberia": {"lat": 62.03, "lon": 129.73, "bbox": (55.0, 80.0, 70.0, 150.0), "type": "area"},
    # cities
    "Doha": {"lat": 25.29, "lon": 51.53, "bbox": None, "type": "city"},
    "Dubai": {"lat": 25.20, "lon": 55.27, "bbox": None, "type": "city"},
    "Mumbai": {"lat": 19.08, "lon": 72.88, "bbox": None, "type": "city"},
    "Nairobi": {"lat": -1.29, "lon": 36.82, "bbox": None, "type": "city"},
    "Cairo": {"lat": 30.04, "lon": 31.24, "bbox": None, "type": "city"},
    "London": {"lat": 51.51, "lon": -0.13, "bbox": None, "type": "city"},
    "New York": {"lat": 40.71, "lon": -74.01, "bbox": None, "type": "city"},
    "Los Angeles": {"lat": 34.05, "lon": -118.24, "bbox": None, "type": "city"},
    "Tokyo": {"lat": 35.68, "lon": 139.69, "bbox": None, "type": "city"},
    "Sydney": {"lat": -33.87, "lon": 151.21, "bbox": None, "type": "city"},
    "São Paulo": {"lat": -23.55, "lon": -46.63, "bbox": None, "type": "city"},
    "Lagos": {"lat": 6.52, "lon": 3.38, "bbox": None, "type": "city"},
    "Jakarta": {"lat": -6.21, "lon": 106.85, "bbox": None, "type": "city"},
    "Beijing": {"lat": 39.90, "lon": 116.41, "bbox": None, "type": "city"},
    "Moscow": {"lat": 55.76, "lon": 37.62, "bbox": None, "type": "city"},
    "Reykjavik": {"lat": 64.15, "lon": -21.94, "bbox": None, "type": "city"},
}

DEFAULT_REGION = "Qatar"
DEFAULT_VARIABLE = "air_temperature"
LATEST_FULL_YEAR = __import__("datetime").date.today().year - 1   # last complete calendar year
DEFAULT_START_YEAR = 1991
DEFAULT_ALPHA = 0.05
