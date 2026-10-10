# tests/test_upstream_name_allocation_guard.py
"""
A BFO / IOF-Core class must never be minted a COPI IRI. When the generator emits a
canonical upstream name under the copi namespace (e.g. :MeasurementProcess) with no
redirect row in copi-iri-map.tsv, allocate_missing_iris() must refuse instead of
allocating COPI_NNNNNNN for it.
"""
import sys
from pathlib import Path

import pytest
from rdflib import Graph, OWL, RDF, URIRef

_SCRIPTS = str(Path(__file__).parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import regen_enriched_owl as regen  # noqa: E402

NS = regen.COPI_NS


def _graph(*names: str) -> Graph:
    g = Graph()
    for n in names:
        g.add((URIRef(NS + n), RDF.type, OWL.Class))
    return g


def _map_file(tmp_path, monkeypatch) -> Path:
    p = tmp_path / "copi-iri-map.tsv"
    p.write_text(f"old_iri\tnew_iri\n{NS}Valve\t{NS}COPI_0000077\n", encoding="utf-8")
    monkeypatch.setattr(regen, "IRI_MAP_PATH", p)
    return p


@pytest.mark.parametrize("name", [
    "MeasurementProcess",   # IOF-Core local name
    "MaterialArtifact",     # IOF-Core local name
    "MaterialEntity",       # BFO label "material entity" (IRI is BFO_0000040)
])
def test_upstream_name_is_not_allocated(tmp_path, monkeypatch, name):
    p = _map_file(tmp_path, monkeypatch)
    before = p.read_text(encoding="utf-8")
    with pytest.raises(regen.StubPolicyError, match=name):
        regen.allocate_missing_iris(_graph(name, "Aerator"), regen._load_iri_map())
    assert p.read_text(encoding="utf-8") == before, "nothing may be appended on refusal"


def test_copi_names_are_still_allocated(tmp_path, monkeypatch):
    p = _map_file(tmp_path, monkeypatch)
    out = regen.allocate_missing_iris(_graph("Aerator"), regen._load_iri_map())
    assert out[NS + "Aerator"] == NS + "COPI_0000078"
    assert f"{NS}Aerator\t{NS}COPI_0000078" in p.read_text(encoding="utf-8")


def test_current_map_has_no_copi_iri_for_an_upstream_name():
    """Ratchet over the real registry: every upstream-named row must redirect upstream."""
    upstream = regen.upstream_class_names()
    offenders = [
        (old, new) for old, new in regen._load_iri_map().items()
        if old.startswith(NS) and old[len(NS):] in upstream and new.startswith(NS)
    ]
    assert offenders == []
