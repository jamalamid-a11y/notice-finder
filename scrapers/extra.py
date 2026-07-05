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
import time

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

from .base import BaseScraper, Notice

try:
    from parsers import parse_all as _parse_all
except Exception:  # parsers lives at project root; fall back to no-op if missing
    def _parse_all(_text):
        return {}

_STATE_NAMES = {"maryland": "MD", "virginia": "VA", "dc": "DC",
                "district of columbia": "DC", "washington dc": "DC"}

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


class EnoticeScraper(BaseScraper):
    """
    Public-notice portals built on the Column / "enotice" platform (e.g. The
    Washington Post at publicnotices.washingtonpost.com). They search an
    Elasticsearch backend exposed as a Cloud Function:
        POST {backend}search/public-notices  {"data": {...}}
    Each result carries the full notice `text`; we run it through the VA notice
    parser to pull sale date/time and property address.
    """

    def __init__(self, source_id, label, backend, newspaper,
                 notice_types=("Trustee Sale",), lookback_days=60):
        self.source_id = source_id
        self.label = label
        self.backend = backend.rstrip("/") + "/"
        self.newspaper = newspaper
        self.notice_types = list(notice_types)
        self.lookback_days = lookback_days

    def fetch(self, max_pages=1):
        since = int((time.time() - self.lookback_days * 86400) * 1000)
        filters = [{"newspapername": [self.newspaper]},
                   {"noticetype": self.notice_types},
                   {"publishedtimestamp": {"from": since}}]
        payload = {"data": {
            "search": "", "allFilters": filters, "noneFilters": [],
            "sort": [{"publishedtimestamp": "desc"}],
            "pageSize": 1000, "isDemo": False,
        }}
        r = requests.post(self.backend + "search/public-notices",
                          json=payload, headers=UA, timeout=60)
        r.raise_for_status()
        for rec in (r.json() or {}).get("results", []):
            # the backend pins a few demo records at the top — keep only ours
            if rec.get("newspapername") != self.newspaper:
                continue
            text = rec.get("text") or ""
            if not text.strip():
                continue
            parsed = _parse_all(text)
            county = (rec.get("county") or parsed.get("county") or "")
            county = re.sub(r"\s+County$", "", county).strip() or None
            state = _STATE_NAMES.get((rec.get("state") or "").strip().lower(),
                                     rec.get("state") or None)
            ts = rec.get("publishedtimestamp")
            pub = (dateparser.parse(time.strftime(
                "%Y-%m-%d", time.gmtime(ts / 1000))).strftime("%Y-%m-%d")
                if ts else None)
            yield Notice(
                source=self.source_id, publication=self.label,
                published_date=pub,
                sale_date=parsed.get("sale_date"),
                sale_time=parsed.get("sale_time"),
                property_address=parsed.get("property_address"),
                court_location=parsed.get("court_location"),
                county=county, state=state,
                title=text[:140], full_text=text[:4000],
                url=rec.get("pdfurl") or "https://publicnotices.washingtonpost.com/",
            )


class WaTimesScraper(BaseScraper):
    """
    The Washington Times classifieds (classified.washingtontimes.com) — an
    AdPortal site that files foreclosure sales under per-jurisdiction categories
    (Foreclosure-Sales-FFX-Cty, -PG-Cty, -DC, ...). The category page lists the
    newest sales; each links to a detail page whose "Seller's Comments and
    Description" block holds the full notice, which we run through the VA parser.
    """

    BASE = "http://classified.washingtontimes.com/"
    # (category path, county label, state)
    # Fairfax and Prince William first: their deeper pages hold the this-week
    # sales users most often report missing, and the TIME_BUDGET below may not
    # reach categories near the end when the site is slow to respond.
    CATEGORIES = [
        ("category/358/Foreclosure-Sales-FFX-Cty", "Fairfax", "VA"),
        ("category/394/Foreclosure-Sales-PW-Cty", "Prince William", "VA"),
        ("category/354/Foreclosure-Sales-ALEX-Cty", "Alexandria", "VA"),
        ("category/355/Foreclosure-Sales-ARL-Cty", "Arlington", "VA"),
        ("category/357/Foreclosure-Sales-DC", "Washington", "DC"),
        ("category/359/Foreclosure-Sales-Mont-Cty", "Montgomery", "MD"),
        ("category/360/Foreclosure-Sales-PG-Cty", "Prince George's", "MD"),
        ("category/393/Foreclosure-Sales-Charles-Cty", "Charles", "MD"),
        ("category/405/Forclosure-Sales-VA", None, "VA"),
    ]

    # Walk deep enough to catch this-week sales that newer postings pushed onto
    # later pages (e.g. 9324 Taney Rd sat on page 4 of the PW list), but not so
    # deep that the free-tier refresh drowns in sequential requests. (The site's
    # huge site-wide "Legal-Notices" category is deliberately not walked here —
    # it's mostly non-foreclosure and too request-heavy for the free tier; the
    # per-county lists below already carry the trustee sales we need.)
    MAX_PAGES = 5  # how many category-browse pages to walk (10 listings each)

    def __init__(self, source_id="watimes", label="Washington Times (foreclosure notices)",
                 per_category=50):
        self.source_id = source_id
        self.label = label
        self.per_category = per_category

    def _detail_links(self, cat_path):
        # The category browse shows ~10 newest per page; older-but-still-upcoming
        # sales sit on later pages (.../<slug>/2.html, /3.html, ...). Page through
        # a few pages so we catch this-week sales that newer postings pushed down,
        # without hammering the site with hundreds of requests each refresh.
        seen = []
        for page in range(1, self.MAX_PAGES + 1):
            url = self.BASE + cat_path + ("" if page == 1 else "/%d" % page) + ".html"
            try:
                r = requests.get(url, headers=UA, timeout=10)
                r.raise_for_status()
            except Exception:
                break
            # detail pages look like category/<id>/<slug>/listings/<set>/<num>.html
            links = re.findall(r'category/\d+/[A-Za-z0-9-]+/listings/\d+/\d+\.html',
                               r.text)
            new = [l for l in links if l not in seen]
            if not new:
                break
            seen.extend(new)
            if len(seen) >= self.per_category:
                break
        return seen[: self.per_category]

    def _detail_text(self, html):
        soup = BeautifulSoup(html, "lxml")
        h3 = soup.find(lambda t: t.name == "h3"
                       and "Seller's Comments" in t.get_text())
        if h3:
            cont = h3.find_parent("div") or h3.parent
            text = cont.get_text(" ", strip=True)
            text = re.sub(r"^.*?Seller's Comments and Description:\s*", "", text)
        else:
            text = soup.get_text(" ", strip=True)
        return re.sub(r"\s+", " ", text).strip()

    # these notices almost always lead with "TRUSTEE['S] SALE <property address>"
    # (or "...KNOWN AS <address>"); prefer that over the parser's guess, which
    # sometimes latches onto the trustee's own office address instead.
    _ADDR_PATTERNS = (
        r"TRUSTEE'?S?\s+SALE\s+(?:OF\b[^|]*?KNOWN AS\s+)?(\d[^.]{5,110}?)"
        r"\s+(?:In execution|Under\b|[A-Z][a-z]+ County)",
        r"KNOWN AS\s+(\d[^.]{5,110}?)\s+(?:Under\b|In execution)",
    )

    def _address(self, text, fallback):
        for pat in self._ADDR_PATTERNS:
            m = re.search(pat, text, re.I)
            if m:
                cand = m.group(1).strip(" ,.")
                if re.search(r"\d", cand):
                    return cand
        return fallback

    # trustee/foreclosure-sale language used to keep only relevant notices out of
    # the mixed Legal-Notices category.
    _FORECLOSURE_RE = re.compile(
        r"trustee'?s?\s+sale|substitute\s+trustee|foreclosure\s+sale", re.I)

    # Hard wall-clock budget for the whole scrape. The site sometimes throttles
    # our detail-page fetches, and on the free tier an unbounded walk hangs the
    # startup refresh — so we stop after this many seconds and keep what we got.
    TIME_BUDGET = 90

    def fetch(self, max_pages=1):
        deadline = time.time() + self.TIME_BUDGET
        for cat_path, county, state in self.CATEGORIES:
            if time.time() > deadline:
                break
            is_legal = "Legal-Notices" in cat_path
            try:
                links = self._detail_links(cat_path)
            except Exception:
                continue
            for link in links:
                if time.time() > deadline:
                    break
                try:
                    dr = requests.get(self.BASE + link, headers=UA, timeout=10)
                    dr.raise_for_status()
                except Exception:
                    continue
                text = self._detail_text(dr.text)
                if not text or len(text) < 40:
                    continue
                # the Legal-Notices section carries many non-foreclosure filings.
                if is_legal and not self._FORECLOSURE_RE.search(text):
                    continue
                parsed = _parse_all(text)
                addr = self._address(text, parsed.get("property_address"))
                ccounty = county or parsed.get("county")
                if ccounty:
                    ccounty = re.sub(r"\s+(County|Cty\.?)$", "", ccounty).strip()
                # categories without a fixed state (VA-wide, Legal-Notices): read
                # the state off the address, falling back to VA.
                nstate = state or _state_from(addr or "") or _state_from(text) or "VA"
                yield Notice(
                    source=self.source_id, publication=self.label,
                    sale_date=parsed.get("sale_date"),
                    sale_time=parsed.get("sale_time"),
                    property_address=addr,
                    court_location=parsed.get("court_location"),
                    county=ccounty, state=nstate,
                    title=text[:140], full_text=text[:4000],
                    url=self.BASE + link,
                )


