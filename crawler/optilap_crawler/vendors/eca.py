"""Crawler for ECA — https://eshop.eca.ir  (Tabriz).

Platform: **PrestaShop** (PHP), server-rendered.
Search: https://eshop.eca.ir/search?controller=search&s=[PART_NAME]

PrestaShop conventions used here (standard 1.7 markup):
  * search results = ``article.product-miniature`` cards, each with a
    ``.product-title a`` / ``a.product-thumbnail`` link to the product page;
  * product page price = ``.current-price`` / ``span[itemprop='price']``;
    availability = ``#product-availability`` / ``.product-availability``.

⚠️ Iranian PrestaShop themes are often customized — verify the selectors below
against a live page with ``scripts/inspect_site.py --vendor ECA --part LM358``.
"""
from __future__ import annotations

from typing import List, Optional

from bs4 import BeautifulSoup

from .. import extract
from ..base import BaseVendorCrawler
from ..models import ProductOffer

_CARD_SELECTORS = (
    "article.product-miniature",
    ".product-miniature",
    ".js-product-miniature",
    "#js-product-list .product",
    ".product_list .product-container",  # PrestaShop 1.6
)
_LINK_SELECTORS = (
    "a.product-thumbnail",
    ".product-title a",
    "h3.product-title a",
    "h2 a",
    ".product-name",  # PrestaShop 1.6
)
# PrestaShop product URLs have no single fixed marker; if cards aren't found we
# fall back to anchors that at least look like product detail pages.
_URL_MARKERS = ("/product/", ".html")

_PRICE_SELECTORS = (
    ".current-price span[itemprop='price']",
    ".current-price .price",
    ".current-price",
    "span[itemprop='price']",
    ".product-price",
    ".price",
)
_STOCK_SELECTORS = (
    ".stock-badge-inline",   # ECA's actual in-stock/out-of-stock badge
    ".stock-badge",
    "#product-availability",
    ".product-availability",
    ".product-quantities",
    "#stock_availability",
    ".availability",
)


class ECACrawler(BaseVendorCrawler):
    vendor_name = "ECA"
    base_url = "https://eshop.eca.ir"
    search_pattern = "https://eshop.eca.ir/search?controller=search&s=[PART_NAME]"

    def find_product_urls(self, search_html: str) -> List[str]:
        soup = BeautifulSoup(search_html, "html.parser")
        return extract.collect_links(
            soup,
            self.base_url,
            card_selectors=_CARD_SELECTORS,
            link_selectors=_LINK_SELECTORS,
            url_markers=_URL_MARKERS,
        )

    def parse_product(self, html: str, url: str, part_query: str) -> Optional[ProductOffer]:
        return extract.build_offer(
            vendor=self.vendor_name,
            base_url=self.base_url,
            part_query=part_query,
            url=url,
            html=html,
            price_selectors=_PRICE_SELECTORS,
            stock_selectors=_STOCK_SELECTORS,
        )
