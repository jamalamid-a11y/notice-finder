"""
Extra scrapers that don't fit the plain-HTML-table mould:

  DivListScraper  - sites that render each sale as a block of label/value pairs
                    (e.g. Brock & Scott: <article class="foreclosure_search">
                    containing <div class="forecol"><p>County:</p><p>...</p>).
  PdfSalesScraper - sites that publish the sale list as a PDF (e.g. Samuel I.
                    White's Sales.pdf), parsed with pdfplumber.
  CsvScraper      - sites whose table is built client-side from a CSV file the
                    page downloads (e.g. CGD Law's /va/data/sales.csv). We just
                    fetch the CSV directly.

All produce the same Notice records as every other source.
"""

import csv as csvmod
import io
import re

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

from .base import BaseScraper, Notice

UA = {"User-Agent": "Mozilla/5.0 (notice-finder; public-records research)"}

_LABELS = [
    ("sale date", "_datetime"),
    ("date/time", "_datetime"),
    ("date", "sale_date"),
    ("time", "sale_time"),
    ("jurisdiction", "county"),
    ("county", "county"),
    ("state", "state"),
    ("street address", "property_address"),
    ("property address", "property_address"),
    ("address", "property_address"),
    ("city state zip", "_city"),
    ("city", "_city"),
    ("location", "court_location"),
]
_TIME_RE = re.compile(r"\d{1,2}(?::\d{2})?(?::\d{2})?\s*[AaPp]\.?\s*[Mm]")
_STATE_RE = re.compile(r",\s*([A-Z]{2})\b")


def _norm_date(raw):
    if not raw:
        return None
    try:
        return dateparser.parse(raw, fuzzy=True).strftime("%Y-%m-%d")
    except (ValueError, OverflowError, TypeError):
        return None


def _split_dt(value):
    """From a combined 'date time' string return (iso_date, time-string)."""
    if not value:
        return None, None
    iso = _norm_date(value)
    tm = _TIME_RE.search(value)
    return iso, (tm.group() if tm else None)


def _label_to_field(label):
    low = label.lower()
    for needle, field in _LABELS:
        if needle in low:
            return field
    return None


class DivListScraper(BaseScraper):
    """Each sale is one `item_selector` element holding `field_selector` label/value blocks."""

    def __init__(self, source_id, label, url, item_selector, field_selector,
                 state_default="VA"):
        self.source_id = source_id
        self.label = label
        self.url = url
        self.item_selector = item_selector
        self.field_selector = field_selector
        self.state_default = state_default

    def fetch(self, max_pages=1):
        r = requests.get(self.url, headers=UA, timeout=45)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        for item in soup.select(self.item_selector):
            fields = {}
            for blk in item.select(self.field_selector):
                txt = blk.get_text(" ", strip=True)
                if ":" not in txt:
                    continue
                label, value = txt.split(":", 1)
                field = _label_to_field(label)
                if field and value.strip():
                    fields[field] = value.strip()
            if not fields:
                continue
            yield self._to_notice(fields, item.get_text(" ", strip=True))

    def _to_notice(self, f, full):
        sale_date = _norm_date(f.get("sale_date"))
        sale_time = f.get("sale_time")
        if f.get("_datetime"):
            d, t = _split_dt(f["_datetime"])
            sale_date = sale_date or d
            sale_time = sale_time or t
        address = _join_addr(f.get("property_address"), f.get("_city"))
        return Notice(
            source=self.source_id, publication=self.label,
            sale_date=sale_date, sale_time=sale_time,
            property_address=address, county=f.get("county"),
            state=f.get("state") or _state_from(address) or self.state_default,
            court_location=f.get("court_location"),
            title=full[:140], full_text=full[:1200], url=self.url,
        )


