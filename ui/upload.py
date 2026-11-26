"""Upload & Process screen (Option A: combined PDF, Option B: individual PDFs)."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from bl_manager import db
from bl_manager.pdf_reader import ocr_available
from bl_manager.pipeline import process_batch

from .common import go


def _run(files, mode, name):
    bar = st.progress(0.0, text="Starting…")

    def progress(frac, msg):
        bar.progress(min(max(frac, 0.0), 1.0), text=msg)

    try:
        bid = process_batch(name, files, mode, progress)
    except Exception as exc:  # pragma: no cover - UI safety net
        st.error(f"Processing failed: {exc}")
        return
    st.session_state["batch_id"] = bid
    st.session_state["doc_id"] = None
    b = db.get_batch(bid)
    rep = b["report"]
    st.success(
        f"Batch processed: **{rep['total_pages']}** pages read, **{rep['documents']}** documents reconstructed "
        f"(**{rep['complete_bls']}** complete BLs without reconstruction issues), "
        f"**{rep['auto_counts'].get('MANUAL_REVIEW', 0)}** in Manual Review. Took {rep['seconds']} s."
    )
    if rep.get("errors"):
        st.warning(f"{rep['errors']} processing error(s) were recorded — see the Dashboard processing report.")
    st.button("Open Dashboard →", type="primary", on_click=go, args=("Dashboard",))


def render() -> None:
    st.title("Upload & Process")
    st.caption("Documents are processed on this computer only. Nothing is uploaded to the internet.")

    default_name = f"Batch {datetime.now():%Y-%m-%d %H:%M}"
    name = st.text_input("Batch name", value=default_name, help="Used to find this batch again later.")

    ok, msg = ocr_available() if db.get_settings().get("ocr_enabled", True) else (False, "OCR disabled in Settings")
    if not ok:
        st.warning(f"OCR fallback for scanned pages is not available: {msg}. Text-based PDFs still work.")

    tab_a, tab_b = st.tabs(["Option A — One combined PDF", "Option B — Individual BL PDFs"])
    with tab_a:
        st.markdown("Upload **one PDF containing many BLs** one after another. The application reads every "
                    "page, identifies each BL by its complete BL number and page numbering, and rebuilds each "
                    "BL as its own PDF.")
        f = st.file_uploader("Combined PDF", type=["pdf"], accept_multiple_files=False, key="up_combined")
        if st.button("Process combined PDF", type="primary", disabled=f is None, key="btn_combined"):
            _run([(f.name, f.getvalue())], "combined", name)
    with tab_b:
        st.markdown("Select **several BL PDF files at once** (hold Ctrl to select multiple files). They are "
                    "processed by exactly the same engine as Option A.")
        fs = st.file_uploader("Individual BL PDFs", type=["pdf"], accept_multiple_files=True, key="up_individual")
        if st.button("Process individual PDFs", type="primary", disabled=not fs, key="btn_individual"):
            _run([(x.name, x.getvalue()) for x in fs], "individual", name)
