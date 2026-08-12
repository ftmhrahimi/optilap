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
    r"ناموجود|اتمام موجودی|اتمام موجودي|تمام شد|موجود نیست|out of stock"
)
# "Being supplied / pre-order" is a DISTINCT state from plain out-of-stock.
_ON_ORDER_RE = re.compile(r"در حال تامین|در حال تأمین|پیش\s*خرید")
# Lead time, e.g. "تحویل ۳۵ روزه" -> 35 days.
_LEAD_TIME_RE = re.compile(r"تحویل\s*([\d,]+)\s*روزه")
_IN_STOCK_RE = re.compile(r"موجود در انبار|in stock|add to cart")

_PACKAGE_LABELS = ("پکیج", "بسته بندی", "پکینگ", "package", "case")

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


class StockInfo:
    """Availability details extracted from a product page."""

    __slots__ = ("qty", "in_stock", "availability", "lead_time_days", "raw")

    def __init__(self, qty=None, in_stock=None, availability=None, lead_time_days=None, raw=None):
        self.qty = qty
        self.in_stock = in_stock
        self.availability = availability  # 'in_stock' / 'out_of_stock' / 'on_order'
        self.lead_time_days = lead_time_days
        self.raw = raw


def _line_with(norm_text: str, pattern: "re.Pattern") -> Optional[str]:
    for line in norm_text.splitlines():
        if pattern.search(line):
            s = line.strip()
            if s:
                return s
    return None


def find_stock(soup: BeautifulSoup, selectors: Sequence[str], norm_text: str) -> StockInfo:
    """Classify availability into in_stock / out_of_stock / on_order (+ lead time).

    Order matters:
      * a "N عدد" packaging count is NOT stock, so quantity requires an
        "انبار/موجود/stock" context;
      * "در حال تامین / پیش‌خرید" (being supplied) is distinct from plain
        "ناموجود" (out of stock) and is checked first;
      * "تحویل N روزه" gives the lead time for back-ordered items.
    """
    lead = None
    ml = _LEAD_TIME_RE.search(norm_text)
    if ml:
        try:
            lead = int(ml.group(1).replace(",", ""))
        except ValueError:
            lead = None

    if _ON_ORDER_RE.search(norm_text):
        return StockInfo(None, False, "on_order", lead, _line_with(norm_text, _ON_ORDER_RE))
    if _OUT_OF_STOCK_RE.search(norm_text):
        return StockInfo(None, False, "out_of_stock", lead, _line_with(norm_text, _OUT_OF_STOCK_RE))

    m_qty = _STOCK_QTY_RE.search(norm_text)
    if m_qty:
        digits = m_qty.group(1) or m_qty.group(2) or m_qty.group(3)
        qty = int(digits.replace(",", ""))
        return StockInfo(qty, qty > 0, "in_stock" if qty > 0 else "out_of_stock",
                         None, m_qty.group(0).strip())

    for sel in selectors:
        el = first_in(soup, [sel])
        if el is None:
            continue
        classes = " ".join(el.get("class", []))
        txt = normalize_digits(el.get_text(" ", strip=True))
        if "out-of-stock" in classes or "unavailable" in classes or _OUT_OF_STOCK_RE.search(txt):
            return StockInfo(None, False, "out_of_stock", lead, txt or "out of stock")
        if "in-stock" in classes or "available" in classes or _IN_STOCK_RE.search(txt):
            qm = re.search(r"(\d+)", txt)
            qty = int(qm.group(1)) if qm else None
            return StockInfo(qty, True, "in_stock", None, txt or "in stock")

    if _IN_STOCK_RE.search(norm_text):
        return StockInfo(None, True, "in_stock", None, "in stock")
    return StockInfo(None, None, None, lead, None)


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


def find_part_type(soup: BeautifulSoup, norm_text: str, default: Optional[str] = None) -> Optional[str]:
    """Detect Original / Copy / Refurbished.

    Iranian shops flag non-genuine parts with a badge: "کپی" (copy) or
    "بازسازی شده" (refurbished); genuine parts carry no badge. We deliberately do
    NOT match a generic English "Type" label — on op-amps that is the amplifier
    configuration ("Single/Dual"), not the part authenticity.
    """
    if "بازسازی" in norm_text:
        return "Refurbished"
    if "کپی" in norm_text:
        return "Copy"
    if "اورجینال" in norm_text:
        return "Original"
    # A Persian "نوع قطعه" field, if the shop uses one.
    raw = _attribute_value(soup, ("نوع قطعه",)) or _labeled_value(norm_text, ("نوع قطعه",))
    if raw:
        low = raw.lower()
        if "کپی" in raw or "copy" in low:
            return "Copy"
        if "بازسازی" in raw or "refurb" in low:
            return "Refurbished"
        if "اورجینال" in raw or "original" in low:
            return "Original"
        return raw
    return default


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
    default_part_type: Optional[str] = None,
):
    """Parse a product-detail page into a ProductOffer (or None to skip).

    Shared by every vendor whose product pages follow the Persian conventions;
    each vendor only passes its platform's price/stock CSS selectors.
    ``default_part_type`` is used when no copy/refurb badge is present (e.g.
    JavanElectronic treats un-badged parts as "Original").
    """
    from .models import ProductOffer  # local import to avoid a cycle

    soup = BeautifulSoup(html, "html.parser")
    norm = text_of(soup)

    parsed = find_price(soup, price_selectors, norm)
    stock = find_stock(soup, stock_selectors, norm)

    # A page with neither a price nor any availability signal isn't a real offer.
    if parsed.amount is None and stock.in_stock is None and stock.availability is None:
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
        in_stock=stock.in_stock,
        availability=stock.availability,
        stock_qty=stock.qty,
        lead_time_days=stock.lead_time_days,
        availability_raw=stock.raw,
        package=find_package(soup, norm),
        part_type=find_part_type(soup, norm, default=default_part_type),
    )
