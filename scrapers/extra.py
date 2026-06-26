"""
Two extra scrapers that don't fit the plain-HTML-table mould:

  DivListScraper  - sites that render each sale as a block of label/value pairs
                    (e.g. Brock & Scott: <article class="foreclosure_search">
                    containing <div class="forecol"><p>County:</p><p>...</p>).
  PdfSalesScraper - sites that publish the sale list as a PDF (e.g. Samuel I.
                    White's Sales.pdf), parsed with pdfplumber.

Both still produce the same Notice records as every other source.
"""

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
    ("property address", "property_address"),
    ("address", "property_address"),
    ("city", "_city"),
    ("location", "court_location"),
]
_TIME_RE = re.compile(r"\d{1,2}(?::\d{2})?(?::\d{2})?\s*[AaPp]\.?\s*[Mm]")


def _norm_date(raw):
    if not raw:
        return None
    try:
        return dateparser.parse(raw, fuzzy=True).strftime("%Y-%m-%d")
    except (ValueError, OverflowError, TypeError):
        return None


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
            yield self._to_notice(fields, item)

    def _to_notice(self, f, item):
        sale_date = _norm_date(f.get("sale_date"))
        sale_time = f.get("sale_time")
        dt = f.get("_datetime")
        if dt:  # e.g. "06/26/2026 - 01:00:00 PM"
            parts = re.split(r"\s*[-–]\s*", dt, maxsplit=1)
            if not sale_date:
                sale_date = _norm_date(parts[0])
            if not sale_time and len(parts) > 1:
                sale_time = parts[1].strip()
        address = f.get("property_address")
        city = f.get("_city")
        if address and city and city.lower() not in address.lower():
            address = f"{address}, {city}"
        full = item.get_text(" ", strip=True)
        return Notice(
            source=self.source_id,
            publication=self.label,
            sale_date=sale_date,
            sale_time=sale_time,
            property_address=address,
            county=f.get("county"),
            state=f.get("state") or self.state_default,
            court_location=f.get("court_location"),
            title=full[:140],
            full_text=full[:1200],
            url=self.url,
        )


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
                            source=self.source_id,
                            publication=self.label,
                            sale_date=_norm_date(d),
                            sale_time=t,
                            property_address=f"{addr} {zipc}".strip(),
                            county=county,
                            state=self.state_default,
                            court_location=loc.strip(),
                            title=f"{addr} {zipc}"[:140],
                            full_text=line,
                            url=self.url,
                        )
                    elif re.fullmatch(r"[A-Za-z][A-Za-z .'-]{2,40}", line) and line != "VA":
                        county = line  # a county / locality heading
