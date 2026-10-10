"""
Task 5 — Stale-write detection.

Tests that POST /enrich/{id}/update returns 409 when loaded_at is older
than the DB's updated_at, and that the response includes conflict metadata.

NOTE: Each test redirects enrichment_service at an isolated per-test SQLite
file via monkeypatch.setattr(svc, "ENRICHMENT_DB_PATH", ...), applied after
importlib.reload(svc) since reload re-executes the module and would otherwise
reset the path.  Unique cluster_labels avoid UNIQUE(cluster_label, created_at)
conflicts within that file.
"""

import sys
import importlib
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

# enrichment_service.py uses bare `from prompts import ...` which resolves
# relative to the enrichment/ directory.  Add it to sys.path so the import
# works when pytest runs from the project root.
_ENRICHMENT_DIR = str(Path(__file__).parent.parent / "enrichment")
if _ENRICHMENT_DIR not in sys.path:
    sys.path.insert(0, _ENRICHMENT_DIR)


def _setup_db(tmp_path, monkeypatch, label: str) -> tuple:
    """
    Insert one enrichment row with a known updated_at, and return (svc, row_id, updated_at).
    Uses datetime('now') so no UNIQUE constraint collision on repeated test runs.
    """
    import enrichment_service as svc
    importlib.reload(svc)
    monkeypatch.setattr(svc, "ENRICHMENT_DB_PATH", tmp_path / "enr.db")

    svc.init_enrichment_schema()
    conn = svc.get_enrichment_db()
    conn.execute(
        "INSERT INTO enrichment (cluster_label, created_at, updated_at) "
        "VALUES (?, datetime('now'), datetime('now'))",
        (label,)
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, updated_at FROM enrichment WHERE cluster_label=? ORDER BY id DESC LIMIT 1",
        (label,)
    ).fetchone()
    row_id = row[0]
    updated_at = row[1]
    conn.close()
    return svc, row_id, updated_at


def test_stale_write_returns_409(tmp_path, monkeypatch):
    """A loaded_at older than DB updated_at must return 409 with conflict metadata."""
    monkeypatch.setenv("DEV_USER", "nosantos")
    svc, row_id, updated_at = _setup_db(tmp_path, monkeypatch, label="stale-test-409")

    import app.main as m
    importlib.reload(m)

    from fastapi.testclient import TestClient
    client = TestClient(m.app)

    # Build a loaded_at that is clearly older than the DB value
    # Parse updated_at and subtract 1 day to ensure it's older
    try:
        dt = datetime.fromisoformat(updated_at)
        stale_ts = (dt - timedelta(days=1)).isoformat()
    except Exception:
        stale_ts = "2025-01-01T00:00:00"

    resp = client.post(
        f"/enrich/{row_id}/update",
        data={
            "status": "reviewed",
            "loaded_at": stale_ts,
        },
    )
    assert resp.status_code == 409, (
        f"Expected 409, got {resp.status_code}: {resp.text[:200]}"
    )
    body = resp.json()
    assert body["conflict"] is True
    assert "last_edited_by" in body


def test_force_sentinel_bypasses_stale_check(tmp_path, monkeypatch):
    """loaded_at='__force__' skips the staleness check and saves successfully."""
    monkeypatch.setenv("DEV_USER", "nosantos")
    svc, row_id, updated_at = _setup_db(tmp_path, monkeypatch, label="stale-test-force")

    import app.main as m
    importlib.reload(m)

    from fastapi.testclient import TestClient
    client = TestClient(m.app)

    resp = client.post(
        f"/enrich/{row_id}/update",
        data={
            "status": "reviewed",
            "loaded_at": "__force__",  # sentinel — skip check
        },
    )
    # Should not return 409; 200 or redirect both acceptable
    assert resp.status_code != 409, (
        f"Force sentinel should bypass stale check, got {resp.status_code}"
    )


def test_fresh_write_does_not_conflict(tmp_path, monkeypatch):
    """loaded_at matching DB updated_at must not return 409."""
    monkeypatch.setenv("DEV_USER", "nosantos")
    svc, row_id, updated_at = _setup_db(tmp_path, monkeypatch, label="stale-test-fresh")

    import app.main as m
    importlib.reload(m)

    from fastapi.testclient import TestClient
    client = TestClient(m.app)

    resp = client.post(
        f"/enrich/{row_id}/update",
        data={
            "status": "reviewed",
            "loaded_at": updated_at,  # matches DB exactly
        },
    )
    assert resp.status_code != 409, (
        f"Fresh write (loaded_at == updated_at) should not conflict, got {resp.status_code}"
    )
