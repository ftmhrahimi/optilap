#!/usr/bin/env python3
"""CLI to run the JavanElectronic (or any registered) crawler.

Examples
--------
Crawl a single part and list every offer:
    python scripts/crawl.py --vendor JavanElectronic --part ATMEGA16A

Crawl a BOM and write BOTH results.json and results.csv:
    python scripts/crawl.py --bom fixtures/bom_sample.xlsx --out results

Write only one format (by extension), or exact paths:
    python scripts/crawl.py --part LM358 --out offers.csv
    python scripts/crawl.py --part LM358 --json a.json --csv b.csv

Show only the single best offer per part (compact view):
    python scripts/crawl.py --part LM358 --best
"""
from __future__ import annotations

import argparse
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
from optilap_crawler.export import write_csv, write_json  # noqa: E402
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
    p.add_argument("--out",
                   help="Base output path. '.json'/'.csv' extension writes that "
                        "one format; no extension writes BOTH <out>.json and <out>.csv")
    p.add_argument("--json", dest="json_path", help="Write JSON to this exact path")
    p.add_argument("--csv", dest="csv_path", help="Write CSV to this exact path")
    return p.parse_args(argv)


def _write_outputs(results, args) -> List[str]:
    """Resolve --out / --json / --csv into actual files. Returns paths written."""
    written: List[str] = []
    if args.out:
        low = args.out.lower()
        if low.endswith(".json"):
            write_json(results, args.out); written.append(args.out)
        elif low.endswith(".csv"):
            write_csv(results, args.out); written.append(args.out)
        else:  # no known extension -> emit both
            j, c = args.out + ".json", args.out + ".csv"
            write_json(results, j); write_csv(results, c)
            written += [j, c]
    if args.json_path:
        write_json(results, args.json_path); written.append(args.json_path)
    if args.csv_path:
        write_csv(results, args.csv_path); written.append(args.csv_path)
    return written


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

    for path in _write_outputs(results, args):
        print(f"Wrote {path}", file=sys.stderr)

    # Non-zero exit only if every crawl errored (useful in CI/monitoring).
    return 1 if results and all(r.status.value == "error" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
