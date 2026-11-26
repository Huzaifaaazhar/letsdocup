"""Group pages into individual BL documents and validate each group.

Pages are grouped by their COMPLETE BL number (across the whole batch,
not just neighbouring pages), then the page numbering of every group is
validated. Nothing is silently attached: pages with no readable BL number
become their own "UNIDENTIFIED" documents for Manual Review.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PageRef:
    global_index: int          # position in the whole batch (0-based)
    file_id: int
    file_name: str
    page_index: int            # 0-based within its file
    bl_number: str | None
    page_no: int | None
    page_total: int | None
    issues: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.file_name} p.{self.page_index + 1}"


@dataclass
class DocGroup:
    doc_key: str
    bl_number: str | None
    pages: list[PageRef]                 # in reconstructed order
    issues: list[dict] = field(default_factory=list)   # review reasons
    warnings: list[str] = field(default_factory=list)


def _reason(code: str, detected: str, why: str, verify: str) -> dict:
    return {"code": code, "detected": detected, "why": why, "verify": verify}


def reconstruct(pages: list[PageRef], settings: dict) -> list[DocGroup]:
    groups: dict[str, list[PageRef]] = {}
    order: list[tuple[int, str]] = []        # (first global index, key) to keep batch order
    unidentified: list[list[PageRef]] = []

    for p in pages:
        if p.bl_number:
            if p.bl_number not in groups:
                groups[p.bl_number] = []
                order.append((p.global_index, p.bl_number))
            groups[p.bl_number].append(p)
        else:
            # Consecutive unidentified pages from the same file are kept together.
            if (
                unidentified
                and unidentified[-1][-1].global_index == p.global_index - 1
                and unidentified[-1][-1].file_id == p.file_id
                and not (p.page_no == 1)
            ):
                unidentified[-1].append(p)
            else:
                unidentified.append([p])

    by_index = {p.global_index: p for p in pages}
    docs: list[tuple[int, DocGroup]] = []

    for first_idx, bl in order:
        grp = groups[bl]
        doc = DocGroup(doc_key=bl, bl_number=bl, pages=list(grp))
        _validate_group(doc, settings)
        docs.append((first_idx, doc))

    for run in unidentified:
        first = run[0]
        key = f"UNIDENTIFIED_{_stem(first.file_name)}_p{first.page_index + 1}"
        if len(run) > 1:
            key += f"-{run[-1].page_index + 1}"
        doc = DocGroup(doc_key=key, bl_number=None, pages=run)
        prev = by_index.get(first.global_index - 1)
        nxt = by_index.get(run[-1].global_index + 1)
        context = []
        if prev and prev.bl_number:
            context.append(f"previous page belongs to BL {prev.bl_number}")
        if nxt and nxt.bl_number:
            context.append(f"next page belongs to BL {nxt.bl_number}")
        numbering = ", ".join(
            f"{p.label}: page {p.page_no} of {p.page_total}" if p.page_no else f"{p.label}: no page numbering"
            for p in run
        )
        doc.issues.append(_reason(
            "BL_NUMBER_NOT_FOUND",
            f"No complete BL number could be read on {', '.join(p.label for p in run)} ({numbering}).",
            "Without the BL number the application cannot prove which BL these pages belong to, "
            "so they were NOT attached to any BL.",
            "Open the page(s) and check the BL number"
            + (f" ({'; '.join(context)})" if context else "")
            + ". Move the document to the correct folder once verified.",
        ))
        for p in run:
            for iss in p.issues:
                doc.warnings.append(f"{p.label}: {iss}")
        docs.append((first.global_index, doc))

    # BL number mismatch between consecutive pages that look like one BL
    # (e.g. page "1 of 2" of BL A followed by page "2 of 2" of BL B).
    doc_by_bl = {d.bl_number: d for _, d in docs if d.bl_number}
    for p, q in zip(pages, pages[1:]):
        if (
            p.bl_number and q.bl_number and p.bl_number != q.bl_number
            and p.file_id == q.file_id
            and p.page_no is not None and q.page_no is not None
            and p.page_total is not None and p.page_no < p.page_total
            and q.page_no == p.page_no + 1 and q.page_total == p.page_total
        ):
            for bl in (p.bl_number, q.bl_number):
                doc_by_bl[bl].issues.append(_reason(
                    "BL_NUMBER_MISMATCH",
                    f"{p.label} (BL {p.bl_number}, page {p.page_no} of {p.page_total}) is followed by "
                    f"{q.label} (BL {q.bl_number}, page {q.page_no} of {q.page_total}).",
                    "The page sequence suggests one BL, but the BL number changes between the pages. "
                    "The pages were NOT merged.",
                    "Check the BL number printed on both pages; one of them may be misprinted or misread.",
                ))

    docs.sort(key=lambda t: t[0])
    return [d for _, d in docs]


def _stem(name: str) -> str:
    return name.rsplit(".", 1)[0]


def _validate_group(doc: DocGroup, settings: dict) -> None:
    pages = doc.pages
    bl = doc.bl_number
    labels = ", ".join(p.label for p in pages)

    # Page-level parsing issues carry through.
    for p in pages:
        for iss in p.issues:
            doc.issues.append(_reason(
                "PAGE_READ_ISSUE", f"{p.label}: {iss}",
                "The page could not be read unambiguously.",
                "Check the BL number and page numbering printed on this page.",
            ))

    numbered = [p for p in pages if p.page_no is not None]
    unnumbered = [p for p in pages if p.page_no is None]

    # Reconstructed order: by printed page number; unnumbered pages keep
    # their source position after numbered ones.
    pages_sorted = sorted(numbered, key=lambda p: (p.page_no, p.global_index)) + sorted(
        unnumbered, key=lambda p: p.global_index
    )
    doc.pages = pages_sorted

    if unnumbered:
        if len(pages) == 1 and settings.get("accept_single_page_without_numbering"):
            doc.warnings.append("Single page without 'Page x of y' — accepted as a 1-page BL (Settings).")
        else:
            doc.issues.append(_reason(
                "PAGE_NUMBERING_MISSING",
                f"No page numbering ('Page x of y') found on: {', '.join(p.label for p in unnumbered)}.",
                "The application cannot confirm the BL is complete without page numbering.",
                f"Confirm that BL {bl} has exactly {len(pages)} page(s) and that none is missing.",
            ))

    totals = {p.page_total for p in numbered}
    if len(totals) > 1:
        doc.issues.append(_reason(
            "PAGE_TOTAL_INCONSISTENT",
            f"Pages of BL {bl} state different totals: "
            + ", ".join(f"{p.label} says {p.page_no} of {p.page_total}" for p in numbered) + ".",
            "The total page count printed on the pages does not agree, so completeness cannot be confirmed.",
            "Check whether pages from another BL or another version of this BL were mixed in.",
        ))
    expected = max(totals) if totals else None

    nos = [p.page_no for p in numbered]
    dups = sorted({n for n in nos if nos.count(n) > 1})
    if dups:
        doc.issues.append(_reason(
            "DUPLICATE_PAGE",
            f"BL {bl}: page number(s) {', '.join(map(str, dups))} appear more than once ({labels}).",
            "The same BL page was found twice (duplicate upload or two versions of the BL).",
            "Compare the duplicate pages and keep the correct version.",
        ))

    if expected:
        missing = [n for n in range(1, expected + 1) if n not in nos]
        if missing:
            doc.issues.append(_reason(
                "MISSING_PAGE",
                f"BL {bl} says it has {expected} page(s) but page(s) {', '.join(map(str, missing))} were not found.",
                "The reconstructed BL is incomplete.",
                "Locate the missing page(s) in the source document. If the page exists but its BL number "
                "was unreadable, it is listed separately as an UNIDENTIFIED document in Manual Review.",
            ))
        extra = [n for n in nos if n > expected]
        if extra:
            doc.issues.append(_reason(
                "PAGE_OUT_OF_RANGE",
                f"BL {bl}: page number(s) {', '.join(map(str, extra))} exceed the stated total of {expected}.",
                "Page numbering is inconsistent.",
                "Check the page numbering printed on each page.",
            ))

    # Pages should be contiguous and in printed order in the source.
    src_order = sorted(pages, key=lambda p: p.global_index)
    gidx = [p.global_index for p in src_order]
    contiguous = all(b - a == 1 for a, b in zip(gidx, gidx[1:])) and len({p.file_id for p in pages}) == 1
    if not contiguous:
        doc.issues.append(_reason(
            "PAGES_NOT_CONTIGUOUS",
            f"Pages of BL {bl} were found at separate positions in the upload: {', '.join(p.label for p in src_order)}.",
            "BL pages normally follow each other. Separated pages may indicate a duplicate BL, "
            "a mis-scanned page or two BLs sharing a number.",
            "Check that every page really belongs to this BL.",
        ))
    elif numbered and [p.page_no for p in src_order if p.page_no is not None] != sorted(nos):
        doc.warnings.append(
            "Pages were out of order in the source; the reconstructed PDF follows the printed page numbers."
        )
