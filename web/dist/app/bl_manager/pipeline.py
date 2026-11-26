"""Batch processing pipeline: upload -> pages -> BLs -> fields -> classification."""
from __future__ import annotations

import json
import time
import traceback
from pathlib import Path
from typing import Callable

import pymupdf

from . import db
from .classification import classify
from .consol import compare_containers
from .constants import FOLDERS, MANUAL_REVIEW
from .extraction import extract_document
from .normalize import safe_filename
from .page_parser import parse_page
from .pdf_reader import PageContent, page_has_images, read_page
from .reconstruction import PageRef, reconstruct

ProgressFn = Callable[[float, str], None]


def _noop(_f: float, _m: str) -> None:
    pass


def process_batch(
    batch_name: str,
    files: list[tuple[str, bytes]],
    mode: str,
    progress: ProgressFn | None = None,
) -> int:
    """Process uploaded PDFs as one batch. Returns the batch id.

    mode: "combined" (one PDF with many BLs) or "individual" (many PDFs).
    Both modes run through exactly the same engine.
    """
    progress = progress or _noop
    db.init_db()
    settings = db.get_settings()
    t0 = time.time()
    bid, bdir = db.create_batch(batch_name, mode)

    # ---------------- 1. Store source files and count pages ----------------
    opened: list[tuple[int, str, pymupdf.Document]] = []
    total_pages = 0
    for i, (fname, data) in enumerate(files):
        stored = bdir / "source" / f"{i + 1:03d}_{safe_filename(fname)}"
        stored.write_bytes(data)
        fid = db.add_source_file(bid, fname, str(stored))
        try:
            d = pymupdf.open(stored)
            if d.needs_pass and not d.authenticate(""):
                raise RuntimeError("PDF is password-protected")
            if d.page_count == 0:
                raise RuntimeError("PDF contains no pages")
            opened.append((fid, fname, d))
            total_pages += d.page_count
            db.update_source_file(fid, d.page_count, None)
        except Exception as exc:
            db.update_source_file(fid, 0, str(exc))
            db.add_error(bid, fname, None, "open", f"Could not open PDF: {exc}")

    # ---------------- 2. Read and identify every page ----------------
    page_refs: list[PageRef] = []
    contents: dict[int, PageContent] = {}
    page_rows: list[dict] = []
    gi = 0
    ocr_pages = 0
    for fid, fname, d in opened:
        for pidx in range(d.page_count):
            progress(0.05 + 0.75 * gi / max(total_pages, 1), f"Reading {fname} — page {pidx + 1} of {d.page_count}")
            issues: list[str] = []
            pc = PageContent(page_index=pidx)
            try:
                page = d.load_page(pidx)
                pc = read_page(page, settings)
                info = parse_page(pc, settings)
                # Text layer present but no BL number: try OCR in case the text layer is partial.
                if (
                    info.bl_number is None and pc.source == "text" and settings.get("ocr_enabled", True)
                    and page_has_images(page)
                ):
                    pc2 = read_page(page, settings, force_ocr=True)
                    info2 = parse_page(pc2, settings)
                    if info2.bl_number:
                        pc, info = pc2, info2
                        pc.notes.append("Text layer had no BL number; page re-read with OCR.")
                issues.extend(info.issues)
                issues.extend(n for n in pc.notes if n.startswith(("OCR failed", "Page has no text")))
                if pc.source == "ocr":
                    ocr_pages += 1
            except Exception as exc:
                info = parse_page(pc, settings)
                issues.append(f"Page could not be read: {exc}")
                db.add_error(bid, fname, pidx, "read", f"{exc}\n{traceback.format_exc(limit=2)}")
            if not pc.segments:
                issues.append("No text could be read from this page.")
            ref = PageRef(gi, fid, fname, pidx, info.bl_number, info.page_no, info.page_total, issues)
            ref.hbl_values = info.hbl_values  # type: ignore[attr-defined]
            ref.warnings = info.warnings + [n for n in pc.notes if n not in issues]  # type: ignore[attr-defined]
            ref.bl_snippet = info.bl_snippet  # type: ignore[attr-defined]
            ref.page_snippet = info.page_snippet  # type: ignore[attr-defined]
            page_refs.append(ref)
            contents[gi] = pc
            page_rows.append({
                "batch_id": bid, "file_id": fid, "page_index": pidx, "global_index": gi,
                "bl_number": info.bl_number, "page_no": info.page_no, "page_total": info.page_total,
                "text_source": pc.source, "issues_json": json.dumps(issues), "doc_id": None,
                "text": pc.text[:20000],
            })
            gi += 1

    # ---------------- 3. Reconstruct BLs ----------------
    progress(0.82, "Reconstructing individual BLs and validating page sequences")
    groups = reconstruct(page_refs, settings)
    file_docs = {fid: d for fid, _n, d in opened}

    docs: list[dict] = []
    used_names: set[str] = set()
    for idx, g in enumerate(groups):
        fname = safe_filename(g.doc_key)
        base, n = fname, 2
        while fname.lower() in used_names:
            fname = f"{base}_{n}"
            n += 1
        used_names.add(fname.lower())
        out_path = bdir / "bls" / f"{fname}.pdf"
        try:
            out = pymupdf.open()
            for p in g.pages:
                out.insert_pdf(file_docs[p.file_id], from_page=p.page_index, to_page=p.page_index)
            out.save(out_path, garbage=3, deflate=True)
            out.close()
        except Exception as exc:
            db.add_error(bid, g.doc_key, None, "reconstruct", f"Could not write PDF: {exc}")
            g.issues.append({"code": "PDF_WRITE_FAILED", "detected": str(exc),
                             "why": "The reconstructed PDF could not be written.", "verify": "Check the source file."})

        pcs = [contents[p.global_index] for p in g.pages]
        hbl_vals = sorted({v for p in g.pages for v in getattr(p, "hbl_values", [])})
        try:
            fields, containers, ext_warn = extract_document(pcs, g.bl_number, hbl_vals)
        except Exception as exc:
            db.add_error(bid, g.doc_key, None, "extract", f"{exc}\n{traceback.format_exc(limit=3)}")
            fields, containers, ext_warn = {}, [], [f"Extraction failed: {exc}"]
        page_warn = [f"{p.label}: {w}" for p in g.pages for w in getattr(p, "warnings", [])]
        fields["_meta"] = {"base_warnings": list(dict.fromkeys(g.warnings + page_warn + ext_warn)),
                           "extracted_containers": containers}

        docs.append({
            "batch_id": bid,
            "sort_index": idx,
            "doc_key": g.doc_key,
            "bl_number": g.bl_number,
            "file_name": f"{fname}.pdf",
            "pdf_path": str(out_path),
            "page_count": len(g.pages),
            "source_pages": [
                {"file": p.file_name, "page": p.page_index + 1, "printed": (f"{p.page_no} of {p.page_total}" if p.page_no else None),
                 "text_source": contents[p.global_index].source, "global_index": p.global_index}
                for p in g.pages
            ],
            "recon_issues": g.issues,
            "fields": fields,
            "containers": containers,
            "ocr_used": any(contents[p.global_index].source == "ocr" for p in g.pages),
        })

    # ---------------- 4. Classify (batch-level) ----------------
    progress(0.92, "Comparing every container across the batch and classifying")
    consol_info = run_classification(docs, settings)

    # ---------------- 5. Save ----------------
    progress(0.97, "Saving results")
    gidx_to_doc = {}
    for d in docs:
        d["current_class"] = d["auto_class"]
        d["manually_changed"] = False
        doc_id = db.insert_document(d)
        for sp in d["source_pages"]:
            gidx_to_doc[sp["global_index"]] = doc_id
    for r in page_rows:
        r["doc_id"] = gidx_to_doc.get(r["global_index"])
    db.insert_pages(page_rows)
    for _fid, _n, d in opened:
        d.close()

    report = build_report(bid, docs, consol_info, total_pages, ocr_pages, time.time() - t0)
    status = "completed" if opened else "failed"
    db.finish_batch(bid, status, total_pages, report)
    db.log(bid, None, "processed", f"{len(docs)} documents from {total_pages} pages")
    progress(1.0, "Done")
    return bid


