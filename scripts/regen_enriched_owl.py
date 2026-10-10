#!/usr/bin/env python3
"""
Regenerate copi-enriched.owl from enrichment.db.

Strategy:
  1. Call generate_combined_turtle() to get all validated enrichment axioms as Turtle.
  2. Apply IRI remapping (readable-name → numeric COPI IRI) using copi-iri-map.tsv.
  3. Remove all triples where the subject is COPI_0000001–COPI_0000060 (vocabulary,
     function, and process-vocabulary classes fully declared in copi-base.ttl).
     Re-declaring these causes BFO disjointness violations or conflicting allValuesFrom
     targets detected by the ELK reasoner.
     Classes 066–204 only have bare owl:Class in copi-base.ttl; their EquivalentClass /
     SubClassOf axioms MUST come from copi-enriched.owl for the HermiT guards to pass.
  4. Assert InformationBearingArtifact is absent (ODR-021, resolved 2026-08-08). COPI has no
     such class: all 8 uses named information content, so each was mapped to the ICE class its
     constraint text supported and IBA was deleted. This retired the last participant-restriction
     quarantine — ALL hasInput/hasSpecifiedOutput restrictions now ship un-stripped, completing
     ODR-020 §6. What remains is a guard against IBA reappearing.
  5. Serialize to RDF/XML and write to the COPI repo component path.

Run from the COPIeditor root:
    python -m scripts.regen_enriched_owl
"""
import functools
import hashlib
import json
import re
import sys
from pathlib import Path

COPIEDITOR_ROOT = Path(__file__).resolve().parents[1]
COPI_REPO_ROOT  = COPIEDITOR_ROOT.parent / "copi"
OUTPUT_PATH     = COPI_REPO_ROOT / "src" / "ontology" / "components" / "copi-enriched.owl"
IRI_MAP_PATH    = COPIEDITOR_ROOT / "enrichment" / "ontologies" / "copi-context" / "copi-iri-map.tsv"
SUBSUMPTION_BASELINE = COPIEDITOR_ROOT / "scripts" / "equivalent-subsumption-baseline.txt"

COPI_NS = "https://www.inf.ufrgs.br/ontologies/copi/"

# COPI_0000001–0000060: fully declared in copi-base.ttl with allValuesFrom/SubClassOf axioms.
# COPI_0000061–0000065: annotation properties (not relevant as class subjects).
# COPI_0000066–0000204: bare owl:Class in copi-base.ttl; axioms must come from copi-enriched.owl.
PROTECTED_MAX = 60

# Vocab-owned classes above PROTECTED_MAX. IRI number does not imply module
# (ODR-022 §10.3) — these are declared with full axioms in copi-vocab.ttl and must be
# stripped from copi-enriched.owl exactly like 001-060, or the reasoner sees two
# competing definitions for one IRI.
#   383-385  ODR-020 qualities (ElectricalCurrent / MechanicalForce / MechanicalLoad)
#   386-400  ODR-022 participant substances
#   401-403  ODR-022 measurement results + position quality
PROTECTED_EXTRA = frozenset(range(383, 404))

# Class declarations for entities owned by BFO / IOF-Core. The generator emits a stub for
# every ":Name" it finds referenced but undeclared; once a canonical name is remapped onto
# an upstream IRI (MaterialEntity -> BFO_0000040, InformationContentEntity -> iof-core:...)
# that stub would re-declare an upstream class inside copi-enriched. ODR-022 §8.4.
UPSTREAM_PREFIXES = (
    "http://purl.obolibrary.org/obo/BFO_",
    "https://spec.industrialontologies.org/ontology/construct/",
)

sys.path.insert(0, str(COPIEDITOR_ROOT / "enrichment"))
from enrichment_service import generate_combined_turtle  # noqa: E402

from rdflib import BNode, Graph, Literal, Namespace, OWL, RDF, RDFS, SKOS, URIRef
from rdflib.collection import Collection


def _load_iri_map() -> dict[str, str]:
    mapping = {}
    with open(IRI_MAP_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) != 2 or parts[0] == "old_iri":
                continue
            mapping[parts[0]] = parts[1]
    return mapping


UPSTREAM_ONTOLOGY_FILES = (
    COPIEDITOR_ROOT / "enrichment" / "ontologies" / "IOF-Core.rdf",
    COPIEDITOR_ROOT / "enrichment" / "ontologies" / "bfo-2020.ttl",
)


