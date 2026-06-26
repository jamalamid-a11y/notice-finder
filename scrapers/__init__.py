"""Scraper registry. Add a site by importing it and listing it in SCRAPERS."""

from .virginia import VirginiaScraper
from .html_table import HtmlTableScraper
from .extra import DivListScraper, PdfSalesScraper

# Every scraper the app knows about.
#  - VirginiaScraper: the publicnoticevirginia.com portal (day-by-day search).
#  - HtmlTableScraper: law-firm sale lists that are plain static HTML tables.
#  - DivListScraper / PdfSalesScraper: div-list and PDF sources.
SCRAPERS = [
    VirginiaScraper(),
    HtmlTableScraper("mwc", "Samuel I. White (MWC)",
                     "https://apps.mwc-law.com/SalesLists/VA.html"),
    HtmlTableScraper("rosenberg", "Rosenberg & Associates",
                     "https://rosenberg-assoc.com/foreclosure-sales/"),
    HtmlTableScraper("tmp", "Trustee Members (TMP)",
                     "https://tmppllc.com/virginia_foreclosure_sales"),
    HtmlTableScraper("glasser", "Glasser & Glasser",
                     "https://www.glasserlaw.com/New%20Folder/Foreclosure%20Sales.html"),
    HtmlTableScraper("valaw_hud", "Virginia Law Office (HUD)",
                     "https://www.virginialawoffice.com/hud"),
    DivListScraper("brockscott", "Brock & Scott",
                   "https://www.brockandscott.com/foreclosure-sales/?_sft_foreclosure_state=va",
                   item_selector="article.foreclosure_search",
                   field_selector="div.forecol"),
    PdfSalesScraper("siwpc", "Samuel I. White (PDF)",
                    "https://www.siwpc.net/AutoUpload/Sales.pdf"),
]


def get(source_id):
    for s in SCRAPERS:
        if s.source_id == source_id:
            return s
    return None
