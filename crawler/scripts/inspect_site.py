#!/usr/bin/env python3
"""Diagnostic helper: dump what a vendor search + product page actually contain.

Uses the same ``requests`` fetcher as the crawler (the verified shops are
server-rendered). Handy for calibrating a new vendor or debugging why a crawl
returns nothing. Run it on a machine that can reach the site.

Usage:
    python scripts/inspect_site.py --part LM358
    python scripts/inspect_site.py --part LM358 --save     # write HTML to fixtures/
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from optilap_crawler.fetch import HttpFetcher  # noqa: E402
from optilap_crawler.registry import get_crawler  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vendor", default="JavanElectronic")
    ap.add_argument("--part", default="LM358")
    ap.add_argument("--save", action="store_true", help="save fetched HTML to fixtures/")
    args = ap.parse_args(argv)

    crawler = get_crawler(args.vendor)()
    fetcher = HttpFetcher()

    search_url = crawler.build_search_url(args.part)
    print(f"SEARCH  {search_url}")
    search_html = fetcher.get_html(search_url)
    print(f"  html size: {len(search_html):,} bytes")

    urls = crawler.find_product_urls(search_html)
    print(f"  product links found: {len(urls)}")
    for u in urls[:10]:
        print(f"    - {u}")
    if not urls:
        print("  !! No product links. Check the search URL / link marker for this vendor.")

    if args.save:
        FIXTURES.mkdir(exist_ok=True)
        (FIXTURES / f"{args.vendor}_search.html").write_text(search_html, encoding="utf-8")

    if urls:
        first = urls[0]
        print(f"\nPRODUCT {first}")
        product_html = fetcher.get_html(first)
        print(f"  html size: {len(product_html):,} bytes")
        offer = crawler.parse_product(product_html, first, args.part)
        if offer is None:
            print("  !! parse_product returned None (no price/stock detected).")
        else:
            print(f"  title   : {offer.title}")
            print(f"  price   : {offer.price_amount} {offer.price_currency} "
                  f"(= {offer.price_rial} Rial)  raw={offer.price_raw!r}")
            print(f"  stock   : in_stock={offer.in_stock} qty={offer.stock_qty}")
            print(f"  package : {offer.package}   type: {offer.part_type}")
        if args.save:
            (FIXTURES / f"{args.vendor}_product.html").write_text(product_html, encoding="utf-8")

    fetcher.close()
    print("\nDone." + ("  (HTML saved to fixtures/)" if args.save else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
