#!/usr/bin/env python3
"""Stability test for the initial vendor crawlers.

Answers the week-1 task *"تست پایداری Crawlerهای اولیه"*:
  * **Do the sites block us?**  — every response is classified for anti-bot /
    challenge / rate-limit signals.
  * **Is the structure parseable?** — the real vendor parser must turn the page
    into at least one offer.

Each (vendor, part) is hit ``--repeat`` times with a polite ``--delay`` so
intermittent blocking shows up too.

Run it from a network that can reach the shops (e.g. locally):

    python scripts/stability_test.py                     # all 3 vendors, default parts
    python scripts/stability_test.py --vendor ECA --parts LM358,NE555 --repeat 5
    python scripts/stability_test.py --out stability.json

NOTE: from a restricted CI/sandbox the shop domains may be blocked at the
network egress (not by the shop) — that shows up here as every trial erroring
with a connection failure. Run it where the sites are reachable.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import List, Optional

# Force UTF-8 so Persian block-page text / titles never crash a Windows console.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from optilap_crawler.bom import read_all_sheets, unique_parts  # noqa: E402
from optilap_crawler.fetch import DEFAULT_HEADERS  # noqa: E402
from optilap_crawler.registry import all_vendor_names  # noqa: E402
from optilap_crawler.stability import (  # noqa: E402
    DEFAULT_PARTS,
    FetchRecord,
    TrialResult,
    classify_block,
    run_stability,
    summarize,
)


class HttpRecordingFetcher:
    """A ``requests`` fetcher that records every GET (status, latency, size,
    block signal) and raises on non-2xx so a blocked/failed fetch surfaces as an
    ERROR trial. Records are drained per trial by the runner.

    Deliberately does a *single* attempt (no retry/backoff): the stability test
    measures raw per-request behaviour, and the trial-level ``--repeat`` already
    provides the repetition.
    """

    def __init__(self, timeout: int = 30):
        import requests

        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.timeout = timeout
        self._records: List[FetchRecord] = []

    def get_html(self, url: str) -> str:
        import requests

        t0 = time.monotonic()
        try:
            r = self.session.get(url, timeout=self.timeout, allow_redirects=True)
        except requests.RequestException as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            self._records.append(
                FetchRecord(url=url, status_code=None, elapsed_ms=elapsed,
                            bytes=0, error=str(exc))
            )
            raise
        elapsed = int((time.monotonic() - t0) * 1000)
        r.encoding = "utf-8"
        body = r.text
        reason = classify_block(r.status_code, body)
        self._records.append(
            FetchRecord(url=url, status_code=r.status_code, elapsed_ms=elapsed,
                        bytes=len(body), block_reason=reason)
        )
        if reason is not None:
            raise RuntimeError(f"blocked: {reason} ({url})")
        if not (200 <= r.status_code < 300):
            raise RuntimeError(f"http {r.status_code} ({url})")
        return body

    def drain_records(self) -> List[FetchRecord]:
        recs = self._records
        self._records = []
        return recs

    def close(self) -> None:
        self.session.close()


def _print_trial(tr: TrialResult) -> None:
    fetch = tr.fetches[0] if tr.fetches else None
    code = fetch.status_code if fetch and fetch.status_code is not None else "-"
    size = f"{fetch.bytes:,}B" if fetch else "-"
    flag = "BLOCKED" if tr.blocked else ("PARSED" if tr.parseable else tr.crawl_status.upper())
    extra = ""
    if tr.blocked:
        extra = f"  <- {tr.block_reason}"
    elif tr.error:
        extra = f"  <- {tr.error}"
    print(f"  [{tr.vendor:<16}] {tr.part:<10} #{tr.trial}  "
          f"{flag:<12} http={code} {size:>10}  {tr.offers} offer(s) "
          f"{tr.duration_ms}ms{extra}", file=sys.stderr)


def _report(summaries) -> str:
    lines: List[str] = []
    lines.append("=" * 72)
    lines.append("STABILITY REPORT — initial vendor crawlers")
    lines.append("=" * 72)
    for s in summaries.values():
        por = "n/a" if s.parse_ok_rate is None else f"{s.parse_ok_rate * 100:.0f}%"
        lines.append("")
        lines.append(f"{s.vendor}  ->  {s.verdict}")
        lines.append(f"  trials         : {s.trials}  (ok={s.ok} zero={s.zero} error={s.error})")
        lines.append(f"  blocked        : {s.blocked}/{s.trials}  ({s.block_rate * 100:.0f}%)")
        if s.block_reasons:
            uniq = sorted(set(s.block_reasons))
            lines.append(f"  block reasons  : {', '.join(uniq)}")
        lines.append(f"  parseable      : {por}  (offers parsed on ok trials; "
                     f"{s.offers_total} offers total)")
        if s.latency_avg_ms is not None:
            lines.append(f"  latency (ms)   : avg={s.latency_avg_ms} "
                         f"median={s.latency_median_ms} max={s.latency_max_ms}")
        lines.append(f"  => {s.note}")
    lines.append("")
    lines.append("-" * 72)
    lines.append("Blocking?   " + _overall_blocking(summaries))
    lines.append("Parseable?  " + _overall_parseable(summaries))
    lines.append("=" * 72)
    return "\n".join(lines)


def _overall_blocking(summaries) -> str:
    blocked = [s.vendor for s in summaries.values() if s.blocked]
    if not blocked:
        return "No blocking observed on any vendor."
    return "Blocking seen on: " + ", ".join(
        f"{s.vendor} ({s.blocked}/{s.trials})" for s in summaries.values() if s.blocked
    )


def _overall_parseable(summaries) -> str:
    good = [s.vendor for s in summaries.values() if s.parse_ok_rate == 1]
    partial = [s.vendor for s in summaries.values()
               if s.parse_ok_rate is not None and 0 < s.parse_ok_rate < 1]
    none = [s.vendor for s in summaries.values() if s.parse_ok_rate == 0]
    bits = []
    if good:
        bits.append("fully parseable: " + ", ".join(good))
    if partial:
        bits.append("partial: " + ", ".join(partial))
    if none:
        bits.append("0 offers parsed: " + ", ".join(none))
    return "; ".join(bits) if bits else "no usable responses to judge."


def _to_json(trials: List[TrialResult], summaries) -> dict:
    return {
        "summary": {
            s.vendor: {
                "verdict": s.verdict,
                "trials": s.trials,
                "ok": s.ok,
                "zero_results": s.zero,
                "error": s.error,
                "blocked": s.blocked,
                "block_rate": round(s.block_rate, 3),
                "parse_ok_rate": (None if s.parse_ok_rate is None
                                  else round(s.parse_ok_rate, 3)),
                "block_reasons": sorted(set(s.block_reasons)),
                "latency_ms": {
                    "avg": s.latency_avg_ms,
                    "median": s.latency_median_ms,
                    "max": s.latency_max_ms,
                },
                "offers_total": s.offers_total,
                "note": s.note,
            }
            for s in summaries.values()
        },
        "trials": [
            {
                "vendor": t.vendor,
                "part": t.part,
                "trial": t.trial,
                "crawl_status": t.crawl_status,
                "offers": t.offers,
                "duration_ms": t.duration_ms,
                "blocked": t.blocked,
                "block_reason": t.block_reason,
                "error": t.error,
                "fetches": [
                    {
                        "url": f.url,
                        "status_code": f.status_code,
                        "elapsed_ms": f.elapsed_ms,
                        "bytes": f.bytes,
                        "block_reason": f.block_reason,
                        "error": f.error,
                    }
                    for f in t.fetches
                ],
            }
            for t in trials
        ],
    }


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="Crawler stability test")
    p.add_argument("--vendor", action="append", dest="vendors",
                   help="Vendor to test (repeatable). Default: all registered.")
    p.add_argument("--parts", help="Comma-separated parts. Default: LM358,NE555,ATMEGA328")
    p.add_argument("--bom", help="Path to a (multi-sheet) BOM .xlsx to draw parts from")
    p.add_argument("--sheets", help="Comma-separated BOM sheet names to use (default: all)")
    p.add_argument("--per-sheet", type=int, default=5,
                   help="BOM mode: parts sampled per sheet (0 = all lines). Default 5")
    p.add_argument("--limit", type=int, default=None,
                   help="Cap the total number of unique parts tested")
    p.add_argument("--repeat", type=int, default=None,
                   help="Trials per (vendor, part). Default: 1 in --bom mode, else 3")
    p.add_argument("--delay", type=float, default=1.0, help="Seconds between requests")
    p.add_argument("--timeout", type=int, default=30, help="Per-request timeout (s)")
    p.add_argument("--max-products", type=int, default=5,
                   help="Cap product-detail fetches per trial (two-stage vendors)")
    p.add_argument("--out", help="Write the full JSON report to this path")
    return p.parse_args(argv)


def _resolve_parts(args) -> List[str]:
    """Build the part list from --bom (all sheets), --parts, or the defaults."""
    if args.bom:
        sheets = ([s.strip() for s in args.sheets.split(",") if s.strip()]
                  if args.sheets else None)
        per_sheet = args.per_sheet if args.per_sheet and args.per_sheet > 0 else None
        lines = read_all_sheets(args.bom, sheets=sheets, per_sheet=per_sheet)
        used_sheets = sorted({ln.sheet for ln in lines}, key=lambda s: (len(s), s))
        parts = unique_parts(lines)
        print(f"BOM: {len(lines)} line(s) across {len(used_sheets)} sheet(s) "
              f"({', '.join(used_sheets)}) -> {len(parts)} unique part(s)",
              file=sys.stderr)
        return parts
    if args.parts:
        return [p.strip() for p in args.parts.split(",") if p.strip()]
    return list(DEFAULT_PARTS)


def main(argv=None) -> int:
    args = _parse_args(argv)
    vendors = args.vendors or all_vendor_names()
    parts = _resolve_parts(args)
    if args.limit:
        parts = parts[: args.limit]
    repeat = args.repeat if args.repeat is not None else (1 if args.bom else 3)

    if not parts:
        print("No parts to test.", file=sys.stderr)
        return 2

    total = len(vendors) * len(parts) * repeat
    print(f"Stability test: {len(vendors)} vendor(s) x {len(parts)} part(s) "
          f"x {repeat} = {total} trials (delay {args.delay}s)", file=sys.stderr)
    est_s = total * args.delay
    print(f"  ~{est_s/60:.0f} min minimum from the delay alone "
          f"(two-stage vendors add per-product fetches)\n", file=sys.stderr)

    def factory(vendor: str) -> HttpRecordingFetcher:
        return HttpRecordingFetcher(timeout=args.timeout)

    trials = run_stability(
        vendors=vendors,
        parts=parts,
        fetcher_factory=factory,
        repeat=repeat,
        delay_s=args.delay,
        max_products=args.max_products,
        on_trial=_print_trial,
    )
    summaries = summarize(trials)

    print("\n" + _report(summaries))

    if args.out:
        Path(args.out).write_text(
            json.dumps(_to_json(trials, summaries), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nWrote {args.out}", file=sys.stderr)

    # Exit non-zero if any vendor is fully blocked / unreachable, so CI can gate.
    return 0 if all(s.verdict != "FAIL" for s in summaries.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
