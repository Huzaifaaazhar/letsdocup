"""End-to-end tests of the BL Manager engine on SYNTHETIC documents.

Numbers in the test names refer to the testing requirements in the brief (§16).
"""
import io
import zipfile

import pymupdf
import pytest

from bl_manager import db, exports
from bl_manager.constants import CONSOL, EPZ, HBL, MANUAL_REVIEW, MBL
from bl_manager.normalize import container_check_digit_ok, make_container as mc, normalize_container, normalize_name
from bl_manager.pipeline import change_classification, process_batch, reclassify_batch, update_fields
from tests.synthetic import SynthBL, make_pdf, rasterize

ORDER = ["TO THE ORDER OF", "HABIB BANK LIMITED", "KARACHI, PAKISTAN"]
PLAIN = ["NOOR FOODS COMPANY", "12 MALL ROAD", "LAHORE"]
FWD = ["SEA STAR LOGISTICS (PVT) LTD", "SUITE 5, SHAHRAH-E-FAISAL", "KARACHI"]
EPZC = ["ZEE APPAREL LIMITED", "PLOT 7, SECTOR B-III", "EXPORT PROCESSING ZONE, KARACHI"]


def run(files, mode="combined"):
    bid = process_batch("test", files, mode)
    docs = db.list_documents(bid)
    return bid, {d["doc_key"]: d for d in docs}


def codes(d):
    return {r["code"] for r in d["review_reasons"]}


def val(d, key):
    return d["fields"][key]["values"]


# ---------------------------------------------------------------- 1, 3, 4
def test_01_combined_pdf_reconstruction_one_and_two_page_bls():
    bls = [
        SynthBL("ONEYSHAB10000100", ORDER, containers=[mc("TCLU", "100001")], pages=2),
        SynthBL("ONEYSHAB10000200", ORDER, containers=[mc("TCLU", "100002")], pages=1),
        SynthBL("ONEYSHAB10000300", ORDER, containers=[mc("TCLU", "100003")], pages=2),
    ]
    bid, docs = run([("combined.pdf", make_pdf(bls))])
    assert list(docs) == ["ONEYSHAB10000100", "ONEYSHAB10000200", "ONEYSHAB10000300"]
    assert [d["page_count"] for d in docs.values()] == [2, 1, 2]
    # Source page mapping: pages 1-2, 3, 4-5
    assert [p["page"] for p in docs["ONEYSHAB10000100"]["source_pages"]] == [1, 2]
    assert [p["page"] for p in docs["ONEYSHAB10000200"]["source_pages"]] == [3]
    assert [p["page"] for p in docs["ONEYSHAB10000300"]["source_pages"]] == [4, 5]
    for d in docs.values():
        assert d["recon_issues"] == []
        assert d["current_class"] == MBL
        with pymupdf.open(d["pdf_path"]) as pdf:
            assert pdf.page_count == d["page_count"]
            assert d["bl_number"] in pdf[0].get_text()
        assert d["file_name"] == f"{d['bl_number']}.pdf"
    assert db.get_batch(bid)["total_pages"] == 5


# ---------------------------------------------------------------- 2
def test_02_individual_pdfs_give_same_result_as_combined():
    bls = [
        SynthBL("ONEYSHAB20000100", ORDER, containers=[mc("TCLU", "200001")], pages=2),
        SynthBL("ONEYSHAB20000200", FWD, containers=[mc("TCLU", "200001")]),
        SynthBL("ONEYSHAB20000300", EPZC, containers=[mc("TCLU", "200003")]),
    ]
    _, combined = run([("all.pdf", make_pdf(bls))])
    _, individual = run([(f"{b.bl}.pdf", make_pdf([b])) for b in bls], mode="individual")
    assert list(combined) == list(individual)
    for k in combined:
        assert combined[k]["current_class"] == individual[k]["current_class"]
        assert combined[k]["page_count"] == individual[k]["page_count"]
        assert combined[k]["fields"]["consignee_name"]["values"] == individual[k]["fields"]["consignee_name"]["values"]


