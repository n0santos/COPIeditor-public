"""
Task 6 — Undo route.

Tests that POST /enrich/{id}/undo restores the most recent history snapshot
and that the route returns 404 when no history exists.

Each test redirects enrichment_service at an isolated per-test SQLite file
via monkeypatch.setattr(svc, "ENRICHMENT_DB_PATH", ...), applied after
importlib.reload(svc) since reload re-executes the module and would otherwise
reset the path.  Unique cluster labels prevent UNIQUE-constraint collisions
within that file.
"""

import sys
import importlib
from pathlib import Path

import pytest

# enrichment_service.py uses bare `from prompts import ...` which resolves
# relative to the enrichment/ directory.  Add it to sys.path so the import
# works when pytest runs from the project root.
_ENRICHMENT_DIR = str(Path(__file__).parent.parent / "enrichment")
if _ENRICHMENT_DIR not in sys.path:
    sys.path.insert(0, _ENRICHMENT_DIR)


def _insert_enrichment(tmp_path, monkeypatch, label: str, reviewer_notes: str = "original note") -> tuple:
    """Insert one enrichment row into an isolated temp DB and return (svc, row_id)."""
    import enrichment_service as svc
    importlib.reload(svc)
    monkeypatch.setattr(svc, "ENRICHMENT_DB_PATH", tmp_path / "enr.db")
    svc.init_enrichment_schema()
    conn = svc.get_enrichment_db()
    conn.execute(
        "INSERT INTO enrichment (cluster_label, created_at, updated_at, reviewer_notes) "
        "VALUES (?, datetime('now'), datetime('now'), ?)",
        (label, reviewer_notes),
    )
    conn.commit()
    row_id = conn.execute(
        "SELECT id FROM enrichment WHERE cluster_label=? ORDER BY id DESC LIMIT 1",
        (label,),
    ).fetchone()[0]
    conn.close()
    return svc, row_id


def test_undo_restores_previous_state(tmp_path, monkeypatch):
    """After a manual save (which snapshots), undo should revert reviewer_notes."""
    monkeypatch.setenv("DEV_USER", "nosantos")
    svc, row_id = _insert_enrichment(tmp_path, monkeypatch, "undo-test-restore", reviewer_notes="original note")

    import app.main as m
    importlib.reload(m)
    from fastapi.testclient import TestClient
    client = TestClient(m.app)

    # Perform a save; the update route snapshots current state first
    resp = client.post(
        f"/enrich/{row_id}/update",
        data={"reviewer_notes": "changed note", "loaded_at": "__force__"},
    )
    assert resp.status_code not in (400, 409, 500), (
        f"Update should succeed, got {resp.status_code}: {resp.text[:200]}"
    )

    # Verify the note was changed
    conn = svc.get_enrichment_db()
    row_after_update = conn.execute(
        "SELECT reviewer_notes FROM enrichment WHERE id=?", (row_id,)
    ).fetchone()
    conn.close()
    assert row_after_update[0] == "changed note", (
        f"Expected 'changed note', got {row_after_update[0]!r}"
    )

    # Undo — should restore the original note
    resp = client.post(f"/enrich/{row_id}/undo")
    assert resp.status_code in (200, 303), (
        f"Expected 200 or 303, got {resp.status_code}: {resp.text[:200]}"
    )

    conn2 = svc.get_enrichment_db()
    row_after_undo = conn2.execute(
        "SELECT reviewer_notes FROM enrichment WHERE id=?", (row_id,)
    ).fetchone()
    conn2.close()
    assert row_after_undo[0] == "original note", (
        f"Undo should restore 'original note', got {row_after_undo[0]!r}"
    )


def test_undo_returns_404_when_no_history(tmp_path, monkeypatch):
    """Undo on a row with no history snapshots must return 404."""
    monkeypatch.setenv("DEV_USER", "nosantos")
    _svc, row_id = _insert_enrichment(tmp_path, monkeypatch, "undo-test-no-history")

    import app.main as m
    importlib.reload(m)
    from fastapi.testclient import TestClient
    client = TestClient(m.app)

    # No update was performed — no history exists
    resp = client.post(f"/enrich/{row_id}/undo")
    assert resp.status_code == 404, (
        f"Expected 404 when no history, got {resp.status_code}: {resp.text[:200]}"
    )


def test_restore_enrichment_snapshot_unit(tmp_path, monkeypatch):
    """Unit test: restore_enrichment_snapshot() returns False with no history."""
    import enrichment_service as svc
    importlib.reload(svc)
    monkeypatch.setattr(svc, "ENRICHMENT_DB_PATH", tmp_path / "enr.db")
    svc.init_enrichment_schema()
    conn = svc.get_enrichment_db()
    conn.execute(
        "INSERT INTO enrichment (cluster_label, created_at, updated_at) "
        "VALUES ('undo-unit-no-history', datetime('now'), datetime('now'))"
    )
    conn.commit()
    row_id = conn.execute(
        "SELECT id FROM enrichment WHERE cluster_label='undo-unit-no-history' ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    conn.close()

    result = svc.restore_enrichment_snapshot(row_id)
    assert result is False, f"Expected False with no history, got {result!r}"


def test_restore_enrichment_snapshot_unit_restores(tmp_path, monkeypatch):
    """Unit test: restore_enrichment_snapshot() returns True and restores data."""
    import enrichment_service as svc
    importlib.reload(svc)
    monkeypatch.setattr(svc, "ENRICHMENT_DB_PATH", tmp_path / "enr.db")
    svc.init_enrichment_schema()
    conn = svc.get_enrichment_db()
    conn.execute(
        "INSERT INTO enrichment (cluster_label, created_at, updated_at, reviewer_notes) "
        "VALUES ('undo-unit-restore', datetime('now'), datetime('now'), 'before')"
    )
    conn.commit()
    row_id = conn.execute(
        "SELECT id FROM enrichment WHERE cluster_label='undo-unit-restore' ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    conn.close()

    # Manually snapshot, then change the row
    svc.snapshot_enrichment(row_id, trigger="save")
    svc.update_enrichment(row_id, {"reviewer_notes": "after"})

    result = svc.restore_enrichment_snapshot(row_id)
    assert result is True, f"Expected True, got {result!r}"

    conn2 = svc.get_enrichment_db()
    restored = conn2.execute(
        "SELECT reviewer_notes FROM enrichment WHERE id=?", (row_id,)
    ).fetchone()
    conn2.close()
    assert restored[0] == "before", (
        f"Expected 'before' after restore, got {restored[0]!r}"
    )
