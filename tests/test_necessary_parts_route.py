# tests/test_necessary_parts_route.py
"""
Integration tests for save-time validation of necessary_parts source_quote.

Each test redirects enrichment_service at an isolated per-test SQLite file
via monkeypatch.setattr(svc, "ENRICHMENT_DB_PATH", ...), applied after
importlib.reload(svc) since reload re-executes the module and would otherwise
reset the path. Each test also uses a unique cluster_label via
_unique_label() to avoid UNIQUE constraint collisions within that file.
DEV_USER is set via monkeypatch so the auth middleware allows POST requests.
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


def _insert_row(tmp_path, monkeypatch, label: str, source_defs: list | None = None) -> int:
    """
    Insert one enrichment row into an isolated temp DB and return the row id.
    """
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


def test_missing_source_quote_returns_422(tmp_path, monkeypatch):
    """POST /enrich/{id}/update with a named part missing source_quote must return 422."""
    monkeypatch.setenv("DEV_USER", "nosantos")

    label = _unique_label("np-guard-422")
    row_id = _insert_row(
        tmp_path, monkeypatch, label,
        source_defs=["The valve body is the main pressure-containing element."],
    )
    parts = [{"name": "ValveBody", "parent": "MaterialArtifact",
              "relation": "hasComponentPartAtAllTimes",
              "source_quote": None}]

    resp = _client().post(
        f"/enrich/{row_id}/update",
        data={"necessary_parts": json.dumps(parts)},
    )
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text[:300]}"
    body = resp.json()
    assert "ValveBody" in body.get("detail", "")


def test_quote_not_in_source_defs_returns_422(tmp_path, monkeypatch):
    """A source_quote not found in source_definitions_used must return 422."""
    monkeypatch.setenv("DEV_USER", "nosantos")

    label = _unique_label("np-guard-nomatch")
    row_id = _insert_row(
        tmp_path, monkeypatch, label,
        source_defs=["A centrifugal pump moves fluid via rotation."],
    )
    parts = [{"name": "Impeller", "parent": "MaterialArtifact",
              "relation": "hasComponentPartAtAllTimes",
              "source_quote": "The impeller spins the fluid at high speed."}]  # not in src

    resp = _client().post(
        f"/enrich/{row_id}/update",
        data={"necessary_parts": json.dumps(parts)},
    )
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text[:300]}"
    assert "Impeller" in resp.json().get("detail", "")


def test_valid_source_quote_is_accepted(tmp_path, monkeypatch):
    """A named part with a valid source_quote found in source_defs must be accepted."""
    monkeypatch.setenv("DEV_USER", "nosantos")

    label = _unique_label("np-guard-ok")
    src_text = "The valve body is the main pressure-containing element."
    row_id = _insert_row(tmp_path, monkeypatch, label, source_defs=[src_text])
    parts = [{"name": "ValveBody", "parent": "MaterialArtifact",
              "relation": "hasComponentPartAtAllTimes",
              "source_quote": "The valve body is the main pressure-containing element."}]

    resp = _client().post(
        f"/enrich/{row_id}/update",
        data={"necessary_parts": json.dumps(parts)},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:300]}"


def test_null_name_parts_bypass_validation(tmp_path, monkeypatch):
    """Parts with name=null must bypass validation (placeholders)."""
    monkeypatch.setenv("DEV_USER", "nosantos")

    label = _unique_label("np-guard-nullname")
    row_id = _insert_row(tmp_path, monkeypatch, label, source_defs=None)  # no source defs
    parts = [{"name": None, "source_quote": None, "rationale": "optional concept"}]

    resp = _client().post(
        f"/enrich/{row_id}/update",
        data={"necessary_parts": json.dumps(parts)},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:300]}"


def test_empty_parts_list_is_accepted(tmp_path, monkeypatch):
    """An empty necessary_parts list must always be accepted."""
    monkeypatch.setenv("DEV_USER", "nosantos")

    label = _unique_label("np-guard-empty")
    row_id = _insert_row(tmp_path, monkeypatch, label, source_defs=None)

    resp = _client().post(
        f"/enrich/{row_id}/update",
        data={"necessary_parts": json.dumps([])},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:300]}"


def test_no_necessary_parts_field_skips_validation(tmp_path, monkeypatch):
    """POSTing without necessary_parts must not trigger validation."""
    monkeypatch.setenv("DEV_USER", "nosantos")
    label = _unique_label("np-guard-noop")
    row_id = _insert_row(tmp_path, monkeypatch, label, source_defs=None)

    resp = _client().post(
        f"/enrich/{row_id}/update",
        data={"status": "reviewed"},  # no necessary_parts key
    )
    # Must not 422 — validation only fires when the field is present
    assert resp.status_code != 422, f"Got 422 without necessary_parts: {resp.text}"
