"""
Scraper for publicnoticevirginia.com.

The site is a classic ASP.NET WebForms app: a cookieless session id lives in
the URL path -- (S(xxxx)) -- and every request must round-trip the hidden
__VIEWSTATE / __EVENTVALIDATION fields. We therefore:

  1. GET the search page, following the redirect that assigns a session id.
  2. Read every form field, then override the keyword + date inputs.
  3. POST the search, then walk the pager via __doPostBack up to max_pages.

Field names are matched heuristically (by substring), so a cosmetic rename on
the site usually won't break us. The CONFIG block at the top is where to tune
the default search if you want different keywords or a different date window.
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

# --- default search ---------------------------------------------------------
DEFAULT_KEYWORDS = (
    "foreclosure, foreclosed, foreclose, judicial sale, judgment, "
    "notice of sale, trustee's sale, forfeiture, forfeit"
)
LOOKBACK_DAYS = 60  # search window: today-LOOKBACK_DAYS .. today
PAGE_DELAY = 1.0    # seconds between page requests (be polite)


class VirginiaScraper(BaseScraper):
    source_id = "va"
    label = "Public Notice Virginia"

    def __init__(self, keywords=DEFAULT_KEYWORDS, lookback_days=LOOKBACK_DAYS):
        self.keywords = keywords
        self.lookback_days = lookback_days

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _form_state(soup):
        """Collect all hidden + visible form fields into a POST dict."""
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

    @staticmethod
    def _match_field(data, *needles):
        """Return the first form-field name whose key contains any needle."""
        for name in data:
            low = name.lower()
            if any(n in low for n in needles):
                return name
        return None

    # -- main ----------------------------------------------------------------

    def fetch(self, max_pages=100):
        sess = requests.Session()
        sess.headers.update({
            "User-Agent": "Mozilla/5.0 (notice-finder; public-records research)",
        })

        # 1. land on the search page (picks up the cookieless session redirect)
        r = sess.get(BASE + SEARCH_PATH, timeout=30, allow_redirects=True)
        r.raise_for_status()
        action_url = r.url  # now carries the (S(...)) session segment
        soup = BeautifulSoup(r.text, "lxml")

        data = self._form_state(soup)

        # 2. fill in keyword + date range
        kw = self._match_field(data, "keyword", "txtsearch", "searchtext")
        if kw:
            data[kw] = self.keywords
        d_from = self._match_field(data, "datefrom", "fromdate", "startdate", "pubfrom")
        d_to = self._match_field(data, "dateto", "todate", "enddate", "pubto")
        end = date.today()
        start = end - timedelta(days=self.lookback_days)
        if d_from:
            data[d_from] = start.strftime("%m/%d/%Y")
        if d_to:
            data[d_to] = end.strftime("%m/%d/%Y")

        # press the search button if we can find it
        btn = None
        for el in soup.select("input[type=submit], input[type=button]"):
            val = (el.get("value") or "").lower()
            if "search" in val and el.get("name"):
                btn = el["name"]
                break
        if btn:
            data[btn] = soup.select_one(f"[name='{btn}']").get("value", "Search")

        r = sess.post(action_url, data=data, timeout=60)
        r.raise_for_status()

        seen = 0
        for page in range(1, max_pages + 1):
            soup = BeautifulSoup(r.text, "lxml")
            count = 0
            for notice in self._parse_results(soup):
                count += 1
                seen += 1
                yield notice

            if count == 0 and page > 1:
                break  # ran past the last page

            nxt = self._next_postback(soup, page + 1)
            if not nxt:
                break
            data = self._form_state(soup)
            data["__EVENTTARGET"], data["__EVENTARGUMENT"] = nxt
            time.sleep(PAGE_DELAY)
            r = sess.post(action_url, data=data, timeout=60)
            r.raise_for_status()

    # -- parsing -------------------------------------------------------------

    def _parse_results(self, soup):
        """
        Each result is a block of notice text. The site renders them in a
        results panel; we grab the repeating containers and fall back to
        scanning for notice-like blocks if the markup differs.
        """
        containers = soup.select(
            ".searchResult, .result, .notice, .NoticeResult, "
            "[id*='Result'] tr, [class*='result']"
        )
        if not containers:
            # fallback: any table rows in a results-looking table
            containers = soup.select("table tr")

        for c in containers:
            text = c.get_text(" ", strip=True)
            if len(text) < 40:
                continue
            if not re.search(r"sale|foreclos|trustee|judicial|auction|notice",
                             text, re.I):
                continue
            fields = parse_all(text)
            link = c.find("a", href=True)
            yield Notice(
                source=self.source_id,
                publication=self._guess_publication(text),
                published_date=self._guess_pubdate(text),
                title=text[:120],
                full_text=text,
                url=(BASE + link["href"]) if link and link["href"].startswith("/")
                    else (link["href"] if link else None),
                **fields,
            )

    @staticmethod
    def _guess_publication(text):
        m = re.match(r"([A-Z][A-Za-z.&'/ -]{3,60}?(?:,\s+The)?)\s+(?:[A-Z][a-z]+day|\d)",
                     text)
        return m.group(1).strip() if m else None

    @staticmethod
    def _guess_pubdate(text):
        m = re.search(r"[A-Z][a-z]+day,\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4}", text)
        return m.group() if m else None

    @staticmethod
    def _next_postback(soup, page_no):
        """Find the __doPostBack target for the given page number link."""
        for a in soup.select("a[href*='__doPostBack']"):
            if a.get_text(strip=True) == str(page_no):
                m = re.search(r"__doPostBack\('([^']+)','([^']*)'\)", a["href"])
                if m:
                    return m.group(1), m.group(2)
        return None
