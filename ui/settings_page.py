"""Settings: classification rules and processing options."""
from __future__ import annotations

import re

import streamlit as st

from bl_manager import db
from bl_manager.constants import FIELD_LABELS, FOLDER_LABELS, MANUAL_REVIEW, MBL, CONSOL, REQUIRABLE_FIELDS


def _lines(s: str) -> list[str]:
    return [x.strip() for x in s.splitlines() if x.strip()]


def render() -> None:
    st.title("Settings")
    st.caption("Classification settings apply to new batches. To apply them to an existing batch, open it and "
               "click 'Re-run classification' on the Dashboard. Reconstruction / OCR settings require the "
               "documents to be uploaded again.")
    s = db.get_settings()

    with st.form("settings"):
        st.subheader("HBL")
        kw = st.text_area("Freight-forwarding keywords in the consignee NAME (one per line)",
                          "\n".join(s["hbl_keywords"]), height=170,
                          help="Matched at the start of a word: 'Logistic' also matches 'Logistics'.")
        st.subheader("MBL")
        to = st.text_area("'To order' phrases in the consignee (one per line)", "\n".join(s["to_order_phrases"]), height=80)
        st.subheader("EPZ")
        epz = st.text_area("EPZ indicators (one per line)", "\n".join(s["epz_terms"]), height=90)
        scope = st.radio("Where to look for EPZ indicators", ["name_and_address", "name_only"],
                         index=0 if s["epz_scope"] == "name_and_address" else 1, horizontal=True,
                         format_func=lambda x: "Consignee name + address" if x == "name_and_address" else "Consignee name only")
        st.subheader("Folder decisions")
        unmatched = st.radio("A BL that matches no rule goes to", [MANUAL_REVIEW, MBL],
                             index=0 if s["unmatched_folder"] == MANUAL_REVIEW else 1,
                             format_func=lambda f: FOLDER_LABELS[f], horizontal=True)
        overlap = st.radio("A BL that is CONSOL and also HBL/MBL goes to", [CONSOL, MANUAL_REVIEW],
                           index=0 if s["consol_overlap_folder"] == CONSOL else 1,
                           format_func=lambda f: FOLDER_LABELS[f], horizontal=True)
        st.caption("Fixed rules: CONSOL + EPZ → Manual Review. HBL + MBL indicators together → Manual Review.")
        req = st.multiselect("Required fields (if missing → Manual Review)", REQUIRABLE_FIELDS,
                             default=[f for f in s["required_fields"] if f in REQUIRABLE_FIELDS],
                             format_func=lambda k: FIELD_LABELS[k])
        bad_cd = st.checkbox("Send BLs with a failing container check digit to Manual Review "
                             "(always applied to OCR-read BLs)", value=s["invalid_check_digit_to_review"])

        st.subheader("BL reconstruction")
        pat = st.text_input("BL number pattern (regular expression)", s["bl_number_pattern"],
                            help="Default ONEY followed by 8–14 letters/digits. Ask IT before changing.")
        lab = st.checkbox("Accept a value printed next to a 'B/L No.' label even if it does not match the pattern "
                          "(a warning is shown)", value=s["accept_labeled_bl_outside_pattern"])
        single = st.checkbox("Accept a single page with no 'Page x of y' as a complete 1-page BL",
                             value=s["accept_single_page_without_numbering"])

        st.subheader("OCR (scanned pages)")
        ocr = st.checkbox("Use OCR when a page has no readable text", value=s["ocr_enabled"])
        c1, c2 = st.columns(2)
        minc = c1.number_input("Minimum characters before OCR is used", 0, 1000, int(s["ocr_min_chars"]))
        dpi = c2.number_input("OCR resolution (DPI)", 100, 400, int(s["ocr_dpi"]), step=25)

        if st.form_submit_button("Save settings", type="primary"):
            try:
                re.compile(pat)
            except re.error as exc:
                st.error(f"BL number pattern is not valid: {exc}")
            else:
                db.save_settings({
                    "hbl_keywords": _lines(kw), "to_order_phrases": _lines(to) or ["TO ORDER"],
                    "epz_terms": _lines(epz), "epz_scope": scope, "unmatched_folder": unmatched,
                    "consol_overlap_folder": overlap, "required_fields": req,
                    "invalid_check_digit_to_review": bad_cd, "bl_number_pattern": pat,
                    "accept_labeled_bl_outside_pattern": lab, "accept_single_page_without_numbering": single,
                    "ocr_enabled": ocr, "ocr_min_chars": int(minc), "ocr_dpi": int(dpi),
                })
                db.log(None, None, "settings_saved", "")
                st.success("Settings saved.")

    with st.expander("Restore default settings"):
        if st.checkbox("I want to restore all default settings"):
            if st.button("Restore defaults"):
                db.reset_settings()
                st.success("Defaults restored.")
                st.rerun()
