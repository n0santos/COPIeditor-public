"""
Ontology verification service.

Provides four independent checks that can be run from the /enrich/verify page:

  run_oops_check(ttl)        — OOPS! Ontology Pitfall Scanner (REST API, with BFO/IOF-Core merged)
  run_foops_check(iri)       — FOOPS! FAIR ontology evaluation (REST API)
  run_consistency_check(ttl) — OWL 2 DL consistency via HermiT (owlready2)
  run_apv_check(ttl)         — APV annotation property verification (local)
  check_undeclared_classes(ttl) — local scan for COPI IRIs used but never declared
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import requests
from rdflib import Graph, OWL, RDF, URIRef

logger = logging.getLogger(__name__)

_COPI_NS  = "https://www.inf.ufrgs.br/ontologies/copi/"
_ONTO_DIR = Path(__file__).parent / "ontologies"
_BFO_PATH = _ONTO_DIR / "bfo-2020.ttl"
_IOF_PATH = _ONTO_DIR / "IOF-Core.rdf"
_COPI_CORE_PATH  = _ONTO_DIR / "copi-context" / "copi-core.ttl"
_COPI_VOCAB_PATH = _ONTO_DIR / "copi-context" / "copi-vocab.ttl"


def merge_base_modules(content: str, fmt: str = "turtle") -> str:
    """
    Merge copi-core.ttl + copi-vocab.ttl into an ontology document that doesn't
    already import them (the enrichment-table-only turtle, or the final RDF/XML
    written to components/copi-enriched.owl -- pass fmt="xml" for the latter).

    check_undeclared_classes()/run_consistency_check()/run_oops_check() (when
    called on the enrichment-table turtle alone) predate the copi-core/copi-vocab
    module split (CLAUDE.md "COPI component structure") and don't know those base
    modules exist, so any reference to a vocab-owned class (e.g. COPI_0000058/59,
    or the ODR-020 qualities COPI_0000383-385) false-positives as "undeclared" or
    reasons incorrectly without their axioms. verify_owl.sh already merges these
    two files correctly for its own reasoning step; callers checking enrichment-DB
    content in isolation should do the same before running those three checks.

    Also strips owl:versionIRI triples: those are ontology-metadata IRIs (dated
    release URLs), not classes, and check_undeclared_classes' namespace-prefix
    match can't otherwise tell them apart from a real undeclared class reference.
    """
    g = Graph()
    g.parse(data=content, format=fmt)
    if _COPI_CORE_PATH.exists():
        g.parse(str(_COPI_CORE_PATH), format="turtle")
    if _COPI_VOCAB_PATH.exists():
        g.parse(str(_COPI_VOCAB_PATH), format="turtle")
    for t in list(g.triples((None, OWL.versionIRI, None))):
        g.remove(t)
    return g.serialize(format="turtle")

# ── OOPS! ─────────────────────────────────────────────────────────────────────

_OOPS_URL = "https://oops.linkeddata.es/rest"
_OOPS_NS  = "http://www.oeg-upm.net/oops"

OOPS_IMPORTANCE_ORDER = {"Critical": 0, "Important": 1, "Minor": 2}


@dataclass
class OopsPitfall:
    code: str
    name: str
    description: str
    importance: str   # Critical | Important | Minor
    affected: list[str] = field(default_factory=list)

    @property
    def importance_level(self) -> int:
        return OOPS_IMPORTANCE_ORDER.get(self.importance, 99)


@dataclass
class OopsResult:
    ok: bool
    pitfalls: list[OopsPitfall] = field(default_factory=list)
    error: str | None = None
    elapsed: float = 0.0

    @property
    def counts(self) -> dict[str, int]:
        c = {"Critical": 0, "Important": 0, "Minor": 0}
        for p in self.pitfalls:
            c[p.importance] = c.get(p.importance, 0) + 1
        return c


def _merge_imports(ttl: str) -> str:
    """
    Return RDF/XML with BFO and IOF-Core merged inline and owl:imports removed.

    Merging the imported ontologies means OOPS sees all BFO/IOF-Core class
    declarations and won't produce false P34/P35 positives for them — only
    genuinely undeclared COPI classes will be flagged.
    """
    g = Graph()
    g.parse(data=ttl, format="turtle")
    if _BFO_PATH.exists():
        g.parse(str(_BFO_PATH), format="turtle")
    if _IOF_PATH.exists():
        g.parse(str(_IOF_PATH), format="xml")
    for s, p, o in list(g.triples((None, OWL.imports, None))):
        g.remove((s, p, o))
    return g.serialize(format="xml")


def check_undeclared_classes(ttl: str) -> dict:
    """
    Local scan: find COPI-namespace IRIs that appear in axioms but are never
    declared as owl:Class, owl:ObjectProperty, or owl:DatatypeProperty.

    Returns {"ok": bool, "undeclared": list[str], "error": str|None}.
    """
    g = Graph()
    try:
        g.parse(data=ttl, format="turtle")
    except Exception as exc:
        return {"ok": False, "undeclared": [], "error": str(exc)}

    _OWL_ENTITY_TYPES = {OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty,
                         OWL.AnnotationProperty, OWL.NamedIndividual, OWL.Ontology}
    declared = {
        str(s)
        for t in _OWL_ENTITY_TYPES
        for s in g.subjects(RDF.type, t)
        if isinstance(s, URIRef)
    }

    referenced: set[str] = set()
    for s, _p, o in g:
        for node in (s, o):
            if isinstance(node, URIRef) and str(node).startswith(_COPI_NS):
                referenced.add(str(node))

    undeclared = sorted(referenced - declared)
    return {"ok": len(undeclared) == 0, "undeclared": undeclared, "error": None}


def run_oops_check(ttl: str, timeout: int = 120) -> OopsResult:
    t0 = time.time()
    try:
        rdfxml = _merge_imports(ttl)
    except Exception as exc:
        return OopsResult(ok=False, error=f"TTL parse error: {exc}")

    xml_body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<OOPSRequest>"
        "<OntologyURI></OntologyURI>"
        f"<OntologyContent><![CDATA[{rdfxml}]]></OntologyContent>"
        "<Pitfalls></Pitfalls>"
        "<OutputFormat>XML</OutputFormat>"
        "</OOPSRequest>"
    )

    try:
        resp = requests.post(
            _OOPS_URL,
            data=xml_body.encode("utf-8"),
            headers={"Content-Type": "application/xml"},
            timeout=timeout,
        )
        resp.raise_for_status()
    except Exception as exc:
        return OopsResult(ok=False, error=f"OOPS request failed: {exc}", elapsed=time.time() - t0)

    return _parse_oops_xml(resp.text, elapsed=time.time() - t0)


def _parse_oops_xml(xml_text: str, elapsed: float) -> OopsResult:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        return OopsResult(ok=False, error=f"OOPS XML parse error: {exc}", elapsed=elapsed)

    # Unexpected error response
    ns = {"oops": _OOPS_NS, "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"}
    if root.find(f"rdf:Description[@rdf:about='{_OOPS_NS}/unexpected_error']", ns) is not None:
        return OopsResult(ok=False, error="OOPS returned an unexpected error.", elapsed=elapsed)

    pitfalls: list[OopsPitfall] = []
    for p_el in root.findall(f"{{{_OOPS_NS}}}Pitfall"):
        def _t(tag: str) -> str:
            el = p_el.find(f"{{{_OOPS_NS}}}{tag}")
            return el.text.strip() if el is not None and el.text else ""

        affected = [
            el.text.strip()
            for el in p_el.findall(f"{{{_OOPS_NS}}}Affects/{{{_OOPS_NS}}}AffectedElement")
            if el.text
        ]
        # deduplicate preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for a in affected:
            if a not in seen:
                seen.add(a)
                deduped.append(a)

        code = _t("Code")
        # P08 (missing annotations) flags imported IOF-Core and BFO elements because
        # their local RDF copies carry rdfs:label but not rdfs:comment. P05 (wrong
        # inverse relationships) and P29 (wrong transitive relationships) likewise
        # fire on BFO/IOF-Core's own object-property axioms merged in by
        # _merge_imports() (needed to avoid false P34/P35 positives on those same
        # upstream classes) -- COPI declares zero custom inverse/transitive
        # properties itself (copi_relation is empty; COPI_0000002 carries neither
        # owl:inverseOf nor owl:TransitiveProperty), so these are exclusively
        # upstream findings COPI cannot fix. Strip external IRIs from the affected
        # list for all three codes; if nothing COPI-own remains, skip the pitfall
        # entirely rather than hard-blocking on content outside this project.
        if code in ("P08", "P05", "P29"):
            _EXTERNAL = (
                "https://spec.industrialontologies.org/ontology/construct/",
                "http://purl.obolibrary.org/obo/",
            )
            deduped = [a for a in deduped if not any(a.startswith(ns) for ns in _EXTERNAL)]
            if not deduped:
                continue

        pitfalls.append(OopsPitfall(
            code=code,
            name=_t("Name"),
            description=_t("Description"),
            importance=_t("Importance"),
            affected=deduped,
        ))

    pitfalls.sort(key=lambda p: p.importance_level)
    return OopsResult(ok=True, pitfalls=pitfalls, elapsed=elapsed)


# ── FOOPS! ────────────────────────────────────────────────────────────────────

_FOOPS_URL = "https://foops.linkeddata.es/assessOntology"

FOOPS_CATEGORIES = ["Findable", "Accessible", "Interoperable", "Reusable"]


@dataclass
class FoopsCheck:
    id: str
    abbreviation: str
    title: str
    principle_id: str
    category_id: str
    status: str   # ok | warning | error | not_applicable | failed
    explanation: str
    total_tests_run: int = 0
    total_passed_tests: int = 0


@dataclass
class FoopsResult:
    ok: bool
    ontology_uri: str = ""
    ontology_title: str = ""
    overall_score: float | None = None
    checks: list[FoopsCheck] = field(default_factory=list)
    error: str | None = None
    elapsed: float = 0.0

    def checks_by_category(self) -> dict[str, list[FoopsCheck]]:
        result: dict[str, list[FoopsCheck]] = {c: [] for c in FOOPS_CATEGORIES}
        for chk in self.checks:
            cat = chk.category_id
            if cat not in result:
                result[cat] = []
            result[cat].append(chk)
        return result

    def score_for_category(self, category: str) -> float | None:
        checks = [c for c in self.checks if c.category_id == category and c.total_tests_run > 0]
        if not checks:
            return None
        passed = sum(c.total_passed_tests for c in checks)
        total  = sum(c.total_tests_run    for c in checks)
        return round(passed / total, 2) if total else None


def run_foops_check(ontology_iri: str) -> FoopsResult:
    t0 = time.time()
    try:
        resp = requests.post(
            _FOOPS_URL,
            json={"ontologyUri": ontology_iri},
            headers={"Content-Type": "application/json;charset=UTF-8", "Accept": "application/json;charset=UTF-8"},
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return FoopsResult(ok=False, error=str(exc), elapsed=time.time() - t0)

    checks = [
        FoopsCheck(
            id=c.get("id", ""),
            abbreviation=c.get("abbreviation", ""),
            title=c.get("title", ""),
            principle_id=c.get("principle_id", ""),
            category_id=c.get("category_id", ""),
            status=c.get("status", ""),
            explanation=c.get("explanation", ""),
            total_tests_run=int(c.get("total_tests_run", 0)),
            total_passed_tests=int(c.get("total_passed_tests", 0)),
        )
        for c in data.get("checks", [])
    ]

    # Guard: FOOPS returns a valid 200 with a degenerate ~4% score (only the URI
    # syntax check passes) and title "unknown" when it could NOT retrieve/parse
    # the ontology at the IRI — e.g. the host was momentarily unreachable or the
    # remote fetch timed out. That is not a real FAIR score; surface it as a
    # transient fetch error so the UI prompts a retry instead of showing "4%".
    title = (data.get("ontology_title") or "").strip()
    tests_passed = sum(c.total_passed_tests for c in checks)
    if title.lower() in ("", "unknown") and tests_passed <= 1:
        return FoopsResult(
            ok=False,
            error=(
                f"FOOPS could not retrieve or parse the ontology at {ontology_iri}. "
                "The ontology host may be temporarily unavailable or FOOPS's fetch "
                "timed out — please try again in a moment."
            ),
            elapsed=time.time() - t0,
        )

    return FoopsResult(
        ok=True,
        ontology_uri=data.get("ontology_URI", ontology_iri),
        ontology_title=data.get("ontology_title", ""),
        overall_score=data.get("overall_score"),
        checks=checks,
        elapsed=time.time() - t0,
    )


def _strip_imports(ttl: str) -> str:
    """Parse Turtle, remove owl:imports triples, return RDF/XML for owlready2."""
    g = Graph()
    g.parse(data=ttl, format="turtle")
    for s, p, o in list(g.triples((None, OWL.imports, None))):
        g.remove((s, p, o))
    return g.serialize(format="xml")


# ── OWL Consistency (HermiT via owlready2) ───────────────────────────────────

@dataclass
class InferredAxiom:
    cls_iri: str       # the class the inference applies to
    cls_label: str     # short local name
    kind: str          # "subClassOf" | "equivalentClass" | "unsatisfiable"
    target_iri: str    # the inferred superclass / equivalent / "owl:Nothing"
    target_label: str  # short local name of target


@dataclass
class ConsistencyResult:
    ok: bool
    consistent: bool | None = None
    inconsistent_classes: list[str] = field(default_factory=list)
    inferences: list[InferredAxiom] = field(default_factory=list)
    class_count: int = 0
    elapsed: float = 0.0
    error: str | None = None
    log_lines: list[str] = field(default_factory=list)


def _short(iri: str) -> str:
    """Return the local name of an IRI (after # or last /)."""
    if "#" in iri:
        return iri.split("#")[-1]
    return iri.rstrip("/").split("/")[-1]


def run_consistency_check(ttl: str) -> ConsistencyResult:
    t0 = time.time()
    try:
        import owlready2
    except ImportError:
        return ConsistencyResult(ok=False, error="owlready2 not installed. Run: pip install owlready2")

    try:
        rdfxml = _strip_imports(ttl)
    except Exception as exc:
        return ConsistencyResult(ok=False, error=f"TTL parse error: {exc}")

    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".owl", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write(rdfxml)
            tmp = f.name

        import io, contextlib
        log_capture = io.StringIO()

        owlready2.JAVA_EXE = "java"
        world = owlready2.World()
        onto = world.get_ontology(f"file://{tmp}").load()

        # Snapshot explicit superclasses BEFORE reasoning
        # Only track copi: classes (ignore imported BFO/IOF-Core classes)
        copi_ns = "https://www.inf.ufrgs.br/ontologies/copi/"
        pre: dict[str, set[str]] = {}
        pre_equiv: dict[str, set[str]] = {}
        for cls in onto.classes():
            if str(cls.iri).startswith(copi_ns):
                pre[str(cls.iri)] = {
                    str(s.iri) if hasattr(s, "iri") else str(s)
                    for s in cls.is_a
                    if hasattr(s, "iri")
                }
                pre_equiv[str(cls.iri)] = {
                    str(s.iri) if hasattr(s, "iri") else str(s)
                    for s in cls.equivalent_to
                    if hasattr(s, "iri")
                }

        class_count = len(list(onto.classes()))

        with contextlib.redirect_stdout(log_capture):
            with onto:
                owlready2.sync_reasoner_hermit(
                    infer_property_values=True,
                    debug=0,
                )

        inconsistent_iris = [str(c.iri) for c in world.inconsistent_classes()]

        # Collect inferences: new superclasses and equivalent classes added by reasoner
        inferences: list[InferredAxiom] = []

        # Unsatisfiable classes
        for iri in inconsistent_iris:
            inferences.append(InferredAxiom(
                cls_iri=iri, cls_label=_short(iri),
                kind="unsatisfiable",
                target_iri="owl:Nothing", target_label="Nothing",
            ))

        # New subClassOf and equivalentClass inferences for copi: classes
        for cls in onto.classes():
            cls_iri = str(cls.iri)
            if not cls_iri.startswith(copi_ns):
                continue
            cls_label = _short(cls_iri)

            # New superclasses (only named classes, not anonymous restrictions)
            post_is_a = {
                str(s.iri) for s in cls.is_a
                if hasattr(s, "iri") and str(s.iri) != cls_iri
            }
            for new_sup in sorted(post_is_a - pre.get(cls_iri, set())):
                # Skip owl:Thing (trivially inferred for everything)
                if new_sup in ("http://www.w3.org/2002/07/owl#Thing",):
                    continue
                inferences.append(InferredAxiom(
                    cls_iri=cls_iri, cls_label=cls_label,
                    kind="subClassOf",
                    target_iri=new_sup, target_label=_short(new_sup),
                ))

            # New equivalent classes
            post_equiv = {
                str(s.iri) for s in cls.equivalent_to
                if hasattr(s, "iri") and str(s.iri) != cls_iri
            }
            for new_eq in sorted(post_equiv - pre_equiv.get(cls_iri, set())):
                inferences.append(InferredAxiom(
                    cls_iri=cls_iri, cls_label=cls_label,
                    kind="equivalentClass",
                    target_iri=new_eq, target_label=_short(new_eq),
                ))

        log_lines = [l for l in log_capture.getvalue().splitlines() if l.strip()]

        return ConsistencyResult(
            ok=True,
            consistent=len(inconsistent_iris) == 0,
            inconsistent_classes=inconsistent_iris,
            inferences=inferences,
            class_count=class_count,
            elapsed=time.time() - t0,
            log_lines=log_lines,
        )

    except Exception as exc:
        return ConsistencyResult(ok=False, error=str(exc), elapsed=time.time() - t0)
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)


