# tests/test_participant_vocabulary_gate.py
"""
Participant types (process_signature inputs/outputs) are hand-authored vocabulary
(CLAUDE.md, ODR-022 §2). A validated entry may only name a participant that is
declared in copi-core / copi-vocab, redirected to BFO / IOF-Core by copi-iri-map.tsv,
or is itself a validated equipment class. Anything else is an LLM-invented type
(e.g. "PhysicalQuantityValue") that the publish path would otherwise mint as a new
COPI class.
"""
import sys
from pathlib import Path

_ENRICHMENT_DIR = str(Path(__file__).parent.parent / "enrichment")
if _ENRICHMENT_DIR not in sys.path:
    sys.path.insert(0, _ENRICHMENT_DIR)

import enrichment_service as svc  # noqa: E402

NS = "https://www.inf.ufrgs.br/ontologies/copi/"


def _patch(monkeypatch, *, baseline=()):
    monkeypatch.setattr(svc, "_load_copi_iri_map", lambda: {
        f"{NS}PortionOfFluid": f"{NS}COPI_0000037",
        f"{NS}MeasurementProcess": "https://spec.industrialontologies.org/ontology/construct/MeasurementProcess",
        f"{NS}SteelPipe": f"{NS}COPI_0000650",   # allocated, but NOT declared in vocab
    })
    monkeypatch.setattr(svc, "_copi_base_module_classes", lambda: frozenset({f"{NS}COPI_0000037"}))
    monkeypatch.setattr(svc, "_validated_equipment_class_names", lambda: frozenset({"PipelinePig"}))
    monkeypatch.setattr(svc, "load_participant_vocabulary_baseline", lambda: set(baseline))


def _sig(*types):
    return {"inputs": [{"type": t} for t in types[:1]], "outputs": [{"type": t} for t in types[1:]]}


def test_vocab_upstream_and_equipment_participants_pass(monkeypatch):
    _patch(monkeypatch)
    sig = {"inputs": [{"type": "portion of fluid"}, {"type": "MeasurementProcess"}],
           "outputs": [{"type": "PipelinePig"}]}
    assert svc.find_unvetted_participants(sig) == []


def test_invented_and_allocated_but_undeclared_types_are_flagged(monkeypatch):
    _patch(monkeypatch)
    sig = _sig("PhysicalQuantityValue", "SteelPipe", "PortionOfFluid")
    assert svc.find_unvetted_participants(sig) == ["PhysicalQuantityValue", "SteelPipe"]


def test_validate_names_the_types_and_how_to_fix(monkeypatch):
    _patch(monkeypatch)
    err = svc.validate_participant_vocabulary("gauge", _sig("PhysicalQuantityValue"))
    assert err is not None
    assert "PhysicalQuantityValue" in err and "copi-vocab" in err


def test_baseline_grandfathers_per_entry(monkeypatch):
    _patch(monkeypatch, baseline={"shear ram|SteelPipe"})
    assert svc.validate_participant_vocabulary("shear ram", _sig("SteelPipe")) is None
    # the same type on a different entry is not grandfathered
    assert svc.validate_participant_vocabulary("other", _sig("SteelPipe")) is not None


def test_empty_or_malformed_signature_passes(monkeypatch):
    _patch(monkeypatch)
    assert svc.validate_participant_vocabulary("x", None) is None
    assert svc.validate_participant_vocabulary("x", "not json") is None
    assert svc.validate_participant_vocabulary("x", {"inputs": ["PortionOfFluid"]}) is None


def test_real_base_modules_declare_known_vocab():
    declared = svc._copi_base_module_classes()
    assert f"{NS}COPI_0000037" in declared   # PortionOfFluid, copi-vocab
    assert f"{NS}COPI_0000001" in declared   # copi-core


# ── Route: saving as validated is refused; saving as proposed is not ─────────

def _insert_row(tmp_path, monkeypatch, label, signature) -> int:
    import importlib, json
    importlib.reload(svc)
    monkeypatch.setattr(svc, "ENRICHMENT_DB_PATH", tmp_path / "enr.db")
    svc.init_enrichment_schema()
    conn = svc.get_enrichment_db()
    conn.execute(
        "INSERT INTO enrichment (cluster_label, status, process_signature) VALUES (?, 'proposed', ?)",
        (label, json.dumps(signature)),
    )
    conn.commit()
    row_id = conn.execute("SELECT id FROM enrichment WHERE cluster_label=?", (label,)).fetchone()[0]
    conn.close()
    return row_id


def _client():
    import importlib
    import app.main as m
    importlib.reload(m)
    from fastapi.testclient import TestClient
    return TestClient(m.app)


def test_update_route_refuses_validating_an_invented_participant(tmp_path, monkeypatch):
    monkeypatch.setenv("DEV_USER", "nosantos")
    sig = {"inputs": [{"type": "PhysicalQuantityValue"}], "outputs": [{"type": "PortionOfFluid"}]}
    row_id = _insert_row(tmp_path, monkeypatch, "pv-gate-gauge", sig)
    client = _client()

    resp = client.post(f"/enrich/{row_id}/update", data={"status": "validated", "loaded_at": "__force__"})
    assert resp.status_code == 422, resp.text[:300]
    assert "PhysicalQuantityValue" in resp.json()["detail"]

    resp = client.post(f"/enrich/{row_id}/update", data={"status": "proposed", "loaded_at": "__force__"})
    assert resp.status_code == 200, resp.text[:300]

    page = client.get(f"/enrich/{row_id}")
    assert page.status_code == 200
    assert "not in COPI vocabulary" in page.text


def test_detail_page_shows_vocabulary_gaps(tmp_path, monkeypatch):
    monkeypatch.setenv("DEV_USER", "nosantos")
    sig = {"inputs": [{"type": "PortionOfLiquid"}], "outputs": [],
           "participant_vocabulary_gaps": [{"needed": "semi-solid sludge", "used_instead": "PortionOfLiquid",
                                            "bfo_category": "portion of matter",
                                            "why_no_listed_type_fits": "copi-vocab has no semi-solid portion"}]}
    row_id = _insert_row(tmp_path, monkeypatch, "pv-gaps-aerator", sig)
    page = _client().get(f"/enrich/{row_id}")
    assert page.status_code == 200
    assert "Vocabulary gaps reported by the LLM" in page.text
    assert "semi-solid sludge" in page.text
