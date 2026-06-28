"""Scraper registry. Add a site by importing it and listing it in SCRAPERS."""

from .virginia import VirginiaScraper
from .html_table import HtmlTableScraper
from .extra import (DivListScraper, PdfSalesScraper, CsvScraper,
                    EnoticeScraper, WaTimesScraper)

# Every scraper the app knows about.
#  - VirginiaScraper: the publicnoticevirginia.com portal (day-by-day search).
#  - HtmlTableScraper: law-firm sale lists that are plain static HTML tables.
#  - DivListScraper / PdfSalesScraper / CsvScraper / EnoticeScraper / WaTimesScraper.
SCRAPERS = [
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
    HtmlTableScraper("dolanreid", "Dolan Reid",
                     "https://dolanreid.com/foreclosure-sales/"),
    DivListScraper("brockscott", "Brock & Scott",
                   "https://www.brockandscott.com/foreclosure-sales/?_sft_foreclosure_state=va",
                   item_selector="article.foreclosure_search",
                   field_selector="div.forecol"),
    CsvScraper("cgd", "CGD Law",
               "https://cgd-law.com/va/data/sales.csv", delimiter=";"),
    PdfSalesScraper("siwpc", "Samuel I. White (PDF)",
                    "https://www.siwpc.net/AutoUpload/Sales.pdf"),
    EnoticeScraper("wapo", "Washington Post (public notices)",
                   "https://us-central1-enotice-demo-8d99a.cloudfunctions.net/api/",
                   newspaper="The Washington Post",
                   notice_types=["Trustee Sale"]),
    WaTimesScraper(),
    VirginiaScraper(),   # slow (day-by-day, ~8 min) — kept last so fast sources load first
]


def get(source_id):
    for s in SCRAPERS:
        if s.source_id == source_id:
            return s
    return None
