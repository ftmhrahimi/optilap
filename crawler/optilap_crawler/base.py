"""Base crawler infrastructure shared by every per-vendor scraper.

The architecture doc (section 7) mandates:
  * one crawler per vendor (each site's HTML differs),
  * Playwright because storefronts are JavaScript-heavy,
  * retry/backoff, and
  * simple monitoring that flags a scraper which keeps returning zero results.

``BaseVendorCrawler`` owns the Playwright lifecycle and the retry loop; each
vendor subclass only implements ``parse_results_html`` (pure, testable) and,
optionally, ``wait_for_results`` to describe when the page is "ready".
"""
from __future__ import annotations

import abc
import asyncio
import logging
import time
from typing import Callable, List, Optional
from urllib.parse import quote

from .models import CrawlResult, CrawlStatus, ProductOffer
from .normalize import normalize_part_query

logger = logging.getLogger("optilap.crawler")

# A monitoring sink is any callable that receives finished CrawlResults. The
# default implementation just logs; the backend will later wire this to an
# alerting channel (see FailureMonitor below).
MonitorSink = Callable[[CrawlResult], None]


class CrawlerConfig:
    """Runtime knobs. Kept as plain attributes so they can come from env/DB."""

    def __init__(
        self,
        headless: bool = True,
        nav_timeout_ms: int = 30_000,
        max_retries: int = 3,
        backoff_base_s: float = 2.0,
        user_agent: Optional[str] = None,
        locale: str = "fa-IR",
    ):
        self.headless = headless
        self.nav_timeout_ms = nav_timeout_ms
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self.user_agent = user_agent or (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
        self.locale = locale


class BaseVendorCrawler(abc.ABC):
    """Abstract base for a single vendor's search scraper."""

    #: Human-readable vendor name (matches Vendors_V1.0.xlsx).
    vendor_name: str = ""
    #: Storefront root, e.g. "https://www.javanelec.com".
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
        """Insert a URL-encoded part query into the vendor search pattern."""
        encoded = quote(part_query, safe="")
        return self.search_pattern.replace("[PART_NAME]", encoded)

    # -- Hooks a subclass implements ----------------------------------------
    @abc.abstractmethod
    def parse_results_html(self, html: str, part_query: str) -> List[ProductOffer]:
        """Parse rendered HTML into offers. Pure function; unit-testable."""

    async def wait_for_results(self, page) -> None:
        """Wait until the results are rendered. Override per vendor if needed.

        Default: wait for the network to go idle, which is a reasonable signal
        for an SPA/ASP.NET storefront that fetches results via XHR.
        """
        try:
            await page.wait_for_load_state("networkidle", timeout=self.config.nav_timeout_ms)
        except Exception:  # noqa: BLE001 - best effort; parsing will still run
            logger.debug("networkidle wait timed out for %s", self.vendor_name)

    # -- Core crawl ----------------------------------------------------------
    async def crawl(self, raw_part: str, context) -> CrawlResult:
        """Crawl one part using an existing Playwright browser ``context``.

        Retries navigation/parse with exponential backoff. Never raises: a
        failure is captured as ``CrawlStatus.ERROR`` so the queue can record it.
        """
        part_query = normalize_part_query(raw_part)
        search_url = self.build_search_url(part_query)
        started = time.monotonic()

        last_error: Optional[str] = None
        for attempt in range(1, self.config.max_retries + 1):
            page = await context.new_page()
            try:
                await page.goto(search_url, timeout=self.config.nav_timeout_ms)
                await self.wait_for_results(page)
                html = await page.content()
                offers = self.parse_results_html(html, part_query)
                duration_ms = int((time.monotonic() - started) * 1000)
                status = CrawlStatus.OK if offers else CrawlStatus.ZERO_RESULTS
                return CrawlResult(
                    vendor=self.vendor_name,
                    part_query=part_query,
                    search_url=search_url,
                    status=status,
                    offers=offers,
                    duration_ms=duration_ms,
                )
            except Exception as exc:  # noqa: BLE001 - convert to a result
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "crawl attempt %d/%d failed for %s '%s': %s",
                    attempt, self.config.max_retries, self.vendor_name,
                    part_query, last_error,
                )
                if attempt < self.config.max_retries:
                    await asyncio.sleep(self.config.backoff_base_s * (2 ** (attempt - 1)))
            finally:
                await page.close()

        duration_ms = int((time.monotonic() - started) * 1000)
        return CrawlResult(
            vendor=self.vendor_name,
            part_query=part_query,
            search_url=search_url,
            status=CrawlStatus.ERROR,
            error=last_error,
            duration_ms=duration_ms,
        )


class FailureMonitor:
    """Simple monitoring sink: flags scrapers that keep failing / finding nothing.

    Section 7 of the architecture doc asks for "a simple monitoring mechanism
    that tells the team when a scraper fails (e.g. consistently returns zero
    results)". This tracks a rolling count of consecutive non-OK results per
    vendor and invokes ``alert`` when it crosses ``threshold``.
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
