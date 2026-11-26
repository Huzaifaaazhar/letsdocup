"""Shared constants: classification folders, field definitions, default settings."""

# ---------------------------------------------------------------------------
# Classification folders
# ---------------------------------------------------------------------------
MBL = "MBL"
HBL = "HBL"
CONSOL = "CONSOL"
EPZ = "EPZ"
MANUAL_REVIEW = "MANUAL_REVIEW"

FOLDERS = [MBL, HBL, CONSOL, EPZ, MANUAL_REVIEW]

FOLDER_LABELS = {
    MBL: "MBL",
    HBL: "HBL",
    CONSOL: "CONSOL",
    EPZ: "EPZ",
    MANUAL_REVIEW: "Manual Review",
}

# Directory names used inside the exported ZIP
FOLDER_DIRS = {
    MBL: "MBL",
    HBL: "HBL",
    CONSOL: "CONSOL",
    EPZ: "EPZ",
    MANUAL_REVIEW: "Manual_Review",
}

NOT_EXTRACTED = "Not extracted — requires verification"

# ---------------------------------------------------------------------------
# Extracted fields (order = display order)
# ---------------------------------------------------------------------------
FIELDS = [
    ("bl_number", "BL Number"),
    ("hbl_number", "HBL Number"),
    ("consignee_name", "Consignee Name"),
    ("consignee_address", "Consignee Address"),
    ("shipper_name", "Shipper Name"),
    ("shipper_address", "Shipper Address"),
    ("hs_codes", "HS Code(s)"),
    ("port_of_loading", "Port of Loading"),
    ("port_of_discharge", "Port of Discharge"),
    ("net_weight", "Net Weight"),
    ("gross_weight", "Gross Weight"),
    ("quantity", "Quantity"),
    ("containers", "Containers"),
]
FIELD_LABELS = dict(FIELDS)

# Fields the user may mark as "required" (missing => Manual Review)
REQUIRABLE_FIELDS = [k for k, _ in FIELDS]

# ---------------------------------------------------------------------------
# Default settings (stored in the database; editable on the Settings screen)
# ---------------------------------------------------------------------------
DEFAULT_SETTINGS = {
    # HBL: consignee-name keywords that indicate a freight forwarder.
    # Matched at the start of a word, so "Logistic" also matches "Logistics".
    "hbl_keywords": [
        "Logistic", "Transport", "Marine", "Shipping",
        "Freight", "Forwarding", "Forwarder", "Cargo",
    ],
    # MBL: phrases in the consignee block that mean "to order".
    "to_order_phrases": ["TO ORDER", "TO THE ORDER"],
    # EPZ indicators and where to look for them.
    "epz_terms": ["EPZ", "E.P.Z", "Export Processing Zone"],
    "epz_scope": "name_and_address",          # or "name_only"
    # A BL that matches no rule goes here.
    "unmatched_folder": MANUAL_REVIEW,         # or MBL
    # CONSOL + HBL/MBL overlap: which folder wins.
    "consol_overlap_folder": CONSOL,           # or MANUAL_REVIEW
    # Missing any of these fields => Manual Review.
    "required_fields": ["bl_number", "consignee_name", "containers"],
    # BL number pattern (regular expression, case-insensitive).
    "bl_number_pattern": r"ONEY[A-Z0-9]{8,14}",
    # Accept a value printed next to a "B/L No." label even if it does
    # not match the pattern above (a warning is still shown).
    "accept_labeled_bl_outside_pattern": True,
    # Single-page BL with no "Page x of y" text: accept as complete?
    "accept_single_page_without_numbering": False,
    # Containers whose ISO 6346 check digit fails => Manual Review.
    "invalid_check_digit_to_review": False,
    # OCR fallback for scanned pages.
    "ocr_enabled": True,
    "ocr_min_chars": 40,
    "ocr_dpi": 200,
}
