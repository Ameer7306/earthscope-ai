"""
EarthScope AI — FastAPI backend (optional separate service).

Exposes the same data and analysis engine as the Streamlit app over a JSON API, so other
front-ends, notebooks or mobile apps can use it.

Run from the project folder:
    uvicorn backend.main:app --reload --port 8001
Interactive docs: http://localhost:8001/docs
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from analysis.regional import classify_pair  # noqa: E402
from analysis.trends import METHODS, STATUS_LABEL, aggregate, interpret, run_trend  # noqa: E402
from backend import database as db  # noqa: E402
from backend import nasa_api  # noqa: E402
from backend.catalog import DATASETS  # noqa: E402
from backend.live_monitoring import collect_detections  # noqa: E402
from core.config import APP_NAME, LATEST_FULL_YEAR, REGIONS, TAGLINE, VARIABLES  # noqa: E402

app = FastAPI(title=f"{APP_NAME} API", description=TAGLINE, version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
                   allow_methods=["GET"], allow_headers=["*"])
db.init_db()


def _clean(obj):
    """Replace NaN/inf (invalid JSON) with None, recursively."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if hasattr(obj, "item"):          # numpy scalars
        return _clean(obj.item())
    return obj


def _regions() -> dict:
    return {**REGIONS, **db.saved_regions()}


def _series(variable: str, region: str, start: int, end: int, sampling: str):
    if variable not in VARIABLES:
        raise HTTPException(404, f"Unknown variable '{variable}'. See /variables.")
    if region not in _regions():
        raise HTTPException(404, f"Unknown region '{region}'. See /regions.")
    try:
        return nasa_api.fetch_series(variable, region, start, end, sampling, custom=_regions())
    except nasa_api.DataSourceError as e:
        raise HTTPException(502, f"NASA data source error: {e}")


@app.get("/health")
def health():
    return {"status": "ok", "app": APP_NAME, "cache": nasa_api.cache_info()}


@app.get("/variables")
def variables():
    return VARIABLES


@app.get("/regions")
def regions():
    return _clean(_regions())


@app.get("/datasets")
def datasets(category: str | None = None, connected: bool | None = None):
    out = DATASETS
    if category:
        out = [d for d in out if d["category"].lower() == category.lower()]
    if connected is not None:
        out = [d for d in out if d["connected"] == connected]
    return out


@app.get("/series")
def series(variable: str, region: str, start: int = 1991, end: int = LATEST_FULL_YEAR,
           sampling: str = Query("point", pattern="^(point|area)$"),
           aggregation: str = Query("monthly", pattern="^(monthly|annual)$")):
    df, meta = _series(variable, region, start, end, sampling)
    s = aggregate(df, aggregation)
    return _clean({"meta": meta, "data": [{"date": i.strftime("%Y-%m-%d"), "value": v} for i, v in s.items()]})


@app.get("/trend")
def trend(variable: str, region: str, start: int = 1991, end: int = LATEST_FULL_YEAR,
          sampling: str = Query("point", pattern="^(point|area)$"),
          aggregation: str = Query("annual", pattern="^(monthly|annual)$"),
          method: str = "auto", alpha: float = Query(0.05, gt=0, lt=0.5)):
    if method not in METHODS:
        raise HTTPException(400, f"method must be one of {list(METHODS)}")
    df, meta = _series(variable, region, start, end, sampling)
    res = run_trend(df, aggregation, method, alpha)
    return _clean({"meta": meta, "result": res, "label": STATUS_LABEL[res["status"]],
                   "interpretation": interpret(res, meta["label"], meta["units"], region)})


@app.get("/compare")
def compare(variable: str, region_a: str, region_b: str, start: int = 1991, end: int = LATEST_FULL_YEAR,
            aggregation: str = Query("annual", pattern="^(monthly|annual)$"), alpha: float = Query(0.05, gt=0, lt=0.5)):
    """Opposite-trend detector for two regions."""
    da, _ = _series(variable, region_a, start, end, "point")
    dbb, _ = _series(variable, region_b, start, end, "point")
    ra, rb = run_trend(da, aggregation, "auto", alpha), run_trend(dbb, aggregation, "auto", alpha)
    return _clean({"variable": variable, "region_a": {"name": region_a, "result": ra},
                   "region_b": {"name": region_b, "result": rb}, "comparison": classify_pair(ra, rb)})


@app.get("/live/detections")
def live_detections(days: int = Query(30, ge=1, le=365), fireballs: bool = False):
    return _clean(collect_detections(days, fireballs))


@app.get("/history")
def history(limit: int = Query(20, ge=1, le=200)):
    return db.analysis_history(limit).to_dict(orient="records")
