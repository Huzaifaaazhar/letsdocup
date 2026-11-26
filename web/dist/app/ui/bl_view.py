"""Individual BL view: original PDF (left) and extracted information (right)."""
from __future__ import annotations

import base64
from pathlib import Path

import pymupdf
import streamlit as st

from bl_manager import db, exports
from bl_manager.classification import match_forwarder
from bl_manager.constants import FIELD_LABELS, FIELDS, FOLDER_LABELS, FOLDERS, HBL
from bl_manager.extraction import display_value
from bl_manager.pipeline import change_classification, reclassify_batch, update_fields

from .common import badge, clear_prepared_downloads, esc, status_badge


def _back():
    st.session_state["doc_id"] = None
    for k in [k for k in st.session_state if str(k).startswith("tbl_")]:
        del st.session_state[k]
    st.session_state.pop("ff_prompt", None)


def _open(doc_id: int):
    st.session_state["doc_id"] = doc_id
    st.session_state.pop("ff_prompt", None)


@st.cache_data(show_spinner=False, max_entries=64)
def _render_page(pdf_path: str, mtime: float, page: int, zoom: float) -> bytes:
    with pymupdf.open(pdf_path) as doc:
        pix = doc[page].get_pixmap(matrix=pymupdf.Matrix(zoom * 1.5, zoom * 1.5))
        return pix.tobytes("png")


def _viewer(d: dict) -> None:
    path = d["pdf_path"]
    if not Path(path).exists():
        st.error("The reconstructed PDF file is missing from disk.")
        return
    n = d["page_count"]
    c1, c2, c3 = st.columns([1.3, 1, 1])
    with c1:
        zoom = st.select_slider("Zoom", options=[0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0], value=1.0,
                                format_func=lambda z: f"{int(z * 100)}%", key=f"zoom_{d['id']}")
    with c2:
        show_all = st.toggle("Show all pages", value=n <= 2, key=f"all_{d['id']}")
    with c3:
        page = st.number_input(f"Page (of {n})", min_value=1, max_value=n, value=1, step=1,
                               key=f"pg_{d['id']}", disabled=show_all)
    mtime = Path(path).stat().st_mtime
    pages = range(n) if show_all else [page - 1]
    # 100% = page fits the panel width; larger values scroll inside the viewer.
    imgs = "".join(
        f'<img src="data:image/png;base64,{base64.b64encode(_render_page(path, mtime, p, zoom)).decode()}" '
        f'style="width:{int(zoom * 100)}%;max-width:none" alt="page {p + 1}"/>'
        for p in pages
    )
    st.markdown(f'<div class="blm-viewer">{imgs}</div>', unsafe_allow_html=True)
    src = ", ".join(
        f"{s['file']} p.{s['page']}" + (f" (printed {s['printed']})" if s.get("printed") else "")
        + (" [OCR]" if s.get("text_source") == "ocr" else "")
        for s in d["source_pages"]
    )
    st.caption(f"Reconstructed from: {src}")
    with open(path, "rb") as fh:
        st.download_button(f"⬇ Download {d['file_name']}", fh.read(), file_name=d["file_name"],
                           mime="application/pdf", type="primary", width="stretch")


