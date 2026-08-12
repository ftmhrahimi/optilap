"""Tests for the MicroModern (Next.js) crawler — parses embedded Flight JSON."""
from decimal import Decimal
from pathlib import Path

from optilap_crawler import crawl_part
from optilap_crawler.vendors.micromodern import extract_products, MicroModernCrawler

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class _FakeFetcher:
    """Returns the saved Next.js HTML for any URL (single-stage vendor)."""

    def __init__(self, html: str):
        self.html = html

    def get_html(self, url: str) -> str:
        return self.html


def test_extract_products_from_flight_json():
    products = extract_products(_fixture("micromodern_next.html"))
    assert len(products) == 3
    assert products[0]["manufacture_part_number"] == "LM358G-S08-R"
    # The double-escaped quote inside the package value survives both decodes.
    assert products[0]["attributes_dict"]["Package"]["value"] == 'SOIC8 (0.154"/3.90mm Width)'


def test_crawl_builds_offers_from_json():
    fetcher = _FakeFetcher(_fixture("micromodern_next.html"))
    result = crawl_part("MicroModern", "LM358", fetcher=fetcher)

    assert result.status.value == "ok"
    assert len(result.offers) == 3

    a, b, c = result.offers
    assert a.vendor == "MicroModern"
    assert "LM358G-S08-R" in (a.title or "")
    assert a.price_amount == Decimal("13234")
    assert a.price_currency == "IRT"
    assert a.price_rial == Decimal("132340")     # Toman -> Rial x10
    assert a.in_stock is True
    assert a.availability == "in_stock"
    assert a.stock_qty == 2122
    assert a.package == 'SOIC8 (0.154"/3.90mm Width)'
    assert a.part_type == "Original"              # Genuine -> Original
    assert a.product_url == "https://www.micmodshop.ir/products/92821/op-amp-13"

    assert b.part_type == "Copy"                  # "General China Made" -> Copy
    assert b.price_amount == Decimal("6190")

    # Out of stock but priced: must be out_of_stock (qty 0), NOT "in stock".
    assert c.price_amount == Decimal("8000")
    assert c.in_stock is False
    assert c.availability == "out_of_stock"
    assert c.stock_qty == 0


def test_empty_page_yields_zero_results():
    fetcher = _FakeFetcher("<html><body>no data here</body></html>")
    result = crawl_part("MicroModern", "NOPART", fetcher=fetcher)
    assert result.status.value == "zero_results"
    assert result.offers == []
