"""Base crawler infrastructure shared by every per-vendor scraper.

The architecture doc (section 7) mandates: one crawler per vendor, retry/backoff,
and simple monitoring that flags a scraper which keeps returning zero results.

The verified target shops are **two-stage and server-rendered**:
  1. the search page lists product *links* (no price there), and
  2. each product's price / stock / package live on its own detail page.

So a vendor crawler implements two pure, testable hooks —
``find_product_urls`` (from the search HTML) and ``parse_product`` (from a
detail HTML) — and ``BaseVendorCrawler.crawl`` orchestrates fetching + retry +
result assembly. Fetching is delegated to a :class:`~optilap_crawler.fetch.Fetcher`
so the same crawler works over ``requests`` or Playwright unchanged.
"""
from __future__ import annotations

import abc
import logging
import time
from typing import Callable, List, Optional
from urllib.parse import quote

from .fetch import Fetcher
from .models import CrawlResult, CrawlStatus, ProductOffer
from .normalize import normalize_part_query

logger = logging.getLogger("optilap.crawler")

MonitorSink = Callable[[CrawlResult], None]


class CrawlerConfig:
    """Runtime knobs. Plain attributes so they can come from env/DB later."""

    def __init__(
        self,
        timeout: int = 30,
        max_retries: int = 3,
        backoff_base_s: float = 2.0,
        max_products: int = 25,
        use_browser: bool = False,
    ):
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        # Cap detail-page fetches per part so one noisy query can't stall a BOM.
        self.max_products = max_products
        # Force the Playwright fetcher (for future JS-only vendors).
        self.use_browser = use_browser


class BaseVendorCrawler(abc.ABC):
    """Abstract base for a single vendor's search scraper."""

    vendor_name: str = ""
    base_url: str = ""
    #: Search URL template containing the literal token ``[PART_NAME]``.
    search_pattern: str = ""

    def __init__(self, config: Optional[CrawlerConfig] = None):
        self.config = config or CrawlerConfig()
        if not (self.vendor_name and self.base_url and self.search_pattern):
            raise ValueError(
                f"{type(self).__name__} must set vendor_name, base_url, search_pattern"
            )

    # -- URL building --------------------------------------------------------
    def build_search_url(self, part_query: str) -> str:
        return self.search_pattern.replace("[PART_NAME]", quote(part_query, safe=""))

    # -- Hooks a subclass implements ----------------------------------------
    @abc.abstractmethod
    def find_product_urls(self, search_html: str) -> List[str]:
        """Return absolute product-detail URLs from a search results page."""

    @abc.abstractmethod
    def parse_product(self, html: str, url: str, part_query: str) -> Optional[ProductOffer]:
        """Parse one product-detail page into an offer (or None to skip)."""

    # -- Core crawl ----------------------------------------------------------
    def crawl(self, raw_part: str, fetcher: Fetcher) -> CrawlResult:
        """Crawl one part: search, then visit each product page. Never raises."""
        part_query = normalize_part_query(raw_part)
        search_url = self.build_search_url(part_query)
        started = time.monotonic()

        # Stage 1: search page -> product URLs.
        try:
            search_html = fetcher.get_html(search_url)
        except Exception as exc:  # noqa: BLE001
            return self._result(part_query, search_url, CrawlStatus.ERROR,
                                 error=f"search fetch failed: {exc}", started=started)

        try:
            urls = self.find_product_urls(search_html)
        except Exception as exc:  # noqa: BLE001
            return self._result(part_query, search_url, CrawlStatus.ERROR,
                                 error=f"link parse failed: {exc}", started=started)

        if not urls:
            return self._result(part_query, search_url, CrawlStatus.ZERO_RESULTS,
                                 started=started)

        # Stage 2: visit each product detail page.
        offers: List[ProductOffer] = []
        for url in urls[: self.config.max_products]:
            try:
                html = fetcher.get_html(url)
                offer = self.parse_product(html, url, part_query)
                if offer is not None:
                    offers.append(offer)
            except Exception as exc:  # noqa: BLE001 - one bad product isn't fatal
                logger.warning("product fetch/parse failed %s: %s", url, exc)

        status = CrawlStatus.OK if offers else CrawlStatus.ZERO_RESULTS
        return self._result(part_query, search_url, status, offers=offers, started=started)

    def _result(self, part_query, search_url, status, *, offers=None, error=None,
                started=None) -> CrawlResult:
        duration_ms = int((time.monotonic() - started) * 1000) if started else None
        return CrawlResult(
            vendor=self.vendor_name,
            part_query=part_query,
            search_url=search_url,
            status=status,
            offers=offers or [],
            error=error,
            duration_ms=duration_ms,
        )


class FailureMonitor:
    """Flags scrapers that keep failing / finding nothing (doc §7).

    Tracks consecutive non-OK results per vendor and fires ``alert`` at
    ``threshold`` — a cheap signal that a site changed its markup or blocked us.
    """

    def __init__(self, threshold: int = 3, alert: Optional[Callable[[str, str], None]] = None):
        self.threshold = threshold
        self.alert = alert or self._default_alert
        self._streaks: dict[str, int] = {}

    def observe(self, result: CrawlResult) -> None:
        vendor = result.vendor
        if result.status is CrawlStatus.OK:
            self._streaks[vendor] = 0
            return
        streak = self._streaks.get(vendor, 0) + 1
        self._streaks[vendor] = streak
        if streak == self.threshold:
            self.alert(
                vendor,
                f"{vendor}: {streak} consecutive {result.status.value} results "
                f"(last: {result.error or result.search_url})",
            )

    @staticmethod
    def _default_alert(vendor: str, message: str) -> None:  # pragma: no cover
        logger.error("SCRAPER ALERT: %s", message)
