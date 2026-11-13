"""
Scientific report generator: PDF (ReportLab), CSV and Excel (pandas).

The chart in the PDF is rendered with Matplotlib (no browser needed) from the same data and
results that the application displays.
"""
from __future__ import annotations

import io
import re
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from analysis.significance import practical_importance, significance_table
from analysis.trends import STATUS_LABEL, aggregate, annual_table, fractional_year, interpret

NAVY = colors.HexColor("#0D1B2A")
BLUE = colors.HexColor("#0284C7")


def _md(text: str) -> str:
    """Convert the small subset of Markdown used in interpretations to ReportLab markup."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)\*", r"<i>\1</i>", text)
    return text.replace("⚠️", "Warning:").replace("\n", "<br/>")


def chart_png(df: pd.DataFrame, result: dict, label: str, units: str, region: str, aggregation: str) -> bytes:
    """Matplotlib time-series chart with Sen's slope line."""
    s = aggregate(df, aggregation)
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=160)
    ax.plot(s.index, s.values, color="#0284C7", lw=1.4 if aggregation != "annual" else 1.8,
            marker="o" if aggregation == "annual" else None, ms=3, label=f"{aggregation.capitalize()} mean")
    if result.get("status") != "insufficient":
        t = fractional_year(s.index)
        ok = ~np.isnan(s.values)
        tmed, ymed = np.nanmedian(t[ok]), np.nanmedian(s.values)
        ax.plot(s.index, ymed + result["sen_slope"] * (t - tmed), "--", color="#DC2626" if result["sen_slope"] > 0 else "#2563EB",
                lw=1.8, label=f"Sen's slope {result['sen_slope_per_decade']:+.3g} {units}/decade")
        lo, hi = ymed + result["sen_ci_low"] * (t - tmed), ymed + result["sen_ci_high"] * (t - tmed)
        if not (np.isnan(lo).any() or np.isnan(hi).any()):
            ax.fill_between(s.index, lo, hi, color="#94A3B8", alpha=.25, label=f"{result['ci_level']}% CI")
    ax.set_title(f"{label} — {region}", fontsize=11, loc="left")
    ax.set_ylabel(units)
    ax.grid(alpha=.25)
    ax.legend(fontsize=8, frameon=False)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def build_pdf(title: str, author: str, df: pd.DataFrame, meta: dict, result: dict, aggregation: str,
              notes: str = "", comparison: dict | None = None) -> bytes:
    """Create the PDF report and return its bytes."""
    label, units, region = meta["label"], meta["units"], meta["region"]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm,
                            bottomMargin=1.8 * cm, title=title, author=author or "EarthScope AI")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=NAVY, fontSize=20, spaceAfter=4)
    sub = ParagraphStyle("sub", parent=ss["Normal"], alignment=TA_CENTER, textColor=colors.grey, fontSize=9)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=BLUE, fontSize=13, spaceBefore=12, spaceAfter=4)
    body = ParagraphStyle("body", parent=ss["BodyText"], fontSize=9.5, leading=13.5)
    small = ParagraphStyle("small", parent=body, fontSize=8, textColor=colors.grey)

    def table(rows, widths=(6.2 * cm, 10.3 * cm)):
        t = Table([[Paragraph(str(a), body), Paragraph(str(b), body)] for a, b in rows], colWidths=widths)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF6FB")),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CBD5E1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        return t

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    story = [Paragraph(title, h1),
             Paragraph(f"EarthScope AI — Discover. Analyse. Understand. Protect.<br/>Generated {now}"
                       + (f" · Prepared by {author}" if author else ""), sub), Spacer(1, 10)]

    story += [Paragraph("1. Study definition", h2), table([
        ("Variable", f"{label} ({units})"),
        ("Region", f"{region} (lat {meta['lat']:.2f}, lon {meta['lon']:.2f})"),
        ("Spatial sampling", "Representative grid cell" if meta["sampling"] == "point"
         else f"Mean of {meta['n_points']} grid cells across the region bounding box"),
        ("Analysis period", f"{meta['start']}–{meta['end']} ({aggregation} aggregation)"),
        ("NASA data source", meta["source"]),
        ("Provider / access", f"{meta['provider']} · retrieved {meta['retrieved']}"),
    ])]

    story += [Paragraph("2. Result", h2),
              Paragraph(f"<b>{STATUS_LABEL[result['status']]}</b>", body),
              Paragraph(_md(interpret(result, label, units, region)), body), Spacer(1, 6)]
    story.append(Image(io.BytesIO(chart_png(df, result, label, units, region, aggregation)), width=16.5 * cm, height=7.4 * cm))
    story.append(Paragraph("Figure 1. Observed series with Sen's slope and its confidence interval.", small))

    story += [Paragraph("3. Statistical results", h2), table(significance_table(result))]
    if result["status"] != "insufficient":
        story += [Spacer(1, 6), Paragraph(_md(practical_importance(result)["text"]), body)]

    if comparison:
        story += [Paragraph("Regional comparison", h2), table(comparison["rows"]),
                  Spacer(1, 4), Paragraph(_md(comparison["text"]), body)]

    story += [PageBreak(), Paragraph("4. Methodology", h2), Paragraph(
        "Monthly values were retrieved from the NASA service listed above. Annual means require at least 10 valid "
        "months. Trend detection uses the <b>Mann-Kendall</b> rank test (H0: no monotonic trend). For monthly data the "
        "<b>Seasonal Kendall</b> form removes the annual cycle; for annual data the <b>Hamed &amp; Rao (1998)</b> variance "
        "correction is applied when lag-1 autocorrelation of the detrended series is significant. The rate of change "
        "is <b>Sen's slope</b> (median of pairwise slopes) with a distribution-free confidence interval "
        "(Gilbert, 1987). An ordinary least-squares slope is given for comparison only.", body)]

    story += [Paragraph("5. Data quality", h2), table([
        ("Sample size", f"{result['n_valid']} valid of {result['n_total']} {aggregation} values"),
        ("Missing data", f"{result['missing_pct']}%"),
        ("Lag-1 autocorrelation", f"{result.get('lag1_autocorr', 'n/a')}"),
        ("Data type", "Reanalysis / satellite-derived estimate; not an in-situ measurement"),
    ])]

    story += [Paragraph("6. Limitations", h2), Paragraph(
        "• Values represent a ~50 km reanalysis grid cell (or a 3×3 sample of cells), or a single 250 m MODIS pixel "
        "for NDVI — not a true area average.<br/>"
        "• The Mann-Kendall test detects monotonic trends only; step changes and cycles need other methods.<br/>"
        "• A non-significant result is <b>not</b> evidence of no change.<br/>"
        "• Statistical significance does not by itself establish practical or environmental importance.<br/>"
        "• Trends do not identify causes; attribution requires additional data and modelling.<br/>"
        "• Recent months may be near-real-time data that are later revised.", body)]

    if notes.strip():
        story += [Paragraph("7. Author notes", h2), Paragraph(_md(notes), body)]

    ann = annual_table(df)
    rows = [["Year", f"Annual mean ({units})", "Change vs previous", "Anomaly"]] + [
        [int(r.year), "" if pd.isna(r.annual_mean) else f"{r.annual_mean:.3f}",
         "" if pd.isna(r.change_vs_prev) else f"{r.change_vs_prev:+.3f}",
         "" if pd.isna(r.anomaly) else f"{r.anomaly:+.3f}"] for r in ann.itertuples()]
    t = Table(rows, repeatRows=1, colWidths=[2.5 * cm, 5 * cm, 4.5 * cm, 4.5 * cm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                           ("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
                           ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F1F5F9")])]))
    b = ann.attrs.get("baseline")
    story += [Paragraph("Appendix A. Annual values", h2), t,
              Paragraph(f"Anomaly relative to the {b[0]}–{b[1]} mean." if b else "", small),
              Spacer(1, 10), Paragraph(
                  "References: Mann (1945) Econometrica 13; Kendall (1975) Rank Correlation Methods; Sen (1968) JASA 63; "
                  "Hirsch, Slack &amp; Smith (1982) Water Resour. Res. 18; Hamed &amp; Rao (1998) J. Hydrol. 204; "
                  "Gilbert (1987) Statistical Methods for Environmental Pollution Monitoring. "
                  "Data: NASA POWER (power.larc.nasa.gov), NASA GISS, ORNL DAAC MODIS web service.", small)]

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.grey)
        canvas.drawString(2 * cm, 1 * cm, "EarthScope AI · NASA Space Apps Challenge · Data courtesy of NASA")
        canvas.drawRightString(A4[0] - 2 * cm, 1 * cm, f"Page {d.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def build_csv(df: pd.DataFrame, meta: dict) -> bytes:
    out = df.reset_index()
    out.columns = ["date", f"{meta['variable']}_{meta['units']}"]
    header = (f"# EarthScope AI export | {meta['label']} | {meta['region']} | {meta['source']} | "
              f"retrieved {meta['retrieved']}\n")
    return (header + out.to_csv(index=False)).encode("utf-8")


def build_excel(df: pd.DataFrame, meta: dict, result: dict) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        monthly = df.reset_index()
        monthly.columns = ["date", "value"]
        monthly["date"] = monthly["date"].dt.date
        monthly.to_excel(xw, sheet_name="Monthly data", index=False)
        annual_table(df).to_excel(xw, sheet_name="Annual", index=False)
        pd.DataFrame(significance_table(result), columns=["Statistic", "Value"]).to_excel(
            xw, sheet_name="Trend results", index=False)
        pd.DataFrame([(k, str(v)) for k, v in meta.items()], columns=["Field", "Value"]).to_excel(
            xw, sheet_name="Metadata", index=False)
    return buf.getvalue()
