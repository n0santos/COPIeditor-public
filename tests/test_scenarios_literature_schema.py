import sqlite3
import pytest


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "enrichment.db"
    path.touch()
    import app.routers.ontology as mod
    monkeypatch.setattr(mod, "_ENRICH_DB", path)
    return path


def test_scenarios_table_created(db_path, monkeypatch):
    import app.routers.ontology as mod
    mod._init_cq_schema()
    conn = sqlite3.connect(str(db_path))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    conn.close()
    assert "scenarios" in tables


def test_literature_table_created(db_path, monkeypatch):
    import app.routers.ontology as mod
    mod._init_cq_schema()
    conn = sqlite3.connect(str(db_path))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    conn.close()
    assert "literature" in tables


def test_scenario_id_column_added(db_path, monkeypatch):
    import app.routers.ontology as mod
    mod._init_cq_schema()
    conn = sqlite3.connect(str(db_path))
    cols = {r[1] for r in conn.execute(
        "PRAGMA table_info(competency_questions)"
    ).fetchall()}
    conn.close()
    assert "scenario_id" in cols


def test_init_idempotent(db_path, monkeypatch):
    import app.routers.ontology as mod
    mod._init_cq_schema()
    mod._init_cq_schema()  # must not raise