@functools.lru_cache(maxsize=1)
def upstream_class_names() -> dict[str, str]:
    """PascalCase name -> IRI for every BFO / IOF-Core class, keyed by both the IRI's
    local name (``MaterialArtifact``) and the English label (``material entity`` ->
    ``MaterialEntity``, since BFO IRIs are opaque ``BFO_0000040``)."""
    names: dict[str, str] = {}
    for path in UPSTREAM_ONTOLOGY_FILES:
        g = Graph()
        g.parse(path)
        for cls in g.subjects(RDF.type, OWL.Class):
            if not isinstance(cls, URIRef):
                continue
            iri = str(cls)
            local = re.split(r"[/#]", iri)[-1]
            if not local.startswith("BFO_"):
                names.setdefault(local, iri)
            for label in g.objects(cls, RDFS.label):
                if getattr(label, "language", None) not in (None, "en"):
                    continue
                pascal = "".join(w[:1].upper() + w[1:] for w in re.split(r"[\s_-]+", str(label)) if w)
                if pascal:
                    names.setdefault(pascal, iri)
    return names


def _copi_numeric_id(uri: str) -> int | None:
    m = re.search(r"COPI_0*(\d+)$", uri)
    return int(m.group(1)) if m else None


def remap_graph(g: Graph, iri_map: dict[str, str]) -> Graph:
    fwd = {URIRef(old): URIRef(new) for old, new in iri_map.items()}

    def _sub(u):
        return fwd.get(u, u)

    new_g = Graph()
    for prefix, namespace in g.namespaces():
        new_g.bind(prefix, namespace)
    for s, p, o in g:
        new_g.add((
            _sub(s) if isinstance(s, URIRef) else s,
            _sub(p) if isinstance(p, URIRef) else p,
            _sub(o) if isinstance(o, URIRef) else o,
        ))
    return new_g


# ODR-022 §O6 / §10.2: standard terms that must enter through the 5-step enrichment
# pipeline, not by IRI allocation. Each is a term in terms.db AND is stated by that
# standard to be a component of a particular equipment (verbatim source_quote in the
# owning entry's necessary_parts). Allocating an IRI here would launder the bypass, so
# emission is a hard error until an enrichment entry exists.
# `Shell` is absent: it was repointed to the already-exported VesselShell (COPI_0000374)
# rather than enriched, because CFIHOS `shell` and COPI `vessel shell` are one universal
# (ODR-022 §O5, scripts/migrations/odr022_repoint_shell.py).
# `CableBundle` is absent: POSC Caesar declares the label with no definition, and with no
# source definition there is nothing for the pipeline's definition-driven steps to work
# from (ODR-022 §10.2). It stays hand-authored vocabulary and takes a numeric IRI like any
# other ungrounded part.
PIPELINE_REQUIRED = frozenset({
    "MasterValve", "WingValve", "DrillBit", "Piston", "TubeBundle",
    "FinnedTube", "FilterMedium", "Panel", "ElectricalSwitch", "StatorWinding",
    "Chamber", "TubingBowl", "GasDetectingMeasuringElement",
})

# §O1: dead stubs whose real classes already carry numeric IRIs. Emission means
# something still references them.
RETIRED_STUBS = {
    "PressureReliefValve": "COPI_0000145 / COPI_0000147",
    "SurfaceSafetyValve": "COPI_0000148",
}


class StubPolicyError(RuntimeError):
    """A readable-name class reached the output that must not be auto-allocated."""


def allocate_missing_iris(g: Graph, iri_map: dict[str, str]) -> dict[str, str]:
    """
    ODR-022 §8.1: allocate a numeric COPI IRI for every readable-name class that has no
    copi-iri-map.tsv row, and append those rows to the map.

    copi-iri-map.tsv is the authoritative readable-name -> numeric registry; this is the
    only place allocation happens. Names in PIPELINE_REQUIRED or RETIRED_STUBS raise
    instead of being allocated.

    Returns the extended map. Writes to IRI_MAP_PATH only when there is something to add.
    """
    readable = sorted({
        str(s) for s, p, o in g
        if p == RDF.type and o == OWL.Class and isinstance(s, URIRef)
        and str(s).startswith(COPI_NS) and _copi_numeric_id(str(s)) is None
        and str(s) not in iri_map
    })
    if not readable:
        return iri_map

    local_names = [u.rsplit("/", 1)[-1] for u in readable]

    # A BFO / IOF-Core class must never become a COPI class. The generator emits canonical
    # upstream names under the copi namespace; they reach the published artifact correctly
    # only through a redirect row in copi-iri-map.tsv. Without that row, allocating here
    # would silently mint a COPI IRI for another ontology's class.
    upstream = upstream_class_names()
    foreign = sorted(n for n in local_names if n in upstream)
    if foreign:
        raise StubPolicyError(
            "These names are BFO / IOF-Core classes, not COPI classes — refusing to allocate "
            "COPI IRIs for them. Add a redirect row to copi-iri-map.tsv pointing at the "
            "upstream IRI (ODR-022 §8.4):\n  "
            + "\n  ".join(f"{COPI_NS}{n}\t{upstream[n]}" for n in foreign)
        )

    retired = [n for n in local_names if n in RETIRED_STUBS]
    if retired:
        raise StubPolicyError(
            "These stubs are retired; a real numeric class already exists "
            "(ODR-022 §O1):\n  "
            + "\n  ".join(f"{n} → {RETIRED_STUBS[n]}" for n in sorted(retired))
        )

    # Standard-term components are NOT auto-allocated: allocating would launder the
    # pipeline bypass (§O6). They stay readable-name stubs, which keeps them
    # grandfathered in scripts/stub-iri-baseline.txt and therefore blocked from a clean
    # deploy by the numeric IRI gate until an enrichment entry exists. Deferral, not
    # silent acceptance — the build says so every run.
    deferred = sorted(n for n in local_names if n in PIPELINE_REQUIRED)
    if deferred:
        print(f"  → {len(deferred)} standard-term components NOT allocated — they must be "
              f"enriched through the 5-step pipeline (ODR-022 §O6):", flush=True)
        for n in deferred:
            print(f"     {n}", flush=True)
        readable = [u for u, n in zip(readable, local_names) if n not in PIPELINE_REQUIRED]
        local_names = [n for n in local_names if n not in PIPELINE_REQUIRED]
        if not readable:
            return iri_map

    used = {n for u in iri_map.values() if (n := _copi_numeric_id(u)) is not None}
    nxt = max(used) + 1
    added = []
    for uri, local in zip(readable, local_names):
        target = f"{COPI_NS}COPI_{nxt:07d}"
        iri_map[uri] = target
        added.append(f"{uri}\t{target}")
        nxt += 1

    with open(IRI_MAP_PATH, "a", encoding="utf-8") as fh:
        fh.write("\n".join(added) + "\n")
    print(f"  → allocated {len(added)} new IRIs "
          f"(COPI_{_copi_numeric_id(added[0].split(chr(9))[1]):07d}–"
          f"COPI_{nxt - 1:07d}) and appended them to copi-iri-map.tsv", flush=True)
    return iri_map


