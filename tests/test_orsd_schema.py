import json
import sqlite3
import pytest


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "enrichment.db"
    path.touch()
    import app.routers.ontology as mod
    monkeypatch.setattr(mod, "_ENRICH_DB", path)
    return path


def test_nfr_table_created(db_path):
    import app.routers.ontology as mod
    mod._init_cq_schema()
    conn = sqlite3.connect(str(db_path))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    conn.close()
    assert "nfr" in tables


def test_nfr_seeded_with_three_defaults(db_path):
    import app.routers.ontology as mod
    mod._init_cq_schema()
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT category FROM nfr ORDER BY id").fetchall()
    conn.close()
    assert [r[0] for r in rows] == ["language", "license", "methodology"]


def test_nfr_seed_is_idempotent(db_path):
    import app.routers.ontology as mod
    mod._init_cq_schema()
    mod._init_cq_schema()
    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM nfr").fetchone()[0]
    conn.close()
    assert count == 3


def test_load_orsd_meta_returns_defaults_when_no_file(tmp_path, monkeypatch):
    import app.routers.ontology as mod
    monkeypatch.setattr(mod, "_ORSD_META_FILE", tmp_path / "orsd_metadata.json")
    meta = mod._load_orsd_meta()
    assert meta["implementation_language"] == "OWL 2 DL"
    assert isinstance(meta["intended_users"], list)
    assert isinstance(meta["intended_uses"], list)
    assert "ontology_name" in meta
    assert "purpose" in meta
    assert "scope" in meta


def test_save_orsd_meta_writes_file(tmp_path, monkeypatch):
    import app.routers.ontology as mod
    meta_file = tmp_path / "orsd_metadata.json"
    monkeypatch.setattr(mod, "_ORSD_META_FILE", meta_file)
    mod._save_orsd_meta({
        "ontology_name": "Test Ontology",
        "purpose": "Test purpose.",
        "scope": "Test scope.",
        "implementation_language": "OWL 2 EL",
        "intended_users": "Engineer, Researcher",
        "intended_uses": "Classification, Reasoning",
    })
    assert meta_file.exists()
    saved = json.loads(meta_file.read_text())
    assert saved["ontology_name"] == "Test Ontology"
    assert saved["intended_users"] == ["Engineer", "Researcher"]
    assert saved["intended_uses"] == ["Classification", "Reasoning"]
    assert saved["implementation_language"] == "OWL 2 EL"