# ---------------------------------------------------------------- 5
def test_05_missing_page_goes_to_manual_review():
    b = SynthBL("ONEYSHAB50000100", ORDER, containers=[mc("TCLU", "500001")], pages=1, page_numbers=[(1, 2)])
    _, docs = run([("x.pdf", make_pdf([b]))])
    d = docs["ONEYSHAB50000100"]
    assert d["current_class"] == MANUAL_REVIEW
    assert "MISSING_PAGE" in codes(d)


def test_05b_duplicate_page_goes_to_manual_review():
    b = SynthBL("ONEYSHAB50000200", ORDER, containers=[mc("TCLU", "500002")], pages=2, page_numbers=[(1, 2), (1, 2)])
    _, docs = run([("x.pdf", make_pdf([b]))])
    d = docs["ONEYSHAB50000200"]
    assert d["current_class"] == MANUAL_REVIEW
    assert {"DUPLICATE_PAGE", "MISSING_PAGE"} <= codes(d)


def test_05c_missing_page_numbering_goes_to_manual_review():
    b = SynthBL("ONEYSHAB50000300", ORDER, containers=[mc("TCLU", "500003")], page_numbers=[None])
    _, docs = run([("x.pdf", make_pdf([b]))])
    assert "PAGE_NUMBERING_MISSING" in codes(docs["ONEYSHAB50000300"])


# ---------------------------------------------------------------- 6
def test_06_bl_number_mismatch_between_pages_is_not_merged():
    b = SynthBL("ONEYSHAB60000100", ORDER, containers=[mc("TCLU", "600001"), mc("TCLU", "600002"),
                                                       mc("TCLU", "600003"), mc("TCLU", "600004")],
                pages=2, bl_per_page=["ONEYSHAB60000100", "ONEYSHAB69999900"])
    _, docs = run([("x.pdf", make_pdf([b]))])
    assert set(docs) == {"ONEYSHAB60000100", "ONEYSHAB69999900"}
    for d in docs.values():
        assert d["page_count"] == 1
        assert d["current_class"] == MANUAL_REVIEW
        assert "BL_NUMBER_MISMATCH" in codes(d)


# ---------------------------------------------------------------- 7
def test_07_consignee_matches_freight_forwarder_master_list():
    db.add_forwarder("Trans Ocean Express Pvt Ltd")
    b = SynthBL("ONEYSHAB70000100", ["TRANS OCEAN EXPRESS (PVT.) LIMITED", "KARACHI"], containers=[mc("TCLU", "700001")])
    _, docs = run([("x.pdf", make_pdf([b]))])
    d = docs["ONEYSHAB70000100"]
    assert d["current_class"] == HBL
    assert "Freight Forwarder Master List" in d["auto_reasons"][0]


def test_07b_substantially_different_name_does_not_match():
    db.add_forwarder("Trans Ocean Express Pvt Ltd")
    b = SynthBL("ONEYSHAB70000200", ["TRANS OCEANIC EXPRESS WAYS CORP", "KARACHI"], containers=[mc("TCLU", "700002")])
    _, docs = run([("x.pdf", make_pdf([b]))])
    assert "hbl_master_list" not in docs["ONEYSHAB70000200"]["indicators"]


# ---------------------------------------------------------------- 8
def test_08_consignee_with_forwarding_keyword():
    b = SynthBL("ONEYSHAB80000100", FWD, containers=[mc("TCLU", "800001")])
    _, docs = run([("x.pdf", make_pdf([b]))])
    d = docs["ONEYSHAB80000100"]
    assert d["current_class"] == HBL
    assert any("keyword 'Logistic'" in r for r in d["auto_reasons"])


# ---------------------------------------------------------------- 9
@pytest.mark.parametrize("cons", [
    ["TO ORDER", "KARACHI"],
    ["TO ORDER OF ABC BANK LIMITED", "KARACHI"],
    ["TO THE ORDER OF XYZ", "KARACHI"],
])
def test_09_to_order_is_mbl(cons):
    b = SynthBL("ONEYSHAB90000100", cons, containers=[mc("TCLU", "900001")])
    _, docs = run([("x.pdf", make_pdf([b]))])
    assert docs["ONEYSHAB90000100"]["current_class"] == MBL


