"""Extract the required fields from one reconstructed BL.

Every value records WHERE it came from (page, method, source text) so the
user can verify it against the original PDF. Values are never invented:
anything not found is marked "missing" and shown as
"Not extracted — requires verification".
"""
from __future__ import annotations

import re

from .labels import LabelHit, block_below, find_labels
from .normalize import container_check_digit_ok, normalize_container
from .pdf_reader import PageContent

CONTAINER_RE = re.compile(r"(?<![A-Z0-9])([A-Z]{4})[ ]?(\d{6})[ ]?-?[ ]?(\d)(?![0-9])", re.I)
_SEAL_BEFORE = re.compile(r"SEAL\s*(?:NO\.?|#|NUMBER)?\s*[:\-]?\s*$", re.I)

WEIGHT_RE = re.compile(
    r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(KGS?|KILOS?|KILOGRAMS?|LBS?|MT|MTS|TONS?)\b", re.I
)
NUM_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
GROSS_INLINE_RE = re.compile(
    r"\bGROSS\s*(?:WEIGHT|WT|WGT)\.?\s*(?:\(\s*KGS?\s*\))?\s*[:\-]?\s*"
    r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(KGS?|KILOS?|LBS?|MT)?", re.I)
NET_INLINE_RE = re.compile(
    r"\bNET\s*(?:WEIGHT|WT|WGT)\.?\s*(?:\(\s*KGS?\s*\))?\s*[:\-]?\s*"
    r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(KGS?|KILOS?|LBS?|MT)?", re.I)

PKG_UNITS = (
    r"BAGS?|CARTONS?|CTNS?|PACKAGES?|PKGS?|PALLETS?|PLTS?|ROLLS?|BALES?|DRUMS?|BUNDLES?|"
    r"CASES?|PCS|PIECES?|UNITS?|SETS?|COILS?|BOXES|BOX|CRATES?|SACKS?|REELS?|SKIDS?|"
    r"JUMBO\s+BAGS?|BULK\s+BAGS?|IBCS?|TINS?|CANS?|BARRELS?|PACKAGE\(S\)"
)
QTY_RE = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+|\d+)\s*(?:\(\s*[A-Z\s\-]+\)\s*)?(" + PKG_UNITS + r")\b", re.I)

HS_LABEL_RE = re.compile(r"\bH\.?\s?S\.?\s*(?:CODE|CODES|NO|NOS|#)?\.?\s*[:\-]?\s*", re.I)
HS_CODE_RE = re.compile(r"(?<![\d.])(\d{4}\.\d{2}(?:\.\d{2,4})?|\d{4}\.\d{4}|\d{6,10}|\d{4})(?![\d])")

_NAME_CONTINUATION = re.compile(
    r"^\s*(?:\(?\s*(?:PVT|PRIVATE|SMC)\s*\.?\s*\)?\s*)?(?:LTD|LIMITED|CO\.?|COMPANY|INC\.?|LLC|"
    r"CORP\.?|CORPORATION|PLC|LLP|GMBH|\(PVT\)|\(PRIVATE\)|PVT\.?|PRIVATE)\b",
    re.I,
)


SUSPECT_CONTAINER_RE = re.compile(r"(?<![A-Z0-9])([A-Z]{4})[ ]?([0-9OQDIlLSBGZ|]{6})[ ]?-?[ ]?([0-9OQDIlLSBGZ|])(?![A-Z0-9])")
_CONFUSABLE = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "|": "1", "S": "5", "B": "86", "G": "6", "Z": "2"}


def _check_digit_candidates(norm: str) -> list[str]:
    """Container numbers that the misread text COULD be and that pass the ISO
    6346 check digit. Shown to the user as hints only — never applied."""
    import itertools

    head, tail = norm[:4], norm[4:].upper()
    if not re.fullmatch(r"[A-Z]{4}", head):
        return []
    tails = [tail] if len(tail) == 7 else (
        [tail[:i] + tail[i + 1:] for i in range(len(tail))] if len(tail) == 8 else [])
    out: list[str] = []
    for t in tails:
        options = [(_CONFUSABLE.get(ch, ch) if not ch.isdigit() else ch) for ch in t]
        if any(not o.isdigit() for opt in options for o in opt):
            continue
        for combo in itertools.product(*options):
            cand = head + "".join(combo)
            if container_check_digit_ok(cand) and cand not in out:
                out.append(cand)
            if len(out) > 3:
                return out
    return out


