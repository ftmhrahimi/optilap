"""Serialize crawl results to JSON (nested) and CSV (flat).

JSON keeps the natural shape: one part -> its CrawlResult -> many offers.

CSV is flat: **one row per extracted offer**, and its columns are exactly the
fields of a JSON offer object (taken straight from the ``ProductOffer`` model,
so the two never drift). Parts that produced no offer contribute no row.

CSV is written with UTF-8 **BOM** (``utf-8-sig``) so Excel on Windows opens the
Persian text correctly instead of showing mojibake.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, Iterator, List

from .models import CrawlResult, ProductOffer

# CSV columns == the JSON offer object's fields, in model order.
CSV_COLUMNS: List[str] = list(ProductOffer.model_fields.keys())


def to_json_payload(results: List[CrawlResult]) -> list:
    """Return a JSON-ready list (nested: result -> offers)."""
    return [json.loads(r.model_dump_json()) for r in results]


def write_json(results: List[CrawlResult], path: str) -> None:
    Path(path).write_text(
        json.dumps(to_json_payload(results), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def iter_offer_rows(results: List[CrawlResult]) -> Iterator[Dict[str, object]]:
    """Yield one dict per offer, serialized exactly like the JSON offer object."""
    for r in results:
        for offer in r.offers:
            yield json.loads(offer.model_dump_json())


def write_csv(results: List[CrawlResult], path: str) -> None:
    # utf-8-sig => Excel on Windows reads Persian correctly.
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in iter_offer_rows(results):
            writer.writerow(row)