def test_09b_form_instruction_in_label_is_not_to_order():
    # The consignee label itself reads "(not negotiable unless consigned to order)".
    b = SynthBL("ONEYSHAB90000200", PLAIN, containers=[mc("TCLU", "900002")])
    _, docs = run([("x.pdf", make_pdf([b]))])
    d = docs["ONEYSHAB90000200"]
    assert "mbl_to_order" not in d["indicators"]
    assert "NO_RULE_MATCHED" in codes(d)


# ---------------------------------------------------------------- 10 (brief's example)
def test_10_two_bls_share_one_container_brief_example():
    bls = [
        SynthBL("ONEYSHAB10100100", ORDER, containers=["ONEU1232131", "ONEU2323230", "ONEY6352342"]),
        SynthBL("ONEYSHAB10100200", ORDER, containers=["ONEU1232131"]),
        SynthBL("ONEYSHAB10100300", ORDER, containers=["ONEU9999999"]),
    ]
    bid, docs = run([("x.pdf", make_pdf(bls))])
    assert docs["ONEYSHAB10100100"]["current_class"] == CONSOL
    assert docs["ONEYSHAB10100200"]["current_class"] == CONSOL
    assert docs["ONEYSHAB10100300"]["current_class"] == MBL
    links = docs["ONEYSHAB10100100"]["consol"]["links"]
    assert links == [{"container": "ONEU1232131", "shared_with": ["ONEYSHAB10100200"]}]
    rep = db.get_batch(bid)["report"]
    assert rep["consol_stats"]["shared_containers"] == 1
    assert rep["consol_groups"][0]["bls"] == ["ONEYSHAB10100100", "ONEYSHAB10100200"]


# ---------------------------------------------------------------- 11
def test_11_three_bls_share_a_container_all_flagged_one_group():
    X = mc("MSCU", "111111")
    bls = [SynthBL(f"ONEYSHAB1100{i}00", ORDER, containers=[X, mc("TCLU", f"11000{i}")]) for i in range(1, 4)]
    bid, docs = run([("x.pdf", make_pdf(bls))])
    assert all(d["current_class"] == CONSOL for d in docs.values())
    groups = db.get_batch(bid)["report"]["consol_groups"]
    assert len(groups) == 1 and len(groups[0]["bls"]) == 3
    assert set(docs["ONEYSHAB1100100"]["consol"]["links"][0]["shared_with"]) == {"ONEYSHAB1100200", "ONEYSHAB1100300"}


# ---------------------------------------------------------------- 12
def test_12_multiple_containers_only_one_shared():
    S = mc("TGHU", "121212")
    bls = [
        SynthBL("ONEYSHAB12000100", FWD, containers=[mc("TCLU", "120001"), S, mc("TCLU", "120003"), mc("TCLU", "120004")], pages=2),
        SynthBL("ONEYSHAB12000200", ORDER, containers=[S]),
        SynthBL("ONEYSHAB12000300", ORDER, containers=[mc("TCLU", "120099")]),
    ]
    _, docs = run([("x.pdf", make_pdf(bls))])
    a = docs["ONEYSHAB12000100"]
    assert len(val(a, "containers")) == 4           # includes the one on page 2
    assert a["current_class"] == CONSOL
    assert "HBL" in a["indicators"]["secondary"]     # HBL kept as secondary indicator
    assert docs["ONEYSHAB12000200"]["current_class"] == CONSOL
    assert docs["ONEYSHAB12000300"]["current_class"] == MBL


def test_12b_container_repeated_within_same_bl_is_not_consol():
    X = mc("TCLU", "121299")
    b = SynthBL("ONEYSHAB12100100", ORDER, containers=[X, X])
    _, docs = run([("x.pdf", make_pdf([b]))])
    assert docs["ONEYSHAB12100100"]["current_class"] == MBL


def test_12c_similar_container_numbers_are_not_matched():
    bls = [
        SynthBL("ONEYSHAB12200100", ORDER, containers=["TCLU1234567"]),
        SynthBL("ONEYSHAB12200200", ORDER, containers=["TCLU1234561"]),
    ]
    bid, docs = run([("x.pdf", make_pdf(bls))])
    assert all(d["current_class"] == MBL for d in docs.values())
    assert db.get_batch(bid)["report"]["near_matches"]
    assert any("NOT treated as the same" in w for w in docs["ONEYSHAB12200100"]["warnings"])


