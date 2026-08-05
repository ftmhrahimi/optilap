"""Crawler for MicroModern — https://www.micmodshop.ir  (Tehran).

Platform: **WordPress + WooCommerce** (PHP), server-rendered.
Search: https://micmodshop.ir/?q=[PART_NAME]&post_type=product

WooCommerce conventions used here:
  * search results = ``ul.products li.product`` cards, each with
    ``a.woocommerce-LoopProduct-link`` (or the title link) to the product page;
  * product page price = ``.summary .price`` (prefer ``ins`` = sale price);
    availability = ``.stock`` (class ``in-stock`` / ``out-of-stock``);
  * package/type live in the attributes table
    (``.woocommerce-product-attributes``), handled by the shared extractor.

⚠️ The search param is ``?q=`` (not WooCommerce's default ``?s=``), so the site
likely uses a custom search plugin — verify results with
``scripts/inspect_site.py --vendor MicroModern --part LM358``.
"""
from __future__ import annotations

from typing import List, Optional

from bs4 import BeautifulSoup

from .. import extract
from ..base import BaseVendorCrawler
from ..models import ProductOffer

_CARD_SELECTORS = (
    "ul.products li.product",
    "li.product",
    ".products .product",
    ".product-item",
)
_LINK_SELECTORS = (
    "a.woocommerce-LoopProduct-link",
    "a.woocommerce-loop-product__link",
    ".woocommerce-loop-product__title a",
    "h2 a",
    "a.product-loop-title",
)
_URL_MARKERS = ("/product/", "/shop/", "post_type=product")

_PRICE_SELECTORS = (
    ".summary .price ins .woocommerce-Price-amount",  # sale price first
    ".summary .price ins",
    ".summary p.price .woocommerce-Price-amount",
    ".summary .price",
    "p.price",
    ".price .woocommerce-Price-amount",
    ".price",
)
_STOCK_SELECTORS = (
    ".summary .stock",
    "p.stock",
    ".stock",
    ".availability",
)


class MicroModernCrawler(BaseVendorCrawler):
    vendor_name = "MicroModern"
    base_url = "https://www.micmodshop.ir"
    search_pattern = "https://micmodshop.ir/?q=[PART_NAME]&post_type=product"

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
