"""Read part identifiers out of a customer BOM (Excel).

The sample BOM (bom_sample.xlsx) has columns:
    PartNumber/MPN/Comment | Package/Footprint | Quantity

For the crawler we only need the part identifier + quantity; header names vary
between customers, so we match columns loosely.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from openpyxl import load_workbook

from .normalize import normalize_part_query

# Substrings we accept (case-insensitive) when locating each column.
_PART_HEADER_HINTS = ("part", "mpn", "comment", "قطعه", "کالا")
_QTY_HEADER_HINTS = ("qty", "quantity", "تعداد")
_PKG_HEADER_HINTS = ("package", "footprint", "بسته")


@dataclass
class BomLine:
    part: str            # normalized query string
    raw_part: str        # exactly as written in the sheet
    quantity: Optional[float] = None
    package: Optional[str] = None
    row: int = 0


def _find_col(headers: List[str], hints) -> Optional[int]:
    for idx, h in enumerate(headers):
        low = (h or "").strip().lower()
        if any(hint in low for hint in hints):
            return idx
    return None


def read_bom(path: str, sheet: Optional[str] = None) -> List[BomLine]:
    """Parse a BOM workbook into ``BomLine`` records (blank part rows skipped)."""
    wb = load_workbook(path, data_only=True, read_only=True)
    ws = wb[sheet] if sheet else wb.worksheets[0]

    rows = ws.iter_rows(values_only=True)
    try:
        header = [str(c) if c is not None else "" for c in next(rows)]
    except StopIteration:
        return []

    part_col = _find_col(header, _PART_HEADER_HINTS)
    if part_col is None:
        part_col = 0  # fall back to the first column
    qty_col = _find_col(header, _QTY_HEADER_HINTS)
    pkg_col = _find_col(header, _PKG_HEADER_HINTS)

    lines: List[BomLine] = []
    for i, row in enumerate(rows, start=2):  # row 1 was the header
        raw = row[part_col] if part_col < len(row) else None
        if raw is None or str(raw).strip() == "":
            continue
        raw_part = str(raw).strip()
        quantity = None
        if qty_col is not None and qty_col < len(row) and row[qty_col] is not None:
            try:
                quantity = float(row[qty_col])
            except (TypeError, ValueError):
                quantity = None
        package = None
        if pkg_col is not None and pkg_col < len(row) and row[pkg_col] is not None:
            package = str(row[pkg_col]).strip()

        lines.append(
            BomLine(
                part=normalize_part_query(raw_part),
                raw_part=raw_part,
                quantity=quantity,
                package=package,
                row=i,
            )
        )
    wb.close()
    return lines


def unique_parts(lines: List[BomLine]) -> List[str]:
    """Distinct, order-preserving list of part queries to crawl."""
    seen: set[str] = set()
    out: List[str] = []
    for line in lines:
        if line.part and line.part not in seen:
            seen.add(line.part)
            out.append(line.part)
    return out
