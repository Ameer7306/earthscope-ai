"""
Smoke tests for report generation, the AI assistant (offline mode) and the FastAPI backend.

Run from the project folder:   venv\\Scripts\\python tests\\test_outputs.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from ai import assistant  # noqa: E402
from ai.context import build_context  # noqa: E402
from analysis.regional import classify_pair  # noqa: E402
from analysis.trends import run_trend  # noqa: E402
from backend import nasa_api  # noqa: E402
from backend.main import app  # noqa: E402
from reports import generator  # noqa: E402


def test_reports():
    df, meta = nasa_api.fetch_series("air_temperature", "Qatar", 1991, 2025)
    res = run_trend(df, "annual")
    pdf = generator.build_pdf("Test report", "QA", df, meta, res, "annual", "Some **bold** notes.",
                              {"rows": [("Trend direction", "A | B")], "text": "Qatar vs India: opposite."})
    assert pdf[:4] == b"%PDF" and len(pdf) > 30_000, len(pdf)
    pdf_m = generator.build_pdf("Monthly", "", df, meta, run_trend(df, "monthly"), "monthly")
    assert pdf_m[:4] == b"%PDF"
    short = df.iloc[:36]
    assert generator.build_pdf("Short", "", short, meta, run_trend(short, "annual"), "annual")[:4] == b"%PDF"
    csv = generator.build_csv(df, meta)
    assert csv.startswith(b"# EarthScope AI export") and csv.count(b"\n") > 400
    xlsx = generator.build_excel(df, meta, res)
    assert xlsx[:2] == b"PK" and len(xlsx) > 5000
    print(f"reports OK  (pdf {len(pdf) // 1024} KB, csv {len(csv) // 1024} KB, xlsx {len(xlsx) // 1024} KB)")
    return df, meta, res


def test_assistant(df, meta, res):
    df_b, _ = nasa_api.fetch_series("air_temperature", "India", 1991, 2025)
    res_b = run_trend(df_b, "annual")
    ctx = {"current_page": "Trend Analysis",
           "selection": {"region": "Qatar", "variable": "air_temperature", "start": 1991, "end": 2025, "sampling": "point"},
           "trend": {"region": "Qatar", "label": meta["label"], "units": meta["units"], "result": res,
                     "annual_values": [(1991, 27.0)], "period_comparison": None},
           "opposite": {"label": meta["label"], "units": meta["units"], "period": "1991–2025", "region_a": "Qatar",
                        "region_b": "India", "result_a": res, "result_b": res_b, "pair": classify_pair(res, res_b)}}
    text = build_context(ctx)
    assert "Qatar" in text and "DATASET CATALOGUE" in text
    for q in ["Explain this graph.", "What is happening to temperatures in Qatar?",
              "Why are these two regions showing opposite trends?", "Explain a p-value of 0.03.",
              "Which NASA dataset should I use for NDVI?", "What is the latest fire detection?",
              "Explain the Mann-Kendall test.", "Help me prepare a scientific report.",
              "What is happening to temperatures in Brazil?", "hello"]:
        a = "".join(assistant.stream_reply([{"role": "user", "content": q}], ctx))
        assert len(a) > 80, (q, a)
    brazil = assistant.offline_answer("What is happening to temperatures in Brazil?", ctx)
    assert "only have results for" in brazil, brazil            # must not invent Brazil numbers
    nofire = assistant.offline_answer("What is the latest fire detection?", {})
    assert "don't have live detections" in nofire
    empty = assistant.offline_answer("Explain this graph.", {})
    assert "no analysis result" in empty
    print("assistant OK  (mode:", assistant.mode_label() + ")")


def test_api():
    c = TestClient(app)
    assert c.get("/health").json()["status"] == "ok"
    assert "air_temperature" in c.get("/variables").json()
    assert "Qatar" in c.get("/regions").json()
    assert len(c.get("/datasets", params={"category": "land"}).json()) >= 5
    s = c.get("/series", params={"variable": "precipitation", "region": "Kenya", "start": 2015, "end": 2025}).json()
    assert len(s["data"]) == 11 * 12
    t = c.get("/trend", params={"variable": "air_temperature", "region": "Qatar"}).json()
    assert t["result"]["status"] == "increasing" and t["result"]["p_value"] < 0.05
    cmp_ = c.get("/compare", params={"variable": "air_temperature", "region_a": "Qatar", "region_b": "India"}).json()
    print("API /compare:", cmp_["comparison"]["label"])
    live = c.get("/live/detections", params={"days": 30}).json()
    assert live["count"] == len(live["detections"]) and live["sources"]["NASA FIRMS"]["status"] in ("ok", "not_configured", "error")
    print(f"API /live/detections: {live['count']} detections, mode {live['mode']}")
    assert c.get("/trend", params={"variable": "nope", "region": "Qatar"}).status_code == 404
    assert c.get("/trend", params={"variable": "air_temperature", "region": "Qatar", "alpha": 2}).status_code == 422
    print("FastAPI OK")


if __name__ == "__main__":
    d, m, r = test_reports()
    test_assistant(d, m, r)
    test_api()
