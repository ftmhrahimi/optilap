"""Unit tests for the Iran-specific normalization layer."""
from decimal import Decimal

from optilap_crawler.normalize import (
    detect_availability,
    normalize_digits,
    normalize_part_query,
    parse_price,
)


def test_normalize_persian_and_arabic_digits():
    assert normalize_digits("۱۲۳۴۵") == "12345"
    assert normalize_digits("٠١٢٣٤") == "01234"
    assert normalize_digits("قیمت ۱۲۳") == "قیمت 123"


def test_parse_price_toman_with_persian_digits():
    p = parse_price("۱٬۲۵۰٬۰۰۰ تومان")
    assert p.amount == Decimal("1250000")
    assert p.currency == "IRT"
    assert p.to_rial() == Decimal("12500000")  # Toman -> Rial x10


def test_parse_price_rial_ascii():
    p = parse_price("1,250,000 ریال")
    assert p.amount == Decimal("1250000")
    assert p.currency == "IRR"
    assert p.to_rial() == Decimal("1250000")


def test_parse_price_call_for_price_has_no_amount():
    p = parse_price("تماس بگیرید")
    assert p.amount is None


def test_parse_price_empty():
    assert parse_price("").amount is None
    assert parse_price(None).amount is None


def test_detect_availability_out_of_stock_before_in_stock():
    # "ناموجود" contains "موجود" — must resolve to out of stock.
    assert detect_availability("ناموجود") is False
    assert detect_availability("موجود در انبار") is True
    assert detect_availability("افزودن به سبد خرید") is True
    assert detect_availability("اتمام موجودی") is False
    assert detect_availability("random") is None


def test_normalize_part_query_collapses_whitespace():
    assert normalize_part_query("  LM358   DR ") == "LM358 DR"
    assert normalize_part_query("۱۰۰nF") == "100nF"
