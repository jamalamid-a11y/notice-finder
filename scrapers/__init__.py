"""Scraper registry. Add a site by importing it and listing it in SCRAPERS."""

from .virginia import VirginiaScraper
from .html_table import HtmlTableScraper

# Every scraper the app knows about.
#  - VirginiaScraper: the publicnoticevirginia.com portal (day-by-day search).
#  - HtmlTableScraper: law-firm sale lists that are plain static HTML tables.
#    Columns are auto-mapped by header name, so each only needs id/label/url.
SCRAPERS = [
    VirginiaScraper(),
    HtmlTableScraper("mwc", "Samuel I. White (MWC)",
                     "https://apps.mwc-law.com/SalesLists/VA.html"),
    HtmlTableScraper("rosenberg", "Rosenberg & Associates",
                     "https://rosenberg-assoc.com/foreclosure-sales/"),
    HtmlTableScraper("brockscott", "Brock & Scott",
                     "https://www.brockandscott.com/foreclosure-sales/?_sft_foreclosure_state=va"),
    HtmlTableScraper("tmp", "Trustee Members (TMP)",
                     "https://tmppllc.com/virginia_foreclosure_sales"),
    HtmlTableScraper("glasser", "Glasser & Glasser",
                     "https://www.glasserlaw.com/New%20Folder/Foreclosure%20Sales.html"),
    HtmlTableScraper("valaw_hud", "Virginia Law Office (HUD)",
                     "https://www.virginialawoffice.com/hud"),
]


def get(source_id):
    for s in SCRAPERS:
        if s.source_id == source_id:
            return s
    return None