def run_classification(docs: list[dict], settings: dict) -> dict:
    """Run the batch-level container comparison and classify every doc (in place)."""
    forwarders = db.list_forwarders()
    consol_info = compare_containers(docs)
    for d in docs:
        d["extract_warnings"] = (d.get("fields") or {}).get("_meta", {}).get("base_warnings", [])
        res = classify(d, consol_info, settings, forwarders)
        d.update(res)
        cons = [{"container": l["container"], "shared_with": l["shared_with"]}
                for l in consol_info["per_doc"].get(d["doc_key"], [])]
        group = next((g for g in consol_info["groups"] if d.get("bl_number") in g["bls"]), None)
        d["consol"] = {"links": cons, "group": group} if cons else []
        d.pop("extract_warnings", None)
    return consol_info


def build_report(bid, docs, consol_info, total_pages, ocr_pages, seconds) -> dict:
    counts = {f: 0 for f in FOLDERS}
    for d in docs:
        counts[d.get("current_class") or d.get("auto_class") or MANUAL_REVIEW] += 1
    return {
        "total_pages": total_pages,
        "pages_ocr": ocr_pages,
        "documents": len(docs),
        "identified_bls": sum(1 for d in docs if d.get("bl_number")),
        "unidentified_docs": sum(1 for d in docs if not d.get("bl_number")),
        "complete_bls": sum(1 for d in docs if d.get("bl_number") and not d.get("recon_issues")),
        "auto_counts": counts,
        "consol_stats": consol_info["stats"],
        "consol_groups": consol_info["groups"],
        "near_matches": consol_info["near_matches"],
        "seconds": round(seconds, 1),
        "errors": len(db.list_errors(bid)),
    }


