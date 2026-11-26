"""Generate SYNTHETIC Bill of Lading PDFs for testing.

These documents are clearly marked as synthetic test documents. They
imitate the general box layout of an ocean Bill of Lading (labels in small
print, values underneath) so the engine can be tested without using real,
confidential BLs. They are NEVER used by the application itself.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import pymupdf
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

W, H = A4
LABEL_FONT = ("Helvetica", 6.5)
VALUE_FONT = ("Helvetica", 8.5)


@dataclass
class SynthBL:
    bl: str
    consignee: list[str]
    shipper: list[str] = field(default_factory=lambda: ["GLOBAL TEXTILE EXPORTS CO., LTD.", "NO. 88 HUAIHAI ROAD", "SHANGHAI 200000, CHINA"])
    notify: list[str] = field(default_factory=lambda: ["SAME AS CONSIGNEE"])
    pol: str = "SHANGHAI, CHINA"
    pod: str = "KARACHI, PAKISTAN"
    containers: list[str] = field(default_factory=list)
    packages: str = "1,200 BAGS"
    description: list[str] = field(default_factory=lambda: ["COTTON YARN 100% COMBED", "NE 30/1"])
    hs_codes: list[str] = field(default_factory=lambda: ["5205.12"])
    net_weight: str | None = "18,000.000 KGS"
    gross_weight: str | None = "18,500.000 KGS"
    hbl: str | None = None
    pages: int = 1
    # Optional overrides for error scenarios
    page_numbers: list[tuple[int, int] | None] | None = None   # per page (no, total) or None = omit
    bl_per_page: list[str | None] | None = None                # per page BL number (None = omit)
    blank_consignee: bool = False


def _label(c, x, y, text):
    c.setFont(*LABEL_FONT)
    c.drawString(x, H - y, text)


def _value(c, x, y, text, size=None):
    c.setFont(VALUE_FONT[0], size or VALUE_FONT[1])
    c.drawString(x, H - y, text)


def _box(c, x0, y0, x1, y1):
    c.setLineWidth(0.5)
    c.rect(x0, H - y1, x1 - x0, y1 - y0)


def _draw_page(c, b: SynthBL, pno: int, total: int):
    bl_here = b.bl if b.bl_per_page is None else b.bl_per_page[pno - 1]
    numbering = (pno, total) if b.page_numbers is None else b.page_numbers[pno - 1]

    c.setFont("Helvetica-Bold", 12)
    c.drawString(30, H - 30, "BILL OF LADING" if pno == 1 else "BILL OF LADING - ATTACHED SHEET")
    c.setFont("Helvetica", 6)
    c.drawString(30, H - 40, "SYNTHETIC TEST DOCUMENT - NOT A REAL BILL OF LADING")
    if numbering:
        _value(c, 480, 30, f"Page {numbering[0]} of {numbering[1]}")

    # B/L number box (every page)
    _box(c, 300, 50, 565, 80)
    _label(c, 304, 58, "B/L No.")
    if bl_here:
        _value(c, 304, 72, bl_here, 10)

    # Split containers: page 1 shows up to 3, rest on continuation pages.
    conts = b.containers
    per_page = 3 if total > 1 else len(conts)
    if pno == 1:
        my_conts = conts[:per_page]
    else:
        rest = conts[per_page:]
        chunk = max(1, -(-len(rest) // max(1, total - 1))) if rest else 0
        my_conts = rest[(pno - 2) * chunk:(pno - 1) * chunk] if chunk else []

    if pno == 1:
        _box(c, 30, 50, 300, 130)
        _label(c, 34, 58, "Shipper / Exporter")
        for i, line in enumerate(b.shipper):
            _value(c, 34, 72 + i * 11, line)

        _box(c, 30, 130, 300, 215)
        _label(c, 34, 138, "Consignee (not negotiable unless consigned to order)")
        if not b.blank_consignee:
            for i, line in enumerate(b.consignee):
                _value(c, 34, 152 + i * 11, line)

        _box(c, 30, 215, 300, 290)
        _label(c, 34, 223, "Notify Party (complete name and address)")
        for i, line in enumerate(b.notify):
            _value(c, 34, 237 + i * 11, line)

        _box(c, 300, 80, 565, 110)
        _label(c, 304, 88, "Booking No.")
        _value(c, 304, 102, "SHAB" + b.bl[-8:])
        if b.hbl:
            _box(c, 300, 110, 565, 140)
            _label(c, 304, 118, "HBL No.")
            _value(c, 304, 132, b.hbl)
        _box(c, 300, 140, 565, 290)
        _label(c, 304, 148, "Export References")
        _value(c, 304, 162, "INV-2026-0091")

        # Routing rows
        for (x0, x1, lab, val) in [
            (30, 165, "Pre-carriage by", ""),
            (165, 300, "Place of Receipt", b.pol),
            (300, 432, "Ocean Vessel / Voyage No.", "ONE SYNTHETIC 001W"),
            (432, 565, "Port of Loading", b.pol),
        ]:
            _box(c, x0, 290, x1, 320)
            _label(c, x0 + 4, 298, lab)
            if val:
                _value(c, x0 + 4, 312, val)
        for (x0, x1, lab, val) in [
            (30, 165, "Port of Discharge", b.pod),
            (165, 300, "Place of Delivery", b.pod),
            (300, 565, "Final Destination (for merchant's reference only)", ""),
        ]:
            _box(c, x0, 320, x1, 350)
            _label(c, x0 + 4, 328, lab)
            if val:
                _value(c, x0 + 4, 342, val)
        top = 350
    else:
        top = 100

    # Particulars table
    _box(c, 30, top, 565, top + 18)
    for x, lab in [(33, "Container No./Seal No."), (175, "No. of Pkgs"), (250, "Description of Goods"),
                   (440, "Gross Weight"), (510, "Measurement")]:
        _label(c, x, top + 11, lab)
    y = top + 30
    for i, cn in enumerate(my_conts):
        _value(c, 33, y + i * 22, cn)
        _value(c, 33, y + i * 22 + 10, f"SEAL: SL{100000 + i * 7 + pno}", 7)
    if pno == 1:
        _value(c, 175, y, b.packages)
        lines = list(b.description)
        if b.hs_codes:
            lines.append("HS CODE: " + ", ".join(b.hs_codes))
        if b.net_weight:
            lines.append(f"NET WEIGHT: {b.net_weight}")
        for i, line in enumerate(lines):
            _value(c, 250, y + i * 11, line)
        if b.gross_weight:
            _value(c, 440, y, b.gross_weight)
        _value(c, 510, y, "45.000 CBM")
    else:
        _value(c, 250, y, "CONTINUED FROM PAGE 1")

    # Footer
    _box(c, 30, 720, 300, 800)
    _label(c, 34, 728, "Freight & Charges")
    _value(c, 34, 742, "FREIGHT PREPAID")
    _box(c, 300, 720, 565, 800)
    _label(c, 304, 728, "Place and Date of Issue")
    _value(c, 304, 742, "SHANGHAI 2026-11-01")


def bl_pages(c, b: SynthBL):
    for pno in range(1, b.pages + 1):
        _draw_page(c, b, pno, b.pages)
        c.showPage()


def make_pdf(bls: list[SynthBL], extra_blank_page_after: int | None = None) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for i, b in enumerate(bls):
        bl_pages(c, b)
        if extra_blank_page_after is not None and i == extra_blank_page_after:
            c.setFont("Helvetica", 9)
            c.drawString(60, H - 100, "Illegible scan")
            c.showPage()
    c.save()
    return buf.getvalue()


def rasterize(pdf_bytes: bytes, dpi: int = 150) -> bytes:
    """Turn a text PDF into an image-only ('scanned') PDF."""
    src = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    out = pymupdf.open()
    for page in src:
        pix = page.get_pixmap(dpi=dpi)
        np_ = out.new_page(width=page.rect.width, height=page.rect.height)
        np_.insert_image(np_.rect, stream=pix.tobytes("png"))
    data = out.tobytes()
    src.close()
    out.close()
    return data
