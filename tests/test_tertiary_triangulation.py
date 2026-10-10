# tests/test_tertiary_triangulation.py
"""
Unit tests for validate_tertiary_triangulation(): a tertiary-tier source
entry in source_definitions_used may only back an axiom once corroborated
by a second, independent tertiary source (manufacturer/patent/web glossary).
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "enrichment"))


def _vt(source_defs):
    import importlib
    import enrichment.enrichment_service as svc
    importlib.reload(svc)
    source_defs_json = json.dumps(source_defs) if source_defs is not None else None
    return svc.validate_tertiary_triangulation(source_defs_json)


def test_no_source_defs_passes():
    """No source_definitions_used at all requires no triangulation."""
    assert _vt(None) is None


def test_no_tertiary_entries_passes():
    """Primary/secondary-only entries never trigger the triangulation gate."""
    entries = [
        {"tier": "primary", "source": "iso15926", "term": "QUICK CONNECTOR"},
        {"tier": "secondary", "source_type": "standard", "source": "ISO 7241",
         "url": "https://www.iso.org/standard/54886.html", "quote": "..."},
    ]
    assert _vt(entries) is None


def test_single_tertiary_entry_fails():
    """One tertiary source alone is not triangulated."""
    entries = [
        {"tier": "tertiary", "source_type": "manufacturer_page", "source": "Swagelok",
         "url": "https://products.swagelok.com/en/all-products/valves/quick-connects",
         "quote": "push-to-connect"},
    ]
    err = _vt(entries)
    assert err is not None
    assert "tertiary" in err.lower()


def test_two_tertiary_entries_same_domain_fails():
    """Two tertiary entries from the same domain are not independent."""
    entries = [
        {"tier": "tertiary", "source_type": "manufacturer_page", "source": "Swagelok page 1",
         "url": "https://products.swagelok.com/en/page-1", "quote": "a"},
        {"tier": "tertiary", "source_type": "manufacturer_page", "source": "Swagelok page 2",
         "url": "https://products.swagelok.com/en/page-2", "quote": "b"},
    ]
    err = _vt(entries)
    assert err is not None


def test_two_tertiary_entries_different_domains_passes():
    """Two tertiary entries from different manufacturer domains triangulate."""
    entries = [
        {"tier": "tertiary", "source_type": "manufacturer_page", "source": "Swagelok",
         "url": "https://products.swagelok.com/en/quick-connects", "quote": "a"},
        {"tier": "tertiary", "source_type": "manufacturer_page", "source": "John Guest",
         "url": "https://www.johnguest.com/speedfit", "quote": "b"},
    ]
    assert _vt(entries) is None


def test_two_different_patents_same_hosting_domain_passes():
    """
    Two distinct patents both hosted on patents.google.com must count as
    independent — the independence key for patents is the patent number,
    not the hosting domain (a plain domain check would wrongly collide them).
    """
    entries = [
        {"tier": "tertiary", "source_type": "patent", "source": "US4526689A",
         "url": "https://patents.google.com/patent/US4526689A/en", "quote": "a"},
        {"tier": "tertiary", "source_type": "patent", "source": "US9527018B2",
         "url": "https://patents.google.com/patent/US9527018B2/en", "quote": "b"},
    ]
    assert _vt(entries) is None


def test_same_patent_cited_twice_fails():
    """Citing the same patent number twice is not triangulation."""
    entries = [
        {"tier": "tertiary", "source_type": "patent", "source": "US4526689A",
         "url": "https://patents.google.com/patent/US4526689A/en", "quote": "a"},
        {"tier": "tertiary", "source_type": "patent", "source": "US4526689A",
         "url": "https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/4526689",
         "quote": "b"},
    ]
    err = _vt(entries)
    assert err is not None


def test_patent_and_manufacturer_are_independent():
    """A patent and a manufacturer page count as two independent tertiary sources."""
    entries = [
        {"tier": "tertiary", "source_type": "patent", "source": "US4526689A",
         "url": "https://patents.google.com/patent/US4526689A/en", "quote": "a"},
        {"tier": "tertiary", "source_type": "manufacturer_page", "source": "Meissner",
         "url": "https://www.meissner.com/products/sanitary-inline-filter-housing",
         "quote": "b"},
    ]
    assert _vt(entries) is None


def test_invalid_json_passes():
    """Malformed source_definitions_used cannot be checked structurally — don't block."""
    import importlib
    import enrichment.enrichment_service as svc
    importlib.reload(svc)
    assert svc.validate_tertiary_triangulation("not valid json") is None
