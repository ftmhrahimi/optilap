"""Crawler for JavanElectronic — https://www.javanelec.com  (Tehran).

Platform: custom ASP.NET Core. Server-rendered.
Search: https://www.javanelec.com/shop?searchfilter=[PART_NAME]

**Single-stage**: the search result cards carry everything we need, so there's
no need to open each product page (faster, and the card price matches exactly
what the customer sees). Each card is an ``li[data-prdid]`` with:

  * ``span[data-prdtype]`` — Original / Copy / Renew (Renew = بازسازی = Refurbished)
  * ``.en-num > div`` (x3) — title, brand, package
  * ``.px-01`` + ``.small`` — price number + currency (present only when in stock)
  * availability text — in-stock, "ناموجود-تحویل N روزه" (out of stock, N-day
    delivery), or "در حال تامین" (being supplied / on order)

``find_product_urls`` / ``parse_product`` remain (two-stage detail parsing) for
callers that want a product page, but the default crawl uses the cards.
"""
from __future__ import annotations

import time
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .. import extract
from ..base import BaseVendorCrawler
from ..fetch import Fetcher
from ..models import CrawlResult, CrawlStatus, ProductOffer
from ..normalize import normalize_digits, normalize_part_query, parse_price

_PRODUCT_HREF_MARKER = "/shop/product/"

# data-prdtype values -> our normalized part type.
_PRDTYPE_MAP = {
    "original": "Original",
    "copy": "Copy",
    "renew": "Refurbished",
    "refurbished": "Refurbished",
}

# Detail-page selectors (used only by parse_product, kept for completeness).
_PRICE_SELECTORS: tuple[str, ...] = ()
_STOCK_SELECTORS: tuple[str, ...] = ()


class JavanElectronicCrawler(BaseVendorCrawler):
    vendor_name = "JavanElectronic"
    base_url = "https://www.javanelec.com"
    search_pattern = "https://www.javanelec.com/shop?searchfilter=[PART_NAME]"

    # -- default (single-stage) crawl over the search cards -----------------
    def crawl(self, raw_part: str, fetcher: Fetcher) -> CrawlResult:
        part_query = normalize_part_query(raw_part)
        search_url = self.build_search_url(part_query)
        started = time.monotonic()

        try:
            html = fetcher.get_html(search_url)
        except Exception as exc:  # noqa: BLE001
            return self._result(part_query, search_url, CrawlStatus.ERROR,
                                 error=f"search fetch failed: {exc}", started=started)
        try:
            offers = self.parse_search_cards(html, part_query)
        except Exception as exc:  # noqa: BLE001
            return self._result(part_query, search_url, CrawlStatus.ERROR,
                                 error=f"card parse failed: {exc}", started=started)

        status = CrawlStatus.OK if offers else CrawlStatus.ZERO_RESULTS
        return self._result(part_query, search_url, status, offers=offers, started=started)

    # -- card parsing (pure, testable) --------------------------------------
    def parse_search_cards(self, html: str, part_query: str) -> List[ProductOffer]:
        soup = BeautifulSoup(html, "html.parser")
        offers: List[ProductOffer] = []
        for li in soup.select("li[data-prdid]"):
            offer = self._parse_card(li, part_query)
            if offer is not None:
                offers.append(offer)
        return offers

    def _parse_card(self, li: Tag, part_query: str) -> Optional[ProductOffer]:
        a = li.find("a", href=True)
        url = urljoin(self.base_url, a["href"]) if a else None

        # Type from the data-prdtype attribute (falls back to the badge text).
        part_type = None
        tspan = li.find(attrs={"data-prdtype": True})
        if tspan is not None:
            part_type = _PRDTYPE_MAP.get((tspan.get("data-prdtype") or "").strip().lower())
            if part_type is None:
                badge = tspan.get_text()
                if "بازسازی" in badge:
                    part_type = "Refurbished"
                elif "کپی" in badge:
                    part_type = "Copy"
                elif "اوریجینال" in badge or "اورجینال" in badge:
                    part_type = "Original"

        # Title / brand / package from the .en-num column (3 divs).
        title = package = None
        en = li.select_one(".en-num")
        if en is not None:
            divs = [normalize_digits(d.get_text(" ", strip=True))
                    for d in en.find_all("div", recursive=False)]
            divs = [d for d in divs if d]
            if divs:
                title = divs[0]
            if len(divs) >= 3:
                package = divs[2]

        # Price (present only for in-stock cards).
        price_amount = price_currency = price_raw = price_rial = None
        pe = li.select_one(".px-01")
        if pe is not None:
            num = normalize_digits(pe.get_text(" ", strip=True))
            cur_el = (pe.parent.select_one(".small") if pe.parent else None) or li.select_one(".small")
            cur = normalize_digits(cur_el.get_text(" ", strip=True)) if cur_el else ""
            parsed = parse_price(f"{num} {cur}".strip())
            price_amount = parsed.amount
            price_currency = parsed.currency
            price_raw = parsed.raw or None
            price_rial = parsed.to_rial()

        # Availability from the card text (handles out-of-stock/on-order + lead).
        card_text = normalize_digits(li.get_text(" ", strip=True))
        stock = extract.find_stock(li, (), card_text)
        in_stock = stock.in_stock
        availability = stock.availability
        if availability is None and price_amount is not None:
            in_stock, availability = True, "in_stock"  # priced card = purchasable

        image = None
        img = li.find("img")
        if img is not None and img.get("src"):
            image = urljoin(self.base_url, img["src"])

        if title is None and price_amount is None and availability is None:
            return None

        return ProductOffer(
            vendor=self.vendor_name,
            part_query=part_query,
            title=title,
            product_url=url,
            image_url=image,
            price_amount=price_amount,
            price_currency=price_currency,
            price_raw=price_raw,
            price_rial=price_rial,
            in_stock=in_stock,
            availability=availability,
            stock_qty=stock.qty,
            lead_time_days=stock.lead_time_days,
            availability_raw=stock.raw,
            package=package,
            part_type=part_type,
        )

    # -- optional two-stage detail parsing (kept for completeness) ----------
    def find_product_urls(self, search_html: str) -> List[str]:
        soup = BeautifulSoup(search_html, "html.parser")
        return extract.collect_links(soup, self.base_url, url_markers=[_PRODUCT_HREF_MARKER])

    def parse_product(self, html: str, url: str, part_query: str) -> Optional[ProductOffer]:
        return extract.build_offer(
            vendor=self.vendor_name, base_url=self.base_url, part_query=part_query,
            url=url, html=html, price_selectors=_PRICE_SELECTORS,
            stock_selectors=_STOCK_SELECTORS, default_part_type="Original",
        )
