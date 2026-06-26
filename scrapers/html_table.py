"""
Generic scraper for sites that publish foreclosure / trustee sales as a plain
HTML <table>.

Most law-firm sale lists are exactly this: one static table, one row per sale.
Rather than write a bespoke scraper per firm, this class fetches the page, finds
the sales table, and maps columns to our fields BY HEADER NAME -- so it adapts
to each site's column order and wording automatically. Adding a new firm is then
just one line in scrapers/__init__.py (id, label, url).

Only static HTML works here. Sites that render their table with JavaScript,
PowerBI, or behind a disclaimer click need a browser-rendering approach instead.
"""

import re

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

from .base import BaseScraper, Notice

# header text -> our field. Matched as case-insensitive substring.
_HEADER_MAP = [
    ("sale date time", "_datetime"),
    ("sale date/time", "_datetime"),
    ("date/time", "_datetime"),
    ("sale date", "sale_date"),
    ("hud sale date", "sale_date"),
    ("date", "sale_date"),
    ("sale time", "sale_time"),
    ("time", "sale_time"),
    ("property address", "property_address"),
    ("address", "property_address"),
    ("jurisdiction", "county"),
    ("county", "county"),
    ("city", "_city"),
    ("state", "state"),
    ("sale location", "court_location"),
    ("location", "court_location"),
    ("case", "_case"),
    ("file", "_case"),
]

_TIME_RE = re.compile(r"\d{1,2}(?::\d{2})?(?::\d{2})?\s*[AaPp]\.?\s*[Mm]")


def _norm_date(raw):
    if not raw:
        return None
    try:
        return dateparser.parse(raw, fuzzy=True).strftime("%Y-%m-%d")
    except (ValueError, OverflowError, TypeError):
        return None


class HtmlTableScraper(BaseScraper):
    def __init__(self, source_id, label, url, state_default="VA"):
        self.source_id = source_id
        self.label = label
        self.url = url
        self.state_default = state_default

    def fetch(self, max_pages=1):
        sess = requests.Session()
        sess.headers.update({
            "User-Agent": "Mozilla/5.0 (notice-finder; public-records research)",
        })
        r = sess.get(self.url, timeout=45)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")

        table = self._pick_table(soup)
        if not table:
            return
        rows = table.find_all("tr")
        if len(rows) < 2:
            return
        headers = [c.get_text(" ", strip=True).lower()
                   for c in rows[0].find_all(["th", "td"])]
        col = self._map_columns(headers)

        for tr in rows[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if not cells or not any(cells):
                continue
            yield self._row_to_notice(cells, col)

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _pick_table(soup):
        """Choose the table that looks like a sales list (has date+address-ish headers)."""
        best, best_score = None, 0
        for t in soup.find_all("table"):
            head = " ".join(c.get_text(" ", strip=True).lower()
                            for c in t.find_all(["th", "td"], limit=12))
            score = sum(k in head for k in ("date", "address", "sale", "county",
                                            "jurisdiction", "bid", "location"))
            rows = len(t.find_all("tr"))
            if score >= 2 and rows > best_score:
                best, best_score = t, rows
        return best

    @staticmethod
    def _map_columns(headers):
        col = {}
        for i, h in enumerate(headers):
            for needle, field in _HEADER_MAP:
                if needle in h and field not in col:
                    col[field] = i
                    break
        return col

    def _row_to_notice(self, cells, col):
        def get(field):
            i = col.get(field)
            return cells[i].strip() if i is not None and i < len(cells) else None

        sale_date = _norm_date(get("sale_date"))
        sale_time = get("sale_time")
        # combined "Sale Date Time" column
        dt = get("_datetime")
        if dt:
            if not sale_date:
                sale_date = _norm_date(dt)
            if not sale_time:
                m = _TIME_RE.search(dt)
                sale_time = m.group() if m else None

        address = get("property_address")
        city = get("_city")
        if address and city and city.lower() not in address.lower():
            address = f"{address}, {city}"

        return Notice(
            source=self.source_id,
            publication=self.label,
            sale_date=sale_date,
            sale_time=sale_time,
            property_address=address,
            court_location=get("court_location"),
            county=get("county"),
            state=get("state") or self.state_default,
            title=" | ".join(c for c in cells if c)[:140],
            full_text=" | ".join(c for c in cells if c),
            url=self.url,
        )
