"""
Step 5 FOL must tie the participants to the process that realizes the function.

The generated axiom used to put participatesIn(m,f) and processType(f,K) on the
function variable f, so f was both the function and the process, and no process
variable or realizedIn(f,p) appeared.  Participants belong to the process p that
realizes f: hasInput(p,m) / hasOutput(p,e), with realizedIn(f,p) in the antecedent
(the same relation the Step 1 function axiom uses).
"""

import sys
import re
from pathlib import Path

_ENRICHMENT_DIR = str(Path(__file__).parent.parent / "enrichment")
if _ENRICHMENT_DIR not in sys.path:
    sys.path.insert(0, _ENRICHMENT_DIR)

import enrichment_service as svc


def _entry(**over):
    e = {
        "cluster_label": "spectacle blind",
        "genus": "LineBlind",
        "function_name": "LineBlindingFunction",
        "process_name": "LineBlindingProcess",
        "axiom_mode": "necessary",
        "differentia_expression": "∃bearerOf.LineBlindingFunction",
        "necessary_parts": [],
        "process_signature": {
            "inputs": [
                {"type": "PortionOfFluid", "count": 1},
                {"type": "PortionOfFluid", "count": 1},
            ],
            "outputs": [{"type": "FluidMixture", "count": 1}],
            "transformation_kind": "mixing",
        },
    }
    e.update(over)
    return e


def _step5(e):
    rows = [r for r in svc.generate_fol_theory(e) if r["step"] == "5"]
    assert len(rows) == 1
    return rows[0]["fol"]


def test_participants_attach_to_the_realizing_process_not_the_function():
    fol = _step5(_entry())
    assert "realizedIn(f,p)" in fol
    assert "hasInput(p,m1)" in fol and "hasInput(p,m2)" in fol
    assert "hasOutput(p,e)" in fol
    assert "participatesIn" not in fol


def test_function_variable_is_never_used_as_a_process():
    fol = _step5(_entry())
    assert "processType" not in fol
    # f may only appear as the function: bearerOf(x,f), the function class, realizedIn(f,p)
    for m in re.finditer(r"(\w+)\(([^()]*\bf\b[^()]*)\)", fol):
        pred = m.group(1)
        assert pred in {"LineBlindingFunction", "bearerOf", "realizedIn"}, fol


def test_process_variable_is_quantified():
    fol = _step5(_entry())
    assert fol.startswith("∀x ∀f ∀p (")


def test_single_input_and_output_keep_plain_variable_names():
    e = _entry(process_signature={
        "inputs": [{"type": "PortionOfFluid"}],
        "outputs": [{"type": "PortionOfFluid"}],
    })
    fol = _step5(e)
    assert "∃m (PortionOfFluid(m) ∧ hasInput(p,m))" in fol
    assert "∃e (PortionOfFluid(e) ∧ hasOutput(p,e))" in fol


def test_no_step5_axiom_without_participants():
    e = _entry(process_signature={"inputs": [], "outputs": [], "transformation_kind": "containment"})
    assert not [r for r in svc.generate_fol_theory(e) if r["step"] == "5"]


def test_owl_step5_output_restriction_uses_has_output(tmp_path, monkeypatch):
    # hasSpecifiedOutput requires a PlannedProcess and an ObjectiveSpecification;
    # the Step 5 signature only asserts that the process yields the participant.
    import json
    monkeypatch.setattr(svc, "ENRICHMENT_DB_PATH", tmp_path / "enr.db")
    svc.init_enrichment_schema()
    conn = svc.get_enrichment_db()
    conn.execute("CREATE TABLE IF NOT EXISTS additional_parents "
                 "(id INTEGER PRIMARY KEY AUTOINCREMENT, cluster_label TEXT, parent_iri TEXT)")
    conn.execute(
        "INSERT INTO enrichment (cluster_label, created_at, updated_at, genus, genus_bfo_root, "
        "function_name, process_name, process_parent, axiom_mode, differentia_expression, process_signature) "
        "VALUES ('line blind', datetime('now'), datetime('now'), 'MaterialArtifact', 'MaterialArtifact', "
        "'LineBlindingFunction', 'LineBlindingProcess', 'FlowControl', 'equivalent', "
        "'∃bearerOf.LineBlindingFunction', ?)",
        (json.dumps({"inputs": [{"type": "PortionOfFluid"}], "outputs": [{"type": "PortionOfFluid"}],
                     "transformation_kind": "flow_isolation"}),),
    )
    conn.commit()
    row_id = conn.execute("SELECT id FROM enrichment").fetchone()["id"]
    conn.close()
    ttl = svc.generate_turtle(row_id)
    assert "iof-core:hasOutput" in ttl
    assert "hasSpecifiedOutput" not in ttl
