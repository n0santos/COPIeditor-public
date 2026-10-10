# tests/test_turtle_numeric_iri_display.py
"""
remap_turtle_to_numeric_iris() is the display-only remap used by the /enrich/{id}/turtle
preview: readable-name COPI IRIs become numeric COPI_* IRIs, while comments, string
literals and unmapped names are left exactly as they were.
"""
import sys
from pathlib import Path

_ENRICHMENT_DIR = str(Path(__file__).parent.parent / "enrichment")
if _ENRICHMENT_DIR not in sys.path:
    sys.path.insert(0, _ENRICHMENT_DIR)

import enrichment_service as svc  # noqa: E402

BASE = "https://www.inf.ufrgs.br/ontologies/copi/"
MAP = {
    f"{BASE}ControlValve": f"{BASE}COPI_0000087",
    f"{BASE}Valve": f"{BASE}COPI_0000077",
    f"{BASE}ProcessControlledFlowProcess": f"{BASE}COPI_0000200",
}


def _remap(ttl: str) -> str:
    return svc.remap_turtle_to_numeric_iris(ttl, iri_map=MAP)


def test_prefixed_names_are_remapped_with_readable_comment():
    out = _remap(":ControlValve rdf:type owl:Class ;\n    rdfs:subClassOf :Valve ;")
    assert out.splitlines() == [
        ":COPI_0000087 rdf:type owl:Class ;  # ControlValve",
        "    rdfs:subClassOf :COPI_0000077 ;  # Valve",
    ]


def test_existing_comment_is_kept():
    line = "        owl:onProperty bfo:BFO_0000054 ;  # realizedIn"
    assert _remap(line) == line
    out = _remap("        owl:someValuesFrom :ProcessControlledFlowProcess  # target")
    assert out == "        owl:someValuesFrom :COPI_0000200  # ProcessControlledFlowProcess · target"


def test_comments_strings_and_unmapped_names_untouched():
    src = "\n".join([
        "### Equipment universal: ControlValve",
        '    rdfs:label "see :ControlValve and copi:Valve"@en ;',
        "    rdfs:subClassOf :UnmappedThing ;",
        "@prefix :         <https://www.inf.ufrgs.br/ontologies/copi/> .",
    ])
    assert _remap(src) == src


def test_upstream_redirects_leave_the_copi_namespace():
    """copi-iri-map.tsv sends some canonical names to BFO / IOF-Core (ODR-022 §8.4).
    The preview must show them there — never as a COPI-prefixed class."""
    upstream = {
        **MAP,
        f"{BASE}MeasurementProcess": "https://spec.industrialontologies.org/ontology/construct/MeasurementProcess",
        f"{BASE}MaterialEntity": "http://purl.obolibrary.org/obo/BFO_0000040",
    }
    src = "    owl:someValuesFrom :MeasurementProcess ;\n:MaterialEntity rdf:type owl:Class ."
    out = svc.remap_turtle_to_numeric_iris(src, iri_map=upstream)
    assert out.splitlines() == [
        "    owl:someValuesFrom iof-core:MeasurementProcess ;",
        "bfo:BFO_0000040 rdf:type owl:Class .  # MaterialEntity",
    ]


def test_copi_prefix_and_full_iri_forms():
    out = _remap(f"copi:Valve rdfs:subClassOf <{BASE}ControlValve> .")
    assert out == f"copi:COPI_0000077 rdfs:subClassOf <{BASE}COPI_0000087> .  # Valve, ControlValve"