def _is_protected(uri: str) -> bool:
    """
    True when the class is fully declared in a base module, so copi-enriched must not
    re-declare it. Membership follows the ODR-022 §10.3 hosting rule (provenance, not
    number): 001-060 are copi-core/copi-vocab, and PROTECTED_EXTRA lists the vocab-owned
    classes that fall above that range — 383-385 (ODR-020 qualities) and 386-403 (ODR-022
    participant substances, measurement results and the position quality).
    """
    nid = _copi_numeric_id(uri)
    if nid is None:
        return False
    return (1 <= nid <= PROTECTED_MAX) or (nid in PROTECTED_EXTRA)


# Blank-node-subject axiom types that are free by construction — never the object of any
# triple in a well-formed graph, so the orphan-reachability heuristic below misclassifies
# them as garbage unconditionally. Confirmed empirically that only AllDisjointClasses
# currently occurs in this pipeline's output (#26); the other three plus SWRL rule heads
# share the exact same shape and would be lost the same way if they were ever emitted.
_FREE_AXIOM_TYPES = (
    OWL.AllDisjointClasses,
    OWL.AllDisjointProperties,
    OWL.AllDifferent,
    OWL.NegativePropertyAssertion,
    URIRef("http://www.w3.org/2003/11/swrl#Imp"),
)


def remove_protected_subject_triples(g: Graph) -> tuple[Graph, set[str]]:
    """Remove subjects in the protected range; then purge orphaned blank nodes.

    Blank nodes that are the subject of a free-standing axiom (AllDisjointClasses and
    siblings, see _FREE_AXIOM_TYPES) are seeded into `reachable` before the purge, and their
    owl:members RDF-list cells are walked too — protecting only the head node and leaving
    the rdf:first/rdf:rest chain unprotected would still purge the list one level down.
    """
    to_remove = []
    removed: set[str] = set()
    for s, p, o in g:
        if isinstance(s, URIRef) and _is_protected(str(s)):
            to_remove.append((s, p, o))
            removed.add(str(s))
    for triple in to_remove:
        g.remove(triple)

    def _collect_reachable(node: BNode, visited: set) -> None:
        if node in visited:
            return
        visited.add(node)
        for _, o in g.predicate_objects(node):
            if isinstance(o, BNode):
                _collect_reachable(o, visited)

    reachable: set = set()
    for s in {s for s, p, o in g if isinstance(s, URIRef)}:
        _collect_reachable(s, reachable)

    free_axiom_subjects: set = set()
    for axiom_type in _FREE_AXIOM_TYPES:
        for s in g.subjects(RDF.type, axiom_type):
            if isinstance(s, BNode):
                free_axiom_subjects.add(s)
    for s in free_axiom_subjects:
        _collect_reachable(s, reachable)

    orphan_triples = [(s, p, o) for s, p, o in g if isinstance(s, BNode) and s not in reachable]
    for triple in orphan_triples:
        g.remove(triple)

    if free_axiom_subjects:
        print(f"     Protected {len(free_axiom_subjects)} free-standing axiom subjects "
              f"(AllDisjointClasses and siblings) from the orphan purge", flush=True)
    if orphan_triples:
        print(f"     Removed {len(orphan_triples)} orphaned blank-node triples", flush=True)

    return g, removed



