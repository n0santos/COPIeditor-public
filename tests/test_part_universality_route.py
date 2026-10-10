# tests/test_part_universality_route.py
"""
Integration tests for save-time enforcement of validate_part_universality()
on POST /enrich/{id}/update, mirroring tests/test_tertiary_triangulation_route.py.
"""
import sys
import json
import importlib
from pathlib import Path
from datetime import datetime, timezone

_ENRICHMENT_DIR = str(Path(__file__).parent.parent / "enrichment")
if _ENRICHMENT_DIR not in sys.path:
    sys.path.insert(0, _ENRICHMENT_DIR)


def _unique_label(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"


def _insert_row(tmp_path, monkeypatch, label: str, source_defs) -> int:
    import enrichment_service as svc
    importlib.reload(svc)
    monkeypatch.setattr(svc, "ENRICHMENT_DB_PATH", tmp_path / "enr.db")
    svc.init_enrichment_schema()
    conn = svc.get_enrichment_db()
    conn.execute(
        "INSERT INTO enrichment (cluster_label, status, source_definitions_used) "
        "VALUES (?, 'proposed', ?)",
        (label, json.dumps(source_defs)),
    )
    conn.commit()
    row_id = conn.execute(
        "SELECT id FROM enrichment WHERE cluster_label=? ORDER BY id DESC LIMIT 1",
        (label,),
    ).fetchone()[0]
    conn.close()
    return row_id


def _client():
    import app.main as m
    importlib.reload(m)
    from fastapi.testclient import TestClient
    return TestClient(m.app)


def test_hedged_part_returns_422(tmp_path, monkeypatch):
    """A necessary_part whose source_quote hedges universality must block the save."""
    monkeypatch.setenv("DEV_USER", "nosantos")

    label = _unique_label("univ-guard-422")
    quote = "An adjusting ring is typically fitted to calibrate the set pressure."
    row_id = _insert_row(tmp_path, monkeypatch, label, source_defs=[quote])
    parts = [{"name": "AdjustingRing", "parent": "MaterialArtifact",
              "relation": "hasComponentPartAtAllTimes", "source_quote": quote}]

    resp = _client().post(
        f"/enrich/{row_id}/update",
        data={"necessary_parts": json.dumps(parts)},
    )
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text[:300]}"
    assert "AdjustingRing" in resp.json().get("detail", "")
    assert "candidate_parts" in resp.json().get("detail", "")


def test_unhedged_part_is_accepted(tmp_path, monkeypatch):
    """A necessary_part whose source_quote states the fact of the genus plainly must save."""
    monkeypatch.setenv("DEV_USER", "nosantos")

    label = _unique_label("univ-guard-ok")
    quote = "The valve body is the main pressure-containing element."
    row_id = _insert_row(tmp_path, monkeypatch, label, source_defs=[quote])
    parts = [{"name": "ValveBody", "parent": "MaterialArtifact",
              "relation": "hasComponentPartAtAllTimes", "source_quote": quote}]

    resp = _client().post(
        f"/enrich/{row_id}/update",
        data={"necessary_parts": json.dumps(parts)},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:300]}"