def test_consol_comparison_runs_even_with_no_shared_containers():
    bls = [SynthBL("ONEYSHAB13000100", ORDER, containers=[mc("TCLU", "130001")]),
           SynthBL("ONEYSHAB13000200", ORDER, containers=[mc("TCLU", "130002")])]
    bid, _ = run([("x.pdf", make_pdf(bls))])
    st = db.get_batch(bid)["report"]["consol_stats"]
    assert st["documents_compared"] == 2 and st["unique_containers"] == 2 and st["shared_containers"] == 0


# ---------------------------------------------------------------- 13, 14
def test_13_epz_consignee():
    b = SynthBL("ONEYSHAB13100100", EPZC, containers=[mc("TCLU", "131001")])
    _, docs = run([("x.pdf", make_pdf([b]))])
    d = docs["ONEYSHAB13100100"]
    assert d["current_class"] == EPZ
    # Full consignee name and address retained separately
    assert val(d, "consignee_name") == ["ZEE APPAREL LIMITED"]
    assert "EXPORT PROCESSING ZONE" in val(d, "consignee_address")[0]


def test_13b_epz_in_name_and_name_only_scope():
    b = SynthBL("ONEYSHAB13200100", ["ACME GARMENTS EPZ LIMITED", "KARACHI"], containers=[mc("TCLU", "132001")])
    c = SynthBL("ONEYSHAB13200200", EPZC, containers=[mc("TCLU", "132002")])
    db.save_settings({"epz_scope": "name_only"})
    _, docs = run([("x.pdf", make_pdf([b, c]))])
    assert docs["ONEYSHAB13200100"]["current_class"] == EPZ
    assert docs["ONEYSHAB13200200"]["current_class"] != EPZ   # EPZ only in address


def test_14_epz_and_consol_goes_to_manual_review():
    X = mc("CAIU", "141414")
    bls = [SynthBL("ONEYSHAB14000100", EPZC, containers=[X]), SynthBL("ONEYSHAB14000200", ORDER, containers=[X])]
    _, docs = run([("x.pdf", make_pdf(bls))])
    d = docs["ONEYSHAB14000100"]
    assert d["current_class"] == MANUAL_REVIEW
    assert "CONSOL_EPZ_OVERLAP" in codes(d)
    assert docs["ONEYSHAB14000200"]["current_class"] == CONSOL


def test_hbl_and_mbl_conflict_goes_to_manual_review():
    b = SynthBL("ONEYSHAB14100100", ["TO THE ORDER OF", "BEST FREIGHT SERVICES", "KARACHI"], containers=[mc("TCLU", "141001")])
    _, docs = run([("x.pdf", make_pdf([b]))])
    d = docs["ONEYSHAB14100100"]
    assert d["current_class"] == MANUAL_REVIEW and "HBL_MBL_CONFLICT" in codes(d)


# ---------------------------------------------------------------- 15
def test_15_unreadable_consignee_and_unidentified_page():
    bls = [
        SynthBL("ONEYSHAB15000100", ORDER, containers=[mc("TCLU", "150001")], blank_consignee=True),
        SynthBL("ONEYSHAB15000200", ORDER, containers=[mc("TCLU", "150002")]),
    ]
    _, docs = run([("x.pdf", make_pdf(bls, extra_blank_page_after=0))])
    a = docs["ONEYSHAB15000100"]
    assert a["current_class"] == MANUAL_REVIEW and "REQUIRED_FIELD_MISSING" in codes(a)
    assert a["fields"]["consignee_name"]["status"] == "missing"
    unid = [d for k, d in docs.items() if k.startswith("UNIDENTIFIED")]
    assert len(unid) == 1 and unid[0]["page_count"] == 1
    assert unid[0]["current_class"] == MANUAL_REVIEW and "BL_NUMBER_NOT_FOUND" in codes(unid[0])
    # The unreadable page was NOT attached to a neighbouring BL
    assert a["page_count"] == 1 and docs["ONEYSHAB15000200"]["page_count"] == 1


def test_15b_corrupted_file_does_not_stop_batch():
    good = make_pdf([SynthBL("ONEYSHAB15100100", ORDER, containers=[mc("TCLU", "151001")])])
    bid, docs = run([("broken.pdf", b"%PDF-1.4 this is not a pdf"), ("good.pdf", good)], mode="individual")
    assert "ONEYSHAB15100100" in docs
    errs = db.list_errors(bid)
    assert errs and errs[0]["file_name"] == "broken.pdf"


