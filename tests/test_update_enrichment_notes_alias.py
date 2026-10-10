"""
update_enrichment() accepts "cross_standard_notes" (the key the LLM response
uses) but the table has no such column: the insert path stores the value in
cross_standard_links.  An update with that key used to crash with
"no such column: cross_standard_notes".  It must now land in
cross_standard_links, serialized the same way the insert path does.
"""

import sys
import json
import importlib
from pathlib import Path

import pytest

_ENRICHMENT_DIR = str(Path(__file__).parent.parent / "enrichment")
if _ENRICHMENT_DIR not in sys.path:
    sys.path.insert(0, _ENRICHMENT_DIR)


def _svc_with_row(tmp_path, monkeypatch, label: str):
    import enrichment_service as svc
    importlib.reload(svc)
    monkeypatch.setattr(svc, "ENRICHMENT_DB_PATH", tmp_path / "enr.db")
    svc.init_enrichment_schema()
    conn = svc.get_enrichment_db()
    conn.execute(
        "INSERT INTO enrichment (cluster_label, created_at, updated_at, cross_standard_links) "
        "VALUES (?, datetime('now'), datetime('now'), ?)",
        (label, json.dumps("old note")),
    )
    conn.commit()
    row_id = conn.execute("SELECT id FROM enrichment WHERE cluster_label = ?", (label,)).fetchone()["id"]
    conn.close()
    return svc, row_id


def _links(svc, row_id):
    conn = svc.get_enrichment_db()
    value = conn.execute("SELECT cross_standard_links FROM enrichment WHERE id = ?", (row_id,)).fetchone()[0]
    conn.close()
    return value


def test_cross_standard_notes_is_stored_in_cross_standard_links(tmp_path, monkeypatch):
    svc, row_id = _svc_with_row(tmp_path, monkeypatch, "notes alias a")
    svc.update_enrichment(row_id, {"cross_standard_notes": "new note"})
    assert json.loads(_links(svc, row_id)) == "new note"


def test_cross_standard_notes_and_links_together_are_rejected(tmp_path, monkeypatch):
    svc, row_id = _svc_with_row(tmp_path, monkeypatch, "notes alias b")
    with pytest.raises(ValueError, match="cross_standard_notes"):
        svc.update_enrichment(row_id, {"cross_standard_notes": "a", "cross_standard_links": ["b"]})
    assert json.loads(_links(svc, row_id)) == "old note"


def test_cross_standard_links_still_updates_directly(tmp_path, monkeypatch):
    svc, row_id = _svc_with_row(tmp_path, monkeypatch, "notes alias c")
    svc.update_enrichment(row_id, {"cross_standard_links": ["x"]})
    assert json.loads(_links(svc, row_id)) == ["x"]
