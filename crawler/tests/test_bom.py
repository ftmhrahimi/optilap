"""Tests for BOM reading against the real sample workbook when available."""
from pathlib import Path

import pytest

from optilap_crawler.bom import read_bom, unique_parts

# The sample BOM lives outside the repo (attached to the task). Tests that need
# it are skipped when it isn't present so CI stays green.
SAMPLE = Path(__file__).resolve().parent.parent / "fixtures" / "bom_sample.xlsx"


@pytest.mark.skipif(not SAMPLE.exists(), reason="bom_sample.xlsx not present")
def test_read_sample_bom():
    lines = read_bom(str(SAMPLE))
    assert lines, "expected at least one BOM line"
    parts = {l.raw_part for l in lines}
    assert "LM358DR" in parts or "ATMEGA16A-AU" in parts
    # Quantities parse as numbers.
    assert any(l.quantity is not None for l in lines)


@pytest.mark.skipif(not SAMPLE.exists(), reason="bom_sample.xlsx not present")
def test_unique_parts_dedupes():
    lines = read_bom(str(SAMPLE))
    uniq = unique_parts(lines)
    assert len(uniq) == len(set(uniq))
    assert len(uniq) <= len(lines)
