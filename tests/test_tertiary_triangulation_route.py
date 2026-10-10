# tests/test_tertiary_triangulation_route.py
"""
Integration tests for save-time enforcement of validate_tertiary_triangulation()
on POST /enrich/{id}/update, mirroring tests/test_necessary_parts_route.py.
"""
import sys
import json
import importlib
from pathlib import Path
from datetime import datetime, timezone

import pytest

_ENRICHMENT_DIR = str(Path(__file__).parent.parent / "enrichment")
if _ENRICHMENT_DIR not in sys.path:
    sys.path.insert(0, _ENRICHMENT_DIR)


def _unique_label(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"


def _insert_row(tmp_path, monkeypatch, label: str, source_defs: list | None) -> int:
    import enrichment_service as svc
    importlib.reload(svc)
    monkeypatch.setattr(svc, "ENRICHMENT_DB_PATH", tmp_path / "enr.db")
    svc.init_enrichment_schema()
    conn = svc.get_enrichment_db()
    conn.execute(
        "INSERT INTO enrichment (cluster_label, status, source_definitions_used) "
        "VALUES (?, 'proposed', ?)",
        (label, json.dumps(source_defs) if source_defs is not None else None),
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


def test_single_tertiary_source_returns_422(tmp_path, monkeypatch):
    """One uncorroborated tertiary source must block the save with a 422."""
    monkeypatch.setenv("DEV_USER", "nosantos")

    label = _unique_label("tri-guard-422")
    row_id = _insert_row(tmp_path, monkeypatch, label, source_defs=[
        {"tier": "tertiary", "source_type": "manufacturer_page", "source": "Swagelok",
         "url": "https://products.swagelok.com/en/quick-connects", "quote": "push-to-connect"},
    ])

    resp = _client().post(
        f"/enrich/{row_id}/update",
        data={"necessary_parts": json.dumps([])},
    )
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text[:300]}"
    assert "tertiary" in resp.json().get("detail", "").lower()


def test_two_independent_tertiary_sources_accepted(tmp_path, monkeypatch):
    """Two independent tertiary sources satisfy triangulation and save succeeds."""
    monkeypatch.setenv("DEV_USER", "nosantos")

    label = _unique_label("tri-guard-ok")
    row_id = _insert_row(tmp_path, monkeypatch, label, source_defs=[
        {"tier": "tertiary", "source_type": "manufacturer_page", "source": "Swagelok",
         "url": "https://products.swagelok.com/en/quick-connects", "quote": "a"},
        {"tier": "tertiary", "source_type": "manufacturer_page", "source": "John Guest",
         "url": "https://www.johnguest.com/speedfit", "quote": "b"},
    ])

    resp = _client().post(
        f"/enrich/{row_id}/update",
        data={"necessary_parts": json.dumps([])},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:300]}"


def test_no_tertiary_sources_unaffected(tmp_path, monkeypatch):
    """Rows without any tertiary-tier entry are never blocked by triangulation."""
    monkeypatch.setenv("DEV_USER", "nosantos")

    label = _unique_label("tri-guard-noop")
    row_id = _insert_row(tmp_path, monkeypatch, label, source_defs=[
        {"tier": "primary", "source": "iso15926", "term": "QUICK CONNECTOR"},
        {"tier": "secondary", "source_type": "standard", "source": "ISO 7241",
         "url": "https://www.iso.org/standard/54886.html", "quote": "..."},
    ])

    resp = _client().post(
        f"/enrich/{row_id}/update",
        data={"necessary_parts": json.dumps([])},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:300]}"
