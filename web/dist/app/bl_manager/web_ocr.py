"""OCR for the WEB version (Python running in the browser via Pyodide).

The desktop version uses RapidOCR (ONNX Runtime), which cannot run inside a
browser. In the browser we use Tesseract.js (Tesseract compiled to
WebAssembly). It runs locally in the visitor's browser: the page image is
never sent to a server. Only the OCR engine and its English language data
(~3 MB) are downloaded from the jsDelivr CDN on first use, then cached by the
browser.

The Python pipeline is synchronous, so the asynchronous JavaScript OCR call
is awaited with Pyodide's ``run_sync`` (WebAssembly JavaScript Promise
Integration). That requires a current Chrome or Edge browser.

This module must only be imported when ``sys.platform == "emscripten"``.
"""
from __future__ import annotations

import json

TESSERACT_JS = "https://cdn.jsdelivr.net/npm/tesseract.js@7.0.0/dist/tesseract.min.js"
WORKER_PATH = "https://cdn.jsdelivr.net/npm/tesseract.js@7.0.0/dist/worker.min.js"
CORE_PATH = "https://cdn.jsdelivr.net/npm/tesseract.js-core@7.0.0"
LANG_PATH = "https://cdn.jsdelivr.net/npm/@tesseract.js-data/eng@1.0.0/4.0.0_best_int"

_JS_HELPERS = """
self.__blmOcrInit = async function () {
  if (!self.__blmOcrWorker) {
    self.__blmOcrWorker = await Tesseract.createWorker('eng', 1, {
      workerPath: '%(worker)s',
      corePath: '%(core)s',
      langPath: '%(lang)s',
    });
    // Page segmentation mode 11 ("sparse text") suits form layouts such as BLs:
    // it also finds the small printed labels in table header rows.
    await self.__blmOcrWorker.setParameters({ preserve_interword_spaces: '1', tessedit_pageseg_mode: '11' });
  }
  return true;
};
self.__blmOcrRecognize = async function (u8) {
  const blob = new Blob([u8], { type: 'image/png' });
  const { data } = await self.__blmOcrWorker.recognize(blob, {}, { blocks: true });
  const lines = [];
  for (const b of (data.blocks || []))
    for (const p of (b.paragraphs || []))
      for (const l of (p.lines || []))
        lines.push((l.words || []).map(w => [w.text, w.bbox.x0, w.bbox.y0, w.bbox.x1, w.bbox.y1, w.confidence]));
  return JSON.stringify(lines);
};
true;
""" % {"worker": WORKER_PATH, "core": CORE_PATH, "lang": LANG_PATH}

_READY = False
_ERROR: str | None = None


def _load_script(url: str) -> None:
    import js

    try:
        js.importScripts(url)
    except Exception:
        # Module workers do not allow importScripts: fetch synchronously and evaluate.
        from pyodide.http import open_url

        js.eval(open_url(url).read())


def ensure_ready() -> None:
    """Load Tesseract.js and create the OCR worker (first call only)."""
    global _READY, _ERROR
    if _READY:
        return
    if _ERROR:
        raise RuntimeError(_ERROR)
    try:
        import js
        from pyodide.ffi import can_run_sync, run_sync

        if not can_run_sync():
            raise RuntimeError(
                "OCR in the web version needs an up-to-date Google Chrome or Microsoft Edge browser"
            )
        if not js.eval("typeof self.Tesseract !== 'undefined'"):
            _load_script(TESSERACT_JS)
        js.eval(_JS_HELPERS)
        run_sync(js.__blmOcrInit())
        _READY = True
    except Exception as exc:
        _ERROR = str(exc).split("\n")[0][:300] or "OCR engine could not be started"
        raise RuntimeError(_ERROR) from exc


def available() -> tuple[bool, str]:
    """Cheap check used by the UI (does not download the engine)."""
    try:
        from pyodide.ffi import can_run_sync

        if not can_run_sync():
            return False, "OCR in the web version needs an up-to-date Google Chrome or Microsoft Edge browser"
    except Exception as exc:
        return False, f"OCR not available: {exc}"
    if _ERROR:
        return False, _ERROR
    return True, ""


def recognize_png(png: bytes) -> list[list[tuple[str, float, float, float, float, float]]]:
    """OCR one PNG image. Returns lines; each line is a list of words
    (text, x0, y0, x1, y1, confidence) in image pixels."""
    import js
    from pyodide.ffi import run_sync, to_js

    ensure_ready()
    u8 = to_js(png)
    raw = run_sync(js.__blmOcrRecognize(u8))
    return [[tuple(w) for w in line] for line in json.loads(str(raw))]
