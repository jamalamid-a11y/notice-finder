"""
Scraper for publicnoticevirginia.com.

Classic ASP.NET WebForms app: cookieless session in the URL path, __VIEWSTATE
round-trips. Real field names (confirmed against the live page):

  search box   ctl00$ContentPlaceHolder1$as1$txtSearch
  match type   ctl00$ContentPlaceHolder1$as1$rdoType      = AND | OR | EXACT
  date mode    ctl00$ContentPlaceHolder1$as1$dateRange     = rbLastNumDays | rbRange
  date from/to ctl00$ContentPlaceHolder1$as1$txtDateFrom / txtDateTo
  search btn   ctl00$ContentPlaceHolder1$as1$btnGo

Results render as <table class="nested"> blocks. The pager is a GridView with
image buttons (btnNext) and a per-page <select> (ddlPerPage).

IMPORTANT -- the 100-page cap: the site only lets you page through the first
1000 records of ANY search. Foreclosure notices are republished weekly across
many papers, so a broad multi-day search easily exceeds 1000 records and the
older notices become unreachable (this is why a specific property could be
missing). The fix is to search ONE DAY AT A TIME: a single day stays well under
the cap, so every notice is reachable. We then merge + de-duplicate upstream.
"""

import re
import time
from datetime import date, timedelta

import requests
from bs4 import BeautifulSoup

from .base import BaseScraper, Notice
from parsers import parse_all

BASE = "https://www.publicnoticevirginia.com"
SEARCH_PATH = "/Search.aspx"

AS = "ctl00$ContentPlaceHolder1$as1$"
GRID = "ctl00$ContentPlaceHolder1$WSExtendedGridNP1$GridView1$ctl01$"

# The site's own "Popular Searches -> Foreclosures" preset, captured from the
# live page. Its syntax matters: terms are separated by DOUBLE spaces and a '+'
# joins the words of a phrase ("real+estate" = the phrase "real estate").
# Comma-separated keywords are NOT the site's format and match poorly.
DEFAULT_KEYWORDS = (
    "real+estate  foreclosure  foreclosed  foreclose  judicial+sale  "
    "judgment  notice+of+sale  forfeiture  forfeit"
)
LOOKBACK_DAYS = 30      # days back from today, searched one day at a time
PER_PAGE = 50           # 5/10/15/20/25/30/50 are the site's allowed values
PAGE_DELAY = 0.6        # seconds between requests (be polite)
PAGE_CAP = 100          # site never serves past page 100


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

    def fetch(self, max_pages=PAGE_CAP):
        sess = requests.Session()
        sess.headers.update({
            "User-Agent": "Mozilla/5.0 (notice-finder; public-records research)",
        })

        r = sess.get(BASE + SEARCH_PATH, timeout=30, allow_redirects=True)
        r.raise_for_status()
        action_url = r.url
        soup = BeautifulSoup(r.text, "lxml")

        today = date.today()
        for offset in range(self.lookback_days + 1):
            day = today - timedelta(days=offset)
            yield from self._fetch_day(sess, action_url, soup, day, max_pages)
            # refresh soup reference for the next day's form state
            soup = self._last_soup or soup

    _last_soup = None

    def _fetch_day(self, sess, action_url, soup, day, max_pages):
        ds = f"{day.month}/{day.day}/{day.year}"   # m/d/Y, no zero-padding

        data = self._form_state(soup)
        data[AS + "txtSearch"] = self.keywords
        data[AS + "rdoType"] = "OR"
        data[AS + "dateRange"] = "rbRange"
        data[AS + "txtDateFrom"] = ds
        data[AS + "txtDateTo"] = ds
        data[AS + "btnGo"] = ""
        r = sess.post(action_url, data=data, timeout=60)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")

        if soup.select_one(f"[name='{GRID}ddlPerPage']"):
            data = self._form_state(soup)
            data[GRID + "ddlPerPage"] = str(PER_PAGE)
            data["__EVENTTARGET"] = GRID + "ddlPerPage"
            data["__EVENTARGUMENT"] = ""
            r = sess.post(action_url, data=data, timeout=60)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")

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
            if total and cur and cur >= total:
                break
            data = self._form_state(soup)
            data[GRID + "btnNext.x"] = "1"
            data[GRID + "btnNext.y"] = "1"
            time.sleep(PAGE_DELAY)
            r = sess.post(action_url, data=data, timeout=60)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")

        self._last_soup = soup

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
            published = lines[1] if self._looks_like_date(lines[1]) else None
            fields = parse_all(body)
            yield Notice(
                source=self.source_id,
                publication=lines[0],
                published_date=published,
                title=body[:140],
                full_text=body,
                state="VA",
                url=self._detail_url(block),
                **fields,
            )

    @staticmethod
    def _detail_url(block):
        """Per-notice permalink.

        The row's <a href> is a bare "/Details.aspx" with no identifier; the
        real target is in the row's onclick:
            location.href='Details.aspx?SID=<session>&ID=502803'
        SID is session-scoped and expires, so keep only the stable numeric ID.
        """
        m = re.search(r"Details\.aspx\?[^'\"]*?\bID=(\d+)", str(block), re.I)
        if m:
            return f"{BASE}/Details.aspx?ID={m.group(1)}"
        link = block.find("a", href=True)
        href = link["href"] if link else ""
        return BASE + href if href.startswith("/") else None

    @staticmethod
    def _looks_like_date(s):
        return bool(re.search(r"\d{4}|\d{1,2}/\d{1,2}", s or ""))

    @staticmethod
    def _page_info(soup):
        el = soup.select_one("[id*='lblCurrentPage']")
        tot = soup.select_one("[id*='lblTotalPages']")
        cur = int(el.get_text(strip=True)) if el and el.get_text(strip=True).isdigit() else None
        m = re.search(r"(\d+)", tot.get_text(strip=True)) if tot else None
        total = int(m.group(1)) if m else None
        return cur, total
