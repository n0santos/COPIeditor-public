"""
Participant-type vocabulary for Step 5 (process participation signature).

Participant types are hand-authored COPI vocabulary (CLAUDE.md, ODR-022 §2). This module
reads that vocabulary from its source of truth -- copi-vocab.ttl plus the BFO / IOF-Core
redirect rows in copi-iri-map.tsv -- so the Step 5 prompt lists exactly what the
participant vocabulary gate (enrichment_service.validate_participant_vocabulary) accepts.

It replaces a hand-maintained list in prompts.py that had drifted: it recommended
`ThermalEnergy`, which copi-vocab never declared, and omitted HeatTransferMedium,
FuelPortion, ExhaustGas, Pressure, MechanicalLoad and the other ODR-020/022 additions.

Deliberately free of enrichment_service imports: prompts.py is imported by
enrichment_service, so this must not import it back.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_CONTEXT_DIR = Path(__file__).parent / "ontologies" / "copi-context"
_ONTOLOGIES_DIR = Path(__file__).parent / "ontologies"
VOCAB_PATH = _CONTEXT_DIR / "copi-vocab.ttl"
CORE_PATH = _CONTEXT_DIR / "copi-core.ttl"
IRI_MAP_PATH = _CONTEXT_DIR / "copi-iri-map.tsv"
UPSTREAM_PATHS = (_ONTOLOGIES_DIR / "IOF-Core.rdf", _ONTOLOGIES_DIR / "bfo-2020.ttl")

COPI_NS = "https://www.inf.ufrgs.br/ontologies/copi/"
BFO = "http://purl.obolibrary.org/obo/"
IOF = "https://spec.industrialontologies.org/ontology/construct/"
_NLDEF = "https://spec.industrialontologies.org/ontology/annotation/naturalLanguageDefinition"

# BFO / IOF-Core roots that decide which prompt group a participant type belongs to.
_GROUPS = (
    ("information", "Information participants (signals, data, indications)", (f"{IOF}InformationContentEntity",)),
    ("quality", "Qualities (a measured or transferred property of a participant)", (f"{BFO}BFO_0000019",)),
    ("material", "Material participants (portions of matter, bodies)", (f"{BFO}BFO_0000040",)),
)
# Anything reaching these is a function or a process, never a participant type.
_NON_PARTICIPANT_ROOTS = (
    f"{BFO}BFO_0000015",            # process
    f"{BFO}BFO_0000034",            # function
    f"{IOF}PlannedProcess",
    f"{IOF}DesignedFunction",
)


@dataclass(frozen=True)
class ParticipantType:
    name: str          # PascalCase name used in process_signature
    iri: str
    label: str
    group: str         # material | information | quality | upstream
    definition: str


_cache: dict = {}


def _pascal(text: str) -> str:
    return "".join(w[:1].upper() + w[1:] for w in re.split(r"[\s_-]+", text) if w)


def _load_map() -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in IRI_MAP_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) == 2 and parts[0] != "old_iri":
            rows[parts[0]] = parts[1]
    return rows


def _build() -> list[ParticipantType]:
    from rdflib import Graph, Literal, OWL, RDF, RDFS, SKOS, URIRef

    g = Graph()
    for path in (CORE_PATH, VOCAB_PATH, *UPSTREAM_PATHS):
        g.parse(path)
    vocab = Graph()
    vocab.parse(VOCAB_PATH)

    def ancestors(node: URIRef) -> set[str]:
        seen: set[str] = set()
        stack = [node]
        while stack:
            for parent in g.objects(stack.pop(), RDFS.subClassOf):
                if isinstance(parent, URIRef) and str(parent) not in seen:
                    seen.add(str(parent))
                    stack.append(parent)
        return seen

    def english(values) -> str:
        for v in values:
            if isinstance(v, Literal) and v.language in (None, "en"):
                return " ".join(str(v).split())
        return ""

    iri_map = _load_map()
    by_target: dict[str, list[str]] = {}
    for old, new in iri_map.items():
        if old.startswith(COPI_NS):
            by_target.setdefault(new, []).append(old[len(COPI_NS):])

    def classify(node: URIRef) -> str | None:
        anc = ancestors(node) | {str(node)}
        if any(root in anc for root in _NON_PARTICIPANT_ROOTS):
            return None
        for key, _title, roots in _GROUPS:
            if any(root in anc for root in roots):
                return key
        return None

    types: list[ParticipantType] = []
    for cls in set(vocab.subjects(RDF.type, OWL.Class)):
        if not (isinstance(cls, URIRef) and str(cls).startswith(COPI_NS)):
            continue
        group = classify(cls)
        if group is None:
            continue
        label = english(g.objects(cls, RDFS.label))
        names = by_target.get(str(cls), [])
        if not names:
            continue  # not addressable by a readable name, so the generator cannot emit it
        preferred = _pascal(label)
        name = preferred if preferred in names else sorted(names, key=len)[0]
        types.append(ParticipantType(
            name=name, iri=str(cls), label=label, group=group,
            definition=english(g.objects(cls, URIRef(_NLDEF))) or english(g.objects(cls, RDFS.comment)),
        ))

    # Canonical names the map redirects to a BFO / IOF-Core continuant: generic fallbacks.
    # Role-defined classes (PieceOfEquipment, MaterialComponent) are excluded: membership
    # follows from a role, so it is inferred, never used as a participant type.
    role_defined = _role_defined_iris(g)
    for old, new in iri_map.items():
        if not old.startswith(COPI_NS) or new.startswith(COPI_NS):
            continue
        node = URIRef(new)
        if classify(node) is None or new in role_defined:
            continue
        label = (english(g.objects(node, RDFS.label)) or english(g.objects(node, SKOS.prefLabel))
                 or re.sub(r"(?<!^)(?=[A-Z])", " ", new.rsplit("/", 1)[-1]).lower())
        types.append(ParticipantType(
            name=old[len(COPI_NS):], iri=new, label=label,
            group="upstream", definition="",
        ))

    return sorted(types, key=lambda t: (t.group, t.name))


def _role_defined_iris(g) -> frozenset[str]:
    """Upstream classes whose owl:equivalentClass has a conjunct `∃ hasRole.X` — e.g.
    iof-core:PieceOfEquipment ≡ … ⊓ ∃hasRole.EquipmentRole. Unlike MaterialArtifact
    (≡ Object ⊓ ∃bearerOf.DesignedFunction), membership is anti-rigid: inferred from a role."""
    from rdflib import OWL, URIRef
    from rdflib.collection import Collection

    def mentions_has_role(node, depth=0) -> bool:
        if depth > 6:
            return False
        prop = g.value(node, OWL.onProperty)
        if prop is not None and str(prop).endswith("hasRole"):
            return True
        for key in (OWL.intersectionOf, OWL.unionOf):
            lst = g.value(node, key)
            if lst is not None and any(mentions_has_role(m, depth + 1) for m in Collection(g, lst)):
                return True
        return False

    return frozenset(
        str(cls) for cls, eq in g.subject_objects(OWL.equivalentClass)
        if isinstance(cls, URIRef) and mentions_has_role(eq)
    )


def role_defined_upstream_iris() -> frozenset[str]:
    """Role-defined BFO / IOF-Core classes; never admissible as participant types."""
    key = tuple(p.stat().st_mtime_ns for p in UPSTREAM_PATHS)
    if _cache.get("role_key") != key:
        from rdflib import Graph
        g = Graph()
        for path in UPSTREAM_PATHS:
            g.parse(path)
        _cache["role_defined"] = _role_defined_iris(g)
        _cache["role_key"] = key
    return _cache["role_defined"]


def participant_types() -> list[ParticipantType]:
    """All admissible participant types, re-read when any source file changes."""
    paths = (CORE_PATH, VOCAB_PATH, IRI_MAP_PATH, *UPSTREAM_PATHS)
    key = tuple(p.stat().st_mtime_ns for p in paths)
    if _cache.get("key") != key:
        _cache["types"] = _build()
        _cache["key"] = key
    return _cache["types"]


def _short(definition: str, limit: int = 150) -> str:
    if len(definition) <= limit:
        return definition
    cut = definition[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"


def format_participant_vocabulary_block() -> str:
    """Markdown list of admissible participant types, grouped, for the Step 5 prompt."""
    types = participant_types()
    sections = []
    for key, title, _roots in _GROUPS + (("upstream", "Generic BFO / IOF-Core fallbacks (use only when nothing above is specific enough)", ()),):
        members = [t for t in types if t.group == key]
        if not members:
            continue
        lines = [f"*{title}:*"]
        for t in members:
            if key == "upstream":
                lines.append(f"- `{t.name}` — {t.label} ({t.iri.replace(IOF, 'iof-core:').replace(BFO, 'bfo:')})")
            else:
                lines.append(f"- `{t.name}` — {_short(t.definition) or t.label}")
        sections.append("\n".join(lines))
    return "\n\n".join(sections)
