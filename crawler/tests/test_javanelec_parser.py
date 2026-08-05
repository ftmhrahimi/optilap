"""Parser tests for the JavanElectronic crawler.

These run the *pure* HTML parser against saved fixtures — no browser, no
network. The synthetic fixture exercises the configured-selector path; the
inline heuristic fixture exercises the class-agnostic fallback.
"""
from decimal import Decimal
from pathlib import Path

from optilap_crawler.vendors.javanelec import JavanElectronicCrawler

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _parse(html: str):
    return JavanElectronicCrawler().parse_results_html(html, "LM358")


def test_parses_configured_selector_fixture():
    html = (FIXTURES / "sample_results.html").read_text(encoding="utf-8")
    offers = _parse(html)
    assert len(offers) == 3

    first = offers[0]
    assert "LM358" in (first.title or "")
    assert first.price_amount == Decimal("12500")
    assert first.price_currency == "IRT"
    assert first.price_rial == Decimal("125000")
    assert first.in_stock is True
    assert first.product_url == "https://www.javanelec.com/product/1001/lm358"
    assert first.image_url == "https://www.javanelec.com/img/lm358.jpg"

    # Second item is explicitly out of stock.
    assert offers[1].in_stock is False

    # Third has "call for price" -> no amount, but still an offer.
    assert offers[2].price_amount is None
    assert offers[2].in_stock is True  # "موجود"


def test_best_offer_picks_cheapest_in_stock():
    from optilap_crawler.models import CrawlResult, CrawlStatus

    offers = _parse((FIXTURES / "sample_results.html").read_text(encoding="utf-8"))
    result = CrawlResult(
        vendor="JavanElectronic", part_query="LM358",
        search_url="x", status=CrawlStatus.OK, offers=offers,
    )
    best = result.best_offer()
    # Only item 1 is both priced and in stock.
    assert best.price_rial == Decimal("125000")


def test_heuristic_fallback_without_known_classes():
    # No .product-item / .price classes at all — parser must still find offers
    # by locating price-bearing containers.
    html = """
    <html><body>
      <ul>
        <li><a href="/p/9">قطعه تست الف</a><span>۵٬۰۰۰ تومان</span></li>
        <li><a href="/p/10">قطعه تست ب</a><span>۷٬۵۰۰ تومان</span></li>
      </ul>
    </body></html>
    """
    offers = _parse(html)
    assert len(offers) == 2
    prices = sorted(o.price_rial for o in offers)
    assert prices == [Decimal("50000"), Decimal("75000")]


def test_zero_results_page_returns_no_offers():
    html = "<html><body><div class='no-results'>نتیجه‌ای یافت نشد</div></body></html>"
    assert _parse(html) == []
