"""Parser tests for the MicroModern (WooCommerce) crawler."""
from decimal import Decimal
from pathlib import Path

from optilap_crawler.vendors.micromodern import MicroModernCrawler

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_find_product_urls():
    urls = MicroModernCrawler().find_product_urls(_fixture("micromodern_search.html"))
    assert urls == [
        "https://www.micmodshop.ir/product/lm358/",
        "https://www.micmodshop.ir/product/lm358-dip/",
    ]


def test_parse_product_sale_price_and_stock():
    offer = MicroModernCrawler().parse_product(
        _fixture("micromodern_product.html"),
        "https://www.micmodshop.ir/product/lm358/", "LM358")
    assert offer is not None
    assert offer.vendor == "MicroModern"
    assert "LM358" in (offer.title or "")
    # Sale price (ins) is taken, not the struck-out 120,000.
    assert offer.price_amount == Decimal("92000")
    assert offer.price_currency == "IRT"
    assert offer.price_rial == Decimal("920000")
    assert offer.in_stock is True
    assert offer.stock_qty == 35          # "۳۵ عدد در انبار"
    assert offer.package == "SOIC-8"
    assert offer.part_type == "Copy"       # کپی -> Copy


def test_parse_product_skips_empty_page():
    html = "<html><head><title>x</title></head><body><p>چیزی پیدا نشد</p></body></html>"
    assert MicroModernCrawler().parse_product(html, "http://x", "LM358") is None
