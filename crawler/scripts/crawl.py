#!/usr/bin/env python3
"""CLI to run the JavanElectronic (or any registered) crawler.

Examples
--------
Crawl a single part and list every offer:
    python scripts/crawl.py --vendor JavanElectronic --part ATMEGA16A

Crawl every unique part in a BOM and write JSON:
    python scripts/crawl.py --bom fixtures/bom_sample.xlsx --out results.json

Show only the single best offer per part (old compact view):
    python scripts/crawl.py --part LM358 --best
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

# Persian output breaks the default Windows console/file codec (cp1252). Force
# UTF-8 for stdout/stderr so printing Persian titles never crashes.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 - older Pythons / non-reconfigurable streams
        pass

# Make the package importable when run directly from scripts/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from optilap_crawler import CrawlerConfig, FailureMonitor, crawl_parts  # noqa: E402
from optilap_crawler.bom import read_bom, unique_parts  # noqa: E402
from optilap_crawler.models import CrawlResult, ProductOffer  # noqa: E402

# Columns shown for every offer (in order).
_COLUMNS = ["Vendor", "Price", "Stock", "Package", "Type", "Time", "Title"]


def _fmt_price(o: ProductOffer) -> str:
    if o.price_amount is None:
        return "no price"
    unit = {"IRT": "Toman", "IRR": "Rial"}.get(o.price_currency or "", o.price_currency or "")
    return f"{o.price_amount:,.0f} {unit}".strip()


def _fmt_stock(o: ProductOffer) -> str:
    if o.stock_qty is not None:
        return f"{o.stock_qty} in stock"
    if o.in_stock is True:
        return "in stock"
    if o.in_stock is False:
        return "out of stock"
    return "unknown"


def _fmt_time(o: ProductOffer) -> str:
    # crawled_at is timezone-aware UTC; show it in the machine's local time.
    return o.crawled_at.astimezone().strftime("%Y-%m-%d %H:%M")


def _offer_row(o: ProductOffer) -> List[str]:
    return [
        o.vendor,
        _fmt_price(o),
        _fmt_stock(o),
        o.package or "-",
        o.part_type or "-",
        _fmt_time(o),
        (o.title or "-"),
    ]


def _print_table(rows: List[List[str]]) -> None:
    """Print a simple left-aligned table. Title is last so RTL text can't
    break the alignment of the numeric columns before it."""
    header = _COLUMNS
    # Width per column based on ASCII-ish content (title excluded from padding).
    widths = [len(h) for h in header]
    for r in rows:
        for i, cell in enumerate(r[:-1]):  # skip Title for width calc
            widths[i] = max(widths[i], len(cell))

    def line(cells: List[str]) -> str:
        out = []
        for i, cell in enumerate(cells):
            out.append(cell if i == len(cells) - 1 else cell.ljust(widths[i]))
        return "  ".join(out)

    print(line(header))
    print(line(["-" * w for w in widths[:-1]] + ["-" * len("Title")]))
    for r in rows:
        print(line(r))


def _report(results: List[CrawlResult], best_only: bool) -> None:
    for r in results:
        print(f"\n=== {r.part_query}  [{r.status.value}]  {len(r.offers)} offer(s)"
              f"  |  {r.search_url}")
        offers = r.offers
        if not offers:
            continue
        if best_only:
            best = r.best_offer()
            offers = [best] if best else []
        _print_table([_offer_row(o) for o in offers])
        # Product URLs printed separately (too long for a table column).
        for i, o in enumerate(offers, 1):
            if o.product_url:
                print(f"    ({i}) {o.product_url}")


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="Optilap vendor crawler")
    p.add_argument("--vendor", default="JavanElectronic")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--part", help="A single part/MPN to search")
    src.add_argument("--bom", help="Path to a BOM .xlsx file")
    p.add_argument("--limit", type=int, default=None, help="Cap number of parts (BOM mode)")
    p.add_argument("--max-products", type=int, default=25,
                   help="Max product pages to open per part")
    p.add_argument("--best", action="store_true",
                   help="Show only the single best offer per part")
    p.add_argument("--browser", action="store_true",
                   help="Use the Playwright fetcher instead of requests")
    p.add_argument("--out", help="Write full results (all offers) as JSON to this path")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)

    if args.part:
        parts = [args.part]
    else:
        parts = unique_parts(read_bom(args.bom))
        if args.limit:
            parts = parts[: args.limit]

    print(f"Crawling {len(parts)} part(s) from {args.vendor} ...", file=sys.stderr)

    config = CrawlerConfig(max_products=args.max_products, use_browser=args.browser)
    monitor = FailureMonitor()
    results = crawl_parts(args.vendor, parts, config=config, monitor=monitor)

    _report(results, best_only=args.best)

    if args.out:
        payload = [json.loads(r.model_dump_json()) for r in results]
        Path(args.out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nWrote {args.out}", file=sys.stderr)

    # Non-zero exit only if every crawl errored (useful in CI/monitoring).
    return 1 if results and all(r.status.value == "error" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
