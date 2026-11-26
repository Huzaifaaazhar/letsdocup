# BL Manager V1

A working application that takes Bill of Lading (BL) PDFs and does the following:

1. **Rebuilds each BL** as its own PDF. It uses the complete BL number **and** the "Page x of y" numbering on every page.
2. **Extracts** these fields:
   - consignee and shipper (name and address)
   - BL number and HBL number
   - HS codes
   - port of loading and port of discharge
   - net weight, gross weight and quantity
   - container numbers
3. **Classifies** every BL into **MBL**, **HBL**, **CONSOL**, **EPZ** or **Manual Review**, and always shows the reason.
4. **Compares every container number across the whole batch** to find consolidated (CONSOL) shipments.
5. Lets you **inspect, correct, copy and download** the results.

Everything runs **on your own computer**. No document is sent to the internet.

---

## 1. Install (one time, Windows)

You do not need to know Python. Follow these steps exactly.

**Step 1 – Install Python**

1. Go to <https://www.python.org/downloads/> and download **Python 3.12** (Windows installer, 64-bit).
2. Run the installer. On the first screen, **tick "Add python.exe to PATH"**, then click **Install Now**.

**Step 2 – Get the BL Manager files**

1. On the GitHub page of this project, click the green **Code** button, then **Download ZIP**.
2. Right-click the downloaded ZIP and choose **Extract All…**. Pick a simple location, for example `C:\BL_Manager`.

**Step 3 – Install BL Manager**

1. Open the extracted folder and double-click **`install.bat`**.
2. A black window appears and installs everything. This takes a few minutes the first time.
3. When it says *"Installation finished"*, press any key to close it.

> If Windows shows "Windows protected your PC", click **More info**, then **Run anyway**. The file is a plain text script; you can open it in Notepad to see exactly what it does.

## 2. Start the application

- Double-click **`run_app.bat`**. Your web browser opens at **http://localhost:8501** after a few seconds.
- **Keep the black window open** while you use the application. Closing it stops the application.

## 3. Try it with test documents (recommended first)

1. Double-click **`make_test_pdfs.bat`**. It creates a `sample_pdfs` folder with **synthetic** (fake) BLs. Each page is marked *"SYNTHETIC TEST DOCUMENT"*:
   - `combined_test_batch.pdf`: 13 BLs plus one unreadable page, in one file (Option A)
   - `individual\*.pdf`: the same BLs as separate files (Option B)
   - `scanned_test_batch.pdf`: an image-only "scanned" version, to test OCR
   - `freight_forwarders_sample.xlsx`: a sample Freight Forwarder list to import
2. In the application:
   1. Go to **Freight Forwarders → Import / Export** and upload `freight_forwarders_sample.xlsx`. Click **Import names**.
   2. Go to **Upload & Process → Option A**, upload `combined_test_batch.pdf` and click **Process**.
   3. Open the **Dashboard**. You should see 14 documents: MBL 1, HBL 1, CONSOL 6, EPZ 1, Manual Review 5.
   4. Open **BL Folders**, then click any row to open the two-panel BL view.

## 3b. Web version (shareable link on Vercel)

The same application also runs as a **web page**. Vercel only delivers the program files. **All processing happens inside the visitor's own browser**, using Python compiled to WebAssembly (stlite + Pyodide). Uploaded PDFs are **not sent to Vercel or to any other server**.

| | Windows installation | Web version |
|---|---|---|
| Install needed | Yes (`install.bat`) | No — open the link |
| Where PDFs are processed | Your computer | Your computer, inside the browser |
| Scanned (image-only) PDFs (OCR) | Yes | **No** — such pages go to Manual Review |
| Where results are stored | `data` folder | This browser only. Another browser or computer starts empty. |
| First start | Instant | About 20–40 seconds while the browser downloads the engine |

How the web version is built and deployed:

- `web/build.py` copies `app.py`, `bl_manager/` and `ui/` into `web/dist/` and writes `web/dist/index.html`, which starts the app in the browser.
- `vercel.json` tells Vercel to run that build and publish `web/dist`. Every push to the connected branch redeploys automatically.
- To test the web version on your own PC, run `python web/build.py` and then `python -m http.server 8700 -d web/dist`, and open <http://localhost:8700>.

## 4. Everyday use

| Task | Where |
|---|---|
| Process one big PDF | **Upload & Process → Option A** |
| Process many separate BL PDFs | **Upload & Process → Option B** (hold **Ctrl** to select several files) |
| See counts and download everything | **Dashboard** |
| Browse folders, search by BL / consignee / container | **BL Folders** |
| See the original BL next to its extracted data | Click a BL in **BL Folders** |
| Copy one value | The copy icon at the right of each value box |
| Copy all data for one BL | *"Copy all extracted information for this BL"* |
| Copy all BLs into Excel | **Dashboard → Copy extracted information for ALL BLs**, then paste into cell A1 |
| Move a BL to another folder | BL view → **Change classification** → **Confirm change** |
| Correct a wrong value / mark it verified | BL view → **Edit extracted values / mark as verified** |
| Manage the Freight Forwarder list | **Freight Forwarders** |
| Change keywords, EPZ terms, rules | **Settings** |
| Reopen or delete an old batch | **Batch History** |

