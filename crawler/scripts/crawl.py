#!/usr/bin/env python3
"""CLI to run the JavanElectronic (or any registered) crawler.

Examples
--------
Crawl a single part:
    python scripts/crawl.py --vendor JavanElectronic --part LM358

Crawl every unique part in a BOM and write JSON:
    python scripts/crawl.py --vendor JavanElectronic --bom ../bom_sample.xlsx \
        --out results.json

Run headful (watch the browser) while debugging selectors:
    python scripts/crawl.py --part LM358 --headful --limit 3
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Make the package importable when run directly from scripts/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from optilap_crawler import CrawlerConfig, FailureMonitor, crawl_parts  # noqa: E402
from optilap_crawler.bom import read_bom, unique_parts  # noqa: E402


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="Optilap vendor crawler")
    p.add_argument("--vendor", default="JavanElectronic")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--part", help="A single part/MPN to search")
    src.add_argument("--bom", help="Path to a BOM .xlsx file")
    p.add_argument("--limit", type=int, default=None, help="Cap number of parts (BOM mode)")
    p.add_argument("--headful", action="store_true", help="Show the browser window")
    p.add_argument("--out", help="Write full results as JSON to this path")
    return p.parse_args(argv)


async def _main(argv=None) -> int:
    args = _parse_args(argv)

    if args.part:
        parts = [args.part]
    else:
        lines = read_bom(args.bom)
        parts = unique_parts(lines)
        if args.limit:
            parts = parts[: args.limit]

    print(f"Crawling {len(parts)} part(s) from {args.vendor} ...", file=sys.stderr)

    config = CrawlerConfig(headless=not args.headful)
    monitor = FailureMonitor()
    results = await crawl_parts(args.vendor, parts, config=config, monitor=monitor)

    for r in results:
        best = r.best_offer()
        summary = "-"
        if best is not None:
            price = f"{best.price_rial:,.0f} Rial" if best.price_rial is not None else "no price"
            stock = "in stock" if best.in_stock else ("out" if best.in_stock is False else "?")
            summary = f"{(best.title or '')[:48]!r} | {price} | {stock}"
        print(f"[{r.status.value:12}] {r.part_query:20} -> {len(r.offers):2} offers | {summary}")

    if args.out:
        payload = [json.loads(r.model_dump_json()) for r in results]
        Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        print(f"Wrote {args.out}", file=sys.stderr)

    # Non-zero exit if every crawl errored (useful in CI/monitoring).
    return 0 if any(r.ok for r in results) or not results else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
