"""
Field extraction from free-form public-notice text.

Public notices are unstructured legal prose, so we pull the useful fields
(sale date, sale time, property address, court / location) with a set of
regular-expression heuristics. These cover the common phrasings used in
Virginia trustee's-sale and foreclosure notices. They will not catch every
oddly-worded notice, which is why the raw text is always kept too.
"""

import re
from datetime import datetime
from dateutil import parser as dateparser

# ----- date -----------------------------------------------------------------

_MONTHS = (
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
)

# "June 30, 2026"  /  "30 June 2026"  /  "6/30/2026"
_DATE_PATTERNS = [
    re.compile(rf"{_MONTHS}\.?\s+\d{{1,2}},?\s+\d{{4}}", re.I),
    re.compile(rf"\d{{1,2}}\s+{_MONTHS}\.?\s+\d{{4}}", re.I),
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"),
]

# phrases that typically precede the *sale* date specifically
_SALE_CUES = re.compile(
    r"(?:sale\s+(?:date|will\s+be\s+held|to\s+be\s+held)|"
    r"will\s+sell|offer\s+for\s+sale|public\s+auction|auctioned?)\b",
    re.I,
)


def _norm_date(raw):
    try:
        dt = dateparser.parse(raw, fuzzy=True, default=datetime(2000, 1, 1))
        return dt.strftime("%Y-%m-%d")
    except (ValueError, OverflowError):
        return None


def extract_sale_date(text):
    """Best guess at the sale/auction date. Returns ISO yyyy-mm-dd or None."""
    if not text:
        return None
    # Prefer a date that sits close after a sale cue.
    for cue in _SALE_CUES.finditer(text):
        window = text[cue.start(): cue.start() + 220]
        for pat in _DATE_PATTERNS:
            m = pat.search(window)
            if m:
                iso = _norm_date(m.group())
                if iso:
                    return iso
    # Fall back to the first date anywhere.
    for pat in _DATE_PATTERNS:
        m = pat.search(text)
        if m:
            iso = _norm_date(m.group())
            if iso:
                return iso
    return None


# ----- time -----------------------------------------------------------------

_TIME = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*([AaPp])\.?\s*[Mm]\.?\b"
)


def extract_sale_time(text):
    if not text:
        return None
    m = _TIME.search(text)
    if not m:
        return None
    hour, minute, ap = m.group(1), m.group(2) or "00", m.group(3).upper()
    return f"{int(hour)}:{minute} {ap}M"


# ----- addresses ------------------------------------------------------------

_STREET_SUFFIX = (
    r"(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Court|Ct|Circle|Cir|"
    r"Boulevard|Blvd|Way|Place|Pl|Highway|Hwy|Route|Rte|Terrace|Ter|Trail|Trl|"
    r"Parkway|Pkwy|Square|Sq|Loop|Pike|Run|Path|Crossing|Xing)"
)

# e.g. "1234 Maple Ridge Road, Louisa, VA 23093"
_ADDRESS = re.compile(
    rf"\d{{1,6}}\s+(?:[A-Z][A-Za-z0-9'.]+\s+){{0,4}}{_STREET_SUFFIX}\.?"
    rf"(?:,?\s+(?:[A-Z][A-Za-z.]+\s*){{1,3}})?"
    rf"(?:,?\s*VA)?(?:\s+\d{{5}}(?:-\d{{4}})?)?",
    re.I,
)


def extract_property_address(text):
    """The property being sold. Prefer an address after a 'property'/'located' cue."""
    if not text:
        return None
    cue = re.search(r"(?:property|premises|real\s+estate|located\s+at|known\s+as)\b",
                    text, re.I)
    if cue:
        window = text[cue.start(): cue.start() + 300]
        m = _ADDRESS.search(window)
        if m:
            return _clean(m.group())
    m = _ADDRESS.search(text)
    return _clean(m.group()) if m else None


def extract_court_location(text):
    """Where the sale is held — usually a courthouse / front steps location."""
    if not text:
        return None
    cue = re.search(
        r"(?:at\s+the\s+(?:front\s+)?(?:steps|door|entrance)\s+of\s+the\s+"
        r"[A-Za-z .]*?(?:Court\s*house|Circuit\s+Court|Courthouse)"
        r"[^.;]*)",
        text, re.I,
    )
    if cue:
        return _clean(cue.group())
    # generic "<Locality> County Courthouse"
    m = re.search(r"[A-Z][A-Za-z]+\s+County\s+Court\s*house[^.;,]*", text, re.I)
    return _clean(m.group()) if m else None


def _clean(s):
    return re.sub(r"\s+", " ", s).strip(" ,.;") if s else None


def parse_all(text):
    """Run every extractor and return a dict of fields."""
    return {
        "sale_date": extract_sale_date(text),
        "sale_time": extract_sale_time(text),
        "property_address": extract_property_address(text),
        "court_location": extract_court_location(text),
    }
