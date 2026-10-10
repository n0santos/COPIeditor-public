# tests/test_provenance_ui.py
"""
GET /enrich/{id} must render the new provenance-tier and candidate_parts UI
blocks without crashing, whether the row has tiered entries, legacy
(pre-tier) entries, or neither.
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


def _insert_row(tmp_path, monkeypatch, label: str, source_defs=None, candidate_parts=None) -> int:
    import enrichment_service as svc
    importlib.reload(svc)
    monkeypatch.setattr(svc, "ENRICHMENT_DB_PATH", tmp_path / "enr.db")
    svc.init_enrichment_schema()
    conn = svc.get_enrichment_db()
    conn.execute(
        "INSERT INTO enrichment (cluster_label, status, source_definitions_used, candidate_parts) "
        "VALUES (?, 'proposed', ?, ?)",
        (
            label,
            json.dumps(source_defs) if source_defs is not None else None,
            json.dumps(candidate_parts) if candidate_parts is not None else None,
        ),
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


def test_detail_page_renders_with_tiered_sources_and_candidate_parts(tmp_path, monkeypatch):
    monkeypatch.setenv("DEV_USER", "nosantos")
    label = _unique_label("prov-ui-tiered")
    row_id = _insert_row(
        tmp_path, monkeypatch, label,
        source_defs=[
            {"tier": "primary", "source_type": "standard", "source": "iso15926",
             "term": "QUICK CONNECTOR", "quote": "..."},
            {"tier": "tertiary", "source_type": "manufacturer_page", "source": "Swagelok",
             "url": "https://products.swagelok.com/en/quick-connects",
             "citation_mode": "verbatim", "quote": "push-to-connect"},
        ],
        candidate_parts=[{"name": "AdjustingMechanism", "source_quote": "calibrate the force"}],
    )

    resp = _client().get(f"/enrich/{row_id}")
    assert resp.status_code == 200, resp.text[:300]
    assert "Provenance tiers" in resp.text
    assert "primary" in resp.text
    assert "tertiary" in resp.text
    assert "Candidate parts" in resp.text
    assert "AdjustingMechanism" in resp.text


def test_detail_page_renders_with_legacy_sources(tmp_path, monkeypatch):
    """Pre-tier {source, term} entries (no 'tier' key) must not crash or show the block."""
    monkeypatch.setenv("DEV_USER", "nosantos")
    label = _unique_label("prov-ui-legacy")
    row_id = _insert_row(
        tmp_path, monkeypatch, label,
        source_defs=[{"source": "iso15926", "term": "AERATOR"}],
    )

    resp = _client().get(f"/enrich/{row_id}")
    assert resp.status_code == 200, resp.text[:300]
    assert "Provenance tiers" not in resp.text
    # "Candidate parts" also appears in a static HTML comment (like every other
    # section marker in this template) — assert on the visible heading text instead.
    assert "Candidate parts (unconfirmed)" not in resp.text


def test_detail_page_renders_with_no_source_defs(tmp_path, monkeypatch):
    """A brand-new row with no source_definitions_used at all must not crash."""
    monkeypatch.setenv("DEV_USER", "nosantos")
    label = _unique_label("prov-ui-empty")
    row_id = _insert_row(tmp_path, monkeypatch, label)

    resp = _client().get(f"/enrich/{row_id}")
    assert resp.status_code == 200, resp.text[:300]