# ── CQ Coverage ──────────────────────────────────────────────────────────────

@dataclass
class CQResult:
    total: int
    answered: int
    partial: int
    open: int
    rows: list[dict]


def get_cq_summary(enrichment_db_path: str) -> CQResult:
    import sqlite3
    conn = sqlite3.connect(enrichment_db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, text, formal_expr, status, linked_classes, notes FROM competency_questions ORDER BY status, id"
    ).fetchall()
    conn.close()

    dicts = [dict(r) for r in rows]
    return CQResult(
        total=len(dicts),
        answered=sum(1 for r in dicts if r["status"] == "answered"),
        partial=sum(1 for r in dicts if r["status"] == "partial"),
        open=sum(1 for r in dicts if r["status"] == "open"),
        rows=dicts,
    )


# ── APV ───────────────────────────────────────────────────────────────────────

_CHECK_PURPOSES = {
    "ClassURIFormationRule": "Checks whether each class IRI follows the configured naming pattern.",
    "RelationURIFormationRule": "Checks whether relation and annotation property IRIs follow the configured naming pattern.",
    "InstanceURIFormationRule": "Checks whether instance IRIs follow the configured naming pattern declared in the ontology.",
    "GlobalMinLanguageCoverage": "Captures the required language tags used by annotation coverage checks.",
    "ClassMinAnnotationCoverage": "Checks whether every class has the required annotation properties with the expected cardinality.",
    "RelationMinAnnotationCoverage": "Checks whether every relation has the required annotation properties.",
    "InstanceMinAnnotationCoverage": "Checks whether every instance has the required annotation properties.",
    "MinAnnotationLength": "Checks whether annotation values meet the configured minimum character length.",
    "MaxAnnotationLength": "Checks whether annotation values stay within the configured maximum character length.",
    "AnnotationRegularExpression": "Checks whether annotation values match the configured syntax or text pattern.",
    "InstanceOfMinAnnotationCoverage": "Checks whether instances of specific classes carry the required annotation properties.",
}