def reclassify_batch(bid: int) -> dict:
    """Re-run classification for a whole batch (needed after edits or list
    changes, because CONSOL is a batch-level relationship). Manual
    classifications are kept; their automated result is updated alongside."""
    settings = db.get_settings()
    docs = db.list_documents(bid)
    consol_info = run_classification(docs, settings)
    for d in docs:
        upd = dict(
            auto_class=d["auto_class"], auto_reasons=d["auto_reasons"], indicators=d["indicators"],
            review_reasons=d["review_reasons"], warnings=d["warnings"], consol=d["consol"],
        )
        if not d["manually_changed"]:
            upd["current_class"] = d["auto_class"]
        db.update_document(d["id"], **upd)
    b = db.get_batch(bid)
    rep = (b or {}).get("report", {})
    rep["consol_stats"] = consol_info["stats"]
    rep["consol_groups"] = consol_info["groups"]
    rep["near_matches"] = consol_info["near_matches"]
    db.update_batch_report(bid, rep)
    db.log(bid, None, "reclassified", "Classification re-run for the whole batch")
    return consol_info


def change_classification(doc_id: int, new_class: str, note: str = "") -> dict:
    d = db.get_document(doc_id)
    if not d:
        raise ValueError("Document not found")
    old = d["current_class"]
    manual = new_class != d["auto_class"]
    db.update_document(doc_id, current_class=new_class, manually_changed=manual,
                       change_note=note, changed_at=db.now())
    db.log(d["batch_id"], doc_id, "classification_changed",
           f"{d['doc_key']}: {old} -> {new_class}" + (f" ({note})" if note else ""))
    return db.get_document(doc_id)


def update_fields(doc_id: int, edits: dict[str, str | None], verified: dict[str, bool]) -> None:
    """Store user corrections separately from the extracted values."""
    d = db.get_document(doc_id)
    fields = d["fields"]
    changes = []
    for k, v in edits.items():
        f = fields.setdefault(k, {"values": [], "status": "missing", "user_value": None, "verified": False})
        v = (v or "").strip() or None
        if v != f.get("user_value"):
            changes.append(f"{k}: {f.get('user_value')!r} -> {v!r}")
            f["user_value"] = v
    for k, flag in verified.items():
        if k in fields and fields[k].get("verified") != flag:
            fields[k]["verified"] = flag
            changes.append(f"{k} verified={flag}")
    upd = {"fields": fields}
    if "containers" in edits:
        cval = fields["containers"].get("user_value")
        if cval is not None or edits["containers"] is not None:
            from .normalize import container_check_digit_ok, normalize_container

            if cval:
                items = [normalize_container(x) for x in cval.replace(",", "\n").split("\n") if x.strip()]
                upd["containers"] = [
                    {"container": c, "raw": c, "pages": [], "occurrences": 1,
                     "check_digit_ok": container_check_digit_ok(c), "snippet": "entered by user"}
                    for c in dict.fromkeys(items)
                ]
            else:
                upd["containers"] = fields.get("_meta", {}).get("extracted_containers", d["containers"])
    db.update_document(doc_id, **upd)
    if changes:
        db.log(d["batch_id"], doc_id, "fields_edited", "; ".join(changes))
