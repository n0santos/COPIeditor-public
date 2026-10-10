"""
Task 3 — Wire attribution into manual saves.

Tests that POST /enrich/{id}/update:
- Sets last_edited_by from the authenticated user (DEV_USER in these tests)
- Sets expert_reviewer to the same user (no longer a free-text form field)
- Takes a history snapshot before each save
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


def _setup_db(tmp_path, monkeypatch, label: str = "pump") -> int:
    """
    Redirect enrichment_service at an isolated temp DB, insert one row, and
    return the row id.  Each test should pass a unique label to avoid
    UNIQUE constraint collisions if module state bleeds between test functions.
    """
    import enrichment_service as svc
    importlib.reload(svc)
    monkeypatch.setattr(svc, "ENRICHMENT_DB_PATH", tmp_path / "enr.db")

    svc.init_enrichment_schema()
    conn = svc.get_enrichment_db()
    conn.execute(
        "INSERT INTO enrichment (cluster_label, created_at, updated_at) "
        "VALUES (?, datetime('now'), datetime('now'))",
        (label,),
    )
    conn.commit()
    row_id = conn.execute(
        "SELECT id FROM enrichment WHERE cluster_label=?", (label,)
    ).fetchone()[0]
    conn.close()
    return row_id


def test_save_sets_last_edited_by(tmp_path, monkeypatch):
    """last_edited_by and expert_reviewer are set from the authenticated user."""
    monkeypatch.setenv("DEV_USER", "nosantos")
    row_id = _setup_db(tmp_path, monkeypatch, label="pump-t1")

    import enrichment_service as svc
    import app.main as m
    importlib.reload(m)

    from fastapi.testclient import TestClient
    client = TestClient(m.app)

    resp = client.post(
        f"/enrich/{row_id}/update",
        data={"status": "reviewed", "reviewer_notes": "looks good"},
    )
    assert resp.status_code in (200, 303), f"Unexpected status: {resp.status_code} — {resp.text[:200]}"

    conn = svc.get_enrichment_db()
    row = conn.execute(
        "SELECT last_edited_by, expert_reviewer FROM enrichment WHERE id=?", (row_id,)
    ).fetchone()
    conn.close()

    assert row is not None, "Row not found after save"
    assert row[0] == "nosantos", f"last_edited_by expected 'nosantos', got {row[0]!r}"
    assert row[1] == "nosantos", f"expert_reviewer expected 'nosantos', got {row[1]!r}"


def test_save_creates_history_snapshot(tmp_path, monkeypatch):
    """A history snapshot is written before each save."""
    monkeypatch.setenv("DEV_USER", "nosantos")
    row_id = _setup_db(tmp_path, monkeypatch, label="pump-t2")

    import enrichment_service as svc
    import app.main as m
    importlib.reload(m)

    from fastapi.testclient import TestClient
    client = TestClient(m.app)

    resp = client.post(
        f"/enrich/{row_id}/update",
        data={"status": "reviewed", "reviewer_notes": "snapshot check"},
    )
    assert resp.status_code in (200, 303)

    conn = svc.get_enrichment_db()
    count = conn.execute(
        "SELECT COUNT(*) FROM enrichment_history WHERE enrichment_id=?", (row_id,)
    ).fetchone()[0]
    conn.close()

    assert count >= 1, "Expected at least one history snapshot after save"


def test_expert_reviewer_not_overridable_from_form(tmp_path, monkeypatch):
    """Form-posted expert_reviewer is ignored; the authenticated user wins."""
    monkeypatch.setenv("DEV_USER", "nosantos")
    row_id = _setup_db(tmp_path, monkeypatch, label="pump-t3")

    import enrichment_service as svc
    import app.main as m
    importlib.reload(m)

    from fastapi.testclient import TestClient
    client = TestClient(m.app)

    # Attempt to set expert_reviewer via form — should be silently ignored
    resp = client.post(
        f"/enrich/{row_id}/update",
        data={"status": "reviewed", "expert_reviewer": "mallory"},
    )
    assert resp.status_code in (200, 303)

    conn = svc.get_enrichment_db()
    row = conn.execute(
        "SELECT expert_reviewer FROM enrichment WHERE id=?", (row_id,)
    ).fetchone()
    conn.close()

    assert row[0] == "nosantos", (
        f"expert_reviewer should be 'nosantos' (from authenticated user), got {row[0]!r}"
    )
