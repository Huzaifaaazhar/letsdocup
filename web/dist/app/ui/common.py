"""Shared UI helpers: navigation, badges, counts, styling."""
from __future__ import annotations

import html

import streamlit as st

from bl_manager import db
from bl_manager.constants import FOLDER_LABELS, FOLDERS, MANUAL_REVIEW

PAGES = ["Upload & Process", "Dashboard", "BL Folders", "Freight Forwarders", "Settings", "Batch History"]

FOLDER_COLORS = {
    "MBL": ("#E8EEF9", "#1F3B73"),
    "HBL": ("#E6F4EA", "#1E6B34"),
    "CONSOL": ("#F1E9FA", "#5B2A86"),
    "EPZ": ("#E3F4F6", "#0E5E6B"),
    "MANUAL_REVIEW": ("#FDF1E1", "#8A4B00"),
}

CSS = """
<style>
.block-container {padding-top: 1.6rem; max-width: 1500px;}
.blm-badge {display:inline-block; padding:2px 10px; border-radius:12px; font-size:0.82rem;
            font-weight:600; letter-spacing:.2px; margin-right:6px;}
.blm-status {display:inline-block; padding:1px 8px; border-radius:10px; font-size:0.72rem; font-weight:600;}
.blm-st-extracted {background:#EEF1F6; color:#44516B;}
.blm-st-verified {background:#E6F4EA; color:#1E6B34;}
.blm-st-corrected {background:#E8EEF9; color:#1F3B73;}
.blm-st-missing {background:#FDECEC; color:#9B1C1C;}
.blm-field-label {font-size:0.80rem; color:#5A6478; font-weight:600; text-transform:uppercase;
                  letter-spacing:.4px; margin-bottom:-6px;}
.blm-card {border:1px solid #E1E5EE; border-radius:8px; padding:14px 16px; margin-bottom:10px; background:#FFFFFF;}
.blm-folder-card {border:1px solid #E1E5EE; border-radius:8px; padding:12px 14px; text-align:left;}
.blm-folder-count {font-size:1.9rem; font-weight:700; line-height:1.1;}
.blm-muted {color:#6B7489; font-size:0.85rem;}
.blm-viewer {height: 900px; overflow: auto; border:1px solid #E1E5EE; border-radius:6px; background:#F3F5F9;
             padding: 10px;}
.blm-viewer img {display:block; margin: 0 auto 12px auto; box-shadow: 0 1px 4px rgba(0,0,0,.18); background:#fff;}
div[data-testid="stMetricValue"] {font-size: 1.8rem;}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def go(page: str, **state) -> None:
    """Navigate (use as an on_click callback)."""
    st.session_state["nav"] = page
    for k, v in state.items():
        st.session_state[k] = v


def clear_prepared_downloads() -> None:
    """Prepared ZIP/PDF downloads become stale after any classification change."""
    for k in ("full_zip", "folder_dl"):
        st.session_state.pop(k, None)


def badge(folder: str) -> str:
    bg, fg = FOLDER_COLORS.get(folder, ("#EEE", "#333"))
    return f'<span class="blm-badge" style="background:{bg};color:{fg}">{html.escape(FOLDER_LABELS.get(folder, folder))}</span>'


def status_badge(f: dict | None) -> str:
    f = f or {}
    if f.get("user_value"):
        cls, txt = "corrected", "Corrected by user"
    elif f.get("status") == "not_present":
        cls, txt = "extracted", "Not present"
    elif not f.get("values"):
        cls, txt = "missing", "Not extracted — requires verification"
    elif f.get("verified"):
        cls, txt = "verified", "Verified by user"
    else:
        cls, txt = "extracted", "Extracted — not yet verified" + (" (OCR)" if f.get("ocr") else "")
    return f'<span class="blm-status blm-st-{cls}">{txt}</span>'


def current_batch_id() -> int | None:
    return st.session_state.get("batch_id")


def counts(docs: list[dict]) -> dict:
    c = {f: 0 for f in FOLDERS}
    for d in docs:
        c[d["current_class"] or MANUAL_REVIEW] += 1
    return c


def require_batch() -> dict | None:
    bid = current_batch_id()
    b = db.get_batch(bid) if bid else None
    if not b:
        st.info("No batch selected. Process a new upload on **Upload & Process**, or open a previous batch "
                "from **Batch History**.")
        st.button("Go to Upload & Process", on_click=go, args=("Upload & Process",))
        return None
    return b


def esc(s) -> str:
    return html.escape("" if s is None else str(s))