class RefererTableScraper(BaseScraper):
    """
    A static HTML <table> that the site only serves after a disclaimer page has
    been visited (it checks the Referer). Aldridge Pite's per-state foreclosure
    listings work this way: the rows render server-side once we send Referer =
    the disclaimer URL. Columns are read from each <th data-name="...">.
    """

    def __init__(self, source_id, label, url, referer, state_default="VA"):
        self.source_id = source_id
        self.label = label
        self.url = url
        self.referer = referer
        self.state_default = state_default

    def fetch(self, max_pages=1):
        r = requests.get(self.url, headers={**UA, "Referer": self.referer}, timeout=45)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        table = None
        for t in soup.find_all("table"):
            if t.find("th", attrs={"data-name": "Address"}):
                table = t
                break
        if table is None:
            return
        heads = [th.get("data-name") for th in table.select("thead th")]
        for tr in table.select("tbody tr"):
            tds = tr.find_all("td")
            if len(tds) < len(heads):
                continue
            row = {heads[i]: tds[i].get_text(" ", strip=True)
                   for i in range(len(heads)) if heads[i]}
            sale_date, sale_time = _split_dt(row.get("Date_Listed") or "")
            addr = ", ".join(x for x in (row.get("Address"), row.get("City"),
                                         row.get("State"), row.get("Zip")) if x)
            county = re.sub(r"\s+County$", "", row.get("County") or "").strip() or None
            yield Notice(
                source=self.source_id, publication=self.label,
                sale_date=sale_date, sale_time=sale_time,
                property_address=addr, county=county,
                state=row.get("State") or self.state_default,
                title=(row.get("title") or addr)[:140],
                full_text=" | ".join(f"{k}: {v}" for k, v in row.items() if v),
                url=self.url,
            )


