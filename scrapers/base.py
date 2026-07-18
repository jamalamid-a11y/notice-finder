"""
Base scraper interface.

Every site lives in its own module under scrapers/ and exposes a subclass of
BaseScraper. To add one of your other websites, copy virginia.py, rename the
class, and rewrite fetch(). The rest of the app (storage, UI, filtering)
needs no changes.
"""

from abc import ABC, abstractmethod


class Notice:
    """One public-notice record, normalised across all sites."""

    __slots__ = (
        "source", "publication", "published_date", "title",
        "sale_date", "sale_time", "property_address", "court_location",
        "county", "state", "full_text", "url",
        # Parsed out of the notice prose. On truncated search-result snippets
        # these are often blank -- the values live in the full notice text,
        # which sits behind a CAPTCHA and is not fetched.
        "trustee_name", "trustee_contact", "deposit", "tax_value",
    )

    def __init__(self, source, publication=None, published_date=None, title=None,
                 sale_date=None, sale_time=None, property_address=None,
                 court_location=None, county=None, state=None,
                 full_text=None, url=None, trustee_name=None,
                 trustee_contact=None, deposit=None, tax_value=None):
        self.source = source
        self.publication = publication
        self.published_date = published_date
        self.title = title
        self.sale_date = sale_date
        self.sale_time = sale_time
        self.property_address = property_address
        self.court_location = court_location
        self.county = county
        self.state = state
        self.full_text = full_text
        self.url = url
        self.trustee_name = trustee_name
        self.trustee_contact = trustee_contact
        self.deposit = deposit
        self.tax_value = tax_value

    def as_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}


class BaseScraper(ABC):
    # short id used in the DB and the UI source filter
    source_id = "base"
    # human label
    label = "Base"

    @abstractmethod
    def fetch(self, max_pages=100):
        """Yield Notice objects. Implementations should be polite (rate-limit)."""
        raise NotImplementedError
