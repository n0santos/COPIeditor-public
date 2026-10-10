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


def test_insert_scenario(db):
    db.execute(
        "INSERT INTO scenarios (title, narrative, actors, status) VALUES (?,?,?,?)",
        ("Identify pump type", "An engineer needs to determine pump subtype.",
         json.dumps(["Process engineer"]), "active"),
    )
    db.commit()
    row = db.execute("SELECT * FROM scenarios WHERE title=?", ("Identify pump type",)).fetchone()
    assert row is not None
    assert row["status"] == "active"
    assert json.loads(row["actors"]) == ["Process engineer"]


def test_update_scenario(db):
    db.execute(
        "INSERT INTO scenarios (title, narrative) VALUES (?,?)",
        ("Draft", "Narrative"),
    )
    sc_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()

    db.execute("UPDATE scenarios SET title=?, status=? WHERE id=?",
               ("Updated", "active", sc_id))
    db.commit()

    row = db.execute("SELECT * FROM scenarios WHERE id=?", (sc_id,)).fetchone()
    assert row["title"] == "Updated"
    assert row["status"] == "active"


def test_delete_scenario_nulls_cq_links(db):
    db.execute("INSERT INTO scenarios (title, narrative) VALUES (?,?)", ("SC", "N"))
    sc_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.execute(
        "INSERT INTO competency_questions (text, scenario_id) VALUES (?,?)",
        ("Can the ontology distinguish X?", sc_id),
    )
    db.commit()

    # Mirror the route logic
    db.execute("UPDATE competency_questions SET scenario_id=NULL WHERE scenario_id=?", (sc_id,))
    db.execute("DELETE FROM scenarios WHERE id=?", (sc_id,))
    db.commit()

    cq = db.execute("SELECT scenario_id FROM competency_questions").fetchone()
    sc = db.execute("SELECT id FROM scenarios WHERE id=?", (sc_id,)).fetchone()
    assert cq["scenario_id"] is None
    assert sc is None


def test_cq_insert_with_scenario_id(db):
    db.execute("INSERT INTO scenarios (title, narrative) VALUES (?,?)", ("S", "N"))
    sc_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.execute(
        "INSERT INTO competency_questions (text, linked_classes, scenario_id) VALUES (?,?,?)",
        ("CQ text", "[]", sc_id),
    )
    db.commit()

    row = db.execute("SELECT scenario_id FROM competency_questions").fetchone()
    assert row["scenario_id"] == sc_id
