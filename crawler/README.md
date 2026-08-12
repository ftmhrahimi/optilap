# Optilap Crawler (MVP — Week 1)

First deliverable of the Optilap roadmap **Masir A / Crawler** (the riskiest
assumption: *"can we stably crawl the vendor sites?"*). It crawls a vendor's
search results for a part and returns normalized **price + stock** offers, ready
to feed the `referencePriceList` and the Scoring Engine.

## Vendors implemented

| Vendor | Platform | Search | Status |
| --- | --- | --- | --- |
| **JavanElectronic** | custom ASP.NET Core | `…/shop?searchfilter=` | verified — single-stage, reads price/stock/type/lead-time from the result cards |
| **ECA** | PrestaShop | `…/search?controller=search&s=` | verified against live site (2-stage; scoped availability) |
| **MicroModern** | Next.js (React) | `…/?q=…&post_type=product` | verified — reads product JSON embedded in the page |

All three share one extraction engine (`extract.py`) for the Persian price /
stock / package / type text; each vendor file only declares its platform's CSS
selectors. That's why adding a vendor is small.

## How JavanElectronic actually works (important)

The site is **server-rendered and two-stage** — confirmed against the live site:

1. **Search page** `…/shop?searchfilter=<part>` returns a listing of
   **product links** (`/shop/product/<id>/<slug>`) — **no price on the listing**.
2. **Each product page** carries the price (`… تومان`), stock
   (`موجود در انبار N`), package (`پکیج: …`) and part type (`نوع قطعه: …`).

Because the pages are server-rendered, a plain **`requests`** GET (with a
browser User-Agent) is enough — no headless browser needed. That's faster (a
BOM is hundreds of page loads) and matches the doc's design principle #1,
"simplest thing that works". A Playwright fetcher is kept available
(`CrawlerConfig(use_browser=True)`) for any future JavaScript-only vendor.

> The very first version of this crawler assumed prices were inline on the
> search grid (single-stage) and returned `zero_results`. The two-stage flow
> above is the fix.

## How it maps to the architecture doc (§7)

| Doc requirement | Where |
| --- | --- |
| One crawler **per vendor** | `vendors/javanelec.py`, registered in `registry.py` |
| Retry / backoff | `HttpFetcher` (`fetch.py`) + `CrawlerConfig` |
| Monitoring when a scraper keeps returning **zero results** | `FailureMonitor` (`base.py`) + distinct `CrawlStatus.ZERO_RESULTS` |
| Cross-vendor price comparison | `price_rial` on `ProductOffer` (Toman→Rial) |
| Reads customer BOM (Excel) | `bom.py` |

Not built yet (later weeks): the Procrastinate queue on PostgreSQL, the
`referencePriceList` table + 2-hour freshness rule, and the FastAPI endpoints.
The crawler is decoupled so those slot in around it.

## Layout

```
optilap_crawler/
  normalize.py   # Persian/Arabic digits, Toman/Rial prices, stock phrases
  models.py      # ProductOffer, CrawlResult, CrawlStatus (pydantic)
  fetch.py       # HttpFetcher (requests, default) + optional PlaywrightFetcher
  extract.py     # shared parsing: links, price, stock, package, type, build_offer
  base.py        # two-stage crawl orchestration, retry, FailureMonitor
  vendors/
    javanelec.py    # custom ASP.NET Core (2-stage HTML)
    eca.py          # PrestaShop (2-stage HTML)
    micromodern.py  # Next.js — reads embedded product JSON (single-stage)
  registry.py    # fixed vendor list
  bom.py         # read part numbers + quantities from a BOM .xlsx
scripts/
  crawl.py       # CLI: crawl a part or a whole BOM -> JSON
  inspect_site.py# debug/calibrate: dump search links + a parsed product page
tests/           # pure parser/normalizer/BOM tests (no network)
fixtures/        # synthetic search/product HTML + the sample BOM
```

## Install

```bash
pip install -r requirements.txt
```

## Use

```bash
# one part, any registered vendor
python scripts/crawl.py --vendor JavanElectronic --part LM358
python scripts/crawl.py --vendor ECA --part LM358
python scripts/crawl.py --vendor MicroModern --part LM358

# a whole BOM -> JSON
python scripts/crawl.py --vendor ECA --bom fixtures/bom_sample.xlsx --out results.json

# calibrate/debug a vendor: shows search links + first product parse
python scripts/inspect_site.py --vendor ECA --part LM358
```

```python
from optilap_crawler import crawl_part
r = crawl_part("JavanElectronic", "LM358")
print(r.status, len(r.offers), r.best_offer())
```

## Test

```bash
python -m pytest -q      # 25 tests, no network required
```

## Adding the next vendor

Subclass `BaseVendorCrawler`, implement `find_product_urls(search_html)` and
`parse_product(html, url, part_query)`, set `vendor_name/base_url/search_pattern`,
and register it in `registry.py`. Use `scripts/inspect_site.py` to discover each
site's product-link marker and its price/stock text.
