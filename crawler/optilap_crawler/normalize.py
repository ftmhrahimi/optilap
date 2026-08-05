"""Text/number normalization helpers for Iranian electronics shops.

Iranian storefronts render numbers with Persian (۰۱۲…) or Arabic-Indic (٠١٢…)
digits, use Toman *or* Rial as the unit, and mix several thousands separators
(",", "٬", "،", ".", or spaces). Availability is expressed in Persian phrases.

These helpers turn that messy on-page text into clean, comparable values. They
are pure functions with no Playwright / network dependency so they can be unit
tested in isolation.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Optional

# ---------------------------------------------------------------------------
# Digits
# ---------------------------------------------------------------------------
_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_ASCII_DIGITS = "0123456789"

_DIGIT_MAP = {ord(p): a for p, a in zip(_PERSIAN_DIGITS, _ASCII_DIGITS)}
_DIGIT_MAP.update({ord(p): a for p, a in zip(_ARABIC_DIGITS, _ASCII_DIGITS)})
# Arabic decimal/thousands separators -> ascii friendly forms
_DIGIT_MAP.update({ord("٬"): ",", ord("،"): ",", ord("٫"): "."})


def normalize_digits(text: str) -> str:
    """Convert Persian/Arabic digits (and their separators) to ASCII."""
    if not text:
        return ""
    return text.translate(_DIGIT_MAP)


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------
# Unit keywords as they appear on Iranian shops.
_TOMAN_TOKENS = ("تومان", "تومـان", "toman", "تومـان")
_RIAL_TOKENS = ("ریال", "﷼", "rial", "rls")

# A run of digits that may contain thousands separators, e.g. "1,250,000".
_PRICE_RE = re.compile(r"\d[\d.,  ]*\d|\d")


def _strip_separators(number_text: str) -> str:
    """Remove thousands separators, keeping the bare integer part.

    Iranian prices are always whole numbers of Toman/Rial, so any ',' or '.' is
    a grouping separator, never a decimal point. We drop them all.
    """
    return re.sub(r"[^\d]", "", number_text)


def parse_price(text: Optional[str]) -> "ParsedPrice":
    """Parse a price string into an amount + detected currency.

    Returns a :class:`ParsedPrice`; ``amount`` is ``None`` when no number is
    found (e.g. "تماس بگیرید" / "call for price").
    """
    raw = (text or "").strip()
    if not raw:
        return ParsedPrice(amount=None, currency=None, raw=raw)

    norm = normalize_digits(raw)
    lowered = norm.lower()

    currency: Optional[str] = None
    if any(tok in norm or tok in lowered for tok in _RIAL_TOKENS):
        currency = "IRR"  # Rial
    elif any(tok in norm or tok in lowered for tok in _TOMAN_TOKENS):
        currency = "IRT"  # Toman (1 Toman = 10 Rial)

    match = _PRICE_RE.search(norm)
    if not match:
        return ParsedPrice(amount=None, currency=currency, raw=raw)

    digits = _strip_separators(match.group(0))
    if not digits:
        return ParsedPrice(amount=None, currency=currency, raw=raw)

    try:
        amount = Decimal(digits)
    except InvalidOperation:
        return ParsedPrice(amount=None, currency=currency, raw=raw)

    return ParsedPrice(amount=amount, currency=currency, raw=raw)


class ParsedPrice:
    """Small value object for a parsed price."""

    __slots__ = ("amount", "currency", "raw")

    def __init__(self, amount: Optional[Decimal], currency: Optional[str], raw: str):
        self.amount = amount
        self.currency = currency
        self.raw = raw

    def to_rial(self) -> Optional[Decimal]:
        """Return the amount normalized to Rial for cross-vendor comparison."""
        if self.amount is None:
            return None
        if self.currency == "IRT":
            return self.amount * 10
        return self.amount  # IRR or unknown -> assume already Rial

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"ParsedPrice(amount={self.amount}, currency={self.currency!r})"


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------
_OUT_OF_STOCK_TOKENS = (
    "ناموجود",
    "اتمام موجودی",
    "اتمام موجودي",
    "تمام شد",
    "موجود نیست",
    "out of stock",
    "ناموجــود",
)
_IN_STOCK_TOKENS = (
    "افزودن به سبد",  # "add to cart" implies purchasable
    "افزودن به سبد خرید",
    "موجود",
    "in stock",
    "add to cart",
)


def detect_availability(text: Optional[str]) -> Optional[bool]:
    """Best-effort in/out-of-stock detection from Persian/English UI text.

    Returns ``True`` (in stock), ``False`` (out of stock) or ``None`` (unknown).
    Out-of-stock is checked first because "ناموجود" contains "موجود".
    """
    if not text:
        return None
    norm = normalize_digits(text).lower()
    if any(tok.lower() in norm for tok in _OUT_OF_STOCK_TOKENS):
        return False
    if any(tok.lower() in norm for tok in _IN_STOCK_TOKENS):
        return True
    return None


# ---------------------------------------------------------------------------
# Part queries
# ---------------------------------------------------------------------------
def normalize_part_query(part: str) -> str:
    """Clean a raw BOM part identifier into a search query string.

    Keeps the manufacturer part number essentially intact (the vendor search
    boxes match on it) while collapsing whitespace and stripping surrounding
    noise. URL-encoding is handled later by the crawler when building the URL.
    """
    if not part:
        return ""
    cleaned = normalize_digits(str(part)).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned
