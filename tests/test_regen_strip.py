def test_strip_source_definitions_removes_tagged_triples():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'enrichment'))
    from rdflib import Graph, URIRef, Literal
    from rdflib.namespace import SKOS

    g = Graph()
    subject = URIRef("https://example.org/TestClass")

    # Copyrighted — must be removed
    g.add((subject, SKOS.definition, Literal("[ISO 15926-4] A test class.", lang="en")))
    g.add((subject, SKOS.definition, Literal("[CFIHOS] Another def.", lang="en")))
    g.add((subject, SKOS.definition, Literal("[ISA 5.1] Tag abbreviation.", lang="en")))
    g.add((subject, SKOS.definition, Literal("[PPDM] A ppdm def.", lang="en")))

    # Clean — must survive
    g.add((subject, SKOS.definition, Literal("A clean AI-generated definition.", lang="en")))

    from regen_enriched_owl import strip_source_definitions
    result = strip_source_definitions(g)

    remaining = [str(o) for _, p, o in result if p == SKOS.definition]
    assert remaining == ["A clean AI-generated definition."], (
        f"Expected only clean def, got: {remaining}"
    )


def test_strip_source_definitions_returns_graph():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'enrichment'))
    from rdflib import Graph
    from regen_enriched_owl import strip_source_definitions
    g = Graph()
    result = strip_source_definitions(g)
    assert isinstance(result, Graph)
