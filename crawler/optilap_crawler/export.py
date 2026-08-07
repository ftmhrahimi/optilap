"""Serialize crawl results to JSON (nested) and CSV (flat).

JSON keeps the natural shape: one part -> its CrawlResult -> many offers.
CSV is flat (one row per offer) because that's what spreadsheets/BI tools and a
quick human scan expect; a part with no offers still gets one row so nothing
silently disappears.

CSV is written with UTF-8 **BOM** (``utf-8-sig``) so Excel on Windows opens the
Persian text correctly instead of showing mojibake.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, Iterator, List

from .models import CrawlResult

# Flat column order for the CSV (one row per offer).
CSV_COLUMNS: List[str] = [
    "part_query",
    "status",
    "vendor",
    "title",
    "price_amount",
    "price_currency",
    "price_rial",
    "in_stock",
    "stock_qty",
    "package",
    "part_type",
    "product_url",
    "search_url",
    "crawled_at",
]


def to_json_payload(results: List[CrawlResult]) -> list:
    """Return a JSON-ready list (nested: result -> offers)."""
    return [json.loads(r.model_dump_json()) for r in results]


def write_json(results: List[CrawlResult], path: str) -> None:
    Path(path).write_text(
        json.dumps(to_json_payload(results), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def iter_csv_rows(results: List[CrawlResult]) -> Iterator[Dict[str, object]]:
    """Yield one flat dict per offer; one row for parts with no offers."""
    for r in results:
        base = {
            "part_query": r.part_query,
            "status": r.status.value,
            "search_url": r.search_url,
        }
        if not r.offers:
            yield {**base, "crawled_at": r.crawled_at.isoformat()}
            continue
        for o in r.offers:
            yield {
                **base,
                "vendor": o.vendor,
                "title": o.title,
                "price_amount": o.price_amount,
                "price_currency": o.price_currency,
                "price_rial": o.price_rial,
                "in_stock": o.in_stock,
                "stock_qty": o.stock_qty,
                "package": o.package,
                "part_type": o.part_type,
                "product_url": o.product_url,
                "crawled_at": o.crawled_at.isoformat(),
            }


def write_csv(results: List[CrawlResult], path: str) -> None:
    # utf-8-sig => Excel on Windows reads Persian correctly.
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in iter_csv_rows(results):
            writer.writerow(row)
