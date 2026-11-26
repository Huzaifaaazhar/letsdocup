"""Build the static web version of BL Manager (for Vercel or any static host).

    python web/build.py        ->  web/dist/

The web version runs the SAME Python code (bl_manager/ and ui/) inside the
visitor's browser using stlite (Streamlit on Pyodide/WebAssembly). The
hosting server only delivers these static files: uploaded BL PDFs are
processed in the browser and are never sent to any server.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "web" / "dist"
STLITE = "https://cdn.jsdelivr.net/npm/@stlite/browser@1.12.2/build"

SOURCES = ["app.py", "bl_manager/*.py", "ui/*.py", "tools/__init__.py", "tools/make_sample_pdfs.py",
           "tests/__init__.py", "tests/synthetic.py"]

REQUIREMENTS = ["pymupdf", "pandas", "openpyxl", "reportlab==4.2.5"]

STREAMLIT_CONFIG = {
    "server.maxUploadSize": 1000,
    "client.toolbarMode": "viewer",
    "browser.gatherUsageStats": False,
    "theme.base": "light",
    "theme.primaryColor": "#1F3B73",
    "theme.backgroundColor": "#FFFFFF",
    "theme.secondaryBackgroundColor": "#F3F5F9",
    "theme.textColor": "#1A1F2B",
}

INDEX = """<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>BL Manager</title>
<link rel="stylesheet" href="__STLITE__/stlite.css" />
<style>
  body { margin: 0; font-family: "Source Sans Pro", system-ui, sans-serif; background: #fff; color: #1A1F2B; }
  #boot { position: fixed; inset: 0; display: flex; align-items: center; justify-content: center; background: #fff; z-index: 10; }
  #boot .box { max-width: 520px; padding: 24px; text-align: center; }
  #boot h1 { font-size: 1.6rem; margin: 0 0 6px 0; color: #1F3B73; }
  #boot p { color: #5A6478; line-height: 1.5; }
  #boot .bar { height: 4px; background: #E1E5EE; border-radius: 2px; overflow: hidden; margin-top: 18px; }
  #boot .bar div { height: 100%; width: 40%; background: #1F3B73; animation: slide 1.4s infinite ease-in-out; }
  @keyframes slide { 0% { margin-left: -40%; } 100% { margin-left: 100%; } }
</style>
</head>
<body>
<div id="boot"><div class="box">
  <h1>BL Manager</h1>
  <p>Loading the application into your browser&hellip;<br/>
  The first visit takes about 20&ndash;40 seconds. Later visits are faster.<br/>
  <strong>Your PDFs are processed inside this browser and are never uploaded to a server.</strong></p>
  <div class="bar"><div></div></div>
</div></div>
<div id="root"></div>
<script type="module">
import { mount } from "__STLITE__/stlite.js";
const files = __FILES__;
const fileMap = {};
for (const f of files) fileMap[f] = { url: "./app/" + f };
mount({
  entrypoint: "app.py",
  files: fileMap,
  requirements: __REQUIREMENTS__,
  streamlitConfig: __CONFIG__,
  idbfsMountpoints: ["/mnt"],
}, document.getElementById("root"));
const hide = () => { const b = document.getElementById("boot"); if (b) b.remove(); };
const obs = new MutationObserver(() => {
  if (document.querySelector('[data-testid="stSidebar"], [data-testid="stMain"]')) { hide(); obs.disconnect(); }
});
obs.observe(document.body, { childList: true, subtree: true });
setTimeout(hide, 120000);
</script>
</body>
</html>
"""


def main() -> None:
    if DIST.exists():
        shutil.rmtree(DIST)
    files: list[str] = []
    for pattern in SOURCES:
        for p in sorted(ROOT.glob(pattern)):
            rel = p.relative_to(ROOT).as_posix()
            dest = DIST / "app" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
            files.append(rel)
    html = (INDEX.replace("__STLITE__", STLITE)
            .replace("__FILES__", json.dumps(files))
            .replace("__REQUIREMENTS__", json.dumps(REQUIREMENTS))
            .replace("__CONFIG__", json.dumps(STREAMLIT_CONFIG)))
    (DIST / "index.html").write_text(html, encoding="utf-8")
    print(f"Built {len(files)} files into {DIST}")


if __name__ == "__main__":
    main()
