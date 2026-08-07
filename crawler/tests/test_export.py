"""Tests for JSON/CSV export."""
import csv
import json
from decimal import Decimal

from optilap_crawler.export import CSV_COLUMNS, write_csv, write_json
from optilap_crawler.models import CrawlResult, CrawlStatus, ProductOffer


def _sample_results():
    offer = ProductOffer(
        vendor="JavanElectronic", part_query="LM358", title="آی‌سی LM358",
        product_url="https://www.javanelec.com/shop/product/1/lm358",
        price_amount=Decimal("12500"), price_currency="IRT", price_rial=Decimal("125000"),
        in_stock=True, stock_qty=42, package="SO-8", part_type="Original",
    )
    ok = CrawlResult(vendor="JavanElectronic", part_query="LM358",
                     search_url="https://x/?s=LM358", status=CrawlStatus.OK, offers=[offer])
    empty = CrawlResult(vendor="JavanElectronic", part_query="NOPART",
                        search_url="https://x/?s=NOPART", status=CrawlStatus.ZERO_RESULTS)
    return [ok, empty]


def test_write_json_roundtrip(tmp_path):
    path = tmp_path / "r.json"
    write_json(_sample_results(), str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data) == 2
    assert data[0]["offers"][0]["title"] == "آی‌سی LM358"
    assert data[0]["offers"][0]["price_rial"] == "125000"  # Decimal serialized


def test_write_csv_flat_with_bom(tmp_path):
    path = tmp_path / "r.csv"
    write_csv(_sample_results(), str(path))

    # utf-8-sig BOM so Excel renders Persian correctly.
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")

    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0].keys()) == CSV_COLUMNS
    # One offer row + one "no offers" row.
    assert len(rows) == 2
    assert rows[0]["part_query"] == "LM358"
    assert rows[0]["vendor"] == "JavanElectronic"
    assert rows[0]["price_rial"] == "125000"
    assert rows[0]["stock_qty"] == "42"
    assert rows[0]["package"] == "SO-8"
    # The zero-results part still appears, with its status and blank offer fields.
    assert rows[1]["part_query"] == "NOPART"
    assert rows[1]["status"] == "zero_results"
    assert rows[1]["vendor"] == ""
