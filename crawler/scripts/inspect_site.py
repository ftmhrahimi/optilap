#!/usr/bin/env python3
"""Calibration + diagnostics: dump a live search-results page.

Run this on a machine that CAN reach the vendor site (the CI/build environment
is blocked from javanelec.com by egress policy). It:
  * opens the search URL for a sample part,
  * prints rich diagnostics (final URL, title, whether the page looks like a
    results page / a "no results" page / an anti-bot challenge),
  * saves the fully-rendered HTML to fixtures/ and a screenshot PNG, and
  * lists the tag/class of every price-bearing element (تومان/ریال) and of the
    most repeated element classes (candidate product-card selectors).

Usage:
    python scripts/inspect_site.py --part LM358
    python scripts/inspect_site.py --part LM358 --headful     # watch the browser
    python scripts/inspect_site.py --part LM358 --wait 8      # extra settle time
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from optilap_crawler.normalize import normalize_digits  # noqa: E402
from optilap_crawler.registry import get_crawler  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

_NO_RESULT_HINTS = ("نتیجه‌ای یافت نشد", "یافت نشد", "no result", "not found", "موردی یافت")
_CHALLENGE_HINTS = ("cloudflare", "checking your browser", "captcha", "are you human",
                    "attention required", " robot")


def _looks_like_price(text: str) -> bool:
    norm = normalize_digits(text)
    return any(u in norm for u in ("تومان", "ریال", "﷼")) and any(c.isdigit() for c in norm)


async def _main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vendor", default="JavanElectronic")
    ap.add_argument("--part", default="LM358")
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--wait", type=float, default=4.0,
                    help="extra seconds to wait after load (for lazy XHR results)")
    args = ap.parse_args(argv)

    from bs4 import BeautifulSoup
    from playwright.async_api import async_playwright

    crawler = get_crawler(args.vendor)()
    url = crawler.build_search_url(args.part)
    print(f"GET {url}\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=not args.headful)
        context = await browser.new_context(
            locale="fa-IR",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
        )
        page = await context.new_page()
        resp = await page.goto(url, timeout=60_000, wait_until="domcontentloaded")
        status = resp.status if resp else "?"
        try:
            await page.wait_for_load_state("networkidle", timeout=20_000)
        except Exception:
            pass
        if args.wait:
            await page.wait_for_timeout(int(args.wait * 1000))

        final_url = page.url
        title = await page.title()
        html = await page.content()
        body_text = await page.inner_text("body")

        FIXTURES.mkdir(exist_ok=True)
        html_path = FIXTURES / f"{args.vendor}_{args.part}.html"
        png_path = FIXTURES / f"{args.vendor}_{args.part}.png"
        html_path.write_text(html, encoding="utf-8")
        await page.screenshot(path=str(png_path), full_page=True)
        await browser.close()

    # ---- Diagnostics -------------------------------------------------------
    print("=" * 60)
    print(f"HTTP status     : {status}")
    print(f"Final URL       : {final_url}")
    print(f"Page title      : {title!r}")
    print(f"HTML size       : {len(html):,} bytes")
    print(f"Visible text    : {len(body_text):,} chars")
    low = body_text.lower()
    if any(h.lower() in low for h in _CHALLENGE_HINTS):
        print("!! Looks like an ANTI-BOT / CHALLENGE page.")
    if any(h in body_text for h in _NO_RESULT_HINTS):
        print("!! Page contains a 'no results' message.")
    print(f"Saved HTML      : {html_path}")
    print(f"Saved screenshot: {png_path}")

    soup = BeautifulSoup(html, "html.parser")

    print("\n--- Price-bearing elements (candidate PRICE selectors) ---")
    seen = set()
    n = 0
    for node in soup.find_all(string=lambda s: bool(s) and _looks_like_price(s)):
        el = node.parent
        sig = (el.name, tuple(el.get("class", [])))
        if sig in seen:
            continue
        seen.add(sig)
        n += 1
        cls = ".".join(el.get("class", [])) or "(no class)"
        print(f"  <{el.name} class='{cls}'>  {normalize_digits(node.strip())[:40]!r}")
    if n == 0:
        print("  (none found — the page has no Toman/Rial price text)")

    print("\n--- Most common element classes (candidate CARD selectors) ---")
    counter = Counter()
    for el in soup.find_all(True):
        classes = el.get("class")
        if classes:
            counter[(el.name, ".".join(classes))] += 1
    for (name, cls), count in counter.most_common(20):
        print(f"  {count:4}x  {name}.{cls}")

    print("\n--- First 800 chars of visible text ---")
    print(body_text[:800])

    print("\nNext: share this console output (and attach the saved .html/.png).")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