# Properties that can carry an identity-giving function onto its bearer. The generator
# emits iof-core:hasFunction; bfo:BFO_0000196 (bearer of) is accepted so the check keeps
# working if CLAUDE.md differentia rule 1 is ever applied to the emitter.
#
# bearer_of also carries QUALITIES (bearer_of some ElectricalPower), so the filler must be
# checked against _FUNCTION_ROOTS before it counts. Without that filter the check reports
# every pair of electrically powered devices as a conflict — sharing a quality is not the
# defect being looked for.
_FUNCTION_PROPS = frozenset({
    URIRef("https://spec.industrialontologies.org/ontology/construct/hasFunction"),
    URIRef("http://purl.obolibrary.org/obo/BFO_0000196"),
})

_FUNCTION_ROOTS = frozenset({
    URIRef("https://spec.industrialontologies.org/ontology/construct/DesignedFunction"),
    URIRef("http://purl.obolibrary.org/obo/BFO_0000034"),          # bfo:Function
})


def _local(u) -> str:
    return str(u).rsplit("/", 1)[-1]


def _is_function_class(g: Graph, cls: URIRef) -> bool:
    """True when `cls` sits under a function root — as opposed to a quality."""
    seen, stack = set(), [cls]
    while stack:
        cur = stack.pop()
        if cur in _FUNCTION_ROOTS:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        for p in g.objects(cur, RDFS.subClassOf):
            if isinstance(p, URIRef):
                stack.append(p)
    return False


def _class_shape(g: Graph, cls: URIRef) -> tuple[set, set]:
    """
    Return (named_parents, functions) for a class.

    Both `equivalent` and `necessary` entries state their genus and their
    identity-giving function; they differ only in whether it is packed into an
    owl:equivalentClass intersection or asserted as separate rdfs:subClassOf axioms.
    Read both shapes so the check does not depend on axiom_mode.
    """
    parents: set = set()
    funcs: set = set()

    def read_restriction(node) -> None:
        if g.value(node, OWL.onProperty) in _FUNCTION_PROPS:
            filler = g.value(node, OWL.someValuesFrom)
            if isinstance(filler, URIRef) and _is_function_class(g, filler):
                funcs.add(filler)

    for parent in g.objects(cls, RDFS.subClassOf):
        if isinstance(parent, URIRef):
            if parent != OWL.Thing:
                parents.add(parent)
        else:
            read_restriction(parent)

    for eq in g.objects(cls, OWL.equivalentClass):
        for lst in g.objects(eq, OWL.intersectionOf):
            for item in Collection(g, lst):
                if isinstance(item, URIRef):
                    parents.add(item)
                else:
                    read_restriction(item)

    return parents, funcs