---

## 5. How the rules work

### BL reconstruction

- On every page the application reads the **complete BL number** (next to the "B/L No." label, or the configured BL number pattern) and the **page numbering** ("Page 1 of 2", "Sheet 1 of 2", "1 of 2 pages").
- Pages are grouped by their complete BL number, **across the whole upload**, not just by position. Each group is then validated:

| Problem | Result |
|---|---|
| A page is missing (e.g. "1 of 2" without "2 of 2") | Manual Review |
| The same page appears twice | Manual Review |
| The pages state different totals | Manual Review |
| A page has no page numbering | Manual Review (can be relaxed for 1-page BLs in Settings) |
| The BL number changes between pages that look like one BL | Both parts go to Manual Review. **Not merged.** |
| A page has no readable BL number | It becomes its own *UNIDENTIFIED* document in Manual Review. **It is never attached to a neighbouring BL.** |
| A BL's pages are scattered in the upload | Manual Review |

- Every BL remembers the file and page numbers it came from. These are shown under the PDF viewer.

### Classification (all rules are checked first, then one primary folder is chosen)

| Rule | Detected from |
|---|---|
| **HBL** | The consignee name matches the Freight Forwarder list (ignoring case, punctuation, spaces and Ltd/Limited-type variants), **or** contains a keyword (Logistic, Transport, Marine, Shipping, Freight, Forwarding, Forwarder, Cargo — editable). |
| **MBL** | The consignee contains **"TO ORDER"** / **"TO THE ORDER"**. The printed form text *"(not negotiable unless consigned to order)"* in the label is ignored. |
| **EPZ** | The consignee contains **EPZ**, **E.P.Z** or **Export Processing Zone**. By default the app searches the name **and** address. A setting can restrict this to the name only. |
| **CONSOL** | A container number appears on **two or more different BL numbers** in the same batch. This is checked across the entire batch, every time. |

**Primary folder priority:**

1. Any reconstruction problem, missing required field or failing data check goes to **Manual Review**.
2. CONSOL and EPZ together go to **Manual Review**.
3. HBL and MBL indicators together go to **Manual Review**.
4. CONSOL goes to **CONSOL**. HBL/MBL is still shown as a secondary indicator. A setting can send this overlap to Manual Review instead.
5. EPZ goes to **EPZ**.
6. HBL goes to **HBL**.
7. MBL goes to **MBL**.
8. A BL that matches no rule goes to **Manual Review**. A setting can send it to MBL instead.

Every BL has exactly one folder. Secondary rules are listed on the BL, not duplicated as files.

### Container matching

- Containers are compared **character for character**, on the complete number.
- Only spaces and hyphens are removed: `TCLU 123456-7` is treated as `TCLU1234567`.
- **Similar numbers are never treated as the same.** If two numbers on different BLs differ by one character, a warning is shown, because one may be misread.
- A container repeated within the **same** BL does not count as CONSOL.
- Each container's ISO 6346 check digit is tested and shown. When a BL was read by OCR, a failing check digit sends it to Manual Review, because a misread container could hide a CONSOL link.

### Extracted vs verified

Every value carries a status:

- **Extracted — not yet verified**
- **Verified by user**
- **Corrected by user**
- **Not extracted — requires verification**

Each value also shows the page and the source text it was read from. Corrections are stored **separately** from the original extraction. Both are kept, and every change is recorded in the activity log.

---

## 6. Where data is stored, and deleting it

