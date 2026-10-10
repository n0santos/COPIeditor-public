"""
The genus/component stub emitter at the end of generate_combined_turtle() must use
class_annotation like every other non-equipment class.  Without it, a stub such as
FluidPort or SubsurfaceAccessProcess shipped with labels only and failed APV's
ClassMinAnnotationCoverage (naturalLanguageDefinition, en and pt-br).
"""

import sys
import json
import importlib
from pathlib import Path

_ENRICHMENT_DIR = str(Path(__file__).parent.parent / "enrichment")
if _ENRICHMENT_DIR not in sys.path:
    sys.path.insert(0, _ENRICHMENT_DIR)


def test_undeclared_stub_gets_definitions_from_class_annotation(tmp_path, monkeypatch):
    import enrichment_service as svc
    importlib.reload(svc)
    monkeypatch.setattr(svc, "ENRICHMENT_DB_PATH", tmp_path / "enr.db")
    svc.init_enrichment_schema()
    conn = svc.get_enrichment_db()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS additional_parents "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, cluster_label TEXT, parent_iri TEXT)"
    )
    conn.execute(
        "INSERT INTO enrichment (cluster_label, status, created_at, updated_at, genus, genus_bfo_root, "
        "function_name, process_name, process_parent, axiom_mode, differentia_expression, process_signature) "
        "VALUES ('discharge port', 'validated', datetime('now'), datetime('now'), 'FluidPort', 'MaterialArtifact', "
        "'DischargeFunction', 'DischargeProcess', 'FlowControl', 'necessary', '∃bearerOf.DischargeFunction', ?)",
        (json.dumps({"inputs": [], "outputs": []}),),
    )
    conn.execute(
        "INSERT INTO class_annotation (class_name, kind, definition_en, definition_pt) VALUES "
        "('FluidPort', 'part', 'An opening through which fluid enters or leaves.', 'Uma abertura pela qual o fluido entra ou sai.')"
    )
    conn.commit()
    conn.close()

    ttl = svc.generate_combined_turtle()
    start = ttl.index(":FluidPort rdf:type owl:Class")
    block = ttl[start:ttl.index(" .\n", start)]
    assert 'iof-av:naturalLanguageDefinition "An opening through which fluid enters or leaves."@en' in block
    assert 'iof-av:naturalLanguageDefinition "Uma abertura pela qual o fluido entra ou sai."@pt-br' in block
    assert block.count("rdfs:label") <= 2  # one en label, at most one pt-br label
    assert block.count("rdfs:label") == len([l for l in block.split("\n") if "rdfs:label" in l])
