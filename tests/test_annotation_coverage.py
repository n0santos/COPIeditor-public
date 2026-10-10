import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'enrichment'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from pathlib import Path
from rdflib import Graph, URIRef, Namespace, RDF, OWL, SKOS, Literal
from enrichment_service import generate_turtle, get_enrichment_db


def _get_exported_id():
    conn = get_enrichment_db()
    row = conn.execute(
        "SELECT id FROM enrichment WHERE status IN ('exported','validated') "
        "AND nl_definition_en IS NOT NULL AND nl_definition_en != '' LIMIT 1"
    ).fetchone()
    conn.close()
    assert row, "No exported/validated enrichment with nl_definition_en found"
    return row["id"]


def test_equipment_class_has_skos_definition():
    eid = _get_exported_id()
    ttl = generate_turtle(eid)
    assert "skos:definition" in ttl, (
        "generate_turtle() must emit skos:definition alongside iof-av:naturalLanguageDefinition"
    )


def test_skos_definition_matches_nl_definition_en():
    conn = get_enrichment_db()
    row = conn.execute(
        "SELECT nl_definition_en FROM enrichment WHERE status IN ('exported','validated') "
        "AND nl_definition_en IS NOT NULL AND nl_definition_en != '' LIMIT 1"
    ).fetchone()
    conn.close()
    eid = _get_exported_id()
    ttl = generate_turtle(eid)
    # The nl_definition_en value (first 30 chars) should appear after skos:definition
    prefix = row["nl_definition_en"][:30].replace('"', '\\"')
    assert prefix in ttl, f"Expected nl_definition_en prefix not found in skos:definition: {prefix!r}"


def test_stub_loader_injects_skos_definition(tmp_path, monkeypatch):
    """stub-definitions.json entries become skos:definition triples in the graph."""
    # Minimal turtle with one readable stub
    ttl = """
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix copi: <https://www.inf.ufrgs.br/ontologies/copi/> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    copi:AbsorptionFunction a owl:Class ; rdfs:label "absorption function"@en .
    """
    stub_defs = {"AbsorptionFunction": "A designed function borne by petroleum production equipment whose realization constitutes the absorption of a gaseous component into a liquid solvent."}

    stub_path = tmp_path / "stub-definitions.json"
    stub_path.write_text(json.dumps(stub_defs))

    g = Graph()
    g.parse(data=ttl, format="turtle")

    # Import and call the loader function (to be created in regen_enriched_owl.py)
    from regen_enriched_owl import inject_stub_definitions
    inject_stub_definitions(g, stub_path)

    COPI_NS = Namespace("https://www.inf.ufrgs.br/ontologies/copi/")
    iri = COPI_NS.AbsorptionFunction
    defs = list(g.objects(iri, SKOS.definition))
    assert len(defs) == 1
    assert str(defs[0]) == stub_defs["AbsorptionFunction"]


def test_stub_loader_skips_missing_class(tmp_path):
    """Stub entries for classes not in the graph are silently ignored."""
    ttl = """
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix copi: <https://www.inf.ufrgs.br/ontologies/copi/> .
    copi:SomeOtherClass a owl:Class .
    """
    stub_defs = {"NonExistentClass": "Some definition."}
    stub_path = tmp_path / "stub-definitions.json"
    stub_path.write_text(json.dumps(stub_defs))

    g = Graph()
    g.parse(data=ttl, format="turtle")

    from regen_enriched_owl import inject_stub_definitions
    inject_stub_definitions(g, stub_path)

    # No exception, no spurious triples
    assert len(list(g.subjects(SKOS.definition, None))) == 0