def _classification_panel(d: dict, docs: list[dict]) -> None:
    st.markdown(
        f'<div class="blm-card"><div class="blm-field-label">Current classification</div>'
        f'<div style="margin:8px 0 6px 0">{badge(d["current_class"])}'
        + (' <span class="blm-muted">changed manually</span>' if d["manually_changed"] else "")
        + f'</div><div class="blm-muted">Automated classification: {esc(FOLDER_LABELS.get(d["auto_class"]))}'
        + (f' · Changed {esc((d["changed_at"] or "").replace("T", " "))}' if d["manually_changed"] else "")
        + (f' · Note: {esc(d["change_note"])}' if d.get("change_note") else "")
        + "</div></div>",
        unsafe_allow_html=True,
    )
    st.markdown("**Classification reason**")
    for r in d["auto_reasons"] or ["—"]:
        st.markdown(f"- {r}")
    sec = (d.get("indicators") or {}).get("secondary") or []
    if sec:
        st.caption("Other rules this BL also meets (not used as the primary folder): " + ", ".join(sec))

    if d["review_reasons"]:
        st.markdown("**Manual Review reasons**")
        for r in d["review_reasons"]:
            st.warning(f"**What was detected:** {r['detected']}\n\n**Why it needs review:** {r['why']}\n\n"
                       f"**What to verify:** {r['verify']}")
    for w in d.get("warnings") or []:
        st.info(w)

    consol = d.get("consol") or {}
    links = consol.get("links", []) if isinstance(consol, dict) else []
    if links:
        st.markdown("**CONSOL relationship**")
        by_bl = {x["bl_number"]: x["id"] for x in docs if x.get("bl_number")}
        for l in links:
            st.markdown(f"Container **`{l['container']}`** is also on: " + ", ".join(f"`{b}`" for b in l["shared_with"]))
            bc = st.columns(min(4, len(l["shared_with"])))
            for i, other in enumerate(l["shared_with"]):
                if other in by_bl:
                    bc[i % len(bc)].button(f"Open {other}", key=f"lnk_{l['container']}_{other}",
                                           on_click=_open, args=(by_bl[other],))
        g = consol.get("group")
        if g and len(g["bls"]) > 2:
            st.caption(f"CONSOL group {g['group_id']}: {', '.join(g['bls'])}")


def _change_classification(d: dict) -> None:
    with st.expander("Change classification", expanded=bool(st.session_state.get("ff_prompt"))):
        new = st.selectbox("Move this BL to folder", FOLDERS, index=FOLDERS.index(d["current_class"]),
                           format_func=lambda f: FOLDER_LABELS[f], key=f"newcls_{d['id']}")
        note = st.text_input("Reason / note (optional)", key=f"note_{d['id']}")
        cols = st.columns(2)
        if cols[0].button("Confirm change", type="primary", disabled=new == d["current_class"], key=f"conf_{d['id']}"):
            old = d["current_class"]
            change_classification(d["id"], new, note)
            clear_prepared_downloads()
            name = display_value(d["fields"].get("consignee_name"))
            has_name = bool(d["fields"].get("consignee_name", {}).get("values") or d["fields"].get("consignee_name", {}).get("user_value"))
            fw = match_forwarder(name, db.list_forwarders()) if has_name else None
            if new == HBL and has_name and not fw:
                st.session_state["ff_prompt"] = {"doc_id": d["id"], "action": "add", "name": name}
            elif old == HBL and new != HBL and fw:
                st.session_state["ff_prompt"] = {"doc_id": d["id"], "action": "remove", "name": fw["entry"]}
            st.rerun()
        if d["manually_changed"]:
            if cols[1].button("Restore automated classification", key=f"reset_{d['id']}"):
                change_classification(d["id"], d["auto_class"], "restored automated classification")
                clear_prepared_downloads()
                st.rerun()

    p = st.session_state.get("ff_prompt")
    if p and p["doc_id"] == d["id"]:
        if p["action"] == "add":
            st.info(f"Would you like to save this consignee as a Freight Forwarder for future classifications?\n\n"
                    f"**{p['name']}**")
        else:
            st.info(f"This BL was classified HBL because the consignee matched the Freight Forwarder list entry "
                    f"**{p['name']}**. Would you like to remove that entry from the list?")
        a, b_ = st.columns(2)
        if a.button("Yes", type="primary", key="ff_yes"):
            if p["action"] == "add":
                ok, msg = db.add_forwarder(p["name"], notes=f"Added from correction of {d['doc_key']}", source="correction")
                db.log(d["batch_id"], d["id"], "forwarder_added" if ok else "forwarder_add_skipped", f"{p['name']}: {msg}")
            else:
                db.delete_forwarder_by_name(p["name"])
                db.log(d["batch_id"], d["id"], "forwarder_removed", p["name"])
                msg = f"Removed '{p['name']}'."
            st.session_state.pop("ff_prompt")
            st.toast(msg + " Use 'Re-run classification' on the Dashboard to apply it to this batch.")
            st.rerun()
        if b_.button("No", key="ff_no"):
            st.session_state.pop("ff_prompt")
            st.rerun()


