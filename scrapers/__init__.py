"""Scraper registry. Add a site by importing it and listing it in SCRAPERS."""

from .virginia import VirginiaScraper
from .html_table import HtmlTableScraper
from .extra import (DivListScraper, PdfSalesScraper, CsvScraper,
                    EnoticeScraper, WaTimesScraper, RefererTableScraper,
                    PowerBIScraper, AuctionIndexScraper)

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
    PowerBIScraper(
        "logs", "LOGS Legal Group",
        cluster="https://wabi-us-north-central-h-primary-api.analysis.windows.net",
        resource_key="62ddb3de-c988-4812-8a65-4bc70d8c132b",
        model_id=453013,
        entity="web Upcoming Sales Report  VA",
        columns=[("FULL_ADDRESS", "property_address"),
                 ("SALE_DATE", "sale_date"),
                 ("SALE_TIME", "sale_time"),
                 ("COUNTY_NAME", "county"),
                 ("STATE_CODE", "state"),
                 ("CONTACT_COMP_NAME", "_company")],
        url="https://www.logs.com/va-sales-report.html"),
    RefererTableScraper("aldridgepite", "Aldridge Pite",
                        "https://aldridgepite.com/sale-day-listings-selection/foreclosure-listings-virginia/",
                        referer="https://aldridgepite.com/disclaimer-virginia/"),
    # Auction houses (commercial + residential). DMV-only; property type is
    # classified app-side so the commercial filter picks up true commercial lots.
    AuctionIndexScraper("ajbillig", "AJ Billig (auctions)",
                        base="https://ajbillig.com",
                        index_url="https://ajbillig.com/auction-list/",
                        link_re=r'href="(https://ajbillig\.com/auction/[^"/]+/)"'),
    AuctionIndexScraper("dudley", "Dudley Resources (auctions)",
                        base="https://www.dudleyresources.auction",
                        index_url="https://www.dudleyresources.auction/auctions",
                        link_re=r'href="(/auctions/detail/[^"]+)"'),
    AuctionIndexScraper("alexcooper", "Alex Cooper (auctions)",
                        base="https://realestate.alexcooper.com",
                        seed_urls=[
                            "https://realestate.alexcooper.com/auction-property/1-6GYU5F/"
                            "substitute-trustees-sale-multi-tenant-retail-shopping-center-"
                            "known-as-the-shops-at-congressional-village-aone-story-commercial-"
                            "building-and-a-leasehold-interest-of-the-first-floor-of-192-"
                            "halpine-road-in-rockville"]),
    VirginiaScraper(),   # slow (day-by-day, ~8 min) — kept last so fast sources load first
]


def get(source_id):
    for s in SCRAPERS:
        if s.source_id == source_id:
            return s
    return None
