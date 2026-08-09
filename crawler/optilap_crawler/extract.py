"""Shared extraction helpers for Iranian electronics storefronts.

Every vendor differs in *where* the price/stock/package sit (which CSS classes),
but the *content* is the same Persian conventions: "… تومان", "موجود در انبار N",
"ناموجود", "پکیج: …", "نوع قطعه: …". These helpers centralize that content
parsing so each vendor crawler only supplies its platform's CSS selectors.

All functions are pure (BeautifulSoup/str in, values out) → unit-testable.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .normalize import normalize_digits, parse_price

# -- regexes over digit-normalized text -------------------------------------
_PRICE_TOMAN_RE = re.compile(r"([\d,][\d,]*)\s*تومان")
_PRICE_RIAL_RE = re.compile(r"([\d,][\d,]*)\s*(?:ریال|﷼)")
_BIG_NUMBER_RE = re.compile(r"\d[\d,]{4,}")

_STOCK_QTY_RE = re.compile(
    r"(?:موجود در انبار|موجودی)\s*[:：]?\s*([\d,]+)"        # "موجود در انبار 42"
    r"|([\d,]+)\s*عدد\s*(?:در انبار|موجود)"                  # "35 عدد در انبار"
    r"|([\d,]+)\s*in stock"                                  # "12 in stock"
)
# Note: a bare "N عدد" is NOT a stock signal — it also appears in packaging info
# (e.g. "بسته‌بندی: Tube-50 عدد"). Quantity requires an "انبار/موجود/stock" context.
_OUT_OF_STOCK_RE = re.compile(
    r"ناموجود|ناموجود|اتمام موجودی|اتمام موجودي|تمام شد|موجود نیست|سفارش\s*دهید|out of stock"
)
_IN_STOCK_RE = re.compile(r"موجود در انبار|افزودن به سبد|in stock|add to cart")

_PACKAGE_LABELS = ("پکیج", "بسته بندی", "پکینگ", "package", "case")
_TYPE_LABELS = ("نوع قطعه", "نوع کالا", "type")

# unit words that confirm a text chunk is a price
_PRICE_UNITS = ("تومان", "ریال", "﷼")


def looks_like_price(text: str) -> bool:
    norm = normalize_digits(text)
    return any(u in norm for u in _PRICE_UNITS) and any(c.isdigit() for c in norm)


def text_of(soup: BeautifulSoup) -> str:
    """Full visible text, digit-normalized, newline-joined."""
    return normalize_digits(soup.get_text("\n", strip=True))


def guess_title(soup: BeautifulSoup) -> Optional[str]:
    for sel in ("h1.product_title", "h1.product-name", "h1[itemprop='name']", "h1"):
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)
    if soup.title and soup.title.text:
        return soup.title.text.strip()
    return None


# -- selectors helpers -------------------------------------------------------
def select_any(soup: Tag, selectors: Sequence[str]) -> List[Tag]:
    for sel in selectors:
        try:
            found = soup.select(sel)
        except Exception:  # noqa: BLE001 - skip malformed selector
            continue
        if found:
            return found
    return []


def first_in(root: Tag, selectors: Sequence[str]) -> Optional[Tag]:
    for sel in selectors:
        try:
            el = root.select_one(sel)
        except Exception:  # noqa: BLE001
            continue
        if el is not None:
            return el
    return None


def collect_links(
    soup: BeautifulSoup,
    base_url: str,
    card_selectors: Sequence[str] = (),
    link_selectors: Sequence[str] = (),
    url_markers: Sequence[str] = (),
) -> List[str]:
    """Discover product-detail URLs from a search results page.

    Strategy: prefer product *cards* (scoped, precise). If a platform has no
    recognizable cards, fall back to any anchor whose href contains a product
    URL marker (e.g. ``/product/``). Always deduped and absolutized.
    """
    urls: List[str] = []
    seen: set[str] = set()

    def add(href: Optional[str]) -> None:
        if not href or href.startswith(("javascript:", "#", "mailto:", "tel:")):
            return
        link = urljoin(base_url, href)
        if link not in seen:
            seen.add(link)
            urls.append(link)

    for card in select_any(soup, card_selectors):
        a = first_in(card, link_selectors) or card.find("a", href=True)
        if isinstance(a, Tag):
            add(a.get("href"))
    if urls:
        return urls

    if url_markers:
        for a in soup.find_all("a", href=True):
            if any(m in a["href"] for m in url_markers):
                add(a["href"])
    return urls


# -- field extraction --------------------------------------------------------
def price_raw_from_text(norm_text: str) -> Optional[str]:
    """Pick a price string from full page text (Toman, then Rial, then a big
    number that is almost certainly a Toman price on these shops)."""
    toman = _PRICE_TOMAN_RE.findall(norm_text)
    if toman:
        return f"{toman[-1]} تومان"
    rial = _PRICE_RIAL_RE.findall(norm_text)
    if rial:
        return f"{rial[-1]} ریال"
    big = _BIG_NUMBER_RE.findall(norm_text)
    if big:
        return f"{big[-1]} تومان"
    return None


def find_price(soup: BeautifulSoup, selectors: Sequence[str], norm_text: str):
    """Return a :class:`ParsedPrice`. Try structured price elements first
    (more precise), then fall back to scanning the whole page text."""
    for sel in selectors:
        el = first_in(soup, [sel])
        if el is None:
            continue
        txt = normalize_digits(el.get_text(" ", strip=True))
        if looks_like_price(txt):
            return parse_price(txt)
    return parse_price(price_raw_from_text(norm_text))


def find_stock(
    soup: BeautifulSoup, selectors: Sequence[str], norm_text: str
) -> Tuple[Optional[int], Optional[bool], Optional[str]]:
    """Return (quantity, in_stock, raw_text).

    Out-of-stock is decided FIRST: an out-of-stock page never shows
    "موجود در انبار N", but may contain "N عدد" inside packaging text that must
    not be mistaken for a stock quantity.
    """
    m_out = _OUT_OF_STOCK_RE.search(norm_text)
    m_qty = _STOCK_QTY_RE.search(norm_text)
    if m_out and not m_qty:
        return None, False, m_out.group(0).strip()
    if m_qty:
        digits = m_qty.group(1) or m_qty.group(2) or m_qty.group(3)
        qty = int(digits.replace(",", ""))
        return qty, qty > 0, m_qty.group(0).strip()

    for sel in selectors:
        el = first_in(soup, [sel])
        if el is None:
            continue
        classes = " ".join(el.get("class", []))
        txt = normalize_digits(el.get_text(" ", strip=True))
        if "out-of-stock" in classes or "unavailable" in classes or _OUT_OF_STOCK_RE.search(txt):
            return None, False, txt or "out of stock"
        if "in-stock" in classes or "available" in classes or _IN_STOCK_RE.search(txt):
            qm = re.search(r"(\d+)", txt)
            return (int(qm.group(1)) if qm else None), True, txt or "in stock"

    if m_out:
        return None, False, m_out.group(0).strip()
    if _IN_STOCK_RE.search(norm_text):
        return None, True, "in stock"
    return None, None, None


def _labeled_value(norm_text: str, labels: Iterable[str]) -> Optional[str]:
    for label in labels:
        m = re.search(re.escape(label) + r"\s*[:：]?\s*(.+)", norm_text, re.IGNORECASE)
        if m:
            value = m.group(1).splitlines()[0].strip()
            if value:
                return value
    return None


def _attribute_value(soup: BeautifulSoup, labels: Iterable[str]) -> Optional[str]:
    """Read a value from PrestaShop/WooCommerce attribute tables by label."""
    rows = soup.select(
        ".product-features dt, .data-sheet dt, "
        ".woocommerce-product-attributes-item__label, .shop_attributes th, "
        "table.data-table th, .product-information dt"
    )
    for label_el in rows:
        label_text = normalize_digits(label_el.get_text(" ", strip=True))
        if any(lbl in label_text.lower() for lbl in (l.lower() for l in labels)):
            value_el = label_el.find_next_sibling()
            if value_el is not None:
                val = value_el.get_text(" ", strip=True)
                if val:
                    return val
    return None


def find_package(soup: BeautifulSoup, norm_text: str) -> Optional[str]:
    return _attribute_value(soup, _PACKAGE_LABELS) or _labeled_value(norm_text, _PACKAGE_LABELS)


def find_part_type(soup: BeautifulSoup, norm_text: str) -> Optional[str]:
    raw = _attribute_value(soup, _TYPE_LABELS) or _labeled_value(norm_text, _TYPE_LABELS)
    if raw is None:
        return None
    if "کپی" in raw or "copy" in raw.lower():
        return "Copy"
    if "بازسازی" in raw or "refurb" in raw.lower():
        return "Refurbished"
    if "اورجینال" in raw or "اصل" in raw or "original" in raw.lower():
        return "Original"
    return raw


def find_image(soup: BeautifulSoup, base_url: str) -> Optional[str]:
    og = soup.find("meta", attrs={"property": "og:image"})
    if og and og.get("content"):
        return urljoin(base_url, og["content"])
    img = soup.find("img")
    if img is not None:
        src = img.get("data-src") or img.get("src")
        if src:
            return urljoin(base_url, src)
    return None


def build_offer(
    vendor: str,
    base_url: str,
    part_query: str,
    url: str,
    html: str,
    price_selectors: Sequence[str],
    stock_selectors: Sequence[str],
):
    """Parse a product-detail page into a ProductOffer (or None to skip).

    Shared by every vendor whose product pages follow the Persian conventions;
    each vendor only passes its platform's price/stock CSS selectors.
    """
    from .models import ProductOffer  # local import to avoid a cycle

    soup = BeautifulSoup(html, "html.parser")
    norm = text_of(soup)

    parsed = find_price(soup, price_selectors, norm)
    qty, in_stock, avail_raw = find_stock(soup, stock_selectors, norm)

    # A page with neither a price nor a stock signal isn't a real offer.
    if parsed.amount is None and in_stock is None:
        return None

    return ProductOffer(
        vendor=vendor,
        part_query=part_query,
        title=guess_title(soup),
        product_url=url,
        image_url=find_image(soup, base_url),
        price_amount=parsed.amount,
        price_currency=parsed.currency,
        price_raw=parsed.raw or None,
        price_rial=parsed.to_rial(),
        in_stock=in_stock,
        stock_qty=qty,
        availability_raw=avail_raw,
        package=find_package(soup, norm),
        part_type=find_part_type(soup, norm),
    )
