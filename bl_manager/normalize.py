"""Normalisation helpers for company names and container numbers.

Rules are deliberately conservative: they only remove differences that
cannot change the identity of a name/container (case, spacing,
punctuation, common legal-suffix spellings). They never perform fuzzy
matching.
"""
from __future__ import annotations

import re

# Legal-suffix spellings that mean the same thing.
_SUFFIX_EQUIV = [
    (r"\bLIMITED\b", "LTD"),
    (r"\bPRIVATE\b", "PVT"),
    (r"\bCOMPANY\b", "CO"),
    (r"\bCORPORATION\b", "CORP"),
    (r"\bINCORPORATED\b", "INC"),
    (r"&", " AND "),
]

# Trailing legal suffixes that may be dropped for a second comparison.
_TRAILING_SUFFIXES = {"LTD", "PVT", "CO", "CORP", "INC", "LLC", "SMC", "PLC", "LLP", "GMBH", "SA", "BV"}


def normalize_name(name: str | None) -> str:
    """Upper-case, unify legal suffixes, strip punctuation and extra spaces."""
    if not name:
        return ""
    s = name.upper()
    for pat, rep in _SUFFIX_EQUIV:
        s = re.sub(pat, rep, s)
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def core_name(name: str | None) -> str:
    """Normalised name with trailing legal suffixes removed
    (e.g. 'ABC LOGISTICS PVT LTD' -> 'ABC LOGISTICS')."""
    words = normalize_name(name).split()
    while words and words[-1] in _TRAILING_SUFFIXES:
        words.pop()
    return " ".join(words)


# ---------------------------------------------------------------------------
# Containers (ISO 6346)
# ---------------------------------------------------------------------------
_LETTER_VALUES = {}
_v = 10
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    if _v % 11 == 0:
        _v += 1
    _LETTER_VALUES[_c] = _v
    _v += 1


def normalize_container(raw: str) -> str:
    """Remove harmless formatting (spaces, hyphens) and upper-case.
    'onEU 123213-1' -> 'ONEU1232131'."""
    return re.sub(r"[\s\-]", "", raw or "").upper()


def container_check_digit_ok(container: str) -> bool | None:
    """Validate the ISO 6346 check digit. Returns None if the value is not
    in the 4-letter + 7-digit shape."""
    c = normalize_container(container)
    if not re.fullmatch(r"[A-Z]{4}\d{7}", c):
        return None
    total = 0
    for i, ch in enumerate(c[:10]):
        val = _LETTER_VALUES[ch] if ch.isalpha() else int(ch)
        total += val * (2 ** i)
    check = total % 11 % 10
    return check == int(c[10])


def make_container(prefix4: str, serial6: str) -> str:
    """Build a container number with a valid check digit (used by tests)."""
    base = (prefix4 + serial6).upper()
    total = 0
    for i, ch in enumerate(base):
        val = _LETTER_VALUES[ch] if ch.isalpha() else int(ch)
        total += val * (2 ** i)
    return base + str(total % 11 % 10)


def safe_filename(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._\-]+", "_", name or "").strip("._")
    return s or "document"