class PowerBIScraper(BaseScraper):
    """
    A PowerBI "publish to web" report (app.powerbi.com/view?r=...). Rather than
    drive a headless browser we call the same public API the embed uses:
        POST {cluster}/public/reports/querydata?synchronous=true
        header  X-PowerBI-ResourceKey: <key>
    LOGS Legal Group's VA foreclosure list is one of these. The response is a
    dictionary-encoded "DSR" shape (row values are indices into per-column
    ValueDicts, with a repeat bitmap for values unchanged from the prior row);
    _parse_dsr unpacks it. cluster/key/model_id/entity/columns are read once from
    the report (modelsAndExploration) and pasted in when registering the source.
    """

    def __init__(self, source_id, label, cluster, resource_key, model_id,
                 entity, columns, url, state_default="VA"):
        # columns: ordered [(powerbi_property, notice_field)] where notice_field
        # is property_address / sale_date / sale_time / county / state / _company.
        self.source_id = source_id
        self.label = label
        self.cluster = cluster.rstrip("/")
        self.resource_key = resource_key
        self.model_id = model_id
        self.entity = entity
        self.columns = columns
        self.url = url
        self.state_default = state_default

    def fetch(self, max_pages=1):
        select = [{"Column": {"Expression": {"SourceRef": {"Source": "u"}},
                              "Property": prop}, "Name": "u.%s" % prop}
                  for prop, _ in self.columns]
        body = {
            "version": "1.0.0",
            "queries": [{
                "Query": {"Commands": [{"SemanticQueryDataShapeCommand": {
                    "Query": {"Version": 2,
                              "From": [{"Name": "u", "Entity": self.entity, "Type": 0}],
                              "Select": select},
                    "Binding": {"Primary": {"Groupings": [
                                    {"Projections": list(range(len(self.columns)))}]},
                                "DataReduction": {"DataVolume": 3,
                                    "Primary": {"Window": {"Count": 30000}}},
                                "Version": 1},
                }}]},
                "QueryId": "",
                "ApplicationContext": {"DatasetId": str(self.model_id)},
            }],
            "cancelQueries": [],
            "modelId": self.model_id,
        }
        headers = dict(UA)
        headers["X-PowerBI-ResourceKey"] = self.resource_key
        headers["Content-Type"] = "application/json;charset=UTF-8"
        r = requests.post(self.cluster + "/public/reports/querydata?synchronous=true",
                          json=body, headers=headers, timeout=60)
        r.raise_for_status()
        ds = r.json()["results"][0]["result"]["data"]["dsr"]["DS"][0]
        for row in self._parse_dsr(ds):
            f = dict(zip((fld for _, fld in self.columns), row))
            yield Notice(
                source=self.source_id, publication=self.label,
                sale_date=self._pbi_date(f.get("sale_date")),
                sale_time=self._pbi_time(f.get("sale_time")),
                property_address=f.get("property_address"),
                county=f.get("county"),
                state=f.get("state") or self.state_default,
                court_location=None,
                title=(f.get("_company") or self.label)[:140],
                full_text=" | ".join(str(f[k]) for k in
                                     ("property_address", "county", "state", "_company")
                                     if f.get(k)),
                url=self.url,
            )

    def _parse_dsr(self, ds):
        rows = (ds.get("PH") or [{}])[0].get("DM0", [])
        dicts = ds.get("ValueDicts", {})
        n = len(self.columns)
        schema = None
        prev = [None] * n
        for dm in rows:
            if "S" in dm:
                schema = dm["S"]
            cvals = dm.get("C", [])
            rep = dm.get("R", 0)          # bit i set -> value repeats prior row
            nul = dm.get("Ø", 0)     # bit i set -> value is null
            out, ci = [], 0
            for i in range(n):
                if nul & (1 << i):
                    v = None
                elif rep & (1 << i):
                    v = prev[i]
                else:
                    v = cvals[ci] if ci < len(cvals) else None
                    ci += 1
                out.append(v)
            prev = list(out)
            resolved = []
            for i in range(n):
                v = out[i]
                dn = schema[i].get("DN") if (schema and i < len(schema)) else None
                if dn and isinstance(v, int) and 0 <= v < len(dicts.get(dn, [])):
                    v = dicts[dn][v]
                resolved.append(v)
            yield resolved

    @staticmethod
    def _pbi_date(ms):
        if isinstance(ms, (int, float)):
            try:
                return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))
            except (ValueError, OverflowError, OSError):
                return None
        return None

    @staticmethod
    def _pbi_time(ms):
        if isinstance(ms, (int, float)):
            secs = int(ms / 1000)
            h, m = secs // 3600, (secs % 3600) // 60
            return "%d:%02d %s" % (h % 12 or 12, m, "AM" if h < 12 else "PM")
        return None
