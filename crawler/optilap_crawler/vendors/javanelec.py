"""Crawler for JavanElectronic — https://www.javanelec.com  (Tehran).

Stack (from Vendors_V1.0.xlsx): ASP.NET Core + JavaScript.
Search pattern: https://www.javanelec.com/shop?searchfilter=[PART_NAME]

Parsing strategy
----------------
The exact CSS classes on the results page can only be confirmed against the
live DOM (blocked from the build environment by egress policy). So parsing runs
in two tiers:

  1. **Configured selectors** — ``SELECTORS`` below. Fill these in once you have
     a real results page (use ``scripts/inspect_site.py`` to dump one). This is
     the fast, precise path.
  2. **Heuristic fallback** — if the configured card selector matches nothing,
     we locate every element that contains a price (Toman/Rial) and treat its
     nearest sensible container as a product card. This keeps the crawler
     returning *something* useful before calibration and resilient if the site
     tweaks a class name.

``parse_results_html`` is a pure function so it can be unit-tested against a
saved HTML fixture with no browser involved.
"""
from __future__ import annotations

from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ..base import BaseVendorCrawler
from ..models import ProductOffer
from ..normalize import (
    detect_availability,
    normalize_digits,
    parse_price,
)

# ---------------------------------------------------------------------------
# CALIBRATION POINT — verify these against a live results page and edit as
# needed. Each key holds a list of candidate CSS selectors tried in order.
# ---------------------------------------------------------------------------
SELECTORS = {
    # A single product card on the search results grid.
    "product_card": [
        ".product-item",
        ".product-box",
        ".productItem",
        "li.product",
        "div.product",
        "[class*='product-item']",
    ],
    # Product title / link inside a card.
    "title": [".product-title a", ".product-title", "a.product-title", "h3 a", "h2 a", "a[title]"],
    # Anchor to the product detail page.
    "link": ["a.product-title", ".product-title a", "a[href*='/product']", "a[href]"],
    # Price element inside a card.
    "price": [".price", ".product-price", "[class*='price']", ".money"],
    # Availability / stock badge or add-to-cart control inside a card.
    "availability": [".stock", ".availability", "[class*='stock']", ".add-to-cart", "button"],
    "image": ["img"],
}

# Tokens that mark a text node as containing a price (post digit-normalization).
_PRICE_UNIT_TOKENS = ("تومان", "ریال", "﷼")


def _first_match(root: Tag, selectors: List[str]) -> Optional[Tag]:
    for sel in selectors:
        try:
            found = root.select_one(sel)
        except Exception:  # noqa: BLE001 - bad selector shouldn't kill the crawl
            continue
        if found is not None:
            return found
    return None


def _select_cards(soup: BeautifulSoup) -> List[Tag]:
    for sel in SELECTORS["product_card"]:
        try:
            cards = soup.select(sel)
        except Exception:  # noqa: BLE001
            continue
        if cards:
            return cards
    return []


def _looks_like_price(text: str) -> bool:
    norm = normalize_digits(text)
    return any(tok in norm for tok in _PRICE_UNIT_TOKENS) and any(c.isdigit() for c in norm)


def _heuristic_cards(soup: BeautifulSoup) -> List[Tag]:
    """Fallback: derive product cards from elements that contain a price.

    For each price-bearing leaf element, walk up a few levels to a container
    that also holds a link — that container is very likely one product card.
    """
    cards: List[Tag] = []
    seen: set[int] = set()
    for node in soup.find_all(string=lambda s: bool(s) and _looks_like_price(s)):
        container = node.parent
        # Climb until we find an ancestor that also contains an <a href>.
        for _ in range(5):
            if container is None or not isinstance(container, Tag):
                break
            if container.find("a", href=True) is not None:
                break
            container = container.parent
        if isinstance(container, Tag) and id(container) not in seen:
            seen.add(id(container))
            cards.append(container)
    return cards


class JavanElectronicCrawler(BaseVendorCrawler):
    vendor_name = "JavanElectronic"
    base_url = "https://www.javanelec.com"
    search_pattern = "https://www.javanelec.com/shop?searchfilter=[PART_NAME]"

    async def wait_for_results(self, page) -> None:
        # Wait for any configured product-card selector to appear, else fall
        # back to the base networkidle wait. Keeps flaky XHR pages honest.
        for sel in SELECTORS["product_card"]:
            try:
                await page.wait_for_selector(sel, timeout=5_000)
                return
            except Exception:  # noqa: BLE001
                continue
        await super().wait_for_results(page)

    def parse_results_html(self, html: str, part_query: str) -> List[ProductOffer]:
        soup = BeautifulSoup(html, "html.parser")

        cards = _select_cards(soup)
        if not cards:
            cards = _heuristic_cards(soup)

        offers: List[ProductOffer] = []
        for card in cards:
            offer = self._parse_card(card, part_query)
            if offer is not None:
                offers.append(offer)
        return offers

    # -- per-card parsing ----------------------------------------------------
    def _parse_card(self, card: Tag, part_query: str) -> Optional[ProductOffer]:
        title = self._extract_title(card)
        url = self._extract_url(card)
        price_text = self._extract_price_text(card)
        avail_text = self._extract_availability_text(card)
        image = self._extract_image(card)

        parsed = parse_price(price_text)
        in_stock = detect_availability(avail_text) if avail_text else None
        if in_stock is None:
            # A visible price with no explicit stock badge usually means buyable.
            in_stock = True if parsed.amount is not None else None

        # Drop pure noise (no title, no price, no link).
        if not title and parsed.amount is None and not url:
            return None

        return ProductOffer(
            vendor=self.vendor_name,
            part_query=part_query,
            title=title,
            product_url=url,
            image_url=image,
            price_amount=parsed.amount,
            price_currency=parsed.currency,
            price_raw=parsed.raw or None,
            price_rial=parsed.to_rial(),
            in_stock=in_stock,
            availability_raw=(avail_text or None),
        )

    def _extract_title(self, card: Tag) -> Optional[str]:
        node = _first_match(card, SELECTORS["title"])
        if node is not None:
            text = node.get("title") or node.get_text(strip=True)
            if text:
                return normalize_digits(text).strip()
        # Fallback: the longest anchor text in the card.
        anchors = [a.get_text(strip=True) for a in card.find_all("a")]
        anchors = [a for a in anchors if a]
        return max(anchors, key=len) if anchors else None

    def _extract_url(self, card: Tag) -> Optional[str]:
        node = _first_match(card, SELECTORS["link"])
        href = node.get("href") if isinstance(node, Tag) else None
        if not href:
            a = card.find("a", href=True)
            href = a["href"] if a else None
        return urljoin(self.base_url, href) if href else None

    def _extract_price_text(self, card: Tag) -> Optional[str]:
        node = _first_match(card, SELECTORS["price"])
        if node is not None and _looks_like_price(node.get_text()):
            return node.get_text(" ", strip=True)
        # Fallback: any descendant text that looks like a price.
        for s in card.find_all(string=lambda t: bool(t) and _looks_like_price(t)):
            return s.strip()
        return None

    def _extract_availability_text(self, card: Tag) -> Optional[str]:
        node = _first_match(card, SELECTORS["availability"])
        if node is not None:
            text = node.get_text(" ", strip=True)
            if text:
                return text
        return None

    def _extract_image(self, card: Tag) -> Optional[str]:
        img = card.find("img")
        if img is None:
            return None
        src = img.get("data-src") or img.get("src")
        return urljoin(self.base_url, src) if src else None
