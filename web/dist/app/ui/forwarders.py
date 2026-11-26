"""Freight Forwarder Management."""
from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from bl_manager import db


def render() -> None:
    st.title("Freight Forwarder Management")
    st.caption("This list is used for HBL classification: a consignee that matches an entry is classified HBL. "
               "Matching ignores capitalisation, extra spaces, punctuation and spelling variants of legal "
               "suffixes (Ltd/Limited, Pvt/Private, Co/Company). It never matches substantially different names.")

    all_rows = db.list_forwarders()
    q = st.text_input("Search the list", placeholder="Type part of a name")
    rows = db.list_forwarders(q) if q else all_rows
    st.markdown(f"**{len(all_rows)}** forwarder(s) in the list" + (f" · {len(rows)} match your search" if q else ""))
    if rows:
        st.dataframe(pd.DataFrame([{"Name": r["name"], "Notes": r["notes"], "Added via": r["source"],
                                    "Added on": r["created_at"].replace("T", " ")} for r in rows]),
                     hide_index=True, width="stretch")

    t_add, t_edit, t_import = st.tabs(["Add", "Edit / Delete", "Import / Export"])
    with t_add:
        with st.form("ff_add", clear_on_submit=True):
            name = st.text_input("Freight forwarder name (as printed on BLs)")
            notes = st.text_input("Notes (optional)")
            if st.form_submit_button("Add to list", type="primary"):
                ok, msg = db.add_forwarder(name, notes)
                (st.success if ok else st.error)(msg)
                if ok:
                    db.log(None, None, "forwarder_added", name)

    with t_edit:
        if not all_rows:
            st.caption("The list is empty.")
        else:
            sel = st.selectbox("Select an entry", all_rows, format_func=lambda r: r["name"], key="ff_sel")
            with st.form("ff_edit"):
                nn = st.text_input("Name", value=sel["name"])
                no = st.text_input("Notes", value=sel["notes"] or "")
                if st.form_submit_button("Save changes", type="primary"):
                    ok, msg = db.update_forwarder(sel["id"], nn, no)
                    (st.success if ok else st.error)(msg)
                    if ok:
                        st.rerun()
            confirm = st.checkbox(f"Yes, delete '{sel['name']}'", key=f"ffdel_{sel['id']}")
            if st.button("Delete entry", disabled=not confirm):
                db.delete_forwarder(sel["id"])
                db.log(None, None, "forwarder_deleted", sel["name"])
                st.success("Deleted.")
                st.rerun()
        st.caption("Changes apply to new batches. To apply them to an open batch, click 'Re-run classification' "
                   "on the Dashboard.")

    with t_import:
        st.markdown("Upload an **Excel (.xlsx)** or **CSV** file. Names are read from a column called "
                    "`Name` (or the first column). Duplicates already in the list are skipped.")
        up = st.file_uploader("Excel or CSV file", type=["xlsx", "xls", "csv"], key="ff_import")
        if up is not None:
            try:
                df = pd.read_csv(up) if up.name.lower().endswith(".csv") else pd.read_excel(up)
                col = next((c for c in df.columns if str(c).strip().lower() in ("name", "freight forwarder", "forwarder", "consignee")),
                           df.columns[0])
                col = st.selectbox("Column containing the names", list(df.columns), index=list(df.columns).index(col))
                names = [str(x).strip() for x in df[col].dropna() if str(x).strip()]
                st.caption(f"{len(names)} name(s) found. Preview: " + "; ".join(names[:5]))
                if st.button("Import names", type="primary"):
                    added = skipped = 0
                    for nm in names:
                        ok, _ = db.add_forwarder(nm, source="import")
                        added += ok
                        skipped += not ok
                    db.log(None, None, "forwarders_imported", f"{added} added, {skipped} skipped")
                    st.success(f"{added} added, {skipped} skipped (duplicates or empty).")
            except Exception as exc:
                st.error(f"Could not read the file: {exc}")
        if all_rows:
            buf = io.BytesIO()
            pd.DataFrame([{"Name": r["name"], "Notes": r["notes"]} for r in all_rows]).to_excel(buf, index=False)
            st.download_button("⬇ Export list to Excel", buf.getvalue(), file_name="freight_forwarders.xlsx")