def test_15c_scanned_pdf_uses_ocr():
    X = mc("TCLU", "152001")
    bls = [SynthBL("ONEYSHAB15200100", ORDER, containers=[X, mc("MSCU", "152002"), mc("TGHU", "152003"), mc("BEAU", "152004")], pages=2),
           SynthBL("ONEYSHAB15200200", FWD, containers=[X])]
    _, docs = run([("scan.pdf", rasterize(make_pdf(bls), 150))])
    a, b = docs["ONEYSHAB15200100"], docs["ONEYSHAB15200200"]
    assert a["ocr_used"] and a["page_count"] == 2
    assert len(val(a, "containers")) == 4
    assert a["current_class"] == CONSOL and b["current_class"] == CONSOL
    assert "MBL" in a["indicators"]["secondary"]
    assert any("OCR" in w for w in a["warnings"])


# ---------------------------------------------------------------- 16
def test_16_manual_classification_change_keeps_original():
    b = SynthBL("ONEYSHAB16000100", PLAIN, containers=[mc("TCLU", "160001")])
    bid, docs = run([("x.pdf", make_pdf([b]))])
    d = docs["ONEYSHAB16000100"]
    assert d["current_class"] == MANUAL_REVIEW
    d2 = change_classification(d["id"], HBL, "Known forwarder")
    assert d2["auto_class"] == MANUAL_REVIEW and d2["current_class"] == HBL and d2["manually_changed"]
    # Saving the consignee to the master list (only after confirmation in the UI) and re-running
    ok, _ = db.add_forwarder(val(d, "consignee_name")[0], source="correction")
    assert ok
    reclassify_batch(bid)
    d3 = db.get_document(d["id"])
    assert d3["auto_class"] == HBL and d3["current_class"] == HBL


def test_16b_user_field_correction_reclassifies_batch():
    X = mc("TCLU", "161001")
    bls = [SynthBL("ONEYSHAB16100100", ORDER, containers=[X]), SynthBL("ONEYSHAB16100200", ORDER, containers=[mc("TCLU", "161002")])]
    bid, docs = run([("x.pdf", make_pdf(bls))])
    b = docs["ONEYSHAB16100200"]
    assert b["current_class"] == MBL
    update_fields(b["id"], {"containers": f"{mc('TCLU', '161002')}\n{X}"}, {})
    reclassify_batch(bid)
    assert db.get_document(b["id"])["current_class"] == CONSOL
    assert db.get_document(docs["ONEYSHAB16100100"]["id"])["current_class"] == CONSOL
    # Original extraction is preserved separately
    assert db.get_document(b["id"])["fields"]["containers"]["values"] == [mc("TCLU", "161002")]


# ---------------------------------------------------------------- 17, 18
def test_17_18_downloads():
    bls = [SynthBL("ONEYSHAB17000100", ORDER, containers=[mc("TCLU", "170001")], pages=2),
           SynthBL("ONEYSHAB17000200", FWD, containers=[mc("TCLU", "170002")]),
           SynthBL("ONEYSHAB17000300", ORDER, containers=[mc("TCLU", "170003")])]
    bid, docs = run([("x.pdf", make_pdf(bls))])
    all_docs = db.list_documents(bid)
    # 17: one BL
    with open(docs["ONEYSHAB17000100"]["pdf_path"], "rb") as f:
        with pymupdf.open(stream=f.read(), filetype="pdf") as pdf:
            assert pdf.page_count == 2
            assert "Page 1 of 2" in pdf[0].get_text() and "Page 2 of 2" in pdf[1].get_text()
    # 18: folder ZIP and combined PDF
    z = zipfile.ZipFile(io.BytesIO(exports.folder_zip(all_docs, MBL)))
    assert sorted(z.namelist()) == ["MBL/ONEYSHAB17000100.pdf", "MBL/ONEYSHAB17000300.pdf"]
    with pymupdf.open(stream=exports.folder_combined_pdf(all_docs, MBL), filetype="pdf") as pdf:
        assert pdf.page_count == 3
    # Full ZIP structure
    z = zipfile.ZipFile(io.BytesIO(exports.full_zip(all_docs)))
    names = set(z.namelist())
    for folder in ("MBL/", "HBL/", "CONSOL/", "EPZ/", "Manual_Review/"):
        assert f"BL_Manager_Results/{folder}" in names
    assert "BL_Manager_Results/HBL/ONEYSHAB17000200.pdf" in names
    assert "BL_Manager_Results/MBL/ONEYSHAB17000100.pdf" in names
    # Manual change moves the file in the export
    change_classification(docs["ONEYSHAB17000300"]["id"], EPZ)
    z = zipfile.ZipFile(io.BytesIO(exports.full_zip(db.list_documents(bid))))
    assert "BL_Manager_Results/EPZ/ONEYSHAB17000300.pdf" in z.namelist()


