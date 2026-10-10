# tests/test_excluded_definitions.py
"""
Source definitions in the generated class Turtle.

1. `excluded_definition_ids` lets a reviewer drop a terms.db definition from a
   cluster -- typically a homonym (ISO 15926-4 DRUM is a shipping container, not
   the POSC Caesar process drum) or a corrupted source text. The docs page
   honoured it, but generate_turtle() called get_cluster_definitions()
   unfiltered, so the excluded definition still reached the class TTL. Both call
   sites now go through _filter_excluded_definitions().

2. Every source standard is copyrighted (COPYRIGHTED_SOURCES), so the class TTL
   must not reproduce definition text. It cites each source by linking to it
   (dcterms:source <source_uri>) instead of copying `skos:definition "[Src] ..."`.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "enrichment"))


def _svc():
    import enrichment.enrichment_service as svc
    return svc


DEFS = [
    {"id": 9889, "source": "iso15926", "definition": "shipping container"},
    {"id": 28833, "source": "posc_caesar", "definition": "process drum"},
]


def test_filter_accepts_json_string_form():
    """The shape stored in the DB column."""
    assert _svc()._filter_excluded_definitions(DEFS, "[9889]") == [DEFS[1]]


def test_filter_accepts_parsed_list_form():
    assert _svc()._filter_excluded_definitions(DEFS, [9889]) == [DEFS[1]]


def test_filter_empty_and_null_keep_everything():
    for excluded in (None, "", "[]", []):
        assert _svc()._filter_excluded_definitions(DEFS, excluded) == DEFS


def test_filter_never_raises_on_malformed_input():
    """A bad exclusion value must not cost the class its source definitions."""
    for excluded in ("not json", "{}", 42):
        assert _svc()._filter_excluded_definitions(DEFS, excluded) == DEFS


def test_source_link_escapes_characters_illegal_in_turtle_iris():
    link = _svc()._source_link_ttl("https://example.org/item/A B<C>")
    assert link == "<https://example.org/item/A%20B%3CC%3E>"


def test_source_link_skips_missing_uri():
    assert _svc()._source_link_ttl("") is None
    assert _svc()._source_link_ttl(None) is None


def _row_with_exclusions():
    svc = _svc()
    conn = svc.get_enrichment_db()
    row = conn.execute(
        "SELECT id, excluded_definition_ids FROM enrichment "
        "WHERE excluded_definition_ids IS NOT NULL "
        "AND excluded_definition_ids NOT IN ('', '[]') LIMIT 1"
    ).fetchone()
    conn.close()
    if row is None:
        pytest.skip("no enrichment row with exclusions in this database")
    return row


def test_generate_turtle_links_sources_without_copying_text(monkeypatch):
    svc = _svc()
    row = _row_with_exclusions()
    excluded_id = json.loads(row["excluded_definition_ids"])[0]
    fake_defs = [
        {"id": excluded_id, "source": "iso15926", "definition": "EXCLUDED-SENTINEL text",
         "source_uri": "https://example.org/excluded-sentinel"},
        {"id": -1, "source": "posc_caesar", "definition": "KEPT-SENTINEL text",
         "source_uri": "https://example.org/kept-sentinel"},
        {"id": -2, "source": "cfihos", "definition": "DUPLICATE-SENTINEL text",
         "source_uri": "https://example.org/kept-sentinel"},
    ]
    monkeypatch.setattr(svc, "get_cluster_definitions", lambda label: list(fake_defs))

    ttl = svc.generate_turtle(row["id"])
    assert ttl.count("dcterms:source <https://example.org/kept-sentinel>") == 1
    assert "excluded-sentinel" not in ttl
    for text in ("EXCLUDED-SENTINEL", "KEPT-SENTINEL", "DUPLICATE-SENTINEL"):
        assert text not in ttl
    assert not any(pfx in ttl for pfx in svc.PUBLIC_STRIP_PREFIXES)
