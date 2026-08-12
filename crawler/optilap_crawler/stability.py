"""Stability testing for the initial vendor crawlers (roadmap week 1 task
*"تست پایداری Crawlerهای اولیه"*).

It answers the two concrete questions the task asks:

1. **Do the sites block us?** — every HTTP response is inspected for a block
   signal: a hostile status code (403/429/503/…) or a challenge/anti-bot body
   (Cloudflare "Just a moment", ArvanCloud, reCAPTCHA, "Access Denied", the
   common Persian "چند لحظه صبر کنید" wait pages).
2. **Is the structure parseable?** — the *real* vendor parser runs on the
   fetched HTML; a trial counts as parseable only when the crawler turns the
   page into at least one :class:`ProductOffer`.

Each ``(vendor, part)`` is probed several times (``repeat``) with a polite delay
so the test also reveals *intermittent* blocking / rate-limiting rather than a
single lucky or unlucky hit.

This module is pure orchestration + classification (no network of its own): the
caller injects a fetcher factory, so the CLI wires in a real recording HTTP
fetcher while the tests inject a fixture-backed fake. That is why the whole
thing is unit-testable offline even though its purpose is a live network probe.
"""
from __future__ import annotations

import re
import statistics
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

from .models import CrawlStatus
from .registry import get_crawler

# --- block detection --------------------------------------------------------

#: HTTP status codes that, on their own, mean the site refused to serve us.
BLOCK_STATUS: frozenset = frozenset({401, 403, 406, 407, 429, 451, 503})

#: Case-insensitive markers of an anti-bot / challenge / rate-limit interstitial
#: served with a 200 body (so the status code alone would miss it).
_BLOCK_BODY_MARKERS: tuple = (
    "just a moment",                 # Cloudflare JS challenge
    "attention required",            # Cloudflare block
    "cf-browser-verification",
    "cf-chl-",                       # Cloudflare challenge assets
    "arvancloud",                    # common Iranian CDN challenge
    "ar-captcha",
    "g-recaptcha",
    "recaptcha",
    "hcaptcha",
    "please enable javascript and cookies",
    "access denied",
    "you have been blocked",
    "ددوس",                          # anti-DDoS
    "چند لحظه صبر",                  # "wait a moment" interstitial
    "لطفا کمی صبر کنید",
    "در حال بررسی مرورگر",           # "checking your browser"
    "دسترسی شما مسدود",              # "your access is blocked"
)


def classify_block(status_code: Optional[int], body: str) -> Optional[str]:
    """Return a human-readable reason if this response looks like a block, else
    ``None``. Checks the status code first, then the (truncated) body text."""
    if status_code is not None and status_code in BLOCK_STATUS:
        return f"http {status_code}"
    if body:
        head = body[:20000].lower()
        for marker in _BLOCK_BODY_MARKERS:
            if marker in head:
                return f"challenge page ({marker!r})"
    return None


# --- records ----------------------------------------------------------------


@dataclass
class FetchRecord:
    """One HTTP GET performed during a trial."""

    url: str
    status_code: Optional[int]
    elapsed_ms: int
    bytes: int
    block_reason: Optional[str] = None
    error: Optional[str] = None

    @property
    def blocked(self) -> bool:
        return self.block_reason is not None


class RecordingFetcher:
    """Fetcher protocol (``drain_records``) — implemented by the CLI's HTTP
    fetcher and by the test fake. Kept here only as documentation of the shape
    :func:`run_stability` relies on."""

    def get_html(self, url: str) -> str:  # pragma: no cover - interface only
        raise NotImplementedError

    def drain_records(self) -> List[FetchRecord]:  # pragma: no cover
        raise NotImplementedError


@dataclass
class TrialResult:
    vendor: str
    part: str
    trial: int
    crawl_status: str
    offers: int
    duration_ms: Optional[int]
    fetches: List[FetchRecord] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def blocked(self) -> bool:
        return any(f.blocked for f in self.fetches)

    @property
    def block_reason(self) -> Optional[str]:
        for f in self.fetches:
            if f.block_reason:
                return f.block_reason
        return None

    @property
    def parseable(self) -> bool:
        """Structure was successfully parsed into at least one offer."""
        return self.crawl_status == CrawlStatus.OK.value and self.offers > 0