def _fields_panel(d: dict) -> None:
    st.markdown("#### Extracted information")
    st.caption("Values are read from the document but are **not verified** until you tick 'verified' or correct "
               "them. Click the copy icon on any value to copy it.")
    for key, label in FIELDS:
        f = d["fields"].get(key) or {}
        st.markdown(f'<div class="blm-field-label">{esc(label)} &nbsp;{status_badge(f)}</div>', unsafe_allow_html=True)
        if key == "containers" and (d.get("containers")):
            lines = []
            for cinfo in d["containers"]:
                cd = cinfo.get("check_digit_ok")
                mark = "" if cd is None else ("  ✓ check digit OK" if cd else "  ⚠ check digit fails — verify")
                lines.append(cinfo["container"] + mark)
            st.code("\n".join(lines), language=None)
        else:
            st.code(display_value(f), language=None)
        meta = []
        if f.get("user_value") and f.get("values"):
            meta.append("Originally extracted: " + " | ".join(f["values"]))
        if f.get("page"):
            meta.append(f"Source: page {f['page']}")
        if f.get("method"):
            meta.append(f"Method: {f['method']}")
        if f.get("snippet") and key not in ("bl_number",):
            meta.append(f"Text: “{f['snippet'][:220]}”")
        if meta:
            st.caption(" · ".join(meta))


def _edit_panel(d: dict) -> None:
    with st.expander("Edit extracted values / mark as verified"):
        st.caption("Corrections are stored separately — the originally extracted value is kept. "
                   "Saving re-runs classification for the whole batch (CONSOL is batch-wide).")
        with st.form(f"edit_{d['id']}"):
            edits, verified = {}, {}
            for key, label in FIELDS:
                if key == "bl_number":
                    continue
                f = d["fields"].get(key) or {}
                cur = f.get("user_value") or ""
                orig = "\n".join(f.get("values") or [])
                edits[key] = st.text_area(
                    f"{label} — correction (leave empty to keep extracted value)", value=cur, height=68 if "\n" not in orig else 100,
                    key=f"e_{d['id']}_{key}", placeholder=orig or "Not extracted",
                    help="Containers: one per line." if key == "containers" else None)
                verified[key] = st.checkbox(f"{label} verified against the original document",
                                            value=bool(f.get("verified")), key=f"v_{d['id']}_{key}")
            if st.form_submit_button("Save corrections", type="primary"):
                update_fields(d["id"], edits, verified)
                reclassify_batch(d["batch_id"])
                clear_prepared_downloads()
                st.success("Saved. Classification re-run for the batch.")
                st.rerun()


def render(d: dict, docs: list[dict]) -> None:
    ids = st.session_state.get("doc_list") or [x["id"] for x in docs]
    if d["id"] not in ids:
        ids = [x["id"] for x in docs]
    pos = ids.index(d["id"])

    top = st.columns([1, 4, 1, 1])
    top[0].button("← Back to list", on_click=_back)
    top[1].markdown(f"### {esc(d['doc_key'])} &nbsp; {badge(d['current_class'])}", unsafe_allow_html=True)
    top[2].button("◀ Previous", disabled=pos == 0, on_click=_open, args=(ids[max(pos - 1, 0)],), width="stretch")
    top[3].button("Next ▶", disabled=pos >= len(ids) - 1, on_click=_open, args=(ids[min(pos + 1, len(ids) - 1)],),
                  width="stretch")

    left, right = st.columns([1.1, 1], gap="large")
    with left:
        _viewer(d)
    with right:
        _classification_panel(d, docs)
        _change_classification(d)
        _fields_panel(d)
        with st.expander("Copy all extracted information for this BL"):
            st.code(exports.doc_text(d), language=None)
        _edit_panel(d)
        with st.expander("History of this BL"):
            logs = db.list_log(d["batch_id"], d["id"])
            for l in logs:
                st.caption(f"{l['ts'].replace('T', ' ')} — {l['action']}: {l['detail']}")
            if not logs:
                st.caption("No changes yet.")
