"""Offline tests for the stability harness.

Two things are validated without any network:
  * ``classify_block`` recognises hostile status codes and challenge bodies and
    passes clean pages through;
  * the ``run_stability`` / ``summarize`` pipeline, driven by a fixture-backed
    fake fetcher, correctly reports the three real vendors as reachable +
    parseable, and reports a 403 fake as fully blocked.

This doubles as the offline *"is the structure parseable?"* check: the saved
fixtures are the known-good page structures, so a green test means the parsers
still turn those structures into offers.
"""
from pathlib import Path
from typing import List

from optilap_crawler.stability import (
    FetchRecord,
    classify_block,
    run_stability,
    summarize,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --- classify_block ---------------------------------------------------------

def test_classify_block_status_codes():
    assert classify_block(403, "whatever") == "http 403"
    assert classify_block(429, "") == "http 429"
    assert classify_block(503, "") == "http 503"


def test_classify_block_challenge_body():
    assert classify_block(200, "<title>Just a moment...</title>") is not None
    assert "recaptcha" in (classify_block(200, "<div class='g-recaptcha'>") or "")
    assert classify_block(200, "لطفا کمی صبر کنید تا مرورگر بررسی شود") is not None


def test_classify_block_clean_page_passes():
    assert classify_block(200, "<html><body>LM358 قیمت</body></html>") is None


# --- fixture-backed fake fetcher --------------------------------------------

class _FixtureFetcher:
    """Serves the saved fixture that matches a vendor's URL and records each
    fetch, mimicking the real HttpRecordingFetcher's ``drain_records`` shape."""

    def __init__(self, vendor: str):
        self.vendor = vendor
        self._records: List[FetchRecord] = []

    def _body_for(self, url: str) -> str:
        if "javanelec" in url:
            return _fixture("javan_search_cards.html")
        if "micmodshop" in url:
            return _fixture("micromodern_next.html")
        if "eca" in url:
            # two-stage: product URLs end in .html, the search URL has ?s=
            if "controller=search" in url or "?s=" in url or "search?" in url:
                return _fixture("eca_search.html")
            return _fixture("eca_product.html")
        return "<html></html>"

    def get_html(self, url: str) -> str:
        body = self._body_for(url)
        self._records.append(
            FetchRecord(url=url, status_code=200, elapsed_ms=5, bytes=len(body),
                        block_reason=classify_block(200, body))
        )
        return body

    def drain_records(self) -> List[FetchRecord]:
        recs = self._records
        self._records = []
        return recs


class _BlockedFetcher:
    """Always returns a 403 challenge page (and raises, like the real one)."""

    def __init__(self, vendor: str):
        self._records: List[FetchRecord] = []

    def get_html(self, url: str) -> str:
        body = "<html><title>Attention Required! | Cloudflare</title></html>"
        reason = classify_block(403, body)
        self._records.append(
            FetchRecord(url=url, status_code=403, elapsed_ms=3, bytes=len(body),
                        block_reason=reason)
        )
        raise RuntimeError(f"blocked: {reason}")

    def drain_records(self) -> List[FetchRecord]:
        recs = self._records
        self._records = []
        return recs


def test_run_stability_all_vendors_parseable():
    vendors = ["JavanElectronic", "ECA", "MicroModern"]
    trials = run_stability(
        vendors=vendors,
        parts=["LM358"],
        fetcher_factory=_FixtureFetcher,
        repeat=2,
        delay_s=0,          # no real waiting in tests
    )
    summaries = summarize(trials)

    for vendor in vendors:
        s = summaries[vendor]
        assert s.trials == 2
        assert s.blocked == 0, f"{vendor} should not look blocked on a clean fixture"
        assert s.ok == 2, f"{vendor} should parse offers from its fixture every trial"
        assert s.parse_ok_rate == 1
        assert s.verdict == "PASS"


def test_run_stability_detects_blocking():
    trials = run_stability(
        vendors=["ECA"],
        parts=["LM358"],
        fetcher_factory=_BlockedFetcher,
        repeat=3,
        delay_s=0,
    )
    s = summarize(trials)["ECA"]
    assert s.blocked == 3
    assert s.block_rate == 1.0
    assert s.verdict == "FAIL"
    assert "blocked" in s.note.lower()
