"""Create SYNTHETIC test PDFs for trying the application.

    python tools/make_sample_pdfs.py

Creates the folder  sample_pdfs/  with:
  combined_test_batch.pdf      one PDF with many BLs (Option A)
  individual/*.pdf             the same BLs as separate files (Option B)
  scanned_test_batch.pdf       an image-only ("scanned") version to test OCR
  freight_forwarders_sample.xlsx  a sample list for the import function

Every page is marked "SYNTHETIC TEST DOCUMENT - NOT A REAL BILL OF LADING".
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from bl_manager.normalize import make_container as mc  # noqa: E402
from tests.synthetic import SynthBL, make_pdf, rasterize  # noqa: E402


def scenario() -> list[SynthBL]:
    shared_a = mc("TCLU", "482913")
    shared_b = mc("MSCU", "771204")
    return [
        # MBL, 2 pages, 4 containers (one shared with BL 3 -> CONSOL)
        SynthBL("ONEYSHAB61002300", ["TO THE ORDER OF", "HABIB BANK LIMITED", "I.I. CHUNDRIGAR ROAD, KARACHI"],
                containers=[mc("ONEU", "120034"), shared_a, mc("TGHU", "553201"), mc("BEAU", "908812")], pages=2,
                hs_codes=["5205.12", "5205.13"]),
        # HBL by keyword
        SynthBL("ONEYSHAB61002400", ["SEA STAR LOGISTICS (PVT) LTD", "SUITE 5, 2ND FLOOR, SHAHRAH-E-FAISAL", "KARACHI 75400, PAKISTAN"],
                containers=[mc("FCIU", "330145")], hbl="SSLKHI260099", packages="640 CARTONS",
                description=["READYMADE GARMENTS", "MEN'S T-SHIRTS"], hs_codes=["6109.10"],
                net_weight="7,950.000 KGS", gross_weight="8,420.000 KGS"),
        # Shares container with BL 1 -> CONSOL (and HBL by master list as secondary)
        SynthBL("ONEYSHAB61002500", ["TRANS OCEAN EXPRESS (PVT.) LIMITED", "OFFICE 12, MARINE PLAZA", "KARACHI"],
                containers=[shared_a], hbl="TOE-HBL-7781", packages="300 BAGS", net_weight="7,500.000 KGS",
                gross_weight="7,560.000 KGS"),
        # EPZ (address)
        SynthBL("ONEYSHAB61002600", ["ZEE APPAREL LIMITED", "PLOT 7, SECTOR B-III", "EXPORT PROCESSING ZONE, LANDHI, KARACHI"],
                containers=[mc("CAIU", "602217")], packages="220 ROLLS", description=["POLYESTER FABRIC"],
                hs_codes=["5407.61"], net_weight="11,200.000 KGS", gross_weight="11,640.000 KGS"),
        # Plain consignee, no rule -> Manual Review
        SynthBL("ONEYSHAB61002700", ["NOOR FOODS COMPANY", "12 MALL ROAD", "LAHORE, PAKISTAN"],
                containers=[mc("TRHU", "448120")], packages="1,800 BAGS", description=["BASMATI RICE SEED"],
                hs_codes=["1006.10"]),
        # Three BLs sharing one container
        SynthBL("ONEYSHAB61002800", ["TO ORDER", "KARACHI"], containers=[shared_b, mc("SEGU", "100201")]),
        SynthBL("ONEYSHAB61002900", ["GLOBAL FREIGHT FORWARDING CO.", "KARACHI"], containers=[shared_b]),
        SynthBL("ONEYSHAB61003000", ["TO ORDER OF MCB BANK LIMITED", "KARACHI"], containers=[shared_b]),
        # EPZ in the name + CONSOL -> Manual Review
        SynthBL("ONEYSHAB61003100", ["ACME TEXTILES EPZ (PVT) LTD", "KARACHI EXPORT PROCESSING ZONE"],
                containers=[mc("TCLU", "900110"), mc("BMOU", "211300")]),
        SynthBL("ONEYSHAB61003200", ["TO ORDER", "LAHORE"], containers=[mc("BMOU", "211300")]),
        # Missing page: says 1 of 2, page 2 not in the file
        SynthBL("ONEYSHAB61003300", ["TO ORDER", "KARACHI"], containers=[mc("GESU", "662210")], pages=1,
                page_numbers=[(1, 2)]),
        # HBL/MBL conflict
        SynthBL("ONEYSHAB61003400", ["TO THE ORDER OF", "PAK CARGO SERVICES", "KARACHI"], containers=[mc("TEMU", "402211")]),
        # One-page MBL with HBL number absent
        SynthBL("ONEYSHAB61003500", ["TO ORDER OF ALLIED BANK LIMITED", "KARACHI"], containers=[mc("DFSU", "711230")],
                packages="25 PALLETS", description=["INDUSTRIAL MACHINERY PARTS"], hs_codes=["8483.40"],
                net_weight="14,880.000 KGS", gross_weight="15,600.000 KGS"),
    ]


def main() -> None:
    out = ROOT / "sample_pdfs"
    (out / "individual").mkdir(parents=True, exist_ok=True)
    bls = scenario()
    # A page with no readable BL number is inserted after the 5th BL.
    (out / "combined_test_batch.pdf").write_bytes(make_pdf(bls, extra_blank_page_after=4))
    for b in bls:
        (out / "individual" / f"{b.bl}.pdf").write_bytes(make_pdf([b]))
    (out / "scanned_test_batch.pdf").write_bytes(rasterize(make_pdf(bls[:5]), 150))
    pd.DataFrame({"Name": ["Trans Ocean Express Pvt Ltd", "Karachi Consolidators Limited", "Blue Water Cargo (Pvt) Ltd"]}
                 ).to_excel(out / "freight_forwarders_sample.xlsx", index=False)
    print(f"Synthetic test files written to: {out}")


if __name__ == "__main__":
    main()
