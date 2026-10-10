# tests/test_secondary_coverage.py
"""
Unit tests for compute_secondary_coverage(): a deterministic function, not an
agent judgment call, so the field stays comparable across runs. Rule: "full"
requires at least one tier='secondary' entry with citation_mode='verbatim'
whose categories_covered (unioned across all secondary entries) spans at
least 4 of the 7 differential categories; any secondary entry at all but not
meeting that bar is "partial"; no secondary entry is "none".
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "enrichment"))


def _cov(entries):
    import importlib
    import enrichment.enrichment_service as svc
    importlib.reload(svc)
    return svc.compute_secondary_coverage(json.dumps(entries) if entries is not None else None)


def test_none_source_defs_returns_none():
    assert _cov(None) == "none"


def test_empty_list_returns_none():
    assert _cov([]) == "none"


def test_only_primary_entry_returns_none():
    entries = [{"tier": "primary", "source": "iso15926", "term": "X"}]
    assert _cov(entries) == "none"


def test_secondary_entry_no_categories_returns_partial():
    entries = [
        {"tier": "primary", "source": "iso15926", "term": "X"},
        {"tier": "secondary", "source_type": "standard", "citation_mode": "verbatim",
         "source": "ISO 1234", "quote": "..."},
    ]
    assert _cov(entries) == "partial"


def test_secondary_summary_mode_with_many_categories_is_still_partial():
    """citation_mode='summary' never counts as full, regardless of category breadth."""
    entries = [
        {"tier": "secondary", "source_type": "standard", "citation_mode": "summary",
         "source": "ISO 1234", "quote": "...",
         "categories_covered": ["structure", "profile", "mechanism", "function", "parameter"]},
    ]
    assert _cov(entries) == "partial"


def test_secondary_verbatim_with_four_categories_is_full():
    entries = [
        {"tier": "secondary", "source_type": "standard", "citation_mode": "verbatim",
         "source": "ISO 1234", "quote": "...",
         "categories_covered": ["structure", "profile", "mechanism", "function"]},
    ]
    assert _cov(entries) == "full"


def test_secondary_verbatim_with_two_categories_is_partial():
    entries = [
        {"tier": "secondary", "source_type": "standard", "citation_mode": "verbatim",
         "source": "ISO 1234", "quote": "...",
         "categories_covered": ["structure", "profile"]},
    ]
    assert _cov(entries) == "partial"


def test_categories_union_across_multiple_secondary_entries_reaches_full():
    """
    Two thin secondary entries whose categories don't overlap can jointly
    cross the threshold -- coverage is measured across all secondary
    evidence for the term, not per-entry.
    """
    entries = [
        {"tier": "secondary", "source_type": "standard", "citation_mode": "verbatim",
         "source": "ISO 1234", "quote": "...",
         "categories_covered": ["structure", "profile"]},
        {"tier": "secondary", "source_type": "curated_dictionary", "citation_mode": "verbatim",
         "source": "NFOGM Handbook", "quote": "...",
         "categories_covered": ["mechanism", "function"]},
    ]
    assert _cov(entries) == "full"


def test_tertiary_entries_do_not_count_toward_secondary_coverage():
    entries = [
        {"tier": "tertiary", "source_type": "manufacturer_page", "citation_mode": "verbatim",
         "source": "Acme Corp", "quote": "...",
         "categories_covered": ["structure", "profile", "mechanism", "function"]},
    ]
    assert _cov(entries) == "none"


def test_invalid_json_returns_none():
    import importlib
    import enrichment.enrichment_service as svc
    importlib.reload(svc)
    assert svc.compute_secondary_coverage("not valid json") == "none"
