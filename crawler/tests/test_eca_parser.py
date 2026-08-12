"""Parser tests for the ECA (PrestaShop) crawler."""
from decimal import Decimal
from pathlib import Path

from optilap_crawler.vendors.eca import ECACrawler

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_find_product_urls():
    urls = ECACrawler().find_product_urls(_fixture("eca_search.html"))
    assert urls == [
        "https://eshop.eca.ir/12345-lm358.html",
        "https://eshop.eca.ir/12346-lm358n.html",
    ]


def test_parse_product_in_stock():
    offer = ECACrawler().parse_product(
        _fixture("eca_product.html"), "https://eshop.eca.ir/12345-lm358.html", "LM358")
    assert offer is not None
    assert offer.vendor == "ECA"
    assert "LM358" in (offer.title or "")
    # ECA shows Rial directly.
    assert offer.price_amount == Decimal("62300")
    assert offer.price_currency == "IRR"
    assert offer.price_rial == Decimal("62300")
    # In stock, from the scoped .stock-badge-inline (NOT the JS 'ناموجود').
    assert offer.in_stock is True
    assert offer.availability == "in_stock"
    assert offer.package == "DIP"
    # No authenticity badge on ECA -> type is unknown, NOT a false "Copy"
    # (from the "کپی لینک" share button / review), NOT the "نوع قطعه" category.
    assert offer.part_type is None


def test_parse_product_skips_empty_page():
    html = "<html><head><title>x</title></head><body><p>موردی یافت نشد</p></body></html>"
    assert ECACrawler().parse_product(html, "http://x", "LM358") is None