def run_apv_check(ttl: str) -> dict:
    """
    Run APV annotation property verification against the combined Turtle export.

    Returns a dict with keys:
      - constraints: dict of APV constraint values read from the ontology
      - violations:  list of {check, parameter, violations, purpose} dicts
      - violation_count: total number of violations across all checks
      - error: error message string if the check failed entirely (else None)
    """
    import sys
    import os
    import tempfile

    # Make the local apv package importable
    _apv_path = os.path.join(os.path.dirname(__file__))
    if _apv_path not in sys.path:
        sys.path.insert(0, _apv_path)

    try:
        from apv.sparql_client import SparqlClient
        from apv.quality_criteria import (
            retrieve_annotation_regular_expression,
            retrieve_class_annotation_coverage,
            retrieve_class_uri_formation_rule,
            retrieve_instance_annotation_coverage,
            retrieve_instance_of_annotation_coverage,
            retrieve_instance_uri_formation_rule,
            retrieve_language_tags,
            retrieve_max_annotation_length,
            retrieve_min_annotation_length,
            retrieve_relation_annotation_coverage,
            retrieve_relation_uri_formation_rule,
        )
        from apv.cli import _build_constraints, _build_results
    except ImportError as exc:
        return {"constraints": {}, "violations": [], "violation_count": 0,
                "error": f"APV package not available: {exc}"}

    try:
        with tempfile.NamedTemporaryFile(suffix=".ttl", mode="w", delete=False, encoding="utf-8") as f:
            f.write(ttl)
            tmp_path = f.name

        try:
            client = SparqlClient.from_local_file(tmp_path, format="ttl")

            class_uri_rule        = retrieve_class_uri_formation_rule(client)
            relation_uri_rule     = retrieve_relation_uri_formation_rule(client)
            instance_uri_rule     = retrieve_instance_uri_formation_rule(client)
            language_tags         = retrieve_language_tags(client)
            class_ann             = retrieve_class_annotation_coverage(client)
            relation_ann          = retrieve_relation_annotation_coverage(client)
            instance_ann          = retrieve_instance_annotation_coverage(client)
            min_lengths           = retrieve_min_annotation_length(client)
            max_lengths           = retrieve_max_annotation_length(client)
            ann_regex             = retrieve_annotation_regular_expression(client)
            instance_of_ann       = retrieve_instance_of_annotation_coverage(client)

            constraints = _build_constraints(
                class_uri_rule, relation_uri_rule, instance_uri_rule,
                language_tags, class_ann, relation_ann, instance_ann,
                min_lengths, max_lengths, ann_regex, instance_of_ann,
            )
            raw_violations = _build_results(
                client,
                class_uri_rule, relation_uri_rule, instance_uri_rule,
                language_tags, class_ann, relation_ann, instance_ann,
                min_lengths, max_lengths, ann_regex, instance_of_ann,
            )
        finally:
            os.unlink(tmp_path)

        # Annotate each check with its human-readable purpose
        violations = [
            {**v, "purpose": _CHECK_PURPOSES.get(v["check"], "")}
            for v in raw_violations
        ]
        violation_count = sum(len(v["violations"]) for v in violations)

        return {
            "constraints": constraints,
            "violations": violations,
            "violation_count": violation_count,
            "error": None,
        }

    except Exception as exc:
        logger.exception("APV check failed")
        return {"constraints": {}, "violations": [], "violation_count": 0,
                "error": str(exc)}


