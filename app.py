"""
EarthScope AI — Discover. Analyse. Understand. Protect.

Streamlit entry point: sets the theme, builds the sidebar navigation (12 pages) and the
persistent AI assistant panel, then runs the selected page.

Run with:   streamlit run app.py
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))   # make project packages importable

from ai import assistant                       # noqa: E402
from backend import database as db             # noqa: E402
from core import state                         # noqa: E402
from core.config import APP_NAME, TAGLINE      # noqa: E402
from visualization.animations import inject_css  # noqa: E402

st.set_page_config(page_title=f"{APP_NAME} — {TAGLINE}", page_icon="🌍", layout="wide",
                   initial_sidebar_state="expanded")


@st.cache_resource
def _init_database() -> bool:
    db.init_db()
    return True


_init_database()
state.init_state()
inject_css()

# ---------------------------------------------------------------- navigation
PAGES = [
    st.Page("views/overview.py", title="Overview", icon="🛰️", default=True),
    st.Page("views/earth_explorer.py", title="Earth Explorer", icon="🌍"),
    st.Page("views/data_explorer.py", title="Data Explorer", icon="🗂️"),
    st.Page("views/trend_analysis.py", title="Trend Analysis", icon="📈"),
    st.Page("views/regional_comparison.py", title="Regional Comparison", icon="🗺️"),
    st.Page("views/opposite_trend.py", title="Opposite Trend Detector", icon="🔀"),
    st.Page("views/significance.py", title="Significance Testing", icon="🧪"),
    st.Page("views/live_monitoring.py", title="Live Earth Monitoring", icon="🔥"),
    st.Page("views/space_tracker.py", title="Space & Orbit Tracker", icon="☄️"),
    st.Page("views/ai_assistant.py", title="AI Science Assistant", icon="🤖"),
    st.Page("views/reports.py", title="Reports", icon="📄"),
    st.Page("views/settings.py", title="Settings", icon="⚙️"),
]

with st.sidebar:
    st.markdown(f"""<div class="es-brand"><div class="logo"></div><div>
        <div class="name">{APP_NAME}</div><div class="tag">{TAGLINE}</div></div></div>""", unsafe_allow_html=True)

page = st.navigation(PAGES, position="sidebar")
state.set_page(page.title)


# ---------------------------------------------------------------- persistent assistant panel
def sidebar_assistant() -> None:
    """Compact chat available on every page; shares history with the full AI Science Assistant page."""
    with st.sidebar:
        with st.container(key="es_sidebar_chat"):
            with st.expander("💬 EarthScope AI Assistant", expanded=False):
                st.caption(f"{assistant.mode_label()} · knows the current page and results")
                for m in st.session_state["chat"][-4:]:
                    text = m["content"] if len(m["content"]) < 600 else m["content"][:600] + "…"
                    if m["role"] == "user":
                        st.markdown(f'<div class="es-mini-msg user">{html.escape(text)}</div>', unsafe_allow_html=True)
                    else:
                        st.container(border=True).markdown(text)
                with st.form("sidebar_chat_form", clear_on_submit=True, border=False):
                    q = st.text_input("Ask about this page", placeholder="e.g. Explain this graph",
                                      label_visibility="collapsed")
                    sent = st.form_submit_button("Ask", width="stretch")
                if sent and q.strip():
                    st.session_state["pending_sidebar_q"] = q.strip()
                    st.rerun()
                st.page_link("views/ai_assistant.py", label="Open full assistant", icon="🤖")


def answer_pending() -> None:
    """Answer a sidebar question AFTER the page has run, so the page's fresh results are in context."""
    q = st.session_state.pop("pending_sidebar_q", None)
    if not q:
        return
    chat = st.session_state["chat"]
    chat.append({"role": "user", "content": q})
    with st.sidebar:
        with st.spinner("EarthScope AI is thinking…"):
            reply = "".join(assistant.stream_reply(chat, st.session_state["ctx"]))
    chat.append({"role": "assistant", "content": reply})
    try:
        db.save_chat(st.session_state["session_id"], "user", q, page.title)
        db.save_chat(st.session_state["session_id"], "assistant", reply, page.title)
    except Exception:
        pass
    st.rerun()


sidebar_assistant()
page.run()
answer_pending()
