"""Optilap crawler subsystem (MVP, week 1).

Public surface:
    from optilap_crawler import crawl_part, crawl_parts
    from optilap_crawler.registry import get_crawler, all_vendor_names
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from .base import BaseVendorCrawler, CrawlerConfig, FailureMonitor
from .models import CrawlResult, CrawlStatus, ProductOffer
from .registry import all_vendor_names, get_crawler

__all__ = [
    "BaseVendorCrawler",
    "CrawlerConfig",
    "FailureMonitor",
    "CrawlResult",
    "CrawlStatus",
    "ProductOffer",
    "crawl_part",
    "crawl_parts",
    "get_crawler",
    "all_vendor_names",
]


async def _run(vendor: str, parts: Sequence[str], config: Optional[CrawlerConfig],
               monitor: Optional[FailureMonitor]) -> List[CrawlResult]:
    from playwright.async_api import async_playwright

    crawler_cls = get_crawler(vendor)
    cfg = config or CrawlerConfig()
    crawler = crawler_cls(cfg)

    results: List[CrawlResult] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=cfg.headless)
        context = await browser.new_context(user_agent=cfg.user_agent, locale=cfg.locale)
        try:
            for part in parts:
                result = await crawler.crawl(part, context)
                if monitor is not None:
                    monitor.observe(result)
                results.append(result)
        finally:
            await context.close()
            await browser.close()
    return results


async def crawl_parts(
    vendor: str,
    parts: Sequence[str],
    config: Optional[CrawlerConfig] = None,
    monitor: Optional[FailureMonitor] = None,
) -> List[CrawlResult]:
    """Crawl several parts from one vendor, reusing a single browser."""
    return await _run(vendor, list(parts), config, monitor)


async def crawl_part(
    vendor: str,
    part: str,
    config: Optional[CrawlerConfig] = None,
    monitor: Optional[FailureMonitor] = None,
) -> CrawlResult:
    """Crawl a single part from one vendor."""
    results = await _run(vendor, [part], config, monitor)
    return results[0]
