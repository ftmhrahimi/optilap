"""Crawler for JavanElectronic — https://www.javanelec.com  (Tehran).

Platform: custom ASP.NET Core. Server-rendered, two-stage:
  * ``/shop?searchfilter=...`` lists product links (``/shop/product/<id>/<slug>``)
    with NO price on the listing;
  * each product page carries price ("… تومان"), stock ("موجود در انبار N"),
    package ("پکیج: …") and part type ("نوع قطعه: …").

Both hooks are pure functions, unit-tested against saved fixtures.
"""
from __future__ import annotations

from typing import List, Optional

from bs4 import BeautifulSoup

from .. import extract
from ..base import BaseVendorCrawler
from ..models import ProductOffer

_PRODUCT_HREF_MARKER = "/shop/product/"

# Empty selectors on purpose: JavanElec's product page shows a struck-out
# original price *before* the final one, so a container selector would grab the
# regular price. The whole-text scan (``price_raw_from_text``) takes the LAST
# Toman number = the final price, which the live run confirmed is correct.
# Stock ("موجود در انبار N") is likewise found from page text.
_PRICE_SELECTORS: tuple[str, ...] = ()
_STOCK_SELECTORS: tuple[str, ...] = ()


class JavanElectronicCrawler(BaseVendorCrawler):
    vendor_name = "JavanElectronic"
    base_url = "https://www.javanelec.com"
    search_pattern = "https://www.javanelec.com/shop?searchfilter=[PART_NAME]"

    def find_product_urls(self, search_html: str) -> List[str]:
        soup = BeautifulSoup(search_html, "html.parser")
        return extract.collect_links(
            soup, self.base_url, url_markers=[_PRODUCT_HREF_MARKER]
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
            # JavanElec flags copies/refurbs with a badge; un-badged = Original.
            default_part_type="Original",
        )
