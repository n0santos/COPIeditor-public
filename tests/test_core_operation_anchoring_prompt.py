# tests/test_core_operation_anchoring_prompt.py
"""
Step 1 anchors every equipment process in COPI-Core's operation taxonomy. The prompt lists
the operations generated from copi-core.ttl / copi-vocab.ttl (it used to hard-code
"process_parent": "PlannedProcess"), requires core_operation_gap when nothing fits, and
states the transformation_kind -> operation agreement.
"""
import json
import sys
from pathlib import Path

_ENRICHMENT_DIR = str(Path(__file__).parent.parent / "enrichment")
if _ENRICHMENT_DIR not in sys.path:
    sys.path.insert(0, _ENRICHMENT_DIR)

import core_operations as co  # noqa: E402
import enrichment_service as svc  # noqa: E402
from prompts import render_system_prompt  # noqa: E402


def test_every_top_operation_is_generated_from_the_ttl():
    names = {op.name for op in co.operations()}
    assert set(co.TOP_OPERATIONS) <= names
    # subtypes declared in copi-core / copi-vocab come along
    assert {"LiquidPressureIncrease", "HeatExchange", "ProcessControlledFlowProcess",
            "SignalTransmissionProcess"} <= names
    # LossOfContainment is an unplanned bfo:Process, not an operation to anchor in
    assert "LossOfContainment" not in names


def test_anchor_resolution():
    assert co.anchor_of("FlowControl") == "FlowControl"
    assert co.anchor_of("SafetyReliefProcess") == "FlowControl"
    assert co.anchor_of("MeasurementProcess") == "MeasurementProcess"
    assert co.anchor_of("PlannedProcess") is None
    assert co.anchor_of(None) is None
    # through an already-enriched process whose parent is an operation
    assert co.anchor_of("PumpingProcess", {"PumpingProcess": "LiquidPressureIncrease"}) == "MomentumTransfer"
    # the process itself is a copi-vocab operation (control valve): its parent field is irrelevant
    assert co.anchor_for_entry("ProcessControlledFlowProcess", "PlannedProcess") == "FlowControl"
    assert co.anchor_for_entry("BrakingProcess", "PlannedProcess") is None
    # cycles terminate
    assert co.anchor_of("AProcess", {"AProcess": "BProcess", "BProcess": "AProcess"}) is None


def test_kind_table_covers_the_controlled_vocabulary_exactly():
    assert set(co.KIND_TO_OPERATIONS) == set(svc.TRANSFORMATION_KINDS_CONTROLLED)
    for tops in co.KIND_TO_OPERATIONS.values():
        assert set(tops) <= set(co.TOP_OPERATIONS)


def test_prompt_lists_operations_and_no_longer_defaults_to_planned_process():
    prompt = render_system_prompt()
    assert "<<" not in prompt
    assert '"process_parent": "PlannedProcess"' not in prompt
    assert "`MaterialContainment`" in prompt and "`HeatExchange`" in prompt
    assert "core_operation_gap" in prompt and "core_coverage_gap" in prompt and "out_of_scope" in prompt
    assert "`fluid_transport` → no COPI-Core operation" in prompt


def test_normalize_core_operation_gap():
    ok = {"kind": "core_coverage_gap", "nearest_operation": "FlowControl", "rationale": "passive transport"}
    assert svc.normalize_core_operation_gap(ok) == ok
    assert svc.normalize_core_operation_gap(json.dumps(ok)) == ok
    assert svc.normalize_core_operation_gap(None) is None
    assert svc.normalize_core_operation_gap("null") is None
    # the unfilled template placeholder is not a gap
    assert svc.normalize_core_operation_gap("<null when process_parent is an operation; ...>") is None
    assert svc.normalize_core_operation_gap({"kind": "whatever"}) is None


def test_store_proposal_persists_core_operation_gap(tmp_path, monkeypatch):
    import importlib
    importlib.reload(svc)
    monkeypatch.setattr(svc, "ENRICHMENT_DB_PATH", tmp_path / "enr.db")
    monkeypatch.setattr(svc, "get_symbol_for_cluster", lambda label: None)
    svc.init_enrichment_schema()
    # A fresh schema lacks columns that separate migrations add; _store_proposal's INSERT names them.
    conn = svc.get_enrichment_db()
    have = {r[1] for r in conn.execute("PRAGMA table_info(enrichment)")}
    for col in ("divergence_flags", "cross_standard_links", "generation_path", "genus_already_provides",
                "distinguishes_from", "cache_write_tokens", "cache_read_tokens", "symbol_path"):
        if col not in have:
            conn.execute(f"ALTER TABLE enrichment ADD COLUMN {col} TEXT")
    conn.commit()
    conn.close()
    gap = {"kind": "core_coverage_gap", "nearest_operation": "FlowControl", "rationale": "pipes pass fluid without modulating it"}
    proposal = {
        "step1_function": {"function_name": "FluidConveyanceFunction", "process_name": "FluidConveyanceProcess",
                           "process_parent": "PlannedProcess", "core_operation_gap": gap},
        "step2_genus": {}, "step3_differentia": {}, "step4_parts": {}, "step5_signature": {},
        "definitions": {},
    }
    pid = svc._store_proposal("pv-anchor-pipe", proposal, [], "test-model")
    stored = svc.get_enrichment(pid)
    assert stored["core_operation_gap"] == gap