def assert_no_unintended_function_subsumption(g: Graph) -> Graph:
    """
    ODR-022 §17: an `equivalent` class must not silently swallow classes that merely
    bear the same function.

    An entry with axiom_mode='equivalent' asserts

        C ≡ Genus ⊓ ∃hasFunction.F

    which makes "is a Genus and bears F" a SUFFICIENT condition for being a C. Anything
    else under that genus bearing that function is then inferred to be a C — including
    parts, components and unrelated universals that merely happen to seal, filter or
    detect. This family of defect was hit four separate times during ODR-022:

        gasket ≡ MaterialArtifact ⊓ ∃hasFunction.SealingFunction
            would have swallowed valve seat (§16)
        filter ≡ Separator ⊓ ∃hasFunction.FiltrationFunction
            would have swallowed filter medium, its own component (§12)
        gas detector ≡ Detector ⊓ ∃hasFunction.GasDetectionFunction
            would have swallowed gas detecting measuring element, its own part (§12)
        electrical connection ≡ MaterialArtifact ⊓ ∃hasFunction.ElectricalConductionFunction
            would have swallowed electrical cable (§14)

    Each was caught by hand, one at a time. This is the check that catches the family.

    What is flagged: D would be inferred ⊑ C, but nothing in the ontology says so — D does
    not name C anywhere in its own genus chain. A genuine subtype (centrifugal pump under
    pump) declares its genus, so the inference is intended and stays silent. An
    unintended one does not, and that gap is exactly the signal.
    """
    named: list[URIRef] = [
        s for s in set(g.subjects(RDF.type, OWL.Class))
        if isinstance(s, URIRef) and str(s).startswith(COPI_NS)
    ]
    shape = {c: _class_shape(g, c) for c in named}

    # Transitive closure over declared parents, so "under this genus" follows the chain.
    ancestors: dict[URIRef, set] = {}

    def climb(c: URIRef) -> set:
        if c in ancestors:
            return ancestors[c]
        ancestors[c] = set()                      # cycle guard
        acc: set = set()
        for p in shape.get(c, (set(), set()))[0]:
            acc.add(p)
            acc |= climb(p)
        ancestors[c] = acc
        return acc

    for c in named:
        climb(c)

    # Classes defined by an equivalentClass intersection are the ones asserting a
    # sufficient condition.
    defined = [c for c in named if (c, OWL.equivalentClass, None) in g]

    problems: list[str] = []
    pairs: list[tuple] = []
    for c in defined:
        c_parents, c_funcs = shape[c]
        if not c_funcs:
            continue
        genera = {p for p in c_parents if p != OWL.Thing}
        for d in named:
            if d is c or d == c:
                continue
            d_parents, d_funcs = shape[d]
            if not (c_funcs & d_funcs):
                continue                          # does not bear the same function
            # C ≡ G1 ⊓ … ⊓ Gn ⊓ ∃f.F, so D is only absorbed when it satisfies EVERY
            # conjunct — a subset test, not an intersection. Getting this wrong reported
            # Sheave and PumpShaft (⊑ MaterialArtifact only) as absorbed by DriveShaft
            # (≡ Assembly ⊓ MaterialArtifact ⊓ …), which they are not.
            if not genera <= (d_parents | ancestors.get(d, set())):
                continue                          # not under every genus of C
            if c in d_parents or c in ancestors.get(d, set()):
                continue                          # declared subtype — inference intended
            shared = ", ".join(sorted(_local(f) for f in (c_funcs & d_funcs)))
            pairs.append((d, c))
            problems.append(
                f"{_local(d)} would be inferred ⊑ {_local(c)} "
                f"(shared function: {shared}) but never declares it"
            )

    # Ratchet, like the numeric IRI gate: 14 occurrences predate this check and each needs
    # an ontological decision (is the absorbed class a genuine subtype, or should the
    # defining class be `necessary`?). Grandfather those, fail on anything new, and prune
    # the baseline as they are resolved.
    baseline: set[str] = set()
    if SUBSUMPTION_BASELINE.exists():
        baseline = {
            line.strip() for line in
            SUBSUMPTION_BASELINE.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }

    keys = {f"{_local(d)} -> {_local(c)}" for d, c in pairs}
    new_hits = sorted(k for k in keys if k not in baseline)
    stale = sorted(baseline - keys)

    if new_hits:
        raise StubPolicyError(
            "Unintended subsumption under an `equivalent` class (ODR-022 §17).\n"
            "An equivalent entry makes genus + function SUFFICIENT, so anything else under\n"
            "that genus bearing that function is silently absorbed. Either the absorbed\n"
            "class is a genuine subtype — then declare it as its genus — or the defining\n"
            "class should be `necessary`, or the two need distinct functions.\n  "
            + "\n  ".join(new_hits)
        )
    if keys:
        print(f"     {len(keys)} grandfathered equivalent-subsumption pairs "
              f"(ODR-022 §17 backlog)", flush=True)
    if stale:
        print(f"     {len(stale)} baseline entries resolved — prune "
              f"{SUBSUMPTION_BASELINE.name}", flush=True)
    return g

def assert_all_classes_anchored(g: Graph) -> Graph:
    """
    ODR-022 §13: every COPI class must have a BFO/IOF anchor, never owl:Thing.

    The stub generator falls back to `owl:Thing` when a referenced name has no row in
    `enrichment` and none in `auxiliary_class`. That fallback is silent, and it is how
    `Surface` shipped unanchored: the §O4 merge (CleanedSurface + ContaminatedSurface ->
    Surface) created a new target name without creating the auxiliary_class row that gives
    it a category.

    §8.1 already guarantees every emitted name has a TSV row. This is the same guarantee
    one level down: an IRI without a parent is a class the reasoner cannot place, and OOPS!
    flags it as P04 (unconnected). Merges are the recurring cause, so the check is on the
    graph rather than on the migration that happens to introduce it.
    """
    unanchored = []
    for s_ in g.subjects(RDF.type, OWL.Class):
        if not (isinstance(s_, URIRef) and str(s_).startswith(COPI_NS)):
            continue
        # A named parent other than owl:Thing counts as an anchor. Anonymous parents
        # (restriction bnodes) do not: a class defined only by restrictions still needs a
        # place in the taxonomy.
        named = {o for o in g.objects(s_, RDFS.subClassOf)
                 if isinstance(o, URIRef) and o != OWL.Thing}
        # An equivalentClass definition also places the class: for axiom_mode='equivalent'
        # the genus lives inside the intersection, so there is no separate subClassOf.
        defined = (s_, OWL.equivalentClass, None) in g
        if not named and not defined:
            unanchored.append(str(s_).rsplit("/", 1)[-1])
    unanchored.sort()
    if unanchored:
        raise StubPolicyError(
            "These classes are declared with no BFO/IOF anchor (rdfs:subClassOf owl:Thing). "
            "Add an auxiliary_class row giving each a bfo_category, or a genus via an "
            "enrichment entry (ODR-022 §13):\n  " + "\n  ".join(unanchored)
        )
    return g


