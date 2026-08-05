#!/usr/bin/env python3
"""Calibration helper: dump a live search-results page for selector tuning.

Run this on a machine that CAN reach the vendor site (the build/CI environment
here is blocked from javanelec.com by egress policy). It:
  * opens the search URL for a sample part,
  * saves the fully-rendered HTML to fixtures/, and
  * prints the tag/class of every element whose text contains a price
    (تومان/ریال), which is exactly what you need to fill in SELECTORS in
    optilap_crawler/vendors/javanelec.py.

Usage:
    python scripts/inspect_site.py --part LM358
    python scripts/inspect_site.py --part LM358 --headful
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from optilap_crawler.normalize import normalize_digits  # noqa: E402
from optilap_crawler.registry import get_crawler  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _looks_like_price(text: str) -> bool:
    norm = normalize_digits(text)
    return any(u in norm for u in ("تومان", "ریال", "﷼")) and any(c.isdigit() for c in norm)


async def _main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vendor", default="JavanElectronic")
    ap.add_argument("--part", default="LM358")
    ap.add_argument("--headful", action="store_true")
    args = ap.parse_args(argv)

    from bs4 import BeautifulSoup
    from playwright.async_api import async_playwright

    crawler = get_crawler(args.vendor)()
    url = crawler.build_search_url(args.part)
    print(f"GET {url}")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=not args.headful)
        context = await browser.new_context(locale="fa-IR")
        page = await context.new_page()
        await page.goto(url, timeout=45_000)
        await crawler.wait_for_results(page)
        html = await page.content()
        await browser.close()

    FIXTURES.mkdir(exist_ok=True)
    out = FIXTURES / f"{args.vendor}_{args.part}.html"
    out.write_text(html, encoding="utf-8")
    print(f"Saved rendered HTML -> {out}  ({len(html):,} bytes)")

    soup = BeautifulSoup(html, "html.parser")
    print("\nElements whose text contains a price (candidate price selectors):")
    seen = set()
    for node in soup.find_all(string=lambda s: bool(s) and _looks_like_price(s)):
        el = node.parent
        sig = (el.name, tuple(el.get("class", [])))
        if sig in seen:
            continue
        seen.add(sig)
        cls = ".".join(el.get("class", [])) or "(no class)"
        print(f"  <{el.name} class='{cls}'>  text={normalize_digits(node.strip())[:40]!r}")
    print("\nEdit SELECTORS in optilap_crawler/vendors/javanelec.py using the above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
