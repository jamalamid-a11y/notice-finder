"""Scraper registry. Add a site by importing it and listing it in SCRAPERS."""

from .virginia import VirginiaScraper

# Every scraper the app knows about. Drop new site classes here.
SCRAPERS = [
    VirginiaScraper(),
]


def get(source_id):
    for s in SCRAPERS:
        if s.source_id == source_id:
            return s
    return None
