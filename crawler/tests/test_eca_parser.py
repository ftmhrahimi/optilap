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
    assert offer.price_amount == Decimal("85000")
    assert offer.price_currency == "IRT"
    assert offer.price_rial == Decimal("850000")
    assert offer.in_stock is True
    assert offer.stock_qty == 27
    assert offer.package == "DIP-8"
    assert offer.part_type == "Original"


def test_parse_product_skips_empty_page():
    html = "<html><head><title>x</title></head><body><p>موردی یافت نشد</p></body></html>"
    assert ECACrawler().parse_product(html, "http://x", "LM358") is None
