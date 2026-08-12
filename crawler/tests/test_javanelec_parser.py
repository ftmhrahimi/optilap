"""Parser tests for the JavanElectronic crawler (two-stage, pure functions)."""
from decimal import Decimal
from pathlib import Path

from optilap_crawler.vendors.javanelec import JavanElectronicCrawler

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _crawler():
    return JavanElectronicCrawler()


# -- Stage 1: search page -> product URLs -----------------------------------
def test_find_product_urls_dedupes_and_absolutizes():
    urls = _crawler().find_product_urls(_fixture("javan_search.html"))
    assert urls == [
        "https://www.javanelec.com/shop/product/1001/lm358-smd",
        "https://www.javanelec.com/shop/product/1002/lm358-dip",
        "https://www.javanelec.com/shop/product/1003/lm358dr",
    ]
    # Non-product links (home, about, contact) are excluded.
    assert all("/shop/product/" in u for u in urls)


def test_find_product_urls_empty_when_no_results():
    html = "<html><body><p>نتیجه‌ای یافت نشد</p></body></html>"
    assert _crawler().find_product_urls(html) == []


# -- Stage 2: product page -> offer -----------------------------------------
def test_parse_product_in_stock():
    offer = _crawler().parse_product(
        _fixture("javan_product_instock.html"),
        "https://www.javanelec.com/shop/product/1001/lm358-smd",
        "LM358",
    )
    assert offer is not None
    assert "LM358" in (offer.title or "")
    # Final (last) Toman price is taken, not the struck-out 18,000.
    assert offer.price_amount == Decimal("12500")
    assert offer.price_currency == "IRT"
    assert offer.price_rial == Decimal("125000")  # Toman -> Rial x10
    assert offer.in_stock is True
    assert offer.availability == "in_stock"
    assert offer.stock_qty == 42          # Persian digits normalized
    assert offer.package == "SO-8"
    assert offer.part_type == "Original"  # اورجینال -> Original


def test_parse_product_out_of_stock_copy():
    offer = _crawler().parse_product(
        _fixture("javan_product_outofstock.html"),
        "https://www.javanelec.com/shop/product/1002/lm358-dip",
        "LM358",
    )
    assert offer is not None
    assert offer.in_stock is False
    assert offer.stock_qty is None
    assert offer.package == "DIP-8"
    assert offer.part_type == "Copy"
    assert offer.price_amount == Decimal("9500")


def test_out_of_stock_order_only_ignores_packaging_quantity():
    # Real case (LM358AN): "ناموجود-سفارش دهید", no price, packaging "Tube-50 عدد".
    # Must be out of stock, and the "50 عدد" packaging must NOT become stock_qty.
    offer = _crawler().parse_product(
        _fixture("javan_product_orderonly.html"),
        "https://www.javanelec.com/shop/product/25145/national-semiconductor/lm358an",
        "LM358",
    )
    assert offer is not None
    assert offer.in_stock is False
    assert offer.stock_qty is None
    assert offer.price_amount is None
    assert offer.package == "DIP-8"


def test_on_order_is_distinct_from_out_of_stock():
    # "در حال تامین - پیش خرید" is a separate state from plain "ناموجود".
    offer = _crawler().parse_product(
        _fixture("javan_product_onorder.html"), "http://x", "LM358")
    assert offer is not None
    assert offer.availability == "on_order"
    assert offer.in_stock is False
    assert offer.part_type == "Original"   # no copy/refurb badge -> default


def test_back_order_keeps_lead_time_and_ignores_english_type_spec():
    # "ناموجود-تحویل ۳۵ روزه": out of stock, 35-day delivery. The English
    # "Type: Single|Dual" amplifier spec must NOT become the part type.
    offer = _crawler().parse_product(
        _fixture("javan_product_backorder.html"), "http://x", "LM358")
    assert offer is not None
    assert offer.availability == "out_of_stock"
    assert offer.lead_time_days == 35
    assert offer.package == "SO-8"
    assert offer.part_type == "Original"   # NOT "Single|Dual"


def test_parse_product_skips_page_with_no_price_or_stock():
    html = "<html><head><title>x</title></head><body><p>بدون اطلاعات</p></body></html>"
    offer = _crawler().parse_product(html, "http://x", "LM358")
    assert offer is None


def test_best_offer_prefers_cheapest_in_stock():
    from optilap_crawler.models import CrawlResult, CrawlStatus

    c = _crawler()
    in_stock = c.parse_product(
        _fixture("javan_product_instock.html"), "http://a", "LM358")
    out = c.parse_product(
        _fixture("javan_product_outofstock.html"), "http://b", "LM358")
    result = CrawlResult(
        vendor="JavanElectronic", part_query="LM358", search_url="x",
        status=CrawlStatus.OK, offers=[out, in_stock],
    )
    # Out-of-stock is cheaper (9,500) but the best offer must be in-stock.
    assert result.best_offer().price_rial == Decimal("125000")