def _field(values, page=None, method="", snippet="", status=None) -> dict:
    values = [v for v in (values or []) if v not in (None, "")]
    return {
        "values": values,
        "status": status or ("extracted" if values else "missing"),
        "page": page,
        "method": method,
        "snippet": (snippet or "")[:400],
        "user_value": None,
        "verified": False,
    }


def _split_party(lines: list[str]) -> tuple[str | None, str | None]:
    lines = [l.strip() for l in lines if l and l.strip()]
    if not lines:
        return None, None
    name_lines = [lines[0]]
    i = 1
    # "TO THE ORDER OF" + next line (bank) form one name
    if re.search(r"(?:\bOF|ORDER\s*OF)\s*:?\s*$", lines[0], re.I) and len(lines) > 1:
        name_lines.append(lines[1])
        i = 2
    while i < len(lines) and _NAME_CONTINUATION.match(lines[i]) and len(name_lines) < 3:
        name_lines.append(lines[i])
        i += 1
    address = "\n".join(lines[i:]) or None
    return " ".join(name_lines), address


def _party(hits_by_page, pages, field_key, max_lines=7):
    """Find a shipper/consignee box on the first page that has it."""
    for pno, (pc, hits) in enumerate(zip(pages, hits_by_page), start=1):
        for h in hits:
            if h.field != field_key:
                continue
            lines = []
            if h.remainder:
                lines.append(h.remainder)
            lines += [s.text for s in block_below(h, hits, pc.segments, pc.width, max_lines, 130, align_tol=60)]
            if lines:
                return lines, pno, h
    return None, None, None


def _single_value(hits_by_page, pages, field_key):
    for pno, (pc, hits) in enumerate(zip(pages, hits_by_page), start=1):
        for h in hits:
            if h.field != field_key:
                continue
            if h.remainder:
                return h.remainder, pno, h.seg.text
            below = block_below(h, hits, pc.segments, pc.width, 1, 40, align_tol=60)
            if below:
                return below[0].text, pno, f"{h.seg.text} → {below[0].text}"
    return None, None, None


def _column_lines(hits_by_page, pages, field_key, max_lines=25, max_height=420):
    out = []  # (page, label text, line)
    for pno, (pc, hits) in enumerate(zip(pages, hits_by_page), start=1):
        for h in hits:
            if h.field != field_key:
                continue
            if h.remainder:
                out.append((pno, h.seg.text, h.remainder))
            for s in block_below(h, hits, pc.segments, pc.width, max_lines, max_height):
                out.append((pno, h.seg.text, s.text))
    return out


def _weights_from_lines(lines):
    vals, pages, snippets = [], [], []
    for pno, label, line in lines:
        for m in WEIGHT_RE.finditer(line):
            vals.append(f"{m.group(1)} {m.group(2).upper()}")
            pages.append(pno)
            snippets.append(f"[{label}] {line}")
        if not WEIGHT_RE.search(line):
            m = NUM_RE.fullmatch(line.strip())
            if m:
                unit = ""
                lm = re.search(r"\(\s*(KGS?|LBS?)\s*\)", label, re.I)
                if lm:
                    unit = " " + lm.group(1).upper()
                vals.append(line.strip() + unit)
                pages.append(pno)
                snippets.append(f"[{label}] {line}")
    return vals, pages, snippets