def canonicalize_rdfxml(rdfxml: str) -> str:
    """
    Emit the top-level <rdf:Description> blocks in a stable order.

    Stable blank-node labels are necessary but not sufficient: rdflib's RDF/XML serializer
    orders subjects unpredictably, so the same graph still came out as a reordered file
    (verified — the set of node IDs was byte-identical across runs while ~21,700 lines
    moved). Neither insertion order nor PYTHONHASHSEED changes that.

    Sorting the blocks by their subject key gives a file that depends only on the graph.
    The blocks are independent siblings under <rdf:RDF>, so reordering them is a no-op in
    RDF; the caller re-parses the result and compares triple counts to prove it.
    """
    m = re.search(r"^(.*?<rdf:RDF[^>]*>\n)(.*)(</rdf:RDF>\s*)$", rdfxml, re.S)
    if not m:
        print("     WARNING: unexpected RDF/XML shape — leaving order untouched", flush=True)
        return rdfxml
    head, body, tail = m.groups()

    blocks = re.findall(
        r"[ \t]*<rdf:Description\b.*?</rdf:Description>\n", body, re.S
    )
    leftover = re.sub(r"[ \t]*<rdf:Description\b.*?</rdf:Description>\n", "", body, flags=re.S)
    if leftover.strip():
        print("     WARNING: non-Description content at top level — leaving order untouched",
              flush=True)
        return rdfxml

    def key(block: str):
        about = re.search(r'rdf:about="([^"]+)"', block)
        if about:
            return (0, about.group(1), "")
        node = re.search(r'rdf:nodeID="([^"]+)"', block)
        # Ties on nodeID are impossible (labels are unique), but fall back to the block
        # text so the sort is total either way.
        return (1, node.group(1) if node else "", block)

    def sort_children(block: str) -> str:
        """Order the property elements inside one block.

        Sorting blocks alone left 18 lines of churn: when a subject carries several values
        for one predicate (two rdfs:label, en and pt-br) their relative order still moved.
        """
        # Non-greedy body and an anchored tail: a greedy `.*` leaves the closing tag's
        # own indentation inside the body, which then never equals the joined children and
        # silently skipped every block.
        bm = re.match(r"([ \t]*<rdf:Description\b[^>]*>\n)(.*?)([ \t]*</rdf:Description>\n)$",
                      block, re.S)
        if not bm:
            return block
        b_head, b_body, b_tail = bm.groups()
        # Prefixes may contain hyphens (iof-av:naturalLanguageDefinition), so the prefix
        # class must allow them — \w+ alone silently failed the shape check below and left
        # every block with an iof-av property unsorted.
        spans = [m.group(0) for m in re.finditer(
            r"[ \t]*<([\w-]+:[\w-]+)\b.*?(?:/>|</\1>)\n", b_body, re.S)]
        if "".join(spans) != b_body:
            return block                      # unexpected shape: leave this block alone
        return b_head + "".join(sorted(spans)) + b_tail

    return head + "".join(sort_children(b) for b in sorted(blocks, key=key)) + tail


def stabilize_blank_nodes(g: Graph) -> Graph:
    """
    Relabel every blank node deterministically, so identical input serializes identically.

    rdflib mints fresh blank-node IDs on every run. copi-enriched.owl holds ~10k
    blank-node triples (restrictions, intersections, RDF lists), so a regeneration with no
    semantic change produced a ~21,800-line diff. That made artifact review in a PR
    useless — a real change could not be told from the churn, and that is how the ODR-021
    quarantine went unnoticed when it silently stopped firing.

    Labels are assigned by POSITION, not by content: walk from every named subject in
    sorted order, depth-first through sorted (predicate, object) edges, numbering each
    blank node the first time it is reached.

    Content-addressed labelling was tried first and is wrong here. Two structurally
    identical blank nodes would collapse to one label and therefore into one node — which
    silently rewires RDF lists, because `rdf:first`/`rdf:rest` cells with equal content
    belong to different lists. That merge dropped 2,361 triples and left a graph that was
    not isomorphic to the original. Positional labelling keeps every node distinct.
    """
    named = sorted(
        {s for s in g.subjects() if isinstance(s, URIRef)}, key=str
    )

    mapping: dict = {}
    counter = 0

    def visit(node) -> None:
        nonlocal counter
        if not isinstance(node, BNode) or node in mapping:
            return
        counter += 1
        mapping[node] = BNode(f"n{counter:06d}")
        for p, o in sorted(g.predicate_objects(node), key=lambda t: (str(t[0]), str(t[1]))):
            visit(o)

    for subj in named:
        for p, o in sorted(g.predicate_objects(subj), key=lambda t: (str(t[0]), str(t[1]))):
            visit(o)

    # Blank nodes not reachable from any named subject would otherwise keep a random
    # label. Sort them by their own serialized content so the order is still stable.
    orphans = sorted(
        (n for n in g.all_nodes() if isinstance(n, BNode) and n not in mapping),
        key=lambda b: sorted(f"{p} {o}" for p, o in g.predicate_objects(b)),
    )
    for b in orphans:
        counter += 1
        mapping[b] = BNode(f"n{counter:06d}")

    if not mapping:
        return g

    # Insert in sorted order: rdflib's serializer follows the store's insertion order, so
    # building `out` by iterating `g` (arbitrary order) is itself a source of churn —
    # stable blank-node labels alone still produced a reordered file.
    out = Graph()
    for prefix, ns in sorted(g.namespaces()):
        out.bind(prefix, ns)
    for s, p, o in sorted(g, key=lambda t: (str(t[0]), str(t[1]), str(t[2]))):
        out.add((mapping.get(s, s), p, mapping.get(o, o)))

    assert len(out) == len(g), (
        f"blank-node relabelling changed the graph: {len(g)} -> {len(out)} triples"
    )
    if orphans:
        print(f"     {len(orphans)} blank nodes unreachable from any named subject",
              flush=True)
    return out


