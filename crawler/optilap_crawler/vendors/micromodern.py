"""Crawler for MicroModern — https://micmodshop.ir  (Tehran).

Platform: **Next.js (React)** single-page app. (The vendor sheet's "WooCommerce"
label is wrong.) Search: https://micmodshop.ir/?q=[PART_NAME]&post_type=product

Key insight: the page is NOT server-rendered product cards — the product data is
embedded as JSON inside the Next.js Flight payload (``self.__next_f.push([...])``
scripts). So instead of scraping the (virtualized) DOM, we reconstruct that JSON
stream and read the ``products`` array directly. This is far more reliable and
gives price, stock, package, brand and authenticity in one request (single-stage,
no per-product fetch needed).

Each product carries: ``price`` / ``discount_price`` (Toman), ``online_quantity``,
``is_available``, ``authenticity`` (Genuine / China-made), ``attributes_dict``
(Package, Manufacture), and ``slug`` + ``shop_id`` → product URL
``/products/{shop_id}/{slug}``.
"""
from __future__ import annotations

import json
import time
from decimal import Decimal
from typing import List, Optional
from urllib.parse import urljoin

from ..base import BaseVendorCrawler
from ..fetch import Fetcher
from ..models import CrawlResult, CrawlStatus, ProductOffer
from ..normalize import normalize_part_query

_IMAGE_BASE = "https://micmodshop.ir/product_backend"


# ---------------------------------------------------------------------------
# Next.js Flight payload extraction (pure functions, unit-testable)
# ---------------------------------------------------------------------------
def _match_bracket(s: str, start: int) -> Optional[str]:
    """Return the balanced ``[...]`` substring beginning at ``s[start] == '['``,
    correctly skipping over string literals (and their escapes)."""
    depth = 0
    in_str = False
    esc = False
    for j in range(start, len(s)):
        c = s[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    return s[start : j + 1]
    return None


def next_flight_stream(html: str) -> str:
    """Reconstruct the Next.js Flight stream by concatenating every string chunk
    pushed via ``self.__next_f.push([1, "<chunk>"])``."""
    parts: List[str] = []
    key = "self.__next_f.push("
    i = 0
    while True:
        idx = html.find(key, i)
        if idx == -1:
            break
        b = html.find("[", idx)
        if b == -1:
            break
        arr_txt = _match_bracket(html, b)
        if not arr_txt:
            i = idx + len(key)
            continue
        i = b + len(arr_txt)
        try:
            arr = json.loads(arr_txt)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(arr, list) and len(arr) >= 2 and isinstance(arr[1], str):
            parts.append(arr[1])
    return "".join(parts)


def extract_products(html: str) -> List[dict]:
    """Pull the ``products`` array out of the embedded Flight JSON."""
    stream = next_flight_stream(html)
    marker = '"products":'
    idx = stream.find(marker)
    if idx == -1:
        return []
    b = stream.find("[", idx)
    if b == -1:
        return []
    arr_txt = _match_bracket(stream, b)
    if not arr_txt:
        return []
    data = json.loads(arr_txt)
    return data if isinstance(data, list) else []


def _authenticity_to_type(auth: Optional[str]) -> Optional[str]:
    if not auth:
        return None
    a = auth.lower()
    if "genuine" in a or "original" in a:
        return "Original"
    if "refurb" in a:
        return "Refurbished"
    if "china" in a or "general" in a or "copy" in a:
        return "Copy"
    return auth


def _attr(attrs: dict, key: str) -> Optional[str]:
    node = attrs.get(key) if isinstance(attrs, dict) else None
    if not isinstance(node, dict):
        return None
    return node.get("value_localized") or node.get("value")


class MicroModernCrawler(BaseVendorCrawler):
    vendor_name = "MicroModern"
    base_url = "https://www.micmodshop.ir"
    search_pattern = "https://micmodshop.ir/?q=[PART_NAME]&post_type=product"

    # This vendor is single-stage (all data in the search page JSON), so we
    # override crawl() and the two-stage hooks below are unused.
    def find_product_urls(self, search_html: str) -> List[str]:  # pragma: no cover
        return []

    def parse_product(self, html, url, part_query):  # pragma: no cover
        return None

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
            products = extract_products(html)
        except Exception as exc:  # noqa: BLE001
            return self._result(part_query, search_url, CrawlStatus.ERROR,
                                 error=f"product json parse failed: {exc}", started=started)

        offers: List[ProductOffer] = []
        for p in products[: self.config.max_products]:
            offer = self._to_offer(p, part_query)
            if offer is not None:
                offers.append(offer)

        status = CrawlStatus.OK if offers else CrawlStatus.ZERO_RESULTS
        return self._result(part_query, search_url, status, offers=offers, started=started)

    def _to_offer(self, p: dict, part_query: str) -> Optional[ProductOffer]:
        if not isinstance(p, dict):
            return None
        price = p.get("discount_price")
        if price in (None, 0):
            price = p.get("price")
        amount = Decimal(str(price)) if price not in (None, "") else None

        qty = p.get("online_quantity")
        try:
            qty = int(qty) if qty is not None else None
        except (TypeError, ValueError):
            qty = None
        in_stock = p.get("is_available")
        if in_stock is None and qty is not None:
            in_stock = qty > 0
        availability = None
        if in_stock is True:
            availability = "in_stock"
        elif in_stock is False:
            availability = "out_of_stock"

        attrs = p.get("attributes_dict") or {}
        package = _attr(attrs, "Package")
        part_type = _authenticity_to_type(p.get("authenticity") or _attr(attrs, "Authenticity"))

        title = p.get("part_number") or p.get("manufacture_part_number") or p.get("part_number_other")

        url = None
        if p.get("shop_id") and p.get("slug"):
            url = urljoin(self.base_url, f"/products/{p['shop_id']}/{p['slug']}")

        image = None
        images = p.get("images")
        if isinstance(images, list) and images and isinstance(images[0], dict):
            src = images[0].get("url")
            if src:
                image = _IMAGE_BASE + src if src.startswith("/") else src

        if amount is None and in_stock is None:
            return None

        return ProductOffer(
            vendor=self.vendor_name,
            part_query=part_query,
            title=title,
            product_url=url,
            image_url=image,
            price_amount=amount,
            price_currency="IRT" if amount is not None else None,
            price_raw=(f"{int(price):,} تومان" if amount is not None else None),
            price_rial=(amount * 10 if amount is not None else None),
            in_stock=in_stock,
            availability=availability,
            stock_qty=qty,
            availability_raw=("in stock" if in_stock else "out of stock" if in_stock is False else None),
            package=package,
            part_type=part_type,
        )
