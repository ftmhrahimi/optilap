"""Crawler for JavanElectronic — https://www.javanelec.com  (Tehran).

Search pattern: https://www.javanelec.com/shop?searchfilter=[PART_NAME]

The site is **server-rendered and two-stage**:
  * ``/shop?searchfilter=...`` returns a listing whose product links look like
    ``/shop/product/<id>/<slug>`` — but with **no price** on the listing;
  * each product page carries the price ("… تومان"), stock ("موجود در انبار N"),
    package ("پکیج: …") and part type ("نوع قطعه: …").

Both hooks below are pure functions (HTML string in, data out), so they can be
unit-tested against saved fixtures with no network.
"""
from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..base import BaseVendorCrawler
from ..models import ProductOffer
from ..normalize import normalize_digits, parse_price

# A product-detail link on the search results page.
_PRODUCT_HREF_MARKER = "/shop/product/"

# Price shown as "<number> تومان" (or ریال). Digits may be Persian; we normalize
# first, so the pattern only needs ASCII digits + grouping separators.
_PRICE_TOMAN_RE = re.compile(r"([\d,][\d,]*)\s*تومان")
_PRICE_RIAL_RE = re.compile(r"([\d,][\d,]*)\s*(?:ریال|﷼)")
# Fallback: any number with >= 5 digits (Toman prices on this shop).
_BIG_NUMBER_RE = re.compile(r"\d[\d,]{4,}")

_STOCK_RE = re.compile(r"موجود در انبار\s*([\d,]+)")
_OUT_OF_STOCK_RE = re.compile(r"ناموجود|اتمام موجودی|تمام شد")
_PACKAGE_RE = re.compile(r"پکیج\s*:?\s*(.+)")
_PART_TYPE_RE = re.compile(r"نوع قطعه\s*:?\s*(.+)")


class JavanElectronicCrawler(BaseVendorCrawler):
    vendor_name = "JavanElectronic"
    base_url = "https://www.javanelec.com"
    search_pattern = "https://www.javanelec.com/shop?searchfilter=[PART_NAME]"

    # -- Stage 1 -------------------------------------------------------------
    def find_product_urls(self, search_html: str) -> List[str]:
        soup = BeautifulSoup(search_html, "html.parser")
        urls: List[str] = []
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if _PRODUCT_HREF_MARKER not in href:
                continue
            link = urljoin(self.base_url, href)
            if link not in seen:
                seen.add(link)
                urls.append(link)
        return urls

    # -- Stage 2 -------------------------------------------------------------
    def parse_product(self, html: str, url: str, part_query: str) -> Optional[ProductOffer]:
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text("\n", strip=True)
        norm = normalize_digits(text)

        title = None
        if soup.title and soup.title.text:
            title = soup.title.text.strip()
        elif soup.find("h1"):
            title = soup.find("h1").get_text(strip=True)

        price_raw = self._extract_price_raw(norm)
        parsed = parse_price(price_raw) if price_raw else parse_price(None)

        stock_qty, in_stock, avail_raw = self._extract_stock(norm)

        package = self._first_line(_PACKAGE_RE, norm)
        part_type = self._extract_part_type(norm)

        image = self._extract_image(soup)

        # Skip pages with neither a price nor a stock signal — not a real offer.
        if parsed.amount is None and in_stock is None:
            return None

        return ProductOffer(
            vendor=self.vendor_name,
            part_query=part_query,
            title=title,
            product_url=url,
            image_url=image,
            price_amount=parsed.amount,
            price_currency=parsed.currency,
            price_raw=price_raw,
            price_rial=parsed.to_rial(),
            in_stock=in_stock,
            stock_qty=stock_qty,
            availability_raw=avail_raw,
            package=package,
            part_type=part_type,
        )

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def _extract_price_raw(norm_text: str) -> Optional[str]:
        # Prefer the last Toman-anchored number (final/discounted price usually
        # appears last on the page), then Rial, then a big-number fallback.
        toman = _PRICE_TOMAN_RE.findall(norm_text)
        if toman:
            return f"{toman[-1]} تومان"
        rial = _PRICE_RIAL_RE.findall(norm_text)
        if rial:
            return f"{rial[-1]} ریال"
        big = _BIG_NUMBER_RE.findall(norm_text)
        if big:
            # No currency word -> this shop prices in Toman; label it so.
            return f"{big[-1]} تومان"
        return None

    @staticmethod
    def _extract_stock(norm_text: str):
        m = _STOCK_RE.search(norm_text)
        if m:
            qty = int(m.group(1).replace(",", ""))
            return qty, qty > 0, m.group(0)
        m2 = _OUT_OF_STOCK_RE.search(norm_text)
        if m2:
            return None, False, m2.group(0)
        return None, None, None

    @staticmethod
    def _first_line(pattern: re.Pattern, norm_text: str) -> Optional[str]:
        m = pattern.search(norm_text)
        if not m:
            return None
        # Capture only up to the end of the line.
        value = m.group(1).splitlines()[0].strip()
        return value or None

    def _extract_part_type(self, norm_text: str) -> Optional[str]:
        raw = self._first_line(_PART_TYPE_RE, norm_text)
        if raw is None:
            return None
        if "کپی" in raw:
            return "Copy"
        if "بازسازی" in raw:
            return "Refurbished"
        return raw or "Original"

    def _extract_image(self, soup: BeautifulSoup) -> Optional[str]:
        # Prefer the OpenGraph image, else the first content image.
        og = soup.find("meta", attrs={"property": "og:image"})
        if og and og.get("content"):
            return urljoin(self.base_url, og["content"])
        img = soup.find("img")
        if img is not None:
            src = img.get("data-src") or img.get("src")
            if src:
                return urljoin(self.base_url, src)
        return None
