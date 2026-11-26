"""Downloads and copy formats: single PDFs, folder ZIP/PDF, full ZIP, TSV/Excel."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd
import pymupdf

from .constants import FIELD_LABELS, FIELDS, FOLDER_DIRS, FOLDER_LABELS, FOLDERS, NOT_EXTRACTED
from .extraction import display_value

ROOT_DIR = "BL_Manager_Results"


def doc_values(d: dict) -> dict[str, str]:
    """Display value for every field (user correction wins over extraction)."""
    out = {}
    for key, _label in FIELDS:
        if key == "bl_number" and d.get("bl_number"):
            out[key] = d["bl_number"]
        else:
            out[key] = display_value(d["fields"].get(key))
    return out


def summary_rows(docs: list[dict]) -> list[dict]:
    rows = []
    for d in docs:
        v = doc_values(d)
        consol = d.get("consol") or {}
        links = consol.get("links", []) if isinstance(consol, dict) else []
        rows.append({
            "Document": d["doc_key"],
            "Folder": FOLDER_LABELS.get(d["current_class"], d["current_class"]),
            "Automated Classification": FOLDER_LABELS.get(d["auto_class"], d["auto_class"]),
            "Manually Changed": "Yes" if d["manually_changed"] else "No",
            **{FIELD_LABELS[k]: v[k] for k, _ in FIELDS},
            "Shared Containers (CONSOL)": "; ".join(
                f"{l['container']} with {', '.join(l['shared_with'])}" for l in links
            ),
            "Classification Reason": " ".join(d.get("auto_reasons") or []),
            "Review Reasons": " | ".join(r["detected"] for r in d.get("review_reasons") or []),
            "Pages": d["page_count"],
            "Source Pages": ", ".join(f"{p['file']} p.{p['page']}" for p in d.get("source_pages") or []),
            "File Name": d["file_name"],
        })
    return rows


def _tsv_cell(x) -> str:
    s = "" if x is None else str(x)
    return s.replace("\t", " ").replace("\r", " ").replace("\n", " | ")


def to_tsv(docs: list[dict]) -> str:
    rows = summary_rows(docs)
    if not rows:
        return ""
    cols = list(rows[0].keys())
    lines = ["\t".join(cols)]
    for r in rows:
        lines.append("\t".join(_tsv_cell(r[c]) for c in cols))
    return "\n".join(lines)


def to_excel(docs: list[dict]) -> bytes:
    buf = io.BytesIO()
    df = pd.DataFrame(summary_rows(docs))
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.to_excel(xw, index=False, sheet_name="BLs")
        ws = xw.sheets["BLs"]
        for i, col in enumerate(df.columns, start=1):
            width = min(60, max(12, int(df[col].astype(str).str.len().quantile(0.9) if len(df) else 12)))
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = width
        ws.freeze_panes = "B2"
    return buf.getvalue()


def doc_text(d: dict) -> str:
    """'Copy all' text for one BL."""
    v = doc_values(d)
    lines = [
        f"BL Number: {v['bl_number']}",
        f"Classification: {FOLDER_LABELS.get(d['current_class'])}"
        + (" (changed manually)" if d["manually_changed"] else ""),
        f"Classification Reason: {' '.join(d.get('auto_reasons') or [])}",
    ]
    for key, label in FIELDS:
        if key == "bl_number":
            continue
        val = v[key]
        if "\n" in val:
            lines.append(f"{label}:")
            lines.extend(f"  {x}" for x in val.split("\n"))
        else:
            lines.append(f"{label}: {val}")
    return "\n".join(lines)


def folder_zip(docs: list[dict], folder: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for d in docs:
            if d["current_class"] == folder and Path(d["pdf_path"]).exists():
                z.write(d["pdf_path"], f"{FOLDER_DIRS[folder]}/{d['file_name']}")
    return buf.getvalue()


def folder_combined_pdf(docs: list[dict], folder: str) -> bytes:
    out = pymupdf.open()
    for d in docs:
        if d["current_class"] == folder and Path(d["pdf_path"]).exists():
            with pymupdf.open(d["pdf_path"]) as src:
                out.insert_pdf(src)
    data = out.tobytes(garbage=3, deflate=True) if out.page_count else b""
    out.close()
    return data


def full_zip(docs: list[dict], include_summary: bool = True) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in FOLDERS:
            # Ensure every folder exists in the archive even when empty.
            z.writestr(f"{ROOT_DIR}/{FOLDER_DIRS[f]}/", "")
        for d in docs:
            if Path(d["pdf_path"]).exists():
                z.write(d["pdf_path"], f"{ROOT_DIR}/{FOLDER_DIRS[d['current_class']]}/{d['file_name']}")
        if include_summary and docs:
            z.writestr(f"{ROOT_DIR}/BL_extraction_summary.xlsx", to_excel(docs))
    return buf.getvalue()