def remove_upstream_declarations(g: Graph) -> tuple[Graph, set[str]]:
    """
    ODR-022 §8.4: drop declaration triples whose subject is a BFO or IOF-Core entity.

    copi-enriched declares only copi classes. An upstream IRI appears as a *subject* here
    only because a canonical name (MaterialEntity, InformationContentEntity, ...) was
    remapped onto it and the generator had already emitted a stub declaration for that
    name. Re-declaring an imported class overrides its real axioms — silently, and only
    for consumers who load copi-enriched without the import closure.

    References to upstream classes as OBJECTS (rdfs:subClassOf iof-core:MaterialArtifact,
    someValuesFrom bfo:BFO_0000040) are untouched — those are the legitimate use.
    """
    to_remove = []
    removed: set[str] = set()
    for s, p, o in g:
        if isinstance(s, URIRef) and str(s).startswith(UPSTREAM_PREFIXES):
            to_remove.append((s, p, o))
            removed.add(str(s))
    for triple in to_remove:
        g.remove(triple)
    if removed:
        print(f"     Removed {len(to_remove)} declaration triples on "
              f"{len(removed)} upstream classes", flush=True)
    return g, removed


def assert_no_information_bearing_artifact(g: Graph) -> Graph:
    """
    ODR-021 (resolved 2026-08-08): COPI has no InformationBearingArtifact.

    This replaces the participant-restriction quarantine. That quarantine existed for
    exactly one reason — IBA was typed bfo:Object while its process forced
    MeasurementICE-only outputs, an IndependentContinuant ⊓ GDC clash yielding 3
    unsatisfiable classes. Every one of the 8 uses actually named information content
    ("visual information", "measurement signal", "control signal"), so IBA was deleted and
    each use mapped to the ICE class its own constraint text supported
    (scripts/migrations/odr021_retire_iba.py). With the cause gone the workaround goes too:
    ALL participant restrictions now ship un-stripped, which was ODR-020 §6's goal.

    What remains is a guard. If IBA ever reappears — a re-import, a hand-edited entry, a
    regenerated proposal — it must fail loudly rather than silently reintroduce
    unsatisfiable classes.
    """
    iba_names = {COPI_NS + "InformationBearingArtifact"}
    mapped = _load_iri_map().get(COPI_NS + "InformationBearingArtifact")
    if mapped:
        iba_names.add(mapped)

    offenders = {
        str(n) for t in g for n in t
        if isinstance(n, URIRef) and str(n) in iba_names
    }
    if offenders:
        raise StubPolicyError(
            "InformationBearingArtifact is present in the graph. COPI does not have this "
            "class (ODR-021): it is typed bfo:Object but is only ever used for information "
            "content, which makes its process-I/O restrictions unsatisfiable. Map each use "
            "to the appropriate ICE class instead.\n  "
            + "\n  ".join(sorted(offenders))
        )
    return g


def strip_source_definitions(g: Graph) -> Graph:
    """Remove skos:definition triples whose literal begins with a copyrighted source tag.

    Copyrighted sources lack explicit redistribution licenses; their verbatim
    text must not appear in the public copi-enriched.owl.
    AI-generated definitions (no [Source] prefix) are unaffected.
    """
    from enrichment_service import PUBLIC_STRIP_PREFIXES
    to_remove = [
        (s, p, o) for s, p, o in g
        if p == SKOS.definition
        and any(str(o).startswith(pfx) for pfx in PUBLIC_STRIP_PREFIXES)
    ]
    for triple in to_remove:
        g.remove(triple)
    print(f"     Stripped {len(to_remove)} copyrighted skos:definition triples", flush=True)
    return g


def inject_stub_definitions(g: Graph, stub_defs_path: Path) -> Graph:
    """Add skos:definition triples for readable-name stub classes from stub-definitions.json."""
    if not stub_defs_path.exists():
        return g
    stub_defs = json.loads(stub_defs_path.read_text(encoding="utf-8"))
    injected = 0
    for class_name, definition in stub_defs.items():
        iri = URIRef(COPI_NS + class_name)
        if (iri, RDF.type, OWL.Class) in g:
            g.add((iri, SKOS.definition, Literal(definition, lang="en")))
            injected += 1
    print(f"     Injected {injected} skos:definition triples from stub-definitions.json", flush=True)
    return g


