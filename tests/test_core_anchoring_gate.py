# tests/test_core_anchoring_gate.py
"""
COPI-Core anchoring gate: a validated process must reach a COPI-Core operation or record a
core_operation_gap, and its transformation_kind must agree with the anchor. Enforced at save
time (422) against the effective values; the detail page lets the reviewer fix it.
"""
import importlib
import json
import sys
from pathlib import Path

_ENRICHMENT_DIR = str(Path(__file__).parent.parent / "enrichment")
if _ENRICHMENT_DIR not in sys.path:
    sys.path.insert(0, _ENRICHMENT_DIR)

import core_operations as co  # noqa: E402
import enrichment_service as svc  # noqa: E402


def test_findings():
    sig = {"transformation_kind": "fluid_transport", "transformation_kind_status": "controlled"}
    assert co.anchoring_findings("PipeFlowProcess", "PlannedProcess", sig, None) == ["unanchored"]
    gap = {"kind": "core_coverage_gap", "nearest_operation": None, "rationale": "passive transport"}
    assert co.anchoring_findings("PipeFlowProcess", "PlannedProcess", sig, json.dumps(gap)) == []
    # fluid_transport has no operation, so anchoring it in MomentumTransfer is a mismatch
    assert co.anchoring_findings("PipeFlowProcess", "MomentumTransfer", sig, None) == ["kind_mismatch:fluid_transport"]
    ok = {"transformation_kind": "flow_regulation", "transformation_kind_status": "controlled"}
    assert co.anchoring_findings("ThrottlingProcess", "FlowControl", ok, None) == []
    # a proposed (uncontrolled) kind is not checked for agreement
    proposed = {"transformation_kind": "signal_relay", "transformation_kind_status": "proposed"}
    assert co.anchoring_findings("RelayProcess", "MeasurementProcess", proposed, None) == []


def _row(tmp_path, monkeypatch, label, process_parent, kind):
    importlib.reload(svc)
    monkeypatch.setattr(svc, "ENRICHMENT_DB_PATH", tmp_path / "enr.db")
    monkeypatch.setattr(svc, "CORE_ANCHORING_BASELINE_PATH", tmp_path / "no-baseline.txt")
    svc.init_enrichment_schema()
    conn = svc.get_enrichment_db()
    sig = {"inputs": [{"type": "PortionOfFluid"}], "outputs": [{"type": "PortionOfFluid"}],
           "transformation_kind": kind, "transformation_kind_status": "controlled"}
    conn.execute(
        "INSERT INTO enrichment (cluster_label, status, process_name, process_parent, process_signature) "
        "VALUES (?, 'proposed', 'SpoolConveyanceProcess', ?, ?)",
        (label, process_parent, json.dumps(sig)),
    )
    conn.commit()
    rid = conn.execute("SELECT id FROM enrichment WHERE cluster_label=?", (label,)).fetchone()[0]
    conn.close()
    return rid


def _client():
    import app.main as m
    importlib.reload(m)
    from fastapi.testclient import TestClient
    return TestClient(m.app)


def test_validating_unanchored_entry_is_refused_until_a_gap_is_recorded(tmp_path, monkeypatch):
    monkeypatch.setenv("DEV_USER", "nosantos")
    rid = _row(tmp_path, monkeypatch, "anchor-gate-spool", "PlannedProcess", "fluid_transport")
    client = _client()

    resp = client.post(f"/enrich/{rid}/update", data={"status": "validated", "loaded_at": "__force__"})
    assert resp.status_code == 422, resp.text[:300]
    assert "COPI-Core anchoring" in resp.json()["detail"]

    gap = json.dumps({"kind": "core_coverage_gap", "nearest_operation": "FlowControl",
                      "rationale": "a spool conveys fluid without modulating it"})
    resp = client.post(f"/enrich/{rid}/update",
                       data={"status": "validated", "core_operation_gap": gap, "loaded_at": "__force__"})
    assert resp.status_code == 200, resp.text[:300]
    assert svc.get_enrichment(rid)["core_operation_gap"]["kind"] == "core_coverage_gap"

    page = client.get(f"/enrich/{rid}")
    assert page.status_code == 200 and "COPI-Core coverage gap" in page.text


def test_kind_mismatch_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("DEV_USER", "nosantos")
    rid = _row(tmp_path, monkeypatch, "anchor-gate-mismatch", "MomentumTransfer", "fluid_transport")
    resp = _client().post(f"/enrich/{rid}/update", data={"status": "validated", "loaded_at": "__force__"})
    assert resp.status_code == 422
    assert "fluid_transport" in resp.json()["detail"]