class CsvScraper(BaseScraper):
    """Fetch a CSV the site's table is built from; map columns by header name."""

    def __init__(self, source_id, label, url, delimiter=",", state_default="VA"):
        self.source_id = source_id
        self.label = label
        self.url = url
        self.delimiter = delimiter
        self.state_default = state_default

    def fetch(self, max_pages=1):
        r = requests.get(self.url, headers=UA, timeout=45)
        r.raise_for_status()
        rows = list(csvmod.reader(io.StringIO(r.text), delimiter=self.delimiter))
        if len(rows) < 2:
            return
        col = {}
        for i, h in enumerate(rows[0]):
            field = _label_to_field(h)
            if field and field not in col:
                col[field] = i
        for cells in rows[1:]:
            if not any(c.strip() for c in cells):
                continue
            f = {k: cells[i].strip() for k, i in col.items() if i < len(cells)}
            if "cancelled" in (cells[-1].lower() if cells else ""):
                pass
            sale_date, sale_time = None, f.get("sale_time")
            if f.get("_datetime"):
                d, t = _split_dt(f["_datetime"])
                sale_date, sale_time = d, sale_time or t
            elif f.get("sale_date"):
                sale_date = _norm_date(f["sale_date"])
            address = _join_addr(f.get("property_address"), f.get("_city"))
            yield Notice(
                source=self.source_id, publication=self.label,
                sale_date=sale_date, sale_time=sale_time,
                property_address=address, county=f.get("county"),
                state=f.get("state") or _state_from(address) or self.state_default,
                title=" | ".join(c for c in cells if c)[:140],
                full_text=" | ".join(c for c in cells if c), url=self.url,
            )


def _join_addr(addr, city):
    if addr and city and city.lower() not in addr.lower():
        return f"{addr}, {city}"
    return addr or city


def _state_from(text):
    m = _STATE_RE.search(text or "")
    return m.group(1) if m else None


# row: <address+city> <zip> <m/d/yyyy> <hh:mm:ss> <sale-city> <file#>
_PDF_ROW = re.compile(
    r"^(.*?)\s+(\d{5}(?:-\d{4})?)\s+(\d{1,2}/\d{1,2}/\d{4})\s+"
    r"(\d{1,2}:\d{2}:\d{2})\s+(.+?)\s+(\d+)$"
)
_PDF_SKIP = re.compile(
    r"Foreclosure Sales Report|Samuel I\. White|Information Reported|"
    r"Property Address|Viking Drive|Virginia Beach, VA|\(757\)|"
    r"representations|assume sole reliance|guarantee the accuracy|"
    r"additonal information|9:00 AM",
    re.I,
)


class PdfSalesScraper(BaseScraper):
    """Parse a foreclosure-sales PDF that groups rows under county headings."""

    def __init__(self, source_id, label, url, state_default="VA"):
        self.source_id = source_id
        self.label = label
        self.url = url
        self.state_default = state_default

    def fetch(self, max_pages=1):
        import pdfplumber  # imported lazily so the rest of the app loads without it

        r = requests.get(self.url, headers=UA, timeout=60)
        r.raise_for_status()
        county = None
        with pdfplumber.open(io.BytesIO(r.content)) as pdf:
            for page in pdf.pages:
                for line in (page.extract_text() or "").split("\n"):
                    line = line.strip()
                    if not line or _PDF_SKIP.search(line):
                        continue
                    m = _PDF_ROW.match(line)
                    if m:
                        addr, zipc, d, t, loc, _file = m.groups()
                        yield Notice(
                            source=self.source_id, publication=self.label,
                            sale_date=_norm_date(d), sale_time=t,
                            property_address=f"{addr} {zipc}".strip(),
                            county=county, state=self.state_default,
                            court_location=loc.strip(),
                            title=f"{addr} {zipc}"[:140], full_text=line,
                            url=self.url,
                        )
                    elif re.fullmatch(r"[A-Za-z][A-Za-z .'-]{2,40}", line) and line != "VA":
                        county = line  # a county / locality heading
