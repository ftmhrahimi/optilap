"""HTTP fetching layer for the crawlers.

JavanElectronic (and the other target shops verified so far) are
**server-rendered**: a plain ``requests`` GET with a browser-like User-Agent
returns the full HTML, including product links and, on detail pages, the price
and stock. So the default fetcher is a lightweight ``requests`` session — much
faster than a headless browser when a single BOM means hundreds of page loads.

A ``PlaywrightFetcher`` (optional) exposes the *same* ``get_html`` interface for
any future vendor whose results genuinely require JavaScript execution, so a
vendor crawler never needs to know which fetcher it's running on.
"""
from __future__ import annotations

import logging
import time
from typing import Optional, Protocol

logger = logging.getLogger("optilap.crawler.fetch")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
}


class Fetcher(Protocol):
    def get_html(self, url: str) -> str: ...


class HttpFetcher:
    """Default fetcher: a persistent ``requests`` session with retry/backoff."""

    def __init__(
        self,
        headers: Optional[dict] = None,
        timeout: int = 30,
        max_retries: int = 3,
        backoff_base_s: float = 2.0,
    ):
        import requests  # imported lazily so importing the package is cheap

        self.session = requests.Session()
        self.session.headers.update(headers or DEFAULT_HEADERS)
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s

    def get_html(self, url: str) -> str:
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                r = self.session.get(url, timeout=self.timeout)
                r.raise_for_status()
                r.encoding = "utf-8"  # Persian pages must decode as UTF-8
                return r.text
            except Exception as exc:  # noqa: BLE001 - retry then re-raise
                last_exc = exc
                logger.warning(
                    "GET failed (%d/%d) %s: %s", attempt, self.max_retries, url, exc
                )
                if attempt < self.max_retries:
                    time.sleep(self.backoff_base_s * (2 ** (attempt - 1)))
        assert last_exc is not None
        raise last_exc

    def close(self) -> None:
        self.session.close()


class PlaywrightFetcher:
    """Optional fetcher for JS-heavy vendors. Uses Playwright's sync API.

    Not needed for the current vendors; kept so a future crawler can opt in via
    ``crawl_parts(..., fetcher=PlaywrightFetcher())`` without any other change.
    """

    def __init__(self, headless: bool = True, timeout_ms: int = 30_000,
                 user_agent: Optional[str] = None, locale: str = "fa-IR"):
        from playwright.sync_api import sync_playwright  # lazy import

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=headless)
        self._context = self._browser.new_context(
            user_agent=user_agent or DEFAULT_HEADERS["User-Agent"], locale=locale
        )
        self.timeout_ms = timeout_ms

    def get_html(self, url: str) -> str:
        page = self._context.new_page()
        try:
            page.goto(url, timeout=self.timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
            except Exception:  # noqa: BLE001
                pass
            return page.content()
        finally:
            page.close()

    def close(self) -> None:
        self._context.close()
        self._browser.close()
        self._pw.stop()
