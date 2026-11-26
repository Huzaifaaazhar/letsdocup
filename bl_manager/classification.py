"""Classification rules (HBL, MBL, CONSOL, EPZ, Manual Review).

All applicable rules are detected first and recorded as *indicators*;
the primary folder is then chosen with an explicit, documented priority:

  1. Reconstruction problems / missing required fields / unreadable data -> Manual Review
  2. CONSOL + EPZ                                     -> Manual Review
  3. HBL and MBL indicators both present              -> Manual Review
  4. CONSOL                                           -> CONSOL (or Manual Review, per Settings,
                                                         when HBL/MBL indicators are also present)
  5. EPZ                                              -> EPZ
  6. HBL                                              -> HBL
  7. MBL                                              -> MBL
  8. Nothing matched                                  -> Manual Review (or MBL, per Settings)

Secondary indicators are always kept and shown; nothing is overwritten silently.
"""
from __future__ import annotations

import re

from .constants import CONSOL, EPZ, FIELD_LABELS, HBL, MANUAL_REVIEW, MBL
from .normalize import core_name, normalize_name


def _reason(code, detected, why, verify):
    return {"code": code, "detected": detected, "why": why, "verify": verify}


def _phrase_regex(phrase: str, prefix_only: bool = False) -> re.Pattern:
    parts = [re.escape(p) for p in phrase.strip().split()]
    # Whitespace between words is optional: OCR frequently drops spaces.
    body = r"\s*".join(parts)
    # Multi-word phrases have no end boundary, so OCR text such as
    # "TOTHEORDEROF" still matches "TO THE ORDER".
    end = "" if (prefix_only or len(parts) > 1) else r"(?![A-Za-z0-9])"
    return re.compile(r"(?<![A-Za-z0-9])" + body + end, re.I)


def field_text(fields: dict, key: str) -> str:
    f = fields.get(key) or {}
    if f.get("user_value") not in (None, ""):
        return f["user_value"]
    return "\n".join(f.get("values") or [])


def field_present(fields: dict, key: str) -> bool:
    f = fields.get(key) or {}
    return bool(f.get("user_value")) or bool(f.get("values"))


def match_forwarder(consignee_name: str, forwarders: list[dict]) -> dict | None:
    if not consignee_name:
        return None
    n = normalize_name(consignee_name)
    c = core_name(consignee_name)
    for fw in forwarders:
        if fw["normalized"] == n:
            return {"entry": fw["name"], "how": "exact match after normalisation"}
    for fw in forwarders:
        if c and core_name(fw["name"]) == c:
            return {"entry": fw["name"], "how": "match ignoring legal suffix (Ltd/Pvt/Co…)"}
    return None