# ── Definition Quality Checks ─────────────────────────────────────────────────

_QUALITY_MIN_REMAINING = 20  # chars required after stripping label from definition (check G)


def _camel_to_words(s: str) -> str:
    """Convert CamelCase to space-separated lowercase words ("MaterialArtifact" → "material artifact")."""
    return re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', s).lower()


def _quality_checks_for_row(
    cluster_label: str,
    genus: str,
    nl_definition_en: str,
    nl_definition_pt: str,
    semiformal_axiom: str,
    label_pt: str,
) -> list[dict]:
    """
    Apply 6 Aristotelian definition quality checks to one enrichment's fields.
    Returns a list of failing checks; empty list means all passed.
    Each item: {check_id: str, field: str, message: str}
    """
    issues: list[dict] = []

    genus = (genus or "").strip()
    nl_en = (nl_definition_en or "").strip()
    nl_pt = (nl_definition_pt or "").strip()
    semi = (semiformal_axiom or "").strip()
    lpt = (label_pt or "").strip()
    label = (cluster_label or "").strip()

    # A: genus appears in the English definition (skip silently if genus not yet filled)
    # Also try CamelCase → words expansion so "MaterialArtifact" matches "material artifact".
    if genus and nl_en and genus.lower() not in nl_en.lower() and _camel_to_words(genus) not in nl_en.lower():
        issues.append({
            "check_id": "A",
            "field": "nl_definition_en",
            "message": f'genus "{genus}" not found in definition',
        })

    # B-en: English definition non-empty
    if not nl_en:
        issues.append({
            "check_id": "B_en",
            "field": "nl_definition_en",
            "message": "English definition is empty",
        })

    # B-pt: Portuguese definition non-empty
    if not nl_pt:
        issues.append({
            "check_id": "B_pt",
            "field": "nl_definition_pt",
            "message": "Portuguese definition is empty",
        })

    # C: semiformal axiom non-empty
    if not semi:
        issues.append({
            "check_id": "C",
            "field": "semiformal_axiom",
            "message": "Semiformal axiom is empty",
        })

    # D: Portuguese label non-empty
    if not lpt:
        issues.append({
            "check_id": "D",
            "field": "label_pt",
            "message": "Portuguese label is empty",
        })

    # G: definition is not circular (has meaningful content beyond the class name)
    if nl_en and label:
        remaining = nl_en
        if remaining.lower().startswith(label.lower()):
            remaining = remaining[len(label):].strip()
        if len(remaining) < _QUALITY_MIN_REMAINING:
            issues.append({
                "check_id": "G",
                "field": "nl_definition_en",
                "message": "Definition appears circular (too similar to class name)",
            })

    return issues


