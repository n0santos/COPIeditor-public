# tests/test_participant_vocabulary_prompt.py
"""
The Step 5 prompt's participant vocabulary is generated from copi-vocab.ttl and the
BFO / IOF-Core redirect rows of copi-iri-map.tsv. It must offer exactly what the
participant vocabulary gate accepts: a prompt that recommends a name the gate rejects
(as the old hand-written list did with ThermalEnergy) sends every run into a validation
block, and a prompt that invites new names reintroduces invented types.
"""
import sys
from pathlib import Path

_ENRICHMENT_DIR = str(Path(__file__).parent.parent / "enrichment")
if _ENRICHMENT_DIR not in sys.path:
    sys.path.insert(0, _ENRICHMENT_DIR)

import enrichment_service as svc  # noqa: E402
import participant_vocabulary as pv  # noqa: E402
from prompts import build_enrichment_prompt, render_system_prompt  # noqa: E402


def test_every_offered_type_passes_the_gate(monkeypatch):
    monkeypatch.setattr(svc, "_validated_equipment_class_names", lambda: frozenset())
    names = [t.name for t in pv.participant_types()]
    assert names, "vocabulary came back empty"
    sig = {"inputs": [{"type": n} for n in names], "outputs": []}
    assert svc.find_unvetted_participants(sig) == []


def test_vocabulary_covers_every_copi_vocab_participant_class():
    """No participant class declared in copi-vocab may be missing from the prompt."""
    from rdflib import Graph, OWL, RDF, URIRef

    offered = {t.iri for t in pv.participant_types()}
    vocab = Graph()
    vocab.parse(pv.VOCAB_PATH)
    declared = {str(c) for c in vocab.subjects(RDF.type, OWL.Class)
                if isinstance(c, URIRef) and str(c).startswith(pv.COPI_NS)}
    functions_and_processes = {
        f"{pv.COPI_NS}COPI_{n:07d}" for n in range(25, 37)   # 025-032 functions, 033-036 processes
    }
    assert declared - functions_and_processes <= offered


def test_known_types_present_and_stale_ones_gone():
    block = pv.format_participant_vocabulary_block()
    for name in ("PortionOfFluid", "HeatTransferMedium", "FuelPortion", "VisualIndication",
                 "Pressure", "MechanicalLoad", "MaterialEntity", "InformationContentEntity"):
        assert f"`{name}`" in block, name
    assert "ThermalEnergy" not in block
    # functions and processes are never offered as participants
    assert "FlowControlFunction" not in block and "SafetyReliefProcess" not in block


def test_system_prompt_closes_the_vocabulary():
    prompt = render_system_prompt()
    assert "<<PARTICIPANT_VOCABULARY>>" not in prompt
    assert "`HeatTransferMedium`" in prompt
    assert "MAY introduce a new type" not in prompt
    assert "new_participant_type_definitions" not in prompt
    assert "participant_vocabulary_gaps" in prompt


def test_build_enrichment_prompt_uses_rendered_system_prompt():
    system, _user = build_enrichment_prompt("control valve", definitions=[])
    assert system == render_system_prompt()


def test_role_defined_upstream_classes_are_neither_offered_nor_accepted(monkeypatch):
    IOF = pv.IOF
    role_defined = pv.role_defined_upstream_iris()
    assert f"{IOF}PieceOfEquipment" in role_defined
    assert f"{IOF}MaterialComponent" in role_defined
    assert f"{IOF}MaterialArtifact" not in role_defined   # function-defined: usable

    block = pv.format_participant_vocabulary_block()
    assert "`EquipmentItem`" not in block and "`MaterialComponent`" not in block
    assert "`MaterialArtifact`" in block

    monkeypatch.setattr(svc, "_validated_equipment_class_names", lambda: frozenset())
    sig = {"inputs": [{"type": "EquipmentItem"}, {"type": "MaterialArtifact"}], "outputs": []}
    assert svc.find_unvetted_participants(sig) == ["EquipmentItem"]
