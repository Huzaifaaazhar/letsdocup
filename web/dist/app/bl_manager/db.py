"""SQLite persistence: settings, freight forwarders, batches, documents, audit log."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .constants import DEFAULT_SETTINGS
from .normalize import normalize_name

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    d = Path(os.environ.get("BLM_DATA_DIR", PROJECT_ROOT / "data"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return data_dir() / "bl_manager.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forwarders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    normalized TEXT NOT NULL UNIQUE,
    notes TEXT DEFAULT '',
    source TEXT DEFAULT 'manual',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    mode TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    dir TEXT NOT NULL,
    total_pages INTEGER DEFAULT 0,
    report_json TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS source_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    page_count INTEGER DEFAULT 0,
    error TEXT
);
CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES source_files(id) ON DELETE CASCADE,
    page_index INTEGER NOT NULL,
    global_index INTEGER NOT NULL,
    bl_number TEXT,
    page_no INTEGER,
    page_total INTEGER,
    text_source TEXT,
    issues_json TEXT DEFAULT '[]',
    doc_id INTEGER,
    text TEXT
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    sort_index INTEGER NOT NULL,
    doc_key TEXT NOT NULL,
    bl_number TEXT,
    file_name TEXT NOT NULL,
    pdf_path TEXT NOT NULL,
    source_pages_json TEXT NOT NULL,
    page_count INTEGER NOT NULL,
    recon_issues_json TEXT DEFAULT '[]',
    fields_json TEXT DEFAULT '{}',
    containers_json TEXT DEFAULT '[]',
    ocr_used INTEGER DEFAULT 0,
    auto_class TEXT,
    auto_reasons_json TEXT DEFAULT '[]',
    indicators_json TEXT DEFAULT '{}',
    review_reasons_json TEXT DEFAULT '[]',
    consol_json TEXT DEFAULT '[]',
    warnings_json TEXT DEFAULT '[]',
    current_class TEXT,
    manually_changed INTEGER DEFAULT 0,
    change_note TEXT,
    changed_at TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER REFERENCES batches(id) ON DELETE CASCADE,
    doc_id INTEGER,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS processing_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    file_name TEXT,
    page_index INTEGER,
    stage TEXT,
    message TEXT
);
CREATE INDEX IF NOT EXISTS idx_docs_batch ON documents(batch_id);
CREATE INDEX IF NOT EXISTS idx_pages_batch ON pages(batch_id);
"""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def connect():
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as c:
        c.executescript(SCHEMA)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def get_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    with connect() as c:
        for row in c.execute("SELECT key, value FROM settings"):
            try:
                s[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                pass
    return s


def save_settings(updates: dict) -> None:
    with connect() as c:
        for k, v in updates.items():
            c.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, json.dumps(v)),
            )


def reset_settings() -> None:
    with connect() as c:
        c.execute("DELETE FROM settings")


# ---------------------------------------------------------------------------
# Freight forwarders
# ---------------------------------------------------------------------------
def list_forwarders(search: str = "") -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT * FROM forwarders ORDER BY name COLLATE NOCASE").fetchall()
    out = [dict(r) for r in rows]
    if search:
        q = normalize_name(search)
        out = [r for r in out if q in r["normalized"] or search.lower() in r["name"].lower()]
    return out


def add_forwarder(name: str, notes: str = "", source: str = "manual") -> tuple[bool, str]:
    name = (name or "").strip()
    norm = normalize_name(name)
    if not norm:
        return False, "Name is empty."
    with connect() as c:
        existing = c.execute("SELECT name FROM forwarders WHERE normalized=?", (norm,)).fetchone()
        if existing:
            return False, f"Already in the list as '{existing['name']}'."
        c.execute(
            "INSERT INTO forwarders(name, normalized, notes, source, created_at) VALUES(?,?,?,?,?)",
            (name, norm, notes or "", source, now()),
        )
    return True, f"Added '{name}'."


