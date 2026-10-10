import json
import sqlite3
import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "enrichment.db"
    path.touch()
    import app.routers.ontology as mod
    monkeypatch.setattr(mod, "_ENRICH_DB", path)
    mod._init_cq_schema()
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def test_insert_nfr(db):
    db.execute("INSERT INTO nfr (category, text) VALUES (?,?)",
               ("language", "Must use OWL 2 DL."))
    db.commit()
    row = db.execute(
        "SELECT * FROM nfr WHERE category='language' AND text LIKE '%OWL 2 DL%'"
    ).fetchone()
    assert row is not None


def test_update_nfr_text(db):
    db.execute("INSERT INTO nfr (category, text) VALUES (?,?)", ("license", "MIT"))
    nfr_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()
    db.execute("UPDATE nfr SET text=? WHERE id=?", ("Apache 2.0", nfr_id))
    db.commit()
    row = db.execute("SELECT * FROM nfr WHERE id=?", (nfr_id,)).fetchone()
    assert row["text"] == "Apache 2.0"


def test_update_nfr_category(db):
    db.execute("INSERT INTO nfr (category, text) VALUES (?,?)", ("language", "OWL"))
    nfr_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()
    db.execute("UPDATE nfr SET category=? WHERE id=?", ("modelling", nfr_id))
    db.commit()
    row = db.execute("SELECT * FROM nfr WHERE id=?", (nfr_id,)).fetchone()
    assert row["category"] == "modelling"


def test_delete_nfr(db):
    db.execute("INSERT INTO nfr (category, text) VALUES (?,?)", ("methodology", "LOT"))
    nfr_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()
    db.execute("DELETE FROM nfr WHERE id=?", (nfr_id,))
    db.commit()
    row = db.execute("SELECT * FROM nfr WHERE id=?", (nfr_id,)).fetchone()
    assert row is None


def test_seeded_nfrs_present_after_init(db):
    rows = db.execute("SELECT category FROM nfr ORDER BY id").fetchall()
    categories = [r["category"] for r in rows]
    assert "language" in categories
    assert "license" in categories
    assert "methodology" in categories
