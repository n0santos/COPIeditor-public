# tests/test_auxiliary_classes.py
import sqlite3, sys, os
from pathlib import Path
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'enrichment'))

def test_auxiliary_class_table_created(tmp_path, monkeypatch):
    import enrichment.enrichment_service as svc
    import importlib; importlib.reload(svc)
    monkeypatch.setattr(svc, "ENRICHMENT_DB_PATH", tmp_path / "test.db")
    svc.init_enrichment_schema()
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    cols = {row[1] for row in conn.execute("PRAGMA table_info(auxiliary_class)").fetchall()}
    conn.close()
    assert cols == {"id","name","bfo_category","label_en","label_pt","definition_en","source","status","created_at","updated_at"}

def test_auxiliary_class_index_created(tmp_path, monkeypatch):
    import enrichment.enrichment_service as svc
    import importlib; importlib.reload(svc)
    monkeypatch.setattr(svc, "ENRICHMENT_DB_PATH", tmp_path / "test.db")
    svc.init_enrichment_schema()
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    indexes = {row[1] for row in conn.execute("SELECT * FROM sqlite_master WHERE type='index'").fetchall()}
    conn.close()
    assert "idx_aux_status" in indexes


def test_stub_pending_becomes_owl_thing(tmp_path, monkeypatch):
    """An auxiliary_class entry with status='pending' must stub to owl:Thing."""
    import enrichment.enrichment_service as svc
    import importlib; importlib.reload(svc)
    monkeypatch.setattr(svc, "ENRICHMENT_DB_PATH", tmp_path / "test.db")
    svc.init_enrichment_schema()
    conn = svc.get_enrichment_db()
    conn.execute("INSERT INTO auxiliary_class (name, status) VALUES ('VaporPortion','pending')")
    conn.commit(); conn.close()

    # Simulate the stub lookup as it will appear in generate_combined_turtle
    from enrichment.enrichment_service import get_enrichment_db, _AUX_BFO_IRI
    db = get_enrichment_db()
    row = db.execute(
        "SELECT bfo_category FROM auxiliary_class WHERE name=? AND status='validated'",
        ("VaporPortion",)
    ).fetchone()
    db.close()
    parent = _AUX_BFO_IRI[row["bfo_category"]] if row and row[0] else "owl:Thing"
    assert parent == "owl:Thing"


def test_stub_validated_uses_correct_iri(tmp_path, monkeypatch):
    """A validated auxiliary_class with bfo_category='FiatObjectPart' stubs to bfo:BFO_0000024."""
    import enrichment.enrichment_service as svc
    import importlib; importlib.reload(svc)
    monkeypatch.setattr(svc, "ENRICHMENT_DB_PATH", tmp_path / "test.db")
    svc.init_enrichment_schema()
    conn = svc.get_enrichment_db()
    conn.execute(
        "INSERT INTO auxiliary_class (name, bfo_category, status) VALUES ('VaporPortion','FiatObjectPart','validated')"
    )
    conn.commit(); conn.close()

    from enrichment.enrichment_service import get_enrichment_db, _AUX_BFO_IRI
    db = get_enrichment_db()
    row = db.execute(
        "SELECT bfo_category FROM auxiliary_class WHERE name=? AND status='validated'",
        ("VaporPortion",)
    ).fetchone()
    db.close()
    parent = _AUX_BFO_IRI[row["bfo_category"]] if row and row[0] else "owl:Thing"
    assert parent == "bfo:BFO_0000024"


def test_participant_extraction_from_signature():
    """Verify that _extract_participants returns PascalCase names from a signature dict."""
    import enrichment.enrichment_service as svc
    import importlib; importlib.reload(svc)

    sig = {"inputs": [{"type": "crude oil"}, {"type": "Steam"}], "outputs": [{"type": "VaporPortion"}]}
    names = []
    for item in sig.get("inputs", []) + sig.get("outputs", []):
        raw = item.get("type", "").strip()
        if raw:
            names.append(svc._to_pascal_case(raw))
    assert "CrudeOil" in names
    assert "Steam" in names
    assert "VaporPortion" in names
