"""Field labels printed on Bills of Lading, and label detection.

A label is recognised only at the START of a text segment. Text after the
label on the same segment is an inline value — except a parenthetical
form instruction such as "(not negotiable unless consigned to order)",
which is discarded so it is never mistaken for data.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .pdf_reader import Segment

_END = r"(?![A-Za-z])"

# field -> list of regex fragments (case-insensitive)
FIELD_LABELS: dict[str, list[str]] = {
    "bl_number": [
        r"B\s*/\s*L\s*(?:No|Number|Nr|#)\.?",
        r"BL\s*(?:No|Number|Nr|#)\.?",
        r"Bill\s+of\s+Lading\s*(?:No|Number|Nr|#)\.?",
        r"Sea\s*Waybill\s*(?:No|Number)\.?",
        r"(?:Master|M)\s*/?\s*B\s*/?\s*L\s*(?:No|Number)\.?",
    ],
    "hbl_number": [
        r"H\s*/?\s*B\s*/?\s*L\s*(?:No|Number|Nr|#)\.?",
        r"House\s+B\s*/?\s*L\s*(?:No|Number)?\.?",
        r"House\s+Bill\s+of\s+Lading\s*(?:No|Number)?\.?",
    ],
    "shipper": [r"Shipper\s*/\s*Exporter", r"Shipper", r"Exporter"],
    "consignee": [r"Consignee"],
    "notify": [r"Notify\s+Party", r"Also\s+Notify", r"Notify"],
    "port_of_loading": [r"Port\s+of\s+Loading", r"POL(?=\s*[:\-])"],
    "port_of_discharge": [r"Port\s+of\s+Discharge", r"POD(?=\s*[:\-])"],
    "containers": [
        r"Container\s*(?:No|Number|Nos)\.?(?:\s*(?:/|&|and)\s*Seal\s*(?:No|Number)s?\.?)?",
        r"Cntr\.?\s*(?:No|Nos)\.?",
    ],
    "quantity": [
        r"No\.?\s*of\s*(?:Containers\s+or\s+)?(?:Pkgs|Packages|Pkg)\.?",
        r"Number\s+of\s+(?:Containers\s+or\s+)?Packages",
        r"Quantity",
        r"Qty\.?",
    ],
    "description": [
        r"(?:Kind\s+of\s+Packages\s*[;,]?\s*)?Description\s+of\s+(?:Goods|Packages\s+and\s+Goods)",
    ],
    "gross_weight": [r"Gross\s*(?:Weight|Wt|Wgt)\.?(?:\s*\(\s*(?:KGS?|KG|LBS)\s*\))?", r"G\.?\s?W\.?(?=\s*[:\-])"],
    "net_weight": [r"Net\s*(?:Weight|Wt|Wgt)\.?(?:\s*\(\s*(?:KGS?|KG|LBS)\s*\))?", r"N\.?\s?W\.?(?=\s*[:\-])"],
    "hs_code": [r"H\.?\s?S\.?\s*(?:Code|Codes|No|Nos)\.?"],
}

# Labels that bound blocks but are not extracted.
STOPPER_LABELS: list[str] = [
    r"Booking\s*(?:No|Number)\.?",
    r"Export\s+References?",
    r"Forwarding\s+Agent",
    r"Point\s+and\s+Country\s+of\s+Origin",
    r"Pre[\-\s]?carriage\s+by",
    r"Place\s+of\s+Receipt",
    r"Ocean\s+Vessel",
    r"Vessel",
    r"Voyage\s*(?:No)?\.?",
    r"Place\s+of\s+Delivery",
    r"Final\s+Destination",
    r"Marks\s*(?:&|and)\s*N(?:umber)?(?:o)?s?\.?",
    r"Measurement",
    r"Freight\s*(?:&|and)\s*Charges",
    r"Freight\s+Payable\s+at",
    r"Place\s+and\s+Date\s+of\s+Issue",
    r"Number\s+of\s+Original",
    r"No\.?\s+of\s+Original",
    r"Total\s+(?:No\.?|Number)\s+of",
    r"Laden\s+on\s+Board",
    r"Shipped\s+on\s+Board",
    r"Declared\s+Value",
    r"Delivery\s+Agent",
    r"Onward\s+Inland\s+Routing",
    r"Particulars\s+Furnished",
    r"Service\s+Contract",
    r"Page\s*:?\s*\d",
    r"Sheet\s+\d",
]


@dataclass
class LabelHit:
    field: str            # field key, or "_stop"
    seg: Segment
    remainder: str        # inline text after the label (may be "")


def _compile(frags: list[str]) -> re.Pattern:
    # OCR often drops spaces ("ExportReferences"), so whitespace between
    # label words is optional.
    frags = [f.replace(r"\s+", r"\s*") for f in frags]
    return re.compile(r"^\s*(?:" + "|".join(f"(?:{f})" for f in frags) + r")" + _END, re.I)


_FIELD_RE = {k: _compile(v) for k, v in FIELD_LABELS.items()}
_STOP_RE = _compile(STOPPER_LABELS)
_PAREN_RE = re.compile(r"^\s*\((?:[^()]|\([^()]*\))*\)\s*")


def _clean_remainder(rest: str) -> str:
    rest = rest.strip()
    # Drop leading form instructions in parentheses, possibly several.
    while True:
        m = _PAREN_RE.match(rest)
        if not m:
            break
        rest = rest[m.end():]
    rest = rest.lstrip(" :.-#–—").strip()
    return rest


def match_label(seg: Segment) -> LabelHit | None:
    # Field labels take precedence over stoppers. Longer/more specific
    # labels are listed first inside each field.
    best = None
    for fld, rx in _FIELD_RE.items():
        m = rx.match(seg.text)
        if m and (best is None or m.end() > best[1].end()):
            best = (fld, m)
    if best:
        fld, m = best
        return LabelHit(fld, seg, _clean_remainder(seg.text[m.end():]))
    m = _STOP_RE.match(seg.text)
    if m:
        return LabelHit("_stop", seg, _clean_remainder(seg.text[m.end():]))
    return None


def find_labels(segments: list[Segment]) -> list[LabelHit]:
    hits = []
    for s in segments:
        h = match_label(s)
        if h:
            hits.append(h)
    return hits


def block_below(
    hit: LabelHit,
    hits: list[LabelHit],
    segments: list[Segment],
    page_width: float,
    max_lines: int = 8,
    max_height: float = 140.0,
    align_tol: float | None = None,
) -> list[Segment]:
    """Return the segments forming the value box under a label.

    The box extends downwards from the label until the next label in the
    same column, and rightwards until the next label that sits beside it.
    """
    L = hit.seg
    left = L.x0 - 8
    label_segs = {id(h.seg) for h in hits}

    # 1) Where does this column end vertically?  Next label below whose
    #    left edge is near this label's left edge (same column).
    stop_y = L.y1 + max_height
    for h in hits:
        s = h.seg
        if s is L:
            continue
        if s.y0 >= L.y1 - 1 and s.x0 < L.x0 + 60 and s.x1 > left:
            stop_y = min(stop_y, s.y0)

    # 2) Where does it end horizontally?  Nearest label to the right whose
    #    vertical extent overlaps this box.
    right = page_width + 1
    for h in hits:
        s = h.seg
        if s is L:
            continue
        if s.x0 > L.x0 + 15 and s.y1 > L.y0 - 3 and s.y0 < stop_y:
            right = min(right, s.x0)

    vals = [
        s for s in segments
        if id(s) not in label_segs
        and s.y0 >= L.y1 - 2
        and s.y0 < stop_y - 1
        and left <= s.x0 < right - 2
        and (align_tol is None or s.x0 <= L.x0 + align_tol)
    ]
    vals.sort(key=lambda s: (round(s.y0, 0), s.x0))
    return vals[:max_lines]