def classify(doc: dict, consol_info: dict, settings: dict, forwarders: list[dict]) -> dict:
    fields = doc.get("fields") or {}
    review: list[dict] = list(doc.get("recon_issues") or [])
    warnings: list[str] = list(doc.get("extract_warnings") or [])
    indicators: dict = {}
    reasons: list[str] = []

    name = field_text(fields, "consignee_name")
    address = field_text(fields, "consignee_address")
    cons = fields.get("consignee_name") or {}
    if cons.get("user_value") or (fields.get("consignee_address") or {}).get("user_value"):
        block = "\n".join(x for x in (name, address) if x)
    else:
        block = cons.get("raw_block") or "\n".join(x for x in (name, address) if x)

    # ---------------- HBL indicators ----------------
    fw = match_forwarder(name, forwarders)
    if fw:
        indicators["hbl_master_list"] = fw
    kw_hits = []
    for kw in settings.get("hbl_keywords") or []:
        if kw.strip() and _phrase_regex(kw, prefix_only=True).search(name or ""):
            kw_hits.append(kw.strip())
    if kw_hits:
        indicators["hbl_keywords"] = kw_hits
    is_hbl = bool(fw or kw_hits)

    # ---------------- MBL indicator ----------------
    to_order = None
    for ph in settings.get("to_order_phrases") or ["TO ORDER", "TO THE ORDER"]:
        m = _phrase_regex(ph).search(block or "")
        if m:
            to_order = m.group(0)
            break
    if to_order:
        indicators["mbl_to_order"] = to_order
    is_mbl = bool(to_order)

    # ---------------- EPZ indicator ----------------
    epz_text = name if settings.get("epz_scope") == "name_only" else block
    epz_hit = None
    for term in settings.get("epz_terms") or []:
        if term.strip():
            m = _phrase_regex(term).search(epz_text or "")
            if m:
                epz_hit = m.group(0)
                break
    if epz_hit:
        indicators["epz"] = {"term": epz_hit,
                             "scope": "consignee name" if settings.get("epz_scope") == "name_only" else "consignee name + address"}
    is_epz = bool(epz_hit)

    # ---------------- CONSOL indicator ----------------
    links = consol_info.get("per_doc", {}).get(doc["doc_key"], [])
    if links:
        indicators["consol"] = links
    is_consol = bool(links)

    # ---------------- Data-quality checks ----------------
    for key in settings.get("required_fields") or []:
        if not field_present(fields, key):
            label = FIELD_LABELS.get(key, key)
            review.append(_reason(
                "REQUIRED_FIELD_MISSING",
                f"{label} could not be extracted.",
                f"{label} is configured as a required field, so the BL cannot be confidently processed without it.",
                f"Read the {label} on the original BL and enter it using 'Edit extracted values', "
                "or move the BL to the correct folder.",
            ))

    conts = doc.get("containers") or []
    bad_cd = [c["container"] for c in conts if c.get("check_digit_ok") is False]
    ocr_used = doc.get("ocr_used")
    if bad_cd and (settings.get("invalid_check_digit_to_review") or ocr_used):
        review.append(_reason(
            "CONTAINER_CHECK_DIGIT",
            "Container number(s) fail the ISO 6346 check digit: " + ", ".join(bad_cd) + ".",
            "A failing check digit usually means a digit was misprinted or misread"
            + (" by OCR" if ocr_used else "") + ". A misread container can hide a CONSOL relationship.",
            "Compare the container numbers with the original document and correct them if necessary.",
        ))

    ulinks = consol_info.get("unidentified_links", {}).get(doc["doc_key"])
    if ulinks:
        warnings.append(
            "Container(s) also appear on unidentified pages: "
            + "; ".join(f"{u['container']} → {', '.join(u['unidentified_docs'])}" for u in ulinks)
            + ". Those pages may belong to this BL."
        )
    for nm in consol_info.get("near_matches", []):
        mine = {c["container"] for c in conts}
        if nm["a"] in mine or nm["b"] in mine:
            warnings.append(
                f"Similar container numbers {nm['a']} ({', '.join(nm['a_bls'])}) and {nm['b']} "
                f"({', '.join(nm['b_bls'])}) differ by one character. They were NOT treated as the same "
                "container — verify for misreads."
            )

    # ---------------- Reasons text ----------------
    if fw:
        reasons.append(f"Consignee matches Freight Forwarder Master List entry '{fw['entry']}' ({fw['how']}).")
    for kw in kw_hits:
        reasons.append(f"Consignee name contains the freight-forwarding keyword '{kw}'.")
    if to_order:
        reasons.append(f"Consignee contains '{to_order}' (TO ORDER rule → MBL).")
    if epz_hit:
        reasons.append(f"Consignee contains EPZ indicator '{epz_hit}'.")
    for l in links:
        reasons.append(f"Container {l['container']} is shared with BL(s) {', '.join(l['shared_with'])} → CONSOL.")

    # ---------------- Decision ----------------
    if is_consol and is_epz:
        review.append(_reason(
            "CONSOL_EPZ_OVERLAP",
            "This BL is both CONSOL (shared container) and EPZ (EPZ consignee).",
            "Business rule: a BL meeting both CONSOL and EPZ rules must be decided by a user.",
            "Decide whether this BL should be handled as CONSOL or EPZ and move it.",
        ))
    if is_hbl and is_mbl:
        review.append(_reason(
            "HBL_MBL_CONFLICT",
            "The consignee shows both HBL indicators ("
            + ", ".join((["master list"] if fw else []) + kw_hits) + f") and the MBL indicator '{to_order}'.",
            "HBL and MBL rules contradict each other.",
            "Read the consignee on the original BL and choose HBL or MBL.",
        ))
    if is_consol and (is_hbl or is_mbl) and settings.get("consol_overlap_folder") == MANUAL_REVIEW:
        review.append(_reason(
            "CONSOL_HBL_MBL_OVERLAP",
            "This BL is CONSOL and also meets the " + ("HBL" if is_hbl else "MBL") + " rule.",
            "Settings require CONSOL overlaps with HBL/MBL to be reviewed.",
            "Choose the correct folder.",
        ))

    if review:
        folder = MANUAL_REVIEW
    elif is_consol:
        folder = CONSOL
    elif is_epz:
        folder = EPZ
    elif is_hbl:
        folder = HBL
    elif is_mbl:
        folder = MBL
    else:
        folder = settings.get("unmatched_folder") or MANUAL_REVIEW
        if folder == MANUAL_REVIEW:
            review.append(_reason(
                "NO_RULE_MATCHED",
                f"Consignee '{name or '—'}' did not match any rule (not on the Freight Forwarder list, "
                "no forwarding keyword, no 'TO ORDER', no EPZ indicator, no shared container).",
                "The application will not guess a classification.",
                "Decide the folder. If the consignee is a freight forwarder, move the BL to HBL and "
                "save the name to the Freight Forwarder list when asked.",
            ))
        else:
            reasons.append("No rule matched — placed in MBL by the 'unmatched BL' setting.")

    secondary = []
    for flag, lab in ((is_consol, CONSOL), (is_epz, EPZ), (is_hbl, HBL), (is_mbl, MBL)):
        if flag and lab != folder:
            secondary.append(lab)
    indicators["secondary"] = secondary

    if not reasons and folder == MANUAL_REVIEW:
        reasons.append("Placed in Manual Review — see the review reasons.")

    return {
        "auto_class": folder,
        "auto_reasons": reasons,
        "indicators": indicators,
        "review_reasons": review,
        "warnings": warnings,
    }