- Everything is in the **`data`** folder inside the application folder:
  - `bl_manager.db` holds the database: Freight Forwarder list, settings, batches, corrections and log.
  - `batches\batch_000NN\` holds the uploaded PDFs and the reconstructed BL PDFs.
- **Batch History → Confirm delete → Delete batch + files** removes a batch's records **and** its PDF files.
- The Freight Forwarder list and settings are kept when you delete batches.
- Backup: copy the `data` folder while the application is closed.

---

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| `install.bat` says Python is not installed | Re-install Python 3.12 and tick **"Add python.exe to PATH"**. Restart the computer, then run `install.bat` again. |
| The browser shows "This site can't be reached" | Wait 10 seconds and refresh. Check that the black `run_app.bat` window is still open and shows no error. |
| "Port 8501 is already in use" | BL Manager is already running in another window. Use that window, or close it and start again. |
| Warning that OCR is not available | Scanned pages cannot be read, but text PDFs still work. Run `install.bat` again. If it still fails, ask IT to check that `rapidocr_onnxruntime` installs on your Python version (Python 3.12 is recommended). |
| A real BL is not split or read correctly | Open **Dashboard → Page-by-page reconstruction detail** to see what was read on each page. Check **Settings → BL number pattern**. See section 8. |
| Web version stays on the loading screen | Use an up-to-date Chrome or Edge, and check that the network allows `cdn.jsdelivr.net`. The browser downloads the Python engine from there. |
| Something looks broken | Close the black window and run `run_app.bat` again. Your data is kept. |

To run the automated tests, double-click **`run_tests.bat`**. All tests should show `PASSED`.

---

## 8. Known limitations (honest status)

- **The extraction has been developed and tested on synthetic BLs** that imitate a standard BL box layout. Real ONE BL PDFs have not been tested yet. Real layouts and label wording may differ. The engine finds fields by their printed labels, and the label list in `bl_manager/labels.py` is easy to extend. The first real batch should be checked carefully and any mis-read field reported, so the labels can be tuned. The application never invents values: anything it cannot find is shown as *"Not extracted — requires verification"*.
- **OCR** (for scanned pages) works offline but is slower: about 1–3 seconds per page. It can misread characters, so OCR-read BLs are clearly marked.
- **Consignee name vs. address** is split by a simple rule: the first line, plus a following "Ltd / (Pvt) Ltd" line or "TO THE ORDER OF" + bank line, is the name. The full original consignee block is always kept and shown.
- If a BL lists several weights or quantities (per container), all are listed and a warning is shown. The application does not guess which one is the total.
- Single-user, local application. It has no login. Authentication and hosting are left for ONE IT to add when productionising.

---

## 9. For the IT team — architecture

```
app.py                    Streamlit entry point (navigation)
ui/                       User interface screens
  upload.py               Option A / Option B upload and processing progress
  dashboard.py            Counts, folders, processing report, batch export, bulk copy
  folders.py              Folder list, search, folder downloads
  bl_view.py              Two-panel BL view, corrections, classification changes
  forwarders.py           Freight Forwarder management (add/edit/delete/import/export)
  settings_page.py        Configurable rules
  batches.py              Batch history and deletion
bl_manager/               Processing engine (no UI code; usable from scripts)
  pdf_reader.py           Text-layer extraction with positions; offline OCR fallback (RapidOCR)
  labels.py               BL field labels and "value box under a label" detection
  page_parser.py          Per-page BL number and page-numbering identification
  reconstruction.py       Grouping pages into BLs and validating page sequences
  extraction.py           Field extraction with source page/text for every value
  consol.py               Batch-wide container comparison and CONSOL grouping
  classification.py       HBL / MBL / EPZ / CONSOL rules and folder priority
  pipeline.py             Orchestration, reclassification, corrections
  exports.py              PDF/ZIP/Excel/TSV outputs
  db.py                   SQLite persistence (data/bl_manager.db)
  normalize.py            Name and container normalisation, ISO 6346 check digit
tests/                    Automated tests on synthetic documents
tools/make_sample_pdfs.py Synthetic test-document generator
```

- **Stack:** Python 3.10+, PyMuPDF (PDF read/split/render), Streamlit (UI), SQLite (storage), RapidOCR + ONNX Runtime (offline OCR, no separate Windows installer needed), pandas/openpyxl (Excel).
- **Why RapidOCR instead of Tesseract:** it installs with `pip` alone and runs fully offline. Tesseract needs a separate system installer on every PC.
- **Privacy:** Streamlit is bound to `localhost` and usage statistics are turned off (`.streamlit/config.toml`).
- **Tests:** `python -m pytest -v`.

## 10. Test coverage (brief §16)

| # | Requirement | Test |
|---|---|---|
| 1 | Combined PDF with multiple BLs | `test_01_combined_pdf_reconstruction_one_and_two_page_bls` |
| 2 | Multiple individual PDFs | `test_02_individual_pdfs_give_same_result_as_combined` |
| 3–4 | Two-page and one-page BL | `test_01_…` |
| 5 | Incorrect / missing page | `test_05_…`, `test_05b_…` (duplicate), `test_05c_…` (no numbering) |
| 6 | BL number mismatch between pages | `test_06_…` |
| 7 | Freight Forwarder list match | `test_07_…`, `test_07b_…` (different name must not match) |
| 8 | Forwarding keyword | `test_08_…` |
| 9 | TO ORDER | `test_09_…` (3 variants), `test_09b_…` (form text ignored) |
| 10 | Two BLs share a container (brief's example) | `test_10_…` |
| 11 | Three BLs share a container | `test_11_…` |
| 12 | Multiple containers, one shared | `test_12_…`, `test_12b_…` (same BL), `test_12c_…` (similar numbers) |
| — | CONSOL check runs with no shared containers | `test_consol_comparison_runs_even_with_no_shared_containers` |
| 13 | EPZ consignee | `test_13_…`, `test_13b_…` (name-only scope) |
| 14 | EPZ + CONSOL | `test_14_…` |
| 15 | Unreadable / incomplete document | `test_15_…`, `test_15b_…` (corrupt file), `test_15c_…` (scanned/OCR) |
| 16 | Manual classification correction | `test_16_…`, `test_16b_…` (field correction re-runs CONSOL) |
| 17–18 | Download one BL / a folder / full ZIP | `test_17_18_downloads` |
| 19 | Bulk copy to Excel | `test_19_bulk_copy_tsv_for_excel` |
