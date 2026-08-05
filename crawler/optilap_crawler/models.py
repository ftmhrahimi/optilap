"""Data models exchanged between crawlers and the rest of Optilap.

These are intentionally decoupled from the (future) FastAPI backend and the
PostgreSQL schema. A crawler's only contract is: given a part query, return a
``CrawlResult``. The reference-price-list updater and the scoring engine consume
``ProductOffer`` records from here.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CrawlStatus(str, enum.Enum):
    """Outcome of a single (vendor, part) crawl.

    ``ZERO_RESULTS`` is distinct from ``ERROR`` on purpose: the architecture doc
    requires monitoring that flags a scraper which *consistently* returns zero
    results (a likely sign the site changed its markup or blocked us).
    """

    OK = "ok"
    ZERO_RESULTS = "zero_results"
    ERROR = "error"


class ProductOffer(BaseModel):
    """A single product hit on a vendor's search results page."""

    vendor: str
    part_query: str = Field(..., description="The normalized query that was searched")

    title: Optional[str] = None
    product_url: Optional[str] = None
    image_url: Optional[str] = None

    # Price as shown on the page.
    price_amount: Optional[Decimal] = None
    price_currency: Optional[str] = Field(
        None, description="'IRT' (Toman), 'IRR' (Rial) or None if not detected"
    )
    price_raw: Optional[str] = Field(None, description="Original price text, unparsed")
    # Canonicalized to Rial so offers from different vendors are comparable.
    price_rial: Optional[Decimal] = None

    # Availability as shown on the page.
    in_stock: Optional[bool] = None
    availability_raw: Optional[str] = None

    crawled_at: datetime = Field(default_factory=_utcnow)


class CrawlResult(BaseModel):
    """Everything one (vendor, part) crawl produced, including diagnostics."""

    vendor: str
    part_query: str
    search_url: str
    status: CrawlStatus
    offers: List[ProductOffer] = Field(default_factory=list)

    error: Optional[str] = None
    duration_ms: Optional[int] = None
    crawled_at: datetime = Field(default_factory=_utcnow)

    @property
    def ok(self) -> bool:
        return self.status is CrawlStatus.OK

    def best_offer(self) -> Optional[ProductOffer]:
        """Cheapest in-stock offer (by Rial), falling back to cheapest overall."""
        priced = [o for o in self.offers if o.price_rial is not None]
        if not priced:
            return self.offers[0] if self.offers else None
        in_stock = [o for o in priced if o.in_stock] or priced
        return min(in_stock, key=lambda o: o.price_rial)  # type: ignore[arg-type]
