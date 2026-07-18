"""Scraper registry.

This project pulls from a SINGLE source: publicnoticevirginia.com, the
Commonwealth's official legal-notice site. Trustee-sale / foreclosure notices
are legally required to be published there, so it is the most complete single
feed for Virginia.

Scope note: Virginia only. Maryland and DC notices are out of scope by
definition -- publicnoticevirginia.com does not carry them.

Data note: the site's search results are TRUNCATED snippets. The full notice
text (which carries the auction date/time, trustee contact, deposit and tax
value) sits behind a CAPTCHA on Details.aspx and is deliberately not fetched,
so those fields are populated only when they happen to fall inside the snippet.
raw_text is always stored so a bad parse can be audited.
"""

from .virginia import VirginiaScraper

SCRAPERS = [
    VirginiaScraper(),
]


def get(source_id):
    for s in SCRAPERS:
        if s.source_id == source_id:
            return s
    return None
