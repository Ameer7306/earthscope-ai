"""AI Science Assistant: context-aware chat about the data, results and methods in the app."""
from __future__ import annotations

import streamlit as st

from ai import assistant
from ai.context import build_context
from ai.prompts import SUGGESTED_QUESTIONS
from backend import database as db
from visualization.animations import badges, hero, typing_indicator

hero("EarthScope AI Assistant", "Ask about the charts, statistics and detections you have explored. "
                                "Answers use the application's real results — never invented numbers.")

ctx = st.session_state["ctx"]
chat = st.session_state["chat"]
live = assistant.is_live()

h1, h2 = st.columns([3, 1])
with h1:
    badges(("live", assistant.mode_label()) if live else ("demo", assistant.mode_label()),
           ("nasa", f"{sum(k in ctx for k in ('trend', 'opposite', 'comparison', 'significance', 'live'))} result sets in context"))
with h2:
    if st.button("🗑️ Clear conversation", width="stretch", disabled=not chat):
        st.session_state["chat"] = []
        st.rerun()

if not live:
    st.info("**DEMO MODE** — no `OPENAI_API_KEY` is configured, so a built-in offline explainer answers using the "
            "results computed in this app. Add your key to `.env` (see Settings) for full conversational answers.")

with st.expander("What the assistant can see right now"):
    st.code(build_context(ctx), language="text")

# ---------------------------------------------------------------- history
for i, m in enumerate(chat):
    with st.chat_message(m["role"], avatar="🧑‍🔬" if m["role"] == "user" else "🌍"):
        st.markdown(m["content"])
        if m["role"] == "assistant":
            with st.popover("📋 Copy response"):
                st.caption("Use the copy icon at the top-right of the box.")
                st.code(m["content"], language="markdown")

# ---------------------------------------------------------------- suggestions
st.markdown("###### Suggested questions")
cols = st.columns(4)
picked = None
for i, q in enumerate(SUGGESTED_QUESTIONS):
    if cols[i % 4].button(q, key=f"sugg_{i}", width="stretch"):
        picked = q

typed = st.chat_input("Ask EarthScope AI about your data…")
question = typed or picked

if question:
    chat.append({"role": "user", "content": question})
    with st.chat_message("user", avatar="🧑‍🔬"):
        st.markdown(question)
    with st.chat_message("assistant", avatar="🌍"):
        slot = st.empty()
        slot.markdown(typing_indicator(), unsafe_allow_html=True)       # typing indicator until first token
        reply, shown = "", False
        try:
            for chunk in assistant.stream_reply(chat, ctx):
                reply += chunk
                slot.markdown(reply + "▌")
            slot.markdown(reply)
        except Exception as e:
            reply = f"⚠️ Sorry — the assistant failed unexpectedly ({type(e).__name__}: {e})."
            slot.error(reply)
    chat.append({"role": "assistant", "content": reply})
    try:
        db.save_chat(st.session_state["session_id"], "user", question, "AI Science Assistant")
        db.save_chat(st.session_state["session_id"], "assistant", reply, "AI Science Assistant")
    except Exception:
        pass
    st.rerun()

if not chat:
    st.caption("Tip: run a Trend Analysis or the Opposite Trend Detector first — the assistant then explains those "
               "exact results. The chat panel in the sidebar works from every page.")