# ---------------------------------------------------------------- 19
def test_19_bulk_copy_tsv_for_excel():
    bls = [SynthBL("ONEYSHAB19000100", ORDER, containers=[mc("TCLU", "190001"), mc("TCLU", "190002")]),
           SynthBL("ONEYSHAB19000200", FWD, containers=[mc("TCLU", "190003")], net_weight=None)]
    bid, _ = run([("x.pdf", make_pdf(bls))])
    tsv = exports.to_tsv(db.list_documents(bid))
    lines = tsv.split("\n")
    assert len(lines) == 3                         # header + 2 BLs, no stray line breaks
    header = lines[0].split("\t")
    assert "BL Number" in header and "Consignee Name" in header and "Containers" in header
    row2 = dict(zip(header, lines[2].split("\t")))
    assert row2["Net Weight"] == "Not extracted — requires verification"
    row1 = dict(zip(header, lines[1].split("\t")))
    assert row1["Containers"] == f"{mc('TCLU', '190001')} | {mc('TCLU', '190002')}"
    assert exports.to_excel(db.list_documents(bid))[:2] == b"PK"


# ---------------------------------------------------------------- extraction detail
def test_all_fields_extracted_with_sources():
    b = SynthBL("ONEYSHAB20100100", FWD, containers=[mc("TCLU", "201001")], hbl="SSLKHI0099",
                hs_codes=["5205.12", "5205.13"])
    _, docs = run([("x.pdf", make_pdf([b]))])
    d = docs["ONEYSHAB20100100"]
    assert val(d, "bl_number") == ["ONEYSHAB20100100"]
    assert val(d, "hbl_number") == ["SSLKHI0099"]          # kept separate from BL number
    assert val(d, "consignee_name") == ["SEA STAR LOGISTICS (PVT) LTD"]
    assert val(d, "consignee_address") == ["SUITE 5, SHAHRAH-E-FAISAL\nKARACHI"]
    assert val(d, "shipper_name") == ["GLOBAL TEXTILE EXPORTS CO., LTD."]
    assert val(d, "port_of_loading") == ["SHANGHAI, CHINA"]
    assert val(d, "port_of_discharge") == ["KARACHI, PAKISTAN"]
    assert val(d, "hs_codes") == ["5205.12", "5205.13"]
    assert val(d, "net_weight") == ["18,000.000 KGS"]
    assert val(d, "gross_weight") == ["18,500.000 KGS"]
    assert val(d, "quantity") == ["1,200 BAGS"]
    for k in ("consignee_name", "port_of_loading", "gross_weight", "containers"):
        assert d["fields"][k]["page"] == 1 and d["fields"][k]["snippet"]
        assert d["fields"][k]["verified"] is False       # extracted ≠ verified


# ---------------------------------------------------------------- unit helpers
def test_normalisation_helpers():
    assert normalize_container("tclu 123456-7") == "TCLU1234567"
    assert container_check_digit_ok(mc("TCLU", "123456")) is True
    assert container_check_digit_ok("CSQU3054383") is True      # ISO 6346 reference example
    assert container_check_digit_ok("CSQU3054384") is False
    assert normalize_name("Trans Ocean Express (Pvt.) Limited") == normalize_name("TRANS OCEAN EXPRESS PVT LTD")
    assert normalize_name("ABC Shipping") != normalize_name("ABC Shipping Lines")
