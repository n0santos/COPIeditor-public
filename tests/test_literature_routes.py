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


def test_insert_paper(db):
    db.execute(
        "INSERT INTO literature (title, authors, year, doi) VALUES (?,?,?,?)",
        ("LOT: Linked Open Terms", "Poveda-Villalón et al.", 2022, "10.1234/lot"),
    )
    db.commit()
    row = db.execute("SELECT * FROM literature WHERE title LIKE ?", ("%LOT%",)).fetchone()
    assert row is not None
    assert row["year"] == 2022
    assert row["doi"] == "10.1234/lot"


def test_delete_paper(db):
    db.execute("INSERT INTO literature (title) VALUES (?)", ("Paper to delete",))
    paper_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()

    db.execute("DELETE FROM literature WHERE id=?", (paper_id,))
    db.commit()

    row = db.execute("SELECT id FROM literature WHERE id=?", (paper_id,)).fetchone()
    assert row is None


def test_update_paper(db):
    db.execute("INSERT INTO literature (title, year) VALUES (?,?)", ("Old title", 2020))
    paper_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()

    db.execute("UPDATE literature SET title=?, year=? WHERE id=?",
               ("New title", 2021, paper_id))
    db.commit()

    row = db.execute("SELECT * FROM literature WHERE id=?", (paper_id,)).fetchone()
    assert row["title"] == "New title"
    assert row["year"] == 2021


def test_papers_ordered_year_desc_title_asc(db):
    db.execute("INSERT INTO literature (title, year) VALUES (?,?)", ("Paper A", 2020))
    db.execute("INSERT INTO literature (title, year) VALUES (?,?)", ("Paper B", 2023))
    db.execute("INSERT INTO literature (title, year) VALUES (?,?)", ("Paper C", 2021))
    db.commit()

    rows = db.execute(
        "SELECT title FROM literature ORDER BY year DESC, title ASC"
    ).fetchall()
    assert [r["title"] for r in rows] == ["Paper B", "Paper C", "Paper A"]
