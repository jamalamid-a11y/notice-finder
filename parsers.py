"""
Field extraction from free-form public-notice text.

Public notices are unstructured legal prose, so we pull the useful fields
(sale date, sale time, property address, court / location, county) with a set
of regular-expression heuristics tuned for Virginia trustee's-sale and
foreclosure notices. The raw text is always kept too, for anything we miss.

Sale-date strategy: the auction date is almost always the date printed next to
a time of day ("...at 11:00 a.m."). Deed/recording dates ("Deed of Trust dated
November 9, 2021") are the main distractor, so we anchor on the *time* first
and only fall back to explicit sale-cue phrases -- never to "the first date in
the text", which is usually the deed date.
"""

import re
from datetime import datetime
from dateutil import parser as dateparser

_MONTHS = (
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
)

_DATE_RE = (
    rf"(?:{_MONTHS}\.?\s+\d{{1,2}},?\s+\d{{4}}"
    rf"|\d{{1,2}}\s+{_MONTHS}\.?\s+\d{{4}}"
    rf"|\d{{1,2}}/\d{{1,2}}/\d{{2,4}})"
)
_DATE = re.compile(_DATE_RE, re.I)
_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([AaPp])\.?\s*[Mm]\.?\b")


def _norm_date(raw):
    try:
        dt = dateparser.parse(raw, fuzzy=False, default=datetime(2000, 1, 1))
        return dt.strftime("%Y-%m-%d")
    except (ValueError, OverflowError, TypeError):
        return None


def _is_deed_date(text, pos):
    """True if the date at `pos` is preceded by deed/recording wording."""
    pre = text[max(0, pos - 24):pos].lower()
    return bool(re.search(r"dated|recorded|modif|instrument|amended", pre))


def extract_sale_datetime(text):
    """Return (sale_date_iso, sale_time) anchored on the auction time."""
    if not text:
        return None, None

    # 1. Date sitting next to a time of day -> the auction date/time.
    for tm in _TIME.finditer(text):
        window = text[max(0, tm.start() - 90): tm.end() + 90]
        for dm in _DATE.finditer(window):
            abs_pos = max(0, tm.start() - 90) + dm.start()
            if _is_deed_date(text, abs_pos):
                continue
            iso = _norm_date(dm.group())
            if iso:
                return iso, _fmt_time(tm)
    # 2. Date after an explicit sale cue (still skip deed dates).
    for cue in re.finditer(
        r"(?:will\s+(?:be\s+)?(?:sell|sold|offer)|public\s+auction|"
        r"sale\s+will\s+be\s+held|offer\s+for\s+sale|date\s+of\s+sale)",
        text, re.I,
    ):
        window = text[cue.start(): cue.start() + 200]
        dm = _DATE.search(window)
        if dm and not _is_deed_date(text, cue.start() + dm.start()):
            iso = _norm_date(dm.group())
            if iso:
                tm = _TIME.search(text)
                return iso, (_fmt_time(tm) if tm else None)
    return None, None


def _fmt_time(m):
    hour, minute, ap = m.group(1), m.group(2) or "00", m.group(3).upper()
    return f"{int(hour)}:{minute} {ap}M"


# ----- addresses ------------------------------------------------------------

_STREET_SUFFIX = (
    r"(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Court|Ct|Circle|Cir|"
    r"Boulevard|Blvd|Way|Place|Pl|Highway|Hwy|Route|Rte|Terrace|Ter|Trail|Trl|"
    r"Parkway|Pkwy|Square|Sq|Loop|Pike|Run|Path|Crossing|Xing)"
)
_ADDRESS = re.compile(
    rf"\d{{1,6}}\s+(?:[A-Z][A-Za-z0-9'.]+\s+){{0,4}}{_STREET_SUFFIX}\.?"
    rf"(?:,?\s+(?:[A-Z][A-Za-z.]+\s*){{1,3}})?"
    rf"(?:,?\s*VA)?(?:\s+\d{{5}}(?:-\d{{4}})?)?",
    re.I,
)


def extract_property_address(text):
    if not text:
        return None
    cue = re.search(r"(?:property|premises|real\s+estate|located\s+at|known\s+as|sale\s+of)\b",
                    text, re.I)
    if cue:
        m = _ADDRESS.search(text[cue.start(): cue.start() + 300])
        if m:
            return _clean(m.group())
    m = _ADDRESS.search(text)
    return _clean(m.group()) if m else None


def extract_court_location(text):
    if not text:
        return None
    cue = re.search(
        r"at\s+the\s+(?:front\s+)?(?:steps|door|entrance)\s+of\s+the\s+"
        r"[A-Za-z .]*?(?:Court\s*house|Circuit\s+Court|Courthouse)[^.;]*",
        text, re.I,
    )
    if cue:
        return _clean(cue.group())
    m = re.search(r"[A-Z][A-Za-z]+\s+County\s+Court\s*house[^.;,]*", text, re.I)
    return _clean(m.group()) if m else None


_COUNTY = re.compile(
    r"\b([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)\s+(County|City)\b"
)
# Virginia independent cities show up as "City of X"
_CITY_OF = re.compile(r"\bCity\s+of\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)")


def extract_county(text):
    """Best guess at the locality (county or independent city)."""
    if not text:
        return None
    m = _COUNTY.search(text)
    if m:
        return _clean(f"{m.group(1)} {m.group(2)}")
    m = _CITY_OF.search(text)
    if m:
        return _clean(f"City of {m.group(1)}")
    return None


def _clean(s):
    return re.sub(r"\s+", " ", s).strip(" ,.;") if s else None


def parse_all(text):
    sale_date, sale_time = extract_sale_datetime(text)
    return {
        "sale_date": sale_date,
        "sale_time": sale_time,
        "property_address": extract_property_address(text),
        "court_location": extract_court_location(text),
        "county": extract_county(text),
    }