def update_forwarder(fid: int, name: str, notes: str = "") -> tuple[bool, str]:
    name = (name or "").strip()
    norm = normalize_name(name)
    if not norm:
        return False, "Name is empty."
    with connect() as c:
        clash = c.execute(
            "SELECT name FROM forwarders WHERE normalized=? AND id<>?", (norm, fid)
        ).fetchone()
        if clash:
            return False, f"Another entry already exists: '{clash['name']}'."
        c.execute(
            "UPDATE forwarders SET name=?, normalized=?, notes=? WHERE id=?",
            (name, norm, notes or "", fid),
        )
    return True, "Saved."


def delete_forwarder(fid: int) -> None:
    with connect() as c:
        c.execute("DELETE FROM forwarders WHERE id=?", (fid,))


def delete_forwarder_by_name(name: str) -> bool:
    with connect() as c:
        cur = c.execute("DELETE FROM forwarders WHERE normalized=?", (normalize_name(name),))
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------
def create_batch(name: str, mode: str) -> tuple[int, Path]:
    with connect() as c:
        cur = c.execute(
            "INSERT INTO batches(name, mode, created_at, status, dir) VALUES(?,?,?,?,?)",
            (name, mode, now(), "processing", ""),
        )
        bid = cur.lastrowid
        bdir = data_dir() / "batches" / f"batch_{bid:05d}"
        (bdir / "source").mkdir(parents=True, exist_ok=True)
        (bdir / "bls").mkdir(parents=True, exist_ok=True)
        c.execute("UPDATE batches SET dir=? WHERE id=?", (str(bdir), bid))
    return bid, bdir


def finish_batch(bid: int, status: str, total_pages: int, report: dict) -> None:
    with connect() as c:
        c.execute(
            "UPDATE batches SET status=?, total_pages=?, report_json=? WHERE id=?",
            (status, total_pages, json.dumps(report), bid),
        )


def update_batch_report(bid: int, report: dict) -> None:
    with connect() as c:
        c.execute("UPDATE batches SET report_json=? WHERE id=?", (json.dumps(report), bid))