@dataclass
class VendorSummary:
    vendor: str
    trials: int = 0
    ok: int = 0
    zero: int = 0
    error: int = 0
    blocked: int = 0
    offers_total: int = 0
    block_reasons: List[str] = field(default_factory=list)
    latencies_ms: List[int] = field(default_factory=list)

    # -- rates ---------------------------------------------------------------
    @property
    def reachable(self) -> bool:
        """We got *some* usable (non-blocked, non-error) response at least once."""
        return (self.ok + self.zero) > 0

    @property
    def parse_ok_rate(self) -> Optional[float]:
        """Fraction of reachable, non-blocked trials that produced offers.

        This is a **hit rate**, not a health score: a real BOM contains many
        exact MPNs a given shop simply doesn't stock, so a value below 100% is
        normal and does *not* by itself mean the parser/structure is broken.
        Only an all-zero hit rate is treated as a (soft) warning below.
        """
        usable = self.ok + self.zero
        return (self.ok / usable) if usable else None

    @property
    def block_rate(self) -> float:
        return (self.blocked / self.trials) if self.trials else 0.0

    def _lat(self, fn) -> Optional[int]:
        return int(fn(self.latencies_ms)) if self.latencies_ms else None

    @property
    def latency_avg_ms(self) -> Optional[int]:
        return self._lat(statistics.mean)

    @property
    def latency_median_ms(self) -> Optional[int]:
        return self._lat(statistics.median)

    @property
    def latency_max_ms(self) -> Optional[int]:
        return self._lat(max)

    # -- verdict -------------------------------------------------------------
    @property
    def verdict(self) -> str:
        """PASS / WARN / FAIL summarizing this vendor's stability."""
        if self.trials == 0:
            return "FAIL"
        if self.blocked == self.trials:
            return "FAIL"          # always blocked
        if self.error == self.trials:
            return "FAIL"          # never reachable
        if self.blocked or self.error:
            return "WARN"          # intermittent blocking / errors
        if self.parse_ok_rate == 0:
            return "WARN"          # reachable but nothing parsed on ANY part
        # A partial hit rate (some parts absent from this shop) is expected on a
        # real BOM and is NOT penalised — stability is about reachability +
        # blocking + a working parser, not catalogue coverage.
        return "PASS"

    @property
    def note(self) -> str:
        if self.trials == 0:
            return "no trials run"
        if self.blocked == self.trials:
            reason = self.block_reasons[0] if self.block_reasons else "blocked"
            return f"blocked on every request ({reason})"
        if self.error == self.trials:
            return "unreachable / all requests errored"
        bits = []
        if self.blocked:
            reason = self.block_reasons[0] if self.block_reasons else "blocked"
            bits.append(f"intermittent blocking ({self.blocked}/{self.trials}, e.g. {reason})")
        if self.error and self.error != self.trials:
            bits.append(f"{self.error}/{self.trials} errored")
        usable = self.ok + self.zero
        if self.parse_ok_rate == 0:
            bits.append("reachable but 0 offers parsed on any part — check selectors "
                        "or that the parts are searchable at this shop")
        elif usable:
            rate = (self.parse_ok_rate or 0) * 100
            bits.append(f"reachable & unblocked; offers found on {self.ok}/{usable} "
                        f"searches ({rate:.0f}% hit rate)")
        if not bits:
            bits.append("stable: reachable, unblocked, structure parsed on every trial")
        return "; ".join(bits)


# --- default probe parts ----------------------------------------------------

#: Common, widely-stocked MPNs — chosen so a *zero* result is more likely to be
#: a real parse/structure problem than "this shop just doesn't carry the part".
DEFAULT_PARTS: tuple = ("LM358", "NE555", "ATMEGA328")


# --- runner -----------------------------------------------------------------


def run_stability(
    vendors: Sequence[str],
    parts: Sequence[str],
    fetcher_factory: Callable[[str], "RecordingFetcher"],
    repeat: int = 3,
    delay_s: float = 1.0,
    max_products: int = 5,
    on_trial: Optional[Callable[[TrialResult], None]] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> List[TrialResult]:
    """Probe every ``(vendor, part)`` ``repeat`` times and return raw trials.

    ``fetcher_factory(vendor)`` must return an object with ``get_html(url)`` and
    ``drain_records() -> List[FetchRecord]``. A fresh fetcher is created per
    vendor so one vendor's session/cookies never mask another's blocking.
    """
    from .base import CrawlerConfig  # local import to avoid a cycle at import time

    config = CrawlerConfig(max_products=max_products, max_retries=1)
    trials: List[TrialResult] = []

    for vendor in vendors:
        crawler = get_crawler(vendor)(config)
        fetcher = fetcher_factory(vendor)
        try:
            fetcher.drain_records()  # discard anything from construction
            first = True
            for part in parts:
                for t in range(1, repeat + 1):
                    if not first and delay_s:
                        sleep(delay_s)
                    first = False
                    result = crawler.crawl(part, fetcher)
                    records = fetcher.drain_records()
                    tr = TrialResult(
                        vendor=vendor,
                        part=part,
                        trial=t,
                        crawl_status=result.status.value,
                        offers=len(result.offers),
                        duration_ms=result.duration_ms,
                        fetches=records,
                        error=result.error,
                    )
                    trials.append(tr)
                    if on_trial is not None:
                        on_trial(tr)
        finally:
            close = getattr(fetcher, "close", None)
            if callable(close):
                close()
    return trials


def summarize(trials: Sequence[TrialResult]) -> Dict[str, VendorSummary]:
    """Aggregate raw trials into a per-vendor :class:`VendorSummary`."""
    out: Dict[str, VendorSummary] = {}
    for tr in trials:
        s = out.setdefault(tr.vendor, VendorSummary(vendor=tr.vendor))
        s.trials += 1
        s.offers_total += tr.offers
        if tr.blocked:
            s.blocked += 1
            if tr.block_reason:
                s.block_reasons.append(tr.block_reason)
        if tr.crawl_status == CrawlStatus.OK.value:
            s.ok += 1
        elif tr.crawl_status == CrawlStatus.ZERO_RESULTS.value:
            s.zero += 1
        else:
            s.error += 1
        for f in tr.fetches:
            if f.status_code == 200 and not f.blocked:
                s.latencies_ms.append(f.elapsed_ms)
    return out