def _dedupe(seq):
    seen, out = set(), []
    for x in seq:
        k = re.sub(r"\s+", " ", x).upper()
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def extract_document(pages: list[PageContent], bl_number: str | None, hbl_values: list[str]) -> tuple[dict, list[dict], list[str]]:
    """Return (fields, containers, warnings) for one reconstructed BL."""
    hits_by_page: list[list[LabelHit]] = [find_labels(pc.segments) for pc in pages]
    warnings: list[str] = []
    fields: dict[str, dict] = {}

    # --- BL / HBL numbers -------------------------------------------------
    fields["bl_number"] = _field([bl_number] if bl_number else [], 1 if bl_number else None,
                                 "page identification", f"Complete BL number read on every page: {bl_number}" if bl_number else "")
    hbl = [v for v in hbl_values if v != bl_number]
    hbl_page = next((i for i, pc in enumerate(pages, start=1) if hbl and hbl[0] in (pc.text or "").upper()), None)
    fields["hbl_number"] = _field(hbl, hbl_page, "box under 'HBL No.' label" if hbl else "",
                                  ", ".join(hbl))
    if not hbl:
        fields["hbl_number"]["status"] = "not_present"

    # --- Parties ----------------------------------------------------------
    for key in ("consignee", "shipper"):
        lines, pno, hit = _party(hits_by_page, pages, key)
        if lines:
            name, addr = _split_party(lines)
            raw = "\n".join(lines)
            fields[f"{key}_name"] = _field([name], pno, f"box under '{hit.seg.text}'", raw)
            fields[f"{key}_address"] = _field([addr] if addr else [], pno, f"box under '{hit.seg.text}'", raw)
            fields[f"{key}_name"]["raw_block"] = raw
        else:
            fields[f"{key}_name"] = _field([])
            fields[f"{key}_address"] = _field([])

    # --- Ports ------------------------------------------------------------
    for key in ("port_of_loading", "port_of_discharge"):
        v, pno, snip = _single_value(hits_by_page, pages, key)
        fields[key] = _field([v] if v else [], pno, "box under label" if v else "", snip or "")

    # --- Full text across pages -------------------------------------------
    page_texts = [pc.text or "" for pc in pages]

    # --- HS codes ---------------------------------------------------------
    hs, hs_pages, hs_snips = [], [], []
    for pno, t in enumerate(page_texts, start=1):
        for m in HS_LABEL_RE.finditer(t):
            span = t[m.end(): m.end() + 120]
            span = re.split(r"\n(?=[A-Z][A-Z ]{3,}:)|(?i:NET|GROSS|WEIGHT|KGS|CBM|CONTAINER)", span)[0]
            for cm in HS_CODE_RE.finditer(span):
                hs.append(cm.group(1))
                hs_pages.append(pno)
                hs_snips.append(t[max(0, m.start() - 10): m.end() + 60].replace("\n", " "))
    hs = _dedupe(hs)
    fields["hs_codes"] = _field(hs, hs_pages[0] if hs_pages else None, "text after 'HS CODE'" if hs else "",
                                " | ".join(_dedupe(hs_snips))[:400])

    # --- Weights ----------------------------------------------------------
    for key, inline_rx in (("gross_weight", GROSS_INLINE_RE), ("net_weight", NET_INLINE_RE)):
        col = _column_lines(hits_by_page, pages, key)
        vals, vpages, snips = _weights_from_lines(col)
        method = "column/box under label"
        if not vals:
            for pno, t in enumerate(page_texts, start=1):
                for m in inline_rx.finditer(t):
                    vals.append(f"{m.group(1)} {(m.group(2) or '').upper()}".strip())
                    vpages.append(pno)
                    snips.append(t[max(0, m.start() - 10): m.end() + 10].replace("\n", " "))
            method = "text pattern"
        vals = _dedupe(vals)
        fields[key] = _field(vals, vpages[0] if vpages else None, method if vals else "", " | ".join(_dedupe(snips))[:400])
        if len(vals) > 1:
            warnings.append(f"{len(vals)} different {key.replace('_', ' ')} values found — check which is the total.")

    # --- Quantity ---------------------------------------------------------
    qcol = _column_lines(hits_by_page, pages, "quantity")
    qvals, qpages, qsnips = [], [], []
    pending_num = None
    for pno, label, line in qcol:
        m = QTY_RE.search(line)
        if m:
            qvals.append(f"{m.group(1)} {m.group(2).upper()}")
            qpages.append(pno)
            qsnips.append(f"[{label}] {line}")
            pending_num = None
        elif re.fullmatch(r"\d{1,3}(?:,\d{3})*|\d+", line.strip()):
            pending_num = (pno, label, line.strip())
        elif pending_num and re.fullmatch(r"(?:" + PKG_UNITS + r")", line.strip(), re.I):
            qvals.append(f"{pending_num[2]} {line.strip().upper()}")
            qpages.append(pending_num[0])
            qsnips.append(f"[{label}] {pending_num[2]} {line}")
            pending_num = None
    if pending_num and not qvals:
        qvals.append(pending_num[2])
        qpages.append(pending_num[0])
        qsnips.append(f"[{pending_num[1]}] {pending_num[2]}")
    qmethod = "column/box under label"
    if not qvals:
        for pno, t in enumerate(page_texts, start=1):
            for m in QTY_RE.finditer(t):
                qvals.append(f"{m.group(1)} {m.group(2).upper()}")
                qpages.append(pno)
                qsnips.append(t[max(0, m.start() - 20): m.end() + 10].replace("\n", " "))
        qmethod = "text pattern"
    qvals = _dedupe(qvals)
    fields["quantity"] = _field(qvals, qpages[0] if qpages else None, qmethod if qvals else "", " | ".join(_dedupe(qsnips))[:400])

    # --- Containers -------------------------------------------------------
    containers: list[dict] = []
    seen: dict[str, dict] = {}
    for pno, t in enumerate(page_texts, start=1):
        for m in CONTAINER_RE.finditer(t):
            before = t[max(0, m.start() - 20): m.start()]
            if _SEAL_BEFORE.search(before):
                continue
            raw = m.group(0)
            norm = normalize_container(raw)
            if bl_number and norm in bl_number.upper():
                continue
            ok = container_check_digit_ok(norm)
            snippet = t[max(0, m.start() - 25): m.end() + 25].replace("\n", " ")
            if norm in seen:
                seen[norm]["occurrences"] += 1
                if pno not in seen[norm]["pages"]:
                    seen[norm]["pages"].append(pno)
                continue
            rec = {
                "container": norm,
                "raw": raw,
                "pages": [pno],
                "occurrences": 1,
                "check_digit_ok": ok,
                "snippet": snippet,
            }
            seen[norm] = rec
            containers.append(rec)
    # Container-like text that is NOT a valid container number because some
    # characters look misread (e.g. OCR 'CAIUB022170'). Never auto-corrected:
    # reported so the BL goes to Manual Review ("unreadable container number").
    suspects: list[dict] = []
    for pno, t in enumerate(page_texts, start=1):
        for m in SUSPECT_CONTAINER_RE.finditer(t):
            raw = m.group(0)
            norm = normalize_container(raw)
            if CONTAINER_RE.fullmatch(raw) or norm in seen or (bl_number and norm in bl_number.upper()):
                continue
            if _SEAL_BEFORE.search(t[max(0, m.start() - 20): m.start()]):
                continue
            if sum(ch.isdigit() for ch in norm[4:]) < 5:
                continue
            if any(sp["raw"] == raw for sp in suspects):
                continue
            suspects.append({"raw": raw, "page": pno, "candidates": _check_digit_candidates(norm)})
    # Also: any ID-like token printed under the "Container No." column that is
    # not a valid container number (catches inserted/dropped characters too,
    # e.g. OCR 'TGHUS5532019').
    for pno, _label, line in _column_lines(hits_by_page, pages, "containers"):
        if re.match(r"\s*SEAL", line, re.I):
            continue
        for tok in re.split(r"[\s/,;]+", line):
            tok = tok.strip(".:()[]")
            norm = normalize_container(tok)
            if (len(norm) < 9 or sum(ch.isdigit() for ch in norm) < 5 or not re.match(r"[A-Z]{3}", norm)
                    or CONTAINER_RE.fullmatch(norm) or norm in seen or (bl_number and norm in bl_number.upper())
                    or any(sp["raw"] == tok for sp in suspects)):
                continue
            suspects.append({"raw": tok, "page": pno, "candidates": _check_digit_candidates(norm)})
    fields["_meta_suspect_containers"] = suspects

    fields["containers"] = _field([c["container"] for c in containers],
                                  containers[0]["pages"][0] if containers else None,
                                  "container-number pattern (4 letters + 7 digits)" if containers else "",
                                  " | ".join(c["snippet"] for c in containers[:6]))
    bad = [c["container"] for c in containers if c["check_digit_ok"] is False]
    if bad:
        warnings.append("ISO 6346 check digit does not validate for: " + ", ".join(bad) +
                        " — the number may be misprinted or misread.")

    # --- OCR note ---------------------------------------------------------
    if any(pc.source == "ocr" for pc in pages):
        warnings.append("One or more pages were read by OCR. OCR can misread characters — verify all values.")
        for k, f in fields.items():
            if not k.startswith("_"):
                f["ocr"] = True

    return fields, containers, warnings


def display_value(f: dict | None) -> str:
    from .constants import NOT_EXTRACTED

    if not f:
        return NOT_EXTRACTED
    if f.get("user_value") not in (None, ""):
        return f["user_value"]
    if f.get("status") == "not_present":
        return "Not present on this BL"
    vals = f.get("values") or []
    if not vals:
        return NOT_EXTRACTED
    return "\n".join(vals)
