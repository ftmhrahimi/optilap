# Optilap Crawler (MVP — Week 1)

First deliverable of the Optilap roadmap **Mmasir A / Crawler** (the riskiest
assumption: *"can we stably crawl the vendor sites?"*). This package crawls a
vendor's search results for a part and returns normalized **price + stock**
offers, ready to feed the `referencePriceList` and the Scoring Engine.

The first vendor is **JavanElectronic** (`https://www.javanelec.com`, Tehran,
ASP.NET Core + JavaScript), searched via
`https://www.javanelec.com/shop?searchfilter=[PART_NAME]`.

## How it maps to the architecture doc

| Doc requirement (§7 Crawler) | Where |
| --- | --- |
| Playwright (sites are JS-heavy) | `base.py` (`BaseVendorCrawler.crawl`) |
| One crawler **per vendor** | `vendors/javanelec.py`, registered in `registry.py` |
| Retry / backoff | `CrawlerConfig` + retry loop in `base.py` |
| Monitoring when a scraper keeps returning **zero results** | `FailureMonitor` (`base.py`) + distinct `CrawlStatus.ZERO_RESULTS` |
| Price freshness / cross-vendor comparison | `price_rial` on `ProductOffer` (Toman→Rial) |
| Reads customer BOM (Excel) | `bom.py` |

Not built yet (later weeks, per the doc): Procrastinate queue on PostgreSQL,
the `referencePriceList` table + 2-hour freshness rule, and the FastAPI
endpoints. The crawler is deliberately decoupled so those slot in around it.

## Layout

```
optilap_crawler/
  normalize.py   # Persian/Arabic digits, Toman/Rial prices, stock phrases
  models.py      # ProductOffer, CrawlResult, CrawlStatus (pydantic)
  base.py        # Playwright driver, retry/backoff, FailureMonitor
  vendors/
    javanelec.py # JavanElectronic scraper (SELECTORS = calibration point)
  registry.py    # fixed vendor list
  bom.py         # read part numbers + quantities from a BOM .xlsx
scripts/
  crawl.py       # CLI: crawl a part or a whole BOM -> JSON
  inspect_site.py# calibration helper: dump a live results page + price selectors
tests/           # pure parser/normalizer/BOM tests (no network)
fixtures/        # synthetic results HTML + the sample BOM
```

## Install

```bash
pip install -r requirements.txt
python -m playwright install chromium   # first time only
```

## Use

```bash
# one part
python scripts/crawl.py --vendor JavanElectronic --part LM358

# a whole BOM -> JSON (first 5 parts while testing)
python scripts/crawl.py --bom fixtures/bom_sample.xlsx --limit 5 --out results.json

# watch the browser while debugging selectors
python scripts/crawl.py --part LM358 --headful
```

```python
import asyncio
from optilap_crawler import crawl_part
r = asyncio.run(crawl_part("JavanElectronic", "LM358"))
print(r.status, len(r.offers), r.best_offer())
```

## ⚠️ One calibration step before the scraper is production-accurate

The exact CSS classes on JavanElec's results page could **not** be confirmed
from the build environment — its egress policy blocks `www.javanelec.com`
(the proxy returns a 403 policy denial on CONNECT). So the parser ships with:

1. **Best-guess selectors** in `SELECTORS` (top of `vendors/javanelec.py`), and
2. a **class-agnostic heuristic fallback** that finds product cards by locating
   price text (Toman/Rial) — this already returns usable offers even before
   calibration.

To make it precise, on a machine that **can** reach the site:

```bash
python scripts/inspect_site.py --part LM358
```

This saves the fully-rendered HTML to `fixtures/` and prints the tag/class of
every price-bearing element. Paste those into `SELECTORS`, drop the saved HTML
into `fixtures/`, point `test_javanelec_parser.py` at it, and re-run
`pytest` to lock the selectors in with a regression test.

## Test

```bash
python -m pytest -q      # 13 tests, no network required
```