def generate_enriched_owl_rdfxml(verbose: bool = True) -> str:
    """
    Run the full enrichment.db -> copi-enriched.owl transform pipeline and return
    the canonical RDF/XML content, WITHOUT writing it to OUTPUT_PATH.

    This is the single source of truth for "what does copi-enriched.owl contain" --
    main() below is a thin CLI wrapper that calls this and writes the result.
    enrichment_routes.push_to_github() calls this directly too, so the dashboard's
    Export -> GitHub PR flow can never again drift from what this script produces
    (see COPIeditor commit fixing the "two independent generators" bug: the
    dashboard used to call a separate, long-unmaintained generate_owl_functional()
    that never remapped readable-name IRIs through copi-iri-map.tsv).
    """
    def _log(msg: str) -> None:
        if verbose:
            print(msg, flush=True)

    _log("Generating combined Turtle from enrichment.db …")
    ttl = generate_combined_turtle()
    _log(f"  → {len(ttl):,} chars")

    _log("Loading IRI map …")
    iri_map = _load_iri_map()
    _log(f"  → {len(iri_map)} entries")

    _log("Parsing Turtle …")
    g = Graph()
    g.parse(data=ttl, format="turtle")
    _log(f"  → {len(g)} triples")

    STUB_DEFS_PATH = COPIEDITOR_ROOT / "data" / "stub-definitions.json"
    _log("Injecting stub definitions from stub-definitions.json (pre-remap) …")
    g = inject_stub_definitions(g, STUB_DEFS_PATH)

    _log("Allocating numeric IRIs for unmapped readable-name classes …")
    iri_map = allocate_missing_iris(g, iri_map)

    _log("Remapping readable IRIs to numeric COPI IRIs …")
    g = remap_graph(g, iri_map)
    _log(f"  → {len(g)} triples (unchanged count — just IRIs swapped)")

    _log(f"Removing conflicting declarations for COPI_0000001–{PROTECTED_MAX:04d} "
         f"+ vocab-owned {min(PROTECTED_EXTRA)}–{max(PROTECTED_EXTRA)} …")
    g, removed = remove_protected_subject_triples(g)
    _log(f"  → {len(removed)} class IRIs removed as subjects")
    for iri in sorted(removed):
        _log(f"     {iri.split('/')[-1]}")
    _log(f"  → {len(g)} triples remaining")

    owl_classes = {str(s) for s, p, o in g if p == RDF.type and o == OWL.Class and isinstance(s, URIRef)}
    numeric  = [u for u in owl_classes if _copi_numeric_id(u) is not None]
    readable = [u for u in owl_classes if _copi_numeric_id(u) is None]
    _log(f"  → {len(numeric)} numeric COPI classes, {len(readable)} readable-name stubs")

    _log("Asserting every class has a BFO/IOF anchor …")
    g = assert_all_classes_anchored(g)
    _log("  → all anchored")

    _log("Checking for unintended subsumption under `equivalent` classes …")
    g = assert_no_unintended_function_subsumption(g)

    _log("Removing upstream (BFO / IOF-Core) declarations …")
    g, up_removed = remove_upstream_declarations(g)
    _log(f"  → {len(up_removed)} upstream class IRIs removed as subjects")
    _log(f"  → {len(g)} triples remaining")

    _log("Stripping copyrighted skos:definition triples …")
    g = strip_source_definitions(g)
    _log(f"  → {len(g)} triples remaining")

    _log("Asserting InformationBearingArtifact is absent (ODR-021) …")
    g = assert_no_information_bearing_artifact(g)
    _log("  → absent; all participant restrictions ship un-stripped")

    _log("Stabilizing blank-node identifiers …")
    g = stabilize_blank_nodes(g)
    _log("  → deterministic; identical input now yields identical bytes")

    _log("Serializing to RDF/XML …")
    rdfxml = g.serialize(format="xml")
    if isinstance(rdfxml, bytes):
        rdfxml = rdfxml.decode("utf-8")

    rdfxml = canonicalize_rdfxml(rdfxml)
    _check = Graph()
    _check.parse(data=rdfxml, format="xml")
    assert len(_check) == len(g), (
        f"canonical ordering changed the graph: {len(g)} -> {len(_check)} triples"
    )
    _log("  → block order canonical; output depends only on the graph")

    return rdfxml


def main():
    rdfxml = generate_enriched_owl_rdfxml()
    print(f"Writing to {OUTPUT_PATH} …", flush=True)
    OUTPUT_PATH.write_text(rdfxml, encoding="utf-8")
    print(f"  → {OUTPUT_PATH.stat().st_size:,} bytes", flush=True)
    print("Done.", flush=True)


if __name__ == "__main__":
    main()
