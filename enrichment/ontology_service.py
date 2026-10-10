"""
Imported-ontology browser service.

Parses BFO 2020 (TTL) and IOF-Core (RDF/XML) into an in-memory index so the
web app can browse classes and their annotations without hitting the DB.

Public API
----------
  get_class_list()      -> list[dict]   # sorted list for the left-panel tree
  get_class(uri)        -> dict | None  # full annotations for the detail panel
  search_classes(q)     -> list[dict]   # substring search on label / definition
  get_property_list()   -> list[dict]   # ObjectProperty / DatatypeProperty / AnnotationProperty
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

import rdflib
from rdflib import OWL, RDF, RDFS, SKOS, URIRef, Namespace, Literal

# ---------------------------------------------------------------------------
# Namespaces
# ---------------------------------------------------------------------------
IOF_AV  = Namespace("https://spec.industrialontologies.org/ontology/annotation/")
DC      = Namespace("http://purl.org/dc/elements/1.1/")
OBO     = Namespace("http://purl.obolibrary.org/obo/")

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------
_BASE = Path(__file__).parent
BFO_PATH = _BASE / "ontologies" / "bfo-2020.ttl"
IOF_PATH = _BASE / "ontologies" / "IOF-Core.rdf"

# ---------------------------------------------------------------------------
# Internal data
# ---------------------------------------------------------------------------
# uri -> class record
_INDEX: dict[str, dict] = {}
# Populated lazily; the first call to get_class_list() triggers _build_index()
_BUILT = False

# uri -> property record
_PROP_INDEX: dict[str, dict] = {}
_PROP_BUILT = False


def _str(node) -> str:
    """Return string value of a literal or URI node, empty string if None."""
    if node is None:
        return ""
    if isinstance(node, Literal):
        return str(node)
    return str(node)


def _short(uri: str) -> str:
    """Return a human-readable short ID (fragment or last path segment)."""
    for sep in ("#", "/"):
        if sep in uri:
            return uri.rsplit(sep, 1)[-1]
    return uri


def _build_index() -> None:
    global _INDEX, _BUILT

    records: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # 1. Parse BFO
    # ------------------------------------------------------------------
    bfo = rdflib.Graph()
    if BFO_PATH.exists():
        bfo.parse(str(BFO_PATH), format="turtle")

    for cls in bfo.subjects(RDF.type, OWL.Class):
        if not isinstance(cls, URIRef):
            continue
        uri = str(cls)
        label  = _str(bfo.value(cls, RDFS.label))
        ann = {
            "definition":  _str(bfo.value(cls, SKOS.definition)),
            "example":     _str(bfo.value(cls, SKOS.example)),
            "scope_note":  _str(bfo.value(cls, SKOS.scopeNote)),
            "alt_label":   _str(bfo.value(cls, SKOS.altLabel)),
            "identifier":  _str(bfo.value(cls, DC.identifier)),
        }
        parents   = [str(p) for p in bfo.objects(cls, RDFS.subClassOf)
                     if isinstance(p, URIRef)]
        disjoints = [str(d) for d in bfo.objects(cls, OWL.disjointWith)
                     if isinstance(d, URIRef)]
        records[uri] = {
            "uri":       uri,
            "short_id":  _short(uri),
            "label":     label or _short(uri),
            "source":    "BFO",
            "bfo":       ann,
            "iof":       {},
            "parents":   parents,
            "children":  [],
            "disjoints": disjoints,
        }

    # ------------------------------------------------------------------
    # 2. Parse IOF-Core
    # ------------------------------------------------------------------
    iof = rdflib.Graph()
    if IOF_PATH.exists():
        iof.parse(str(IOF_PATH), format="xml")

    for cls in iof.subjects(RDF.type, OWL.Class):
        if not isinstance(cls, URIRef):
            continue
        uri = str(cls)
        label  = _str(iof.value(cls, RDFS.label))

        def _ann(prop_name: str) -> str:
            return _str(iof.value(cls, IOF_AV[prop_name]))

        def _skos(prop) -> str:
            return _str(iof.value(cls, prop))

        ann = {
            "natural_language_definition":          _ann("naturalLanguageDefinition"),
            "semi_formal_nl_definition":            _ann("semiFormalNaturalLanguageDefinition"),
            "first_order_logic_definition":         _ann("firstOrderLogicDefinition"),
            "first_order_logic_axiom":              _ann("firstOrderLogicAxiom"),
            "semi_formal_nl_axiom":                 _ann("semiFormalNaturalLanguageAxiom"),
            "explanatory_note":                     _ann("explanatoryNote"),
            "example":                              _skos(SKOS.example),
            "counter_example":                      _ann("counterExample"),
            "primitive_rationale":                  _ann("primitiveRationale"),
            "is_primitive":                         _ann("isPrimitive"),
            "synonym":                              _ann("synonym"),
            "abbreviation":                         _ann("abbreviation"),
            "adapted_from":                         _ann("adaptedFrom"),
            "usage_note":                           _ann("usageNote"),
            "maturity":                             _ann("maturity"),
        }
        parents   = [str(p) for p in iof.objects(cls, RDFS.subClassOf)
                     if isinstance(p, URIRef)]
        disjoints = [str(d) for d in iof.objects(cls, OWL.disjointWith)
                     if isinstance(d, URIRef)]

        if uri in records:
            # BFO URI referenced in IOF — merge
            records[uri]["source"]   = "BOTH"
            records[uri]["iof"]      = ann
            records[uri]["parents"]  = list(set(records[uri]["parents"] + parents))
            records[uri]["disjoints"] = list(set(records[uri]["disjoints"] + disjoints))
            if label and not records[uri]["label"]:
                records[uri]["label"] = label
        else:
            records[uri] = {
                "uri":       uri,
                "short_id":  _short(uri),
                "label":     label or _short(uri),
                "source":    "IOF-Core",
                "bfo":       {},
                "iof":       ann,
                "parents":   parents,
                "children":  [],
                "disjoints": disjoints,
            }

    # ------------------------------------------------------------------
    # 3. Build parent → children edges
    # ------------------------------------------------------------------
    for uri, rec in records.items():
        for parent_uri in rec["parents"]:
            if parent_uri in records:
                records[parent_uri]["children"].append(uri)

    _INDEX = records
    _BUILT = True


def _ensure() -> None:
    if not _BUILT:
        _build_index()


def _build_property_index() -> None:
    """Extract ObjectProperty, DatatypeProperty, AnnotationProperty from both ontologies."""
    global _PROP_INDEX, _PROP_BUILT
    props: dict[str, dict] = {}

    _PROP_TYPES = {
        OWL.ObjectProperty:     "ObjectProperty",
        OWL.DatatypeProperty:   "DatatypeProperty",
        OWL.AnnotationProperty: "AnnotationProperty",
    }

    for owl_file, fmt, src_label in [
        (BFO_PATH, "turtle", "BFO"),
        (IOF_PATH, "xml",    "IOF-Core"),
    ]:
        if not owl_file.exists():
            continue
        g = rdflib.Graph()
        g.parse(str(owl_file), format=fmt)
        for prop_type, type_label in _PROP_TYPES.items():
            for prop in g.subjects(RDF.type, prop_type):
                if not isinstance(prop, URIRef):
                    continue
                uri = str(prop)
                label = _str(g.value(prop, RDFS.label))
                definition = (
                    _str(g.value(prop, SKOS.definition))
                    or _str(g.value(prop, IOF_AV["naturalLanguageDefinition"]))
                )
                domain_node = g.value(prop, RDFS.domain)
                range_node  = g.value(prop, RDFS.range)
                domain = _short(str(domain_node)) if domain_node else ""
                range_ = _short(str(range_node))  if range_node  else ""
                parents = [str(p) for p in g.objects(prop, RDFS.subPropertyOf)
                           if isinstance(p, URIRef)]
                if uri in props:
                    # merge: same property referenced in both ontologies
                    props[uri]["source"] = "BOTH"
                    if not props[uri]["definition"] and definition:
                        props[uri]["definition"] = definition
                else:
                    props[uri] = {
                        "uri":       uri,
                        "short_id":  _short(uri),
                        "label":     label or _short(uri),
                        "prop_type": type_label,
                        "source":    src_label,
                        "definition": definition,
                        "domain":    domain,
                        "range":     range_,
                        "parents":   parents,
                    }

    _PROP_INDEX = props
    _PROP_BUILT = True


def _ensure_props() -> None:
    if not _PROP_BUILT:
        _build_property_index()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_class_list() -> list[dict]:
    """Return lightweight list for the left panel (label, uri, source)."""
    _ensure()
    rows = [
        {
            "uri":    r["uri"],
            "label":  r["label"],
            "source": r["source"],
            "short_id": r["short_id"],
        }
        for r in _INDEX.values()
    ]
    return sorted(rows, key=lambda r: r["label"].lower())


def get_class(uri: str) -> Optional[dict]:
    """Return full record for one class, or None if not found."""
    _ensure()
    rec = _INDEX.get(uri)
    if rec is None:
        return None
    # Enrich children with labels
    result = dict(rec)
    result["children_detail"] = [
        {"uri": c, "label": _INDEX[c]["label"], "source": _INDEX[c]["source"]}
        for c in rec["children"] if c in _INDEX
    ]
    result["parents_detail"] = [
        {"uri": p, "label": _INDEX[p]["label"], "source": _INDEX[p]["source"]}
        for p in rec["parents"] if p in _INDEX
    ]
    result["disjoints_detail"] = [
        {"uri": d, "label": _INDEX[d]["label"], "source": _INDEX[d]["source"]}
        for d in rec.get("disjoints", []) if d in _INDEX
    ]
    return result


def get_property_list() -> list[dict]:
    """Return sorted list of OWL properties from BFO and IOF-Core."""
    _ensure_props()
    return sorted(_PROP_INDEX.values(), key=lambda r: r["label"].lower())


def search_classes(q: str) -> list[dict]:
    """Case-insensitive substring search on label and definitions."""
    _ensure()
    q_low = q.lower()
    results = []
    for rec in _INDEX.values():
        haystack = (
            rec["label"].lower() + " "
            + rec["bfo"].get("definition", "").lower() + " "
            + rec["iof"].get("natural_language_definition", "").lower()
        )
        if q_low in haystack:
            results.append({
                "uri":    rec["uri"],
                "label":  rec["label"],
                "source": rec["source"],
                "short_id": rec["short_id"],
            })
    return sorted(results, key=lambda r: (
        not r["label"].lower().startswith(q_low),
        r["label"].lower()
    ))
