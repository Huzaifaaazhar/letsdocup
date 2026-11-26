"""Batch History: reopen or delete previous batches."""
from __future__ import annotations

import streamlit as st

from bl_manager import db

from .common import go


def render() -> None:
    st.title("Batch History")
    st.caption("Each batch keeps its uploaded PDFs, reconstructed BLs, extracted data and corrections on this "
               "computer until you delete it. Deleting removes the database records AND all stored PDF files "
               "for that batch.")
    batches = db.list_batches()
    if not batches:
        st.info("No batches yet.")
        return
    for b in batches:
        with st.container(border=True):
            c1, c2, c3 = st.columns([4, 1, 1.4])
            c1.markdown(f"**{b['name']}** · #{b['id']}  \n"
                        f"<span class='blm-muted'>{b['created_at'].replace('T', ' ')} · {b['total_pages']} pages · "
                        f"{b['doc_count']} documents · {b['status']}</span>", unsafe_allow_html=True)
            c2.button("Open", key=f"open_b{b['id']}", on_click=go, args=("Dashboard",),
                      kwargs={"batch_id": b["id"], "doc_id": None}, width="stretch",
                      type="primary" if st.session_state.get("batch_id") == b["id"] else "secondary")
            with c3:
                confirm = st.checkbox("Confirm delete", key=f"cdel_{b['id']}")
                if st.button("Delete batch + files", key=f"del_{b['id']}", disabled=not confirm, width="stretch"):
                    db.delete_batch(b["id"])
                    if st.session_state.get("batch_id") == b["id"]:
                        st.session_state["batch_id"] = None
                        st.session_state["doc_id"] = None
                    st.rerun()
