"""BL Manager V1 — Streamlit entry point.

Run with:  streamlit run app.py   (or double-click run_app.bat on Windows)
"""
import streamlit as st

st.set_page_config(page_title="BL Manager", page_icon="📄", layout="wide")

from bl_manager import __version__, db  # noqa: E402
from ui import batches, dashboard, folders, forwarders, settings_page, upload  # noqa: E402
from ui.common import PAGES, inject_css  # noqa: E402

db.init_db()
inject_css()


def _is_hosted() -> bool:
    try:
        host = (st.context.headers.get("Host") or "").split(":")[0].lower()
    except Exception:
        return False
    return host not in ("", "localhost", "127.0.0.1", "::1")


if _is_hosted():
    st.warning("**Hosted test version.** Use only the synthetic test documents (Upload & Process → "
               "'Download synthetic test BLs'). Do not upload real or confidential BLs to this link. "
               "Data on the hosted version may be reset at any time.", icon="⚠️")

if "nav" not in st.session_state:
    st.session_state["nav"] = "Upload & Process"
if "batch_id" not in st.session_state:
    latest = db.list_batches()
    st.session_state["batch_id"] = latest[0]["id"] if latest else None

with st.sidebar:
    st.markdown("## BL Manager")
    st.caption(f"Bill of Lading classification · V{__version__}")
    st.radio("Navigation", PAGES, key="nav", label_visibility="collapsed")
    st.divider()
    bs = db.list_batches()
    if bs:
        ids = [b["id"] for b in bs]
        cur = st.session_state.get("batch_id")
        idx = ids.index(cur) if cur in ids else 0
        chosen = st.selectbox("Current batch", ids, index=idx,
                              format_func=lambda i: next(f"#{b['id']} · {b['name']}" for b in bs if b["id"] == i))
        if chosen != cur:
            st.session_state["batch_id"] = chosen
            st.session_state["doc_id"] = None
            st.rerun()
    else:
        st.caption("No batch processed yet.")
    st.divider()
    st.caption("All processing runs locally on this computer.")

PAGE_RENDER = {
    "Upload & Process": upload.render,
    "Dashboard": dashboard.render,
    "BL Folders": folders.render,
    "Freight Forwarders": forwarders.render,
    "Settings": settings_page.render,
    "Batch History": batches.render,
}
PAGE_RENDER[st.session_state["nav"]]()
