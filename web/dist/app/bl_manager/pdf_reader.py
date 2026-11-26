"""Read PDF pages into positioned text segments, with OCR fallback.

A *segment* is a run of text on one visual line with its bounding box in
PDF points. Spans on the same line separated by a large horizontal gap are
split into separate segments, so text in neighbouring boxes/columns never
merges together.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pymupdf

log = logging.getLogger(__name__)


@dataclass
class Segment:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def h(self) -> float:
        return self.y1 - self.y0


@dataclass
class PageContent:
    page_index: int                      # 0-based within its source file
    segments: list[Segment] = field(default_factory=list)
    text: str = ""
    source: str = "none"                 # text | ocr | none
    width: float = 595.0
    height: float = 842.0
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Text layer
# ---------------------------------------------------------------------------
def _segments_from_text_layer(page: pymupdf.Page) -> list[Segment]:
    segs: list[Segment] = []
    d = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)
    for block in d.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            spans.sort(key=lambda s: s["bbox"][0])
            cur = None
            for s in spans:
                x0, y0, x1, y1 = s["bbox"]
                size = s.get("size", 8) or 8
                if cur is not None and x0 - cur.x1 > max(12.0, size * 1.6):
                    segs.append(cur)
                    cur = None
                if cur is None:
                    cur = Segment(s["text"].strip(), x0, y0, x1, y1)
                else:
                    sep = " " if x0 - cur.x1 > size * 0.15 or not cur.text.endswith(" ") else ""
                    cur.text = (cur.text + sep + s["text"].strip()).strip()
                    cur.x1 = max(cur.x1, x1)
                    cur.y0 = min(cur.y0, y0)
                    cur.y1 = max(cur.y1, y1)
            if cur is not None:
                segs.append(cur)
    # Large gaps inside a single span (multiple spaces) also separate columns.
    out: list[Segment] = []
    for s in segs:
        parts = [p for p in s.text.split("     ") if p.strip()]
        if len(parts) <= 1:
            s.text = " ".join(s.text.split())
            out.append(s)
            continue
        # Approximate positions proportionally to character offsets.
        total = max(len(s.text), 1)
        pos = 0
        for p in s.text.split("     "):
            if p.strip():
                a = s.x0 + (s.x1 - s.x0) * pos / total
                b = s.x0 + (s.x1 - s.x0) * (pos + len(p)) / total
                out.append(Segment(" ".join(p.split()), a, s.y0, b, s.y1))
            pos += len(p) + 5
    return out


# ---------------------------------------------------------------------------
# OCR (RapidOCR, fully offline)
# ---------------------------------------------------------------------------
_OCR_ENGINE = None
_OCR_ERROR: str | None = None


def ocr_available() -> tuple[bool, str]:
    eng = _get_ocr()
    return (eng is not None, _OCR_ERROR or "")


def _get_ocr():
    global _OCR_ENGINE, _OCR_ERROR
    if _OCR_ENGINE is not None or _OCR_ERROR is not None:
        return _OCR_ENGINE
    import sys

    if sys.platform == "emscripten":
        _OCR_ERROR = "OCR is not available in the web version (use the Windows installation for scanned PDFs)"
        return None
    try:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore

        _OCR_ENGINE = RapidOCR()
    except Exception as exc:  # pragma: no cover - depends on install
        _OCR_ERROR = f"OCR engine not available: {exc}"
        log.warning(_OCR_ERROR)
    return _OCR_ENGINE


def _segments_from_ocr(page: pymupdf.Page, dpi: int) -> list[Segment]:
    eng = _get_ocr()
    if eng is None:
        raise RuntimeError(_OCR_ERROR or "OCR engine not available")
    pix = page.get_pixmap(dpi=dpi)
    img = pix.tobytes("png")
    result, _ = eng(img)
    scale = 72.0 / dpi
    segs: list[Segment] = []
    for box, text, _score in result or []:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        t = " ".join(str(text).split())
        if t:
            segs.append(Segment(t, min(xs) * scale, min(ys) * scale, max(xs) * scale, max(ys) * scale))
    return segs


def _compose_text(segs: list[Segment]) -> str:
    """Reading-order text: rows top-to-bottom, segments left-to-right."""
    if not segs:
        return ""
    ordered = sorted(segs, key=lambda s: (s.y0, s.x0))
    rows: list[list[Segment]] = []
    for s in ordered:
        if rows and abs(rows[-1][0].y0 - s.y0) < max(3.0, s.h * 0.4):
            rows[-1].append(s)
        else:
            rows.append([s])
    return "\n".join("   ".join(x.text for x in sorted(r, key=lambda s: s.x0)) for r in rows)


def read_page(page: pymupdf.Page, settings: dict, force_ocr: bool = False) -> PageContent:
    pc = PageContent(page_index=page.number, width=page.rect.width, height=page.rect.height)
    segs = [] if force_ocr else _segments_from_text_layer(page)
    text_chars = sum(len(s.text) for s in segs)
    if segs and text_chars >= int(settings.get("ocr_min_chars", 40)):
        pc.segments, pc.source = segs, "text"
    elif settings.get("ocr_enabled", True):
        try:
            osegs = _segments_from_ocr(page, int(settings.get("ocr_dpi", 200)))
            if osegs:
                pc.segments, pc.source = osegs, "ocr"
                pc.notes.append("Text read by OCR (scanned page) — verify values carefully.")
            elif segs:
                pc.segments, pc.source = segs, "text"
        except Exception as exc:
            pc.notes.append(f"OCR failed: {exc}")
            if segs:
                pc.segments, pc.source = segs, "text"
    elif segs:
        pc.segments, pc.source = segs, "text"
    else:
        pc.notes.append("Page has no text layer and OCR is disabled in Settings.")
    pc.text = _compose_text(pc.segments)
    return pc


def page_has_images(page: pymupdf.Page) -> bool:
    try:
        return bool(page.get_images(full=False))
    except Exception:
        return False
