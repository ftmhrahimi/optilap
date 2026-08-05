"""Vendor registry — the single fixed list of MVP scrapers.

The architecture doc pins the MVP to a *fixed* list of ~10 known-good vendors,
each with its own crawler. New vendor crawlers register here; callers look them
up by name (matching Vendors_V1.0.xlsx) rather than importing classes directly.
"""
from __future__ import annotations

from typing import Dict, List, Type

from .base import BaseVendorCrawler
from .vendors.javanelec import JavanElectronicCrawler

# Ordered so the "first 2-3 vendors" of week 1 are obvious.
_CRAWLERS: List[Type[BaseVendorCrawler]] = [
    JavanElectronicCrawler,
    # ECA, MicroModern, ... to be added as their scrapers are written.
]

REGISTRY: Dict[str, Type[BaseVendorCrawler]] = {
    c.vendor_name: c for c in _CRAWLERS
}


def get_crawler(vendor_name: str) -> Type[BaseVendorCrawler]:
    try:
        return REGISTRY[vendor_name]
    except KeyError:
        raise KeyError(
            f"No crawler registered for {vendor_name!r}. "
            f"Available: {', '.join(sorted(REGISTRY))}"
        )


def all_vendor_names() -> List[str]:
    return [c.vendor_name for c in _CRAWLERS]
