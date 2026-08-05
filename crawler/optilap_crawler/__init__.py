"""Optilap crawler subsystem (MVP, week 1).

Public surface:
    from optilap_crawler import crawl_part, crawl_parts
    from optilap_crawler.registry import get_crawler, all_vendor_names

Crawls are synchronous and use a ``requests`` session by default (the verified
shops are server-rendered). Pass ``CrawlerConfig(use_browser=True)`` for a
future JavaScript-only vendor.
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from .base import BaseVendorCrawler, CrawlerConfig, FailureMonitor
from .fetch import Fetcher, HttpFetcher
from .models import CrawlResult, CrawlStatus, ProductOffer
from .registry import all_vendor_names, get_crawler

__all__ = [
    "BaseVendorCrawler",
    "CrawlerConfig",
    "FailureMonitor",
    "Fetcher",
    "HttpFetcher",
    "CrawlResult",
    "CrawlStatus",
    "ProductOffer",
    "crawl_part",
    "crawl_parts",
    "get_crawler",
    "all_vendor_names",
]


def _make_fetcher(config: CrawlerConfig) -> Fetcher:
    if config.use_browser:
        from .fetch import PlaywrightFetcher

        return PlaywrightFetcher()
    return HttpFetcher(
        timeout=config.timeout,
        max_retries=config.max_retries,
        backoff_base_s=config.backoff_base_s,
    )


def crawl_parts(
    vendor: str,
    parts: Sequence[str],
    config: Optional[CrawlerConfig] = None,
    monitor: Optional[FailureMonitor] = None,
    fetcher: Optional[Fetcher] = None,
) -> List[CrawlResult]:
    """Crawl several parts from one vendor, reusing a single fetcher/session."""
    cfg = config or CrawlerConfig()
    crawler = get_crawler(vendor)(cfg)

    own_fetcher = fetcher is None
    fetcher = fetcher or _make_fetcher(cfg)

    results: List[CrawlResult] = []
    try:
        for part in parts:
            result = crawler.crawl(part, fetcher)
            if monitor is not None:
                monitor.observe(result)
            results.append(result)
    finally:
        if own_fetcher and hasattr(fetcher, "close"):
            fetcher.close()  # type: ignore[attr-defined]
    return results


def crawl_part(
    vendor: str,
    part: str,
    config: Optional[CrawlerConfig] = None,
    monitor: Optional[FailureMonitor] = None,
    fetcher: Optional[Fetcher] = None,
) -> CrawlResult:
    """Crawl a single part from one vendor."""
    return crawl_parts(vendor, [part], config=config, monitor=monitor, fetcher=fetcher)[0]
