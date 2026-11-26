"""Dashboard: counts, folders, processing report, batch downloads, bulk copy."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from bl_manager import db, exports
from bl_manager.constants import FOLDER_LABELS, FOLDERS
from bl_manager.pipeline import reclassify_batch

from .common import FOLDER_COLORS, clear_prepared_downloads, counts, go, require_batch


def render() -> None:
    b = require_batch()
    if not b:
        return
    bid = b["id"]
    docs = db.list_documents(bid)
    rep = b["report"]
    c = counts(docs)

    st.title("Dashboard")
    files = db.list_source_files(bid)
    st.caption(
        f"Batch **{b['name']}** · uploaded {b['created_at'].replace('T', ' ')} · "
        f"{'combined PDF' if b['mode'] == 'combined' else 'individual PDFs'} · "
        f"{len(files)} file(s): {', '.join(f['filename'] for f in files)}"
    )

    m = st.columns(7)
    m[0].metric("Total BLs", len(docs))
    m[1].metric("MBL", c["MBL"])
    m[2].metric("HBL", c["HBL"])
    m[3].metric("CONSOL", c["CONSOL"])
    m[4].metric("EPZ", c["EPZ"])
    m[5].metric("Manual Review", c["MANUAL_REVIEW"])
    m[6].metric("Pages processed", b["total_pages"])
    manual = sum(1 for d in docs if d["manually_changed"])
    if manual:
        st.caption(f"{manual} BL(s) were reclassified manually. Counts show the current folders.")

    st.subheader("Folders")
    cols = st.columns(5)
    for col, f in zip(cols, FOLDERS):
        bg, fg = FOLDER_COLORS[f]
        with col:
            st.markdown(
                f'<div class="blm-folder-card" style="background:{bg}">'
                f'<div style="color:{fg};font-weight:600">{FOLDER_LABELS[f]}</div>'
                f'<div class="blm-folder-count" style="color:{fg}">{c[f]}</div></div>',
                unsafe_allow_html=True,
            )
            st.button("Open", key=f"open_{f}", on_click=go, args=("BL Folders",),
                      kwargs={"folder": f, "doc_id": None}, width="stretch")
    st.caption(f"Total across all folders: **{sum(c.values())}** BLs/documents.")

    # ---------------- downloads & copy ----------------
    st.subheader("Export the whole batch")
    d1, d2, d3 = st.columns(3)
    with d1:
        if st.button("Prepare complete ZIP (all folders)", width="stretch"):
            st.session_state["full_zip"] = (bid, exports.full_zip(docs))
        z = st.session_state.get("full_zip")
        if z and z[0] == bid:
            st.download_button("⬇ Download BL_Manager_Results.zip", z[1], file_name="BL_Manager_Results.zip",
                               mime="application/zip", type="primary", width="stretch")
            st.caption("Prepared with the folder assignment at the time you clicked 'Prepare'.")
    with d2:
        st.download_button("⬇ Extraction summary (Excel)", exports.to_excel(docs) if docs else b"",
                           file_name=f"BL_summary_batch_{bid}.xlsx", disabled=not docs,
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           width="stretch")
    with d3:
        if st.button("Re-run classification", width="stretch",
                     help="Re-applies the current Settings and Freight Forwarder list to this batch, including the "
                          "batch-wide container comparison. Manual classifications are kept."):
            reclassify_batch(bid)
            clear_prepared_downloads()
            st.success("Classification re-run for the whole batch.")
            st.rerun()

    with st.expander("Copy extracted information for ALL BLs (tab-separated, paste straight into Excel)"):
        st.caption("Click the copy icon at the top-right of the box, then paste into cell A1 in Excel.")
        st.code(exports.to_tsv(docs), language=None)

    # ---------------- processing report ----------------
    st.subheader("Processing report")
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Pages read", rep.get("total_pages", 0))
    r2.metric("Pages read by OCR", rep.get("pages_ocr", 0))
    r3.metric("Complete BLs (no reconstruction issue)", rep.get("complete_bls", 0))
    r4.metric("Unidentified page groups", rep.get("unidentified_docs", 0))

    cs = rep.get("consol_stats") or {}
    st.markdown(
        f"**Container comparison (CONSOL check) — executed across the entire batch.** "
        f"{cs.get('documents_compared', 0)} documents compared · {cs.get('unique_containers', 0)} unique containers · "
        f"**{cs.get('shared_containers', 0)}** container(s) shared by different BL numbers · "
        f"**{cs.get('consol_bls', 0)}** BL(s) affected in {cs.get('groups', 0)} group(s)."
    )
    groups = rep.get("consol_groups") or []
    if groups:
        st.dataframe(
            pd.DataFrame([{"Group": g["group_id"], "Shared container(s)": ", ".join(g["containers"]),
                           "Linked BLs": ", ".join(g["bls"]), "BL count": len(g["bls"])} for g in groups]),
            hide_index=True, width="stretch",
        )
    near = rep.get("near_matches") or []
    if near:
        st.warning("Similar container numbers (one character different) were found on different BLs. They were "
                   "**not** treated as the same container. Check them for misprints or misreads:\n\n"
                   + "\n".join(f"- {n['a']} ({', '.join(n['a_bls'])}) vs {n['b']} ({', '.join(n['b_bls'])})" for n in near))

    errs = db.list_errors(bid)
    bad_files = [f for f in files if f.get("error")]
    if errs or bad_files:
        st.error(f"{len(errs)} processing error(s). The rest of the batch was processed normally.")
        st.dataframe(pd.DataFrame([{"File": e["file_name"], "Page": (e["page_index"] + 1) if e["page_index"] is not None else "",
                                    "Stage": e["stage"], "Message": e["message"].split("\n")[0]} for e in errs]),
                     hide_index=True, width="stretch")

    with st.expander("Page-by-page reconstruction detail"):
        pages = db.list_pages(bid)
        doc_keys = {d["id"]: d["doc_key"] for d in docs}
        st.dataframe(pd.DataFrame([{
            "Batch page": p["global_index"] + 1,
            "File": p["filename"],
            "File page": p["page_index"] + 1,
            "BL number read": p["bl_number"] or "— not found —",
            "Printed page": f"{p['page_no']} of {p['page_total']}" if p["page_no"] else "— not found —",
            "Read by": p["text_source"],
            "Assigned to": doc_keys.get(p["doc_id"], ""),
            "Issues": "; ".join(p["issues"]),
        } for p in pages]), hide_index=True, width="stretch")

    with st.expander("Activity log (classification changes, edits)"):
        logs = db.list_log(bid)
        if logs:
            st.dataframe(pd.DataFrame([{"Time": l["ts"].replace("T", " "), "Action": l["action"], "Detail": l["detail"]}
                                       for l in logs]), hide_index=True, width="stretch")
        else:
            st.caption("No activity yet.")
