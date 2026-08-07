"""Crawler for MicroModern — https://www.micmodshop.ir  (Tehran).

Platform: **WordPress + WooCommerce** (PHP), but with a customized theme.
Search: https://micmodshop.ir/?s=[PART_NAME]&post_type=product

⚠️ CALIBRATION STILL NEEDED. The vendor sheet's ``?q=`` URL returns a
JavaScript search *modal* (autocomplete), whose server HTML contains only site
chrome + "popular searches" links (``?...&custom_tags=popular_*``) — NOT a
product listing. We therefore:
  * use the standard WordPress results URL ``?s=...&post_type=product`` instead
    of the AJAX ``?q=``;
  * discover product links strictly by the ``/product/`` path, so the
    "popular searches" navigation links can never be mistaken for products.

The real results page uses a custom comparison-table theme, so the price/stock
selectors below are placeholders. Run
``scripts/inspect_site.py --vendor MicroModern --part LM358 --save`` on a machine
that can reach the site and share the saved HTML to finalize the selectors.
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
# Strictly real product pages — NOT "?post_type=product" (that also matches the
# site's "popular searches" navigation links, which caused garbage results).
_URL_MARKERS = ("/product/",)

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
    search_pattern = "https://micmodshop.ir/?s=[PART_NAME]&post_type=product"

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