def list_batches() -> list[dict]:
    with connect() as c:
        rows = c.execute(
            "SELECT b.*, (SELECT COUNT(*) FROM documents d WHERE d.batch_id=b.id) AS doc_count "
            "FROM batches b ORDER BY b.id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_batch(bid: int) -> dict | None:
    with connect() as c:
        r = c.execute("SELECT * FROM batches WHERE id=?", (bid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["report"] = json.loads(d.get("report_json") or "{}")
    return d


def delete_batch(bid: int) -> None:
    b = get_batch(bid)
    with connect() as c:
        c.execute("DELETE FROM batches WHERE id=?", (bid,))
    if b and b.get("dir"):
        p = Path(b["dir"])
        # Only delete inside our own data directory.
        if p.exists() and data_dir() in p.resolve().parents:
            shutil.rmtree(p, ignore_errors=True)


def add_source_file(bid: int, filename: str, stored_path: str) -> int:
    with connect() as c:
        cur = c.execute(
            "INSERT INTO source_files(batch_id, filename, stored_path) VALUES(?,?,?)",
            (bid, filename, stored_path),
        )
        return cur.lastrowid


def update_source_file(fid: int, page_count: int, error: str | None) -> None:
    with connect() as c:
        c.execute("UPDATE source_files SET page_count=?, error=? WHERE id=?", (page_count, error, fid))


def list_source_files(bid: int) -> list[dict]:
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM source_files WHERE batch_id=? ORDER BY id", (bid,))]


def add_error(bid: int, file_name: str | None, page_index: int | None, stage: str, message: str) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO processing_errors(batch_id, file_name, page_index, stage, message) VALUES(?,?,?,?,?)",
            (bid, file_name, page_index, stage, message),
        )


def list_errors(bid: int) -> list[dict]:
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM processing_errors WHERE batch_id=? ORDER BY id", (bid,))]


def insert_pages(rows: list[dict]) -> None:
    with connect() as c:
        c.executemany(
            "INSERT INTO pages(batch_id, file_id, page_index, global_index, bl_number, page_no, page_total, "
            "text_source, issues_json, doc_id, text) VALUES(:batch_id,:file_id,:page_index,:global_index,"
            ":bl_number,:page_no,:page_total,:text_source,:issues_json,:doc_id,:text)",
            rows,
        )


def list_pages(bid: int) -> list[dict]:
    with connect() as c:
        rows = c.execute(
            "SELECT p.*, f.filename FROM pages p JOIN source_files f ON f.id=p.file_id "
            "WHERE p.batch_id=? ORDER BY p.global_index",
            (bid,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["issues"] = json.loads(d.pop("issues_json") or "[]")
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# Documents (reconstructed BLs)
# ---------------------------------------------------------------------------
_JSON_COLS = {
    "source_pages": "source_pages_json",
    "recon_issues": "recon_issues_json",
    "fields": "fields_json",
    "containers": "containers_json",
    "auto_reasons": "auto_reasons_json",
    "indicators": "indicators_json",
    "review_reasons": "review_reasons_json",
    "consol": "consol_json",
    "warnings": "warnings_json",
}


def _doc_from_row(r) -> dict:
    d = dict(r)
    for k, col in _JSON_COLS.items():
        d[k] = json.loads(d.pop(col) or ("{}" if k in ("fields", "indicators") else "[]"))
    d["manually_changed"] = bool(d["manually_changed"])
    d["ocr_used"] = bool(d["ocr_used"])
    return d


def insert_document(doc: dict) -> int:
    cols = {
        "batch_id": doc["batch_id"],
        "sort_index": doc["sort_index"],
        "doc_key": doc["doc_key"],
        "bl_number": doc.get("bl_number"),
        "file_name": doc["file_name"],
        "pdf_path": doc["pdf_path"],
        "page_count": doc["page_count"],
        "ocr_used": int(bool(doc.get("ocr_used"))),
        "auto_class": doc.get("auto_class"),
        "current_class": doc.get("current_class"),
        "manually_changed": int(bool(doc.get("manually_changed"))),
    }
    for k, col in _JSON_COLS.items():
        cols[col] = json.dumps(doc.get(k, {} if k in ("fields", "indicators") else []))
    names = ",".join(cols)
    marks = ",".join("?" for _ in cols)
    with connect() as c:
        cur = c.execute(f"INSERT INTO documents({names}) VALUES({marks})", list(cols.values()))
        return cur.lastrowid


def update_document(doc_id: int, **fields) -> None:
    sets, vals = [], []
    for k, v in fields.items():
        if k in _JSON_COLS:
            sets.append(f"{_JSON_COLS[k]}=?")
            vals.append(json.dumps(v))
        else:
            sets.append(f"{k}=?")
            vals.append(int(v) if isinstance(v, bool) else v)
    vals.append(doc_id)
    with connect() as c:
        c.execute(f"UPDATE documents SET {', '.join(sets)} WHERE id=?", vals)


def list_documents(bid: int) -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT * FROM documents WHERE batch_id=? ORDER BY sort_index", (bid,)).fetchall()
    return [_doc_from_row(r) for r in rows]


def get_document(doc_id: int) -> dict | None:
    with connect() as c:
        r = c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    return _doc_from_row(r) if r else None


def log(bid: int | None, doc_id: int | None, action: str, detail: str = "") -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO audit_log(batch_id, doc_id, ts, action, detail) VALUES(?,?,?,?,?)",
            (bid, doc_id, now(), action, detail),
        )


def list_log(bid: int, doc_id: int | None = None) -> list[dict]:
    with connect() as c:
        if doc_id is None:
            rows = c.execute("SELECT * FROM audit_log WHERE batch_id=? ORDER BY id DESC", (bid,))
        else:
            rows = c.execute("SELECT * FROM audit_log WHERE doc_id=? ORDER BY id DESC", (doc_id,))
        return [dict(r) for r in rows]
