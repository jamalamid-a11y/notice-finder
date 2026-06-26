"""
Scraper for publicnoticevirginia.com.

Classic ASP.NET WebForms app. A cookieless session id lives in the URL path
-- (S(xxxx)) -- and every request round-trips __VIEWSTATE / __EVENTVALIDATION.

The real form field names (confirmed against the live page) are:

  search box   ctl00$ContentPlaceHolder1$as1$txtSearch
  match type   ctl00$ContentPlaceHolder1$as1$rdoType         = AND | OR | EXACT
  date mode    ctl00$ContentPlaceHolder1$as1$dateRange       = rbLastNumDays | rbRange | ...
  last N days  ctl00$ContentPlaceHolder1$as1$txtLastNumDays
  date from/to ctl00$ContentPlaceHolder1$as1$txtDateFrom / txtDateTo
  search btn   ctl00$ContentPlaceHolder1$as1$btnGo

Results render as <table class="nested"> blocks (publication / date / notice
text). The pager is a GridView with image buttons (btnNext etc.) and a
per-page <select> (ddlPerPage) that we set to 50 to minimise requests.
"""

import re
import time

import requests
from bs4 import BeautifulSoup

from .base import BaseScraper, Notice
from parsers import parse_all

BASE = "https://www.publicnoticevirginia.com"
SEARCH_PATH = "/Search.aspx"

AS = "ctl00$ContentPlaceHolder1$as1$"
GRID = "ctl00$ContentPlaceHolder1$WSExtendedGridNP1$GridView1$ctl01$"

DEFAULT_KEYWORDS = (
    "foreclosure, foreclose, foreclosed, trustee sale, judicial sale, "
    "notice of sale, forfeiture, forfeit"
)
LOOKBACK_DAYS = 60
PER_PAGE = 50         # 5/10/15/20/25/30/50 are the site's allowed values
PAGE_DELAY = 1.0


class VirginiaScraper(BaseScraper):
    source_id = "va"
    label = "Public Notice Virginia"

    def __init__(self, keywords=DEFAULT_KEYWORDS, lookback_days=LOOKBACK_DAYS):
        self.keywords = keywords
        self.lookback_days = lookback_days

    # -- form helpers --------------------------------------------------------

    @staticmethod
    def _form_state(soup):
        data = {}
        for el in soup.select("input"):
            name = el.get("name")
            if not name:
                continue
            t = (el.get("type") or "text").lower()
            if t in ("submit", "button", "image"):
                continue
            if t in ("checkbox", "radio") and not el.has_attr("checked"):
                continue
            data[name] = el.get("value", "")
        for sel in soup.select("select"):
            name = sel.get("name")
            if not name:
                continue
            opt = sel.find("option", selected=True) or sel.find("option")
            data[name] = opt.get("value", "") if opt else ""
        for ta in soup.select("textarea"):
            if ta.get("name"):
                data[ta["name"]] = ta.text
        return data

    # -- main ----------------------------------------------------------------

    def fetch(self, max_pages=100):
        sess = requests.Session()
        sess.headers.update({
            "User-Agent": "Mozilla/5.0 (notice-finder; public-records research)",
        })

        # 1. land on the search page (picks up the cookieless session redirect)
        r = sess.get(BASE + SEARCH_PATH, timeout=30, allow_redirects=True)
        r.raise_for_status()
        action_url = r.url
        soup = BeautifulSoup(r.text, "lxml")

        # 2. run the search
        data = self._form_state(soup)
        data[AS + "txtSearch"] = self.keywords
        data[AS + "rdoType"] = "OR"                 # match ANY of the keywords
        data[AS + "dateRange"] = "rbLastNumDays"
        data[AS + "txtLastNumDays"] = str(self.lookback_days)
        data[AS + "btnGo"] = ""                      # press the search button
        r = sess.post(action_url, data=data, timeout=60)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")

        # 3. bump results-per-page to 50 (autopostback on the dropdown)
        if soup.select_one(f"[name='{GRID}ddlPerPage']"):
            data = self._form_state(soup)
            data[GRID + "ddlPerPage"] = str(PER_PAGE)
            data["__EVENTTARGET"] = GRID + "ddlPerPage"
            data["__EVENTARGUMENT"] = ""
            r = sess.post(action_url, data=data, timeout=60)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")

        # 4. walk pages via the Next image button
        for page in range(1, max_pages + 1):
            count = 0
            for notice in self._parse_results(soup):
                count += 1
                yield notice
            if count == 0:
                break
            if not soup.select_one(f"[name='{GRID}btnNext']"):
                break
            cur, total = self._page_info(soup)
            if total and cur >= total:
                break
            data = self._form_state(soup)
            data[GRID + "btnNext.x"] = "1"           # ImageButton needs x/y
            data[GRID + "btnNext.y"] = "1"
            time.sleep(PAGE_DELAY)
            r = sess.post(action_url, data=data, timeout=60)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")

    # -- parsing -------------------------------------------------------------

    def _parse_results(self, soup):
        for block in soup.select("table.nested"):
            text = block.get_text("\n", strip=True)
            lines = [ln for ln in (l.strip() for l in text.split("\n")) if ln]
            if len(lines) < 2:
                continue
            body = " ".join(lines[2:]) if len(lines) > 2 else " ".join(lines)
            if not re.search(r"sale|foreclos|trustee|judicial|auction|notice",
                             body, re.I):
                continue
            publication = lines[0]
            published = lines[1] if self._looks_like_date(lines[1]) else None
            fields = parse_all(body)
            link = block.find("a", href=True)
            yield Notice(
                source=self.source_id,
                publication=publication,
                published_date=published,
                title=body[:140],
                full_text=body,
                url=(BASE + link["href"]) if link and link["href"].startswith("/")
                    else None,
                **fields,
            )

    @staticmethod
    def _looks_like_date(s):
        return bool(re.search(r"\d{4}|\d{1,2}/\d{1,2}", s or ""))

    @staticmethod
    def _page_info(soup):
        m = re.search(r"Page\s+(\d+)\s+of\s+(\d+)", soup.get_text(" ", strip=True), re.I)
        return (int(m.group(1)), int(m.group(2))) if m else (None, None)
