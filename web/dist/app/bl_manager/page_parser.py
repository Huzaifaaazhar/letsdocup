"""Per-page identification: complete BL number and page numbering."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .labels import block_below, find_labels
from .pdf_reader import PageContent

PAGE_PATTERNS = [
    re.compile(r"\bPage\s*(?:No\.?)?\s*:?\s*(\d{1,3})\s*(?:of|/)\s*(\d{1,3})\b", re.I),
    re.compile(r"\bSheet\s*:?\s*(\d{1,3})\s*(?:of|/)\s*(\d{1,3})\b", re.I),
    re.compile(r"\b(\d{1,3})\s+of\s+(\d{1,3})\s+Pages?\b", re.I),
]

_TOKEN = re.compile(r"[A-Z0-9][A-Z0-9\-]{5,24}[A-Z0-9]", re.I)


@dataclass
class PageInfo:
    bl_number: str | None = None
    bl_method: str = ""
    bl_snippet: str = ""
    page_no: int | None = None
    page_total: int | None = None
    page_snippet: str = ""
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    hbl_values: list[str] = field(default_factory=list)


def _bl_regex(settings: dict) -> re.Pattern:
    pat = settings.get("bl_number_pattern") or r"ONEY[A-Z0-9]{8,14}"
    return re.compile(r"(?<![A-Z0-9])(" + pat + r")(?![A-Z0-9])", re.I)


def _first_token(text: str) -> str | None:
    m = _TOKEN.search(text.replace(" ", "") if len(text.split()) == 1 else text)
    if not m:
        return None
    tok = m.group(0).upper().replace("-", "")
    # Must contain at least one digit to be a document number.
    return tok if any(ch.isdigit() for ch in tok) else None


def parse_page(pc: PageContent, settings: dict) -> PageInfo:
    info = PageInfo()
    text = pc.text or ""
    bl_rx = _bl_regex(settings)

    # ---------------- page numbering ----------------
    found = []
    for rx in PAGE_PATTERNS:
        for m in rx.finditer(text):
            a, b = int(m.group(1)), int(m.group(2))
            if 1 <= a <= b <= 500:
                found.append((a, b, m.group(0)))
    distinct = {(a, b) for a, b, _ in found}
    if len(distinct) == 1:
        info.page_no, info.page_total, info.page_snippet = found[0]
    elif len(distinct) > 1:
        info.issues.append(
            "Conflicting page numbers on the same page: " + ", ".join(f"{a} of {b}" for a, b in sorted(distinct))
        )

    # ---------------- BL number ----------------
    hits = find_labels(pc.segments)
    hbl_vals: set[str] = set()
    for h in hits:
        if h.field == "hbl_number":
            vals = [h.remainder] if h.remainder else [s.text for s in block_below(h, hits, pc.segments, pc.width, 1, 30)]
            for v in vals:
                t = _first_token(v)
                if t:
                    hbl_vals.add(t)
    info.hbl_values = sorted(hbl_vals)

    labeled: list[tuple[str, str]] = []
    for h in hits:
        if h.field != "bl_number":
            continue
        cands = [h.remainder] if h.remainder else []
        cands += [s.text for s in block_below(h, hits, pc.segments, pc.width, 2, 30)]
        for c in cands:
            m = bl_rx.search(c)
            if m:
                labeled.append((m.group(1).upper(), f"label '{h.seg.text}' → {c}"))
                break
            if settings.get("accept_labeled_bl_outside_pattern", True):
                t = _first_token(c)
                if t and t not in hbl_vals and len(t) >= 8:
                    labeled.append((t, f"label '{h.seg.text}' → {c} (does not match BL pattern)"))
                    break

    pattern_hits = []
    for m in bl_rx.finditer(text):
        v = m.group(1).upper()
        if v not in hbl_vals:
            start = max(0, m.start() - 30)
            pattern_hits.append((v, text[start:m.end() + 10].replace("\n", " ")))

    labeled_vals = {v for v, _ in labeled}
    pattern_vals = {v for v, _ in pattern_hits}
    if len(labeled_vals) == 1:
        v = next(iter(labeled_vals))
        info.bl_number, info.bl_method = v, "label"
        info.bl_snippet = next(s for x, s in labeled if x == v)
        if "does not match" in info.bl_snippet:
            info.warnings.append(f"BL number '{v}' does not match the configured BL number pattern.")
        others = pattern_vals - {v}
        if others:
            info.issues.append(
                f"Page also contains other BL-like numbers ({', '.join(sorted(others))}) besides the labelled BL number {v}."
            )
    elif len(labeled_vals) > 1:
        info.issues.append("Different BL numbers printed next to B/L labels: " + ", ".join(sorted(labeled_vals)))
    elif len(pattern_vals) == 1:
        v = next(iter(pattern_vals))
        info.bl_number, info.bl_method = v, "pattern"
        info.bl_snippet = pattern_hits[0][1]
    elif len(pattern_vals) > 1:
        info.issues.append("Several different BL-like numbers on the page and none is labelled: " + ", ".join(sorted(pattern_vals)))
    return info
