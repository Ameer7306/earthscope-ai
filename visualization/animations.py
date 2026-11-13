"""
UI building blocks with CSS animations: hero headers, animated KPI cards with counters,
status badges, loaders and result cards. All HTML is static (no user input is injected
unescaped) and animations honour the reduced-motion preference and the Settings toggle.
"""
from __future__ import annotations

import html
from contextlib import contextmanager
from pathlib import Path

import streamlit as st

from core.config import COLORS, ROOT


@st.cache_data(show_spinner=False)
def _css() -> str:
    return (Path(ROOT) / "assets" / "styles.css").read_text(encoding="utf-8")


def inject_css() -> None:
    """Load the theme. When animations are switched off in Settings, neutralise all motion."""
    css = _css()
    if not st.session_state.get("animations", True):
        css += "\n*, *::before, *::after { animation: none !important; transition: none !important; }"
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def hero(title: str, subtitle: str = "", eyebrow: str = "EarthScope AI") -> None:
    st.markdown(
        f"""<div class="es-hero"><div class="eyebrow">{html.escape(eyebrow)}</div>
        <h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p></div>""", unsafe_allow_html=True)


def badge(kind: str, text: str) -> str:
    """kind: live | demo | nasa | stale | final"""
    return f'<span class="badge {kind}">{html.escape(text)}</span>'


def badges(*items: tuple[str, str]) -> None:
    st.markdown(" ".join(badge(k, t) for k, t in items), unsafe_allow_html=True)


def kpi_card(label: str, value, sub: str = "", icon: str = "", delay: float = 0.0,
             accent: str = COLORS["primary"]) -> None:
    """Animated KPI card. Integer values count up from zero; other values fade in."""
    if isinstance(value, int) and not isinstance(value, bool):
        val_html = f'<span class="counter" style="--n:{value}"></span>'
    else:
        val_html = html.escape(str(value))
    st.markdown(
        f"""<div class="kpi" style="animation-delay:{delay:.2f}s; --accent:{accent}">
        <div class="icon">{icon}</div><div class="k">{html.escape(label)}</div>
        <div class="v">{val_html}</div><div class="s">{html.escape(sub)}</div></div>""",
        unsafe_allow_html=True)


def card(title: str, body_html: str, delay: float = 0.0) -> None:
    st.markdown(f'<div class="es-card" style="animation-delay:{delay:.2f}s"><h4>{html.escape(title)}</h4>'
                f'<div class="muted">{body_html}</div></div>', unsafe_allow_html=True)


def result_card(status: str, title: str, big: str, detail: str) -> None:
    """status: increasing | decreasing | no_significant_trend | insufficient"""
    cls = {"increasing": "up", "decreasing": "down", "no_significant_trend": "flat"}.get(status, "insufficient")
    arrow = {"increasing": "▲", "decreasing": "▼", "no_significant_trend": "◆"}.get(status, "⚠")
    color = {"up": COLORS["positive"], "down": COLORS["negative"], "flat": COLORS["muted"]}.get(cls, COLORS["warning"])
    st.markdown(
        f"""<div class="es-result {cls}"><div class="title"><span style="color:{color}">{arrow}</span>
        {html.escape(title)}</div><div class="big" style="color:{color}">{html.escape(big)}</div>
        <div style="color:{COLORS['muted']};font-size:.88rem">{html.escape(detail)}</div></div>""",
        unsafe_allow_html=True)


def alert_row(title: str, meta: str, color: str = COLORS["primary"], delay: float = 0.0) -> None:
    st.markdown(
        f"""<div class="es-alert" style="animation-delay:{delay:.2f}s"><div class="dot" style="background:{color};
        box-shadow:0 0 10px {color}"></div><div><div class="t">{html.escape(title)}</div>
        <div class="m">{html.escape(meta)}</div></div></div>""", unsafe_allow_html=True)


@contextmanager
def loading(message: str = "Contacting NASA data services…"):
    """Animated loading indicator shown while a block runs."""
    slot = st.empty()
    slot.markdown(f'<div class="es-loader"><div class="orb"></div><div>{html.escape(message)}</div></div>',
                  unsafe_allow_html=True)
    try:
        yield
    finally:
        slot.empty()


def typing_indicator() -> str:
    return '<div class="typing"><span></span><span></span><span></span></div>'


CATEGORY_COLORS = {
    "Wildfires": "#F97316", "Severe Storms": "#38BDF8", "Volcanoes": "#EF4444", "Sea and Lake Ice": "#A5F3FC",
    "Floods": "#3B82F6", "Drought": "#EAB308", "Dust and Haze": "#D6B88A", "Earthquakes": "#A855F7",
    "Landslides": "#92400E", "Fireball (meteor)": "#FBBF24", "Active fire": "#F97316",
    "Temperature Extremes": "#F43F5E", "Water Color": "#14B8A6", "Snow": "#E2E8F0", "Manmade": "#94A3B8",
}


def category_color(cat: str) -> str:
    return CATEGORY_COLORS.get(cat, COLORS["primary"])
