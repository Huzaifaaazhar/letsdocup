"""Folder navigation, BL list with search, folder downloads."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from bl_manager import db, exports
from bl_manager.constants import FOLDER_LABELS, FOLDERS
from bl_manager.extraction import display_value
from bl_manager.normalize import normalize_container

from . import bl_view
from .common import counts, require_batch

ALL = "ALL"


def _matches(d: dict, q: str) -> bool:
    if not q:
        return True
    ql = q.strip().lower()
    qc = normalize_container(q)
    if ql in (d["doc_key"] or "").lower():
        return True
    if ql in display_value(d["fields"].get("consignee_name")).lower():
        return True
    conts = [c["container"] for c in d.get("containers") or []]
    return any(qc and qc in c for c in conts)


def render() -> None:
    b = require_batch()
    if not b:
        return
    bid = b["id"]
    docs = db.list_documents(bid)

    if st.session_state.get("doc_id"):
        d = db.get_document(st.session_state["doc_id"])
        if d and d["batch_id"] == bid:
            bl_view.render(d, docs)
            return
        st.session_state["doc_id"] = None

    st.title("BL Folders")
    c = counts(docs)
    options = FOLDERS + [ALL]
    labels = {**{f: f"{FOLDER_LABELS[f]} ({c[f]})" for f in FOLDERS}, ALL: f"All ({len(docs)})"}
    if st.session_state.get("folder") not in options:
        st.session_state["folder"] = FOLDERS[0]
    folder = st.radio("Folder", options, format_func=lambda f: labels[f], horizontal=True, key="folder",
                      label_visibility="collapsed")

    q = st.text_input("Search by BL number, consignee name or container number", key="search",
                      placeholder="e.g. ONEYSHAB123, LOGISTICS, TCLU1234567")
    shown = [d for d in docs if (folder == ALL or d["current_class"] == folder) and _matches(d, q)]

    left, right = st.columns([3, 1])
    with left:
        st.caption(f"{len(shown)} document(s) shown. Click a row to open the BL.")
    with right:
        if folder != ALL:
            n = c[folder]
            if st.button(f"Prepare {FOLDER_LABELS[folder]} downloads", disabled=n == 0, width="stretch"):
                st.session_state["folder_dl"] = (bid, folder, exports.folder_zip(docs, folder),
                                             exports.folder_combined_pdf(docs, folder))
            dl = st.session_state.get("folder_dl")
            if dl and dl[0] == bid and dl[1] == folder:
                st.download_button(f"⬇ {FOLDER_LABELS[folder]} as ZIP", dl[2],
                                   file_name=f"{FOLDER_LABELS[folder].replace(' ', '_')}.zip",
                                   mime="application/zip", width="stretch")
                st.download_button(f"⬇ {FOLDER_LABELS[folder]} as one combined PDF", dl[3],
                                   file_name=f"{FOLDER_LABELS[folder].replace(' ', '_')}_combined.pdf",
                                   mime="application/pdf", width="stretch")

    if not shown:
        st.info("No documents in this view.")
        return

    rows = []
    for d in shown:
        consol = d.get("consol") or {}
        rows.append({
            "BL number": d["doc_key"],
            "Folder": FOLDER_LABELS[d["current_class"]],
            "Consignee": display_value(d["fields"].get("consignee_name")).split("\n")[0],
            "Containers": ", ".join(c["container"] for c in d.get("containers") or []),
            "Pages": d["page_count"],
            "Shared with": ", ".join(sorted({b for l in (consol.get("links", []) if isinstance(consol, dict) else [])
                                             for b in l["shared_with"]})),
            "Why": (f"Moved manually (automated result: {FOLDER_LABELS[d['auto_class']]})"
                    + (f" — {d['change_note']}" if d.get("change_note") else "")
                    if d["manually_changed"] else
                    (d["review_reasons"][0]["detected"] if d["review_reasons"] else " ".join(d["auto_reasons"])))[:160],
            "Manual change": "Yes" if d["manually_changed"] else "",
        })
    ev = st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                      on_select="rerun", selection_mode="single-row", key=f"tbl_{folder}_{q}")
    sel = ev.selection.rows if ev and ev.selection else []
    if sel:
        st.session_state["doc_id"] = shown[sel[0]]["id"]
        st.session_state["doc_list"] = [d["id"] for d in shown]
        st.rerun()