def run_quality_checks_batch(db_path: str) -> list[dict]:
    """
    Run quality checks over all validated/reviewed enrichments with a copi_id assigned.
    Returns list sorted by issue_count desc, then cluster_label asc.
    Each item: {id, cluster_label, copi_id, issue_count, issues: list[dict]}
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, cluster_label, genus, nl_definition_en, nl_definition_pt, "
            "semiformal_axiom, label_pt, copi_id "
            "FROM enrichment "
            "WHERE status IN ('validated', 'reviewed') "
            "  AND copi_id IS NOT NULL AND copi_id != '' "
            "ORDER BY cluster_label"
        ).fetchall()

        results = []
        for row in rows:
            issues = _quality_checks_for_row(
                cluster_label=row["cluster_label"],
                genus=row["genus"],
                nl_definition_en=row["nl_definition_en"],
                nl_definition_pt=row["nl_definition_pt"],
                semiformal_axiom=row["semiformal_axiom"],
                label_pt=row["label_pt"],
            )
            results.append({
                "id": row["id"],
                "cluster_label": row["cluster_label"],
                "copi_id": row["copi_id"],
                "issue_count": len(issues),
                "issues": issues,
            })

    results.sort(key=lambda r: (-r["issue_count"], r["cluster_label"]))
    return results
