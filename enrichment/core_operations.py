"""
COPI-Core operation anchoring for Step 1 (process_parent) and Step 5 (transformation_kind).

Every equipment process is meant to sit under one of COPI-Core's operation categories —
the eight subclasses of Operation (COPI_0000001) plus iof-core:MeasurementProcess, which
realizes the measurement-instrument category (COPI_0000024). The Step 1 prompt used to
hard-code `"process_parent": "PlannedProcess"` and never listed the operations, so 90 of
293 validated entries (2026-09-14) reach no operation through either their own process or
its parent. This module reads the operation taxonomy from
copi-core.ttl / copi-vocab.ttl (the source of truth) for the prompt and for the anchoring
gate, and holds the transformation_kind -> operation agreement table.

Free of enrichment_service imports (prompts.py imports this; enrichment_service imports prompts).
"""

from __future__ import annotations

from dataclasses import dataclass

from participant_vocabulary import (
    BFO, COPI_NS, CORE_PATH, IOF, IRI_MAP_PATH, VOCAB_PATH, _load_map, _pascal,
)

OPERATION_IRI = f"{COPI_NS}COPI_0000001"
MEASUREMENT_PROCESS_IRI = f"{IOF}MeasurementProcess"
_NLDEF = "https://spec.industrialontologies.org/ontology/annotation/naturalLanguageDefinition"

# COPI-Core operation categories a process can be anchored in (readable names).
TOP_OPERATIONS = (
    "MomentumTransfer", "HeatTransfer", "MassTransfer", "MechanicalSeparation",
    "ChemicalReaction", "PhaseChange", "MaterialContainment", "FlowControl",
    "MeasurementProcess",
)

# transformation_kind (controlled vocabulary, enrichment_service.TRANSFORMATION_KINDS_CONTROLLED)
# -> the top operation(s) a process of that kind may be anchored in. An empty tuple means
# COPI-Core has no operation for the kind: an entry of that kind must record a
# core_operation_gap (out_of_scope or core_coverage_gap) instead of an anchor.
# Derived from how validated entries already combine the two (2026-09-14), with two
# corrections: fluid_transport is "passage without mechanical work", which contradicts
# MomentumTransfer's definition (the 9 entries anchored there are mis-anchored), and
# flow_direction_control belongs to FlowControl (5 check-valve-like entries sit under
# MomentumTransfer).
KIND_TO_OPERATIONS: dict[str, tuple[str, ...]] = {
    "flow_regulation":               ("FlowControl",),
    "flow_isolation":                ("FlowControl",),
    "flow_direction_control":        ("FlowControl",),
    "pressure_reduction":            ("FlowControl",),
    "pressure_increase":             ("MomentumTransfer",),
    "mixing":                        ("MomentumTransfer",),
    "thermal_energy_transfer":       ("HeatTransfer", "PhaseChange"),
    "phase_separation":              ("MechanicalSeparation", "MassTransfer", "PhaseChange"),
    "mass_transfer":                 ("MassTransfer",),
    "mechanical_filtration":         ("MechanicalSeparation",),
    "chemical_transformation":       ("ChemicalReaction",),
    "measurement_transduction":      ("MeasurementProcess",),
    "containment":                   ("MaterialContainment",),
    "fluid_transport":               (),
    "mechanical_power_transmission": (),
    "electrical_power_conversion":   (),
    "subsurface_access":             (),
}

GAP_KINDS = ("out_of_scope", "core_coverage_gap")

# COPI's own scope statement (skos:scopeNote on the ontology header).
COPI_SCOPE = (
    "material artifacts that (i) are part of a petroleum production plant, and (ii) bear at "
    "least one function whose realization involves the transport (e.g. production and "
    "injection), processing (separation and other processes), control, monitoring, "
    "measurement, containment or offloading of material or energy"
)


@dataclass(frozen=True)
class Operation:
    name: str
    iri: str
    label: str
    definition: str
    depth: int
    top: str          # the TOP_OPERATIONS entry it falls under


_cache: dict = {}


def _build() -> tuple[list[Operation], dict[str, str]]:
    from rdflib import Graph, Literal, RDFS, URIRef

    g = Graph()
    for path in (CORE_PATH, VOCAB_PATH):
        g.parse(path)
    by_target: dict[str, list[str]] = {}
    for old, new in _load_map().items():
        if old.startswith(COPI_NS):
            by_target.setdefault(new, []).append(old[len(COPI_NS):])

    def english(values) -> str:
        for v in values:
            if isinstance(v, Literal) and v.language in (None, "en"):
                return " ".join(str(v).split())
        return ""

    def name_for(iri: str, label: str) -> str:
        if iri == MEASUREMENT_PROCESS_IRI:
            return "MeasurementProcess"
        names = by_target.get(iri, [])
        preferred = _pascal(label)
        if preferred in names:
            return preferred
        return sorted(names, key=len)[0] if names else preferred

    ops: list[Operation] = []
    iri_to_top: dict[str, str] = {}

    def walk(node: URIRef, depth: int, top: str | None) -> None:
        for child in sorted(g.subjects(RDFS.subClassOf, node), key=str):
            if not isinstance(child, URIRef):
                continue
            label = english(g.objects(child, RDFS.label))
            name = name_for(str(child), label)
            this_top = top or name
            if this_top not in TOP_OPERATIONS:
                continue
            iri_to_top[str(child)] = this_top
            ops.append(Operation(name, str(child), label,
                                 english(g.objects(child, URIRef(_NLDEF))), depth, this_top))
            walk(child, depth + 1, this_top)

    walk(URIRef(OPERATION_IRI), 0, None)
    iri_to_top[MEASUREMENT_PROCESS_IRI] = "MeasurementProcess"
    ops.append(Operation("MeasurementProcess", MEASUREMENT_PROCESS_IRI, "measurement process",
                         "A planned process that produces a measurement result (iof-core); "
                         "the operation realized by COPI's measurement-instrument category.", 0,
                         "MeasurementProcess"))
    walk(URIRef(MEASUREMENT_PROCESS_IRI), 1, "MeasurementProcess")
    return ops, iri_to_top


def _data() -> tuple[list[Operation], dict[str, str]]:
    key = tuple(p.stat().st_mtime_ns for p in (CORE_PATH, VOCAB_PATH, IRI_MAP_PATH))
    if _cache.get("key") != key:
        _cache["data"] = _build()
        _cache["key"] = key
    return _cache["data"]


def operations() -> list[Operation]:
    return _data()[0]


def anchor_of(process_parent: str | None, process_parents: dict[str, str | None] | None = None) -> str | None:
    """The top COPI-Core operation a process_parent resolves to, following already-enriched
    process names (process_name -> process_parent) when the parent is itself a pipeline
    process. None when the chain never reaches an operation (e.g. bare PlannedProcess)."""
    iri_map = _load_map()
    iri_to_top = _data()[1]
    seen: set[str] = set()
    current = process_parent
    while current and current not in seen:
        seen.add(current)
        name = _pascal(current) if " " in current else current
        if name == "MeasurementProcess":
            return "MeasurementProcess"
        target = iri_map.get(f"{COPI_NS}{name}")
        if target and target in iri_to_top:
            return iri_to_top[target]
        current = (process_parents or {}).get(name)
    return None


def anchor_for_entry(process_name: str | None, process_parent: str | None,
                     process_parents: dict[str, str | None] | None = None) -> str | None:
    """Anchor of an enrichment entry. The process itself may already be a COPI-Core /
    copi-vocab operation (e.g. control valve's ProcessControlledFlowProcess ⊑ FlowControl),
    in which case its own process_parent field is irrelevant: regen strips those subjects."""
    return anchor_of(process_name) or anchor_of(process_parent, process_parents)


def format_core_operations_block() -> str:
    """Indented list of anchorable operations for the Step 1 prompt."""
    lines = []
    for op in operations():
        definition = op.definition if len(op.definition) <= 170 else op.definition[:170].rsplit(" ", 1)[0] + "…"
        lines.append(f"{'  ' * op.depth}- `{op.name}` — {definition or op.label}")
    return "\n".join(lines)


def format_kind_agreement_block() -> str:
    """transformation_kind -> allowed anchor(s), for the Step 5 prompt."""
    lines = []
    for kind, tops in KIND_TO_OPERATIONS.items():
        target = " or ".join(f"`{t}`" for t in tops) if tops else "no COPI-Core operation → `core_operation_gap` required"
        lines.append(f"- `{kind}` → {target}")
    return "\n".join(lines)


def anchoring_findings(process_name: str | None, process_parent: str | None, signature,
                       core_operation_gap, process_parents: dict[str, str | None] | None = None) -> list[str]:
    """Finding types for one entry: `unanchored` (no operation reached, no gap recorded) and
    `kind_mismatch:<kind>` (a controlled transformation_kind that does not allow the anchor)."""
    import json

    def _load(value, default):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return default
        return value if value is not None else default

    sig = _load(signature, {}) or {}
    gap = _load(core_operation_gap, None)
    gap = gap if isinstance(gap, dict) and gap.get("kind") in GAP_KINDS else None
    anchor = anchor_for_entry(process_name, process_parent, process_parents)
    kind = sig.get("transformation_kind") if sig.get("transformation_kind_status", "controlled") == "controlled" else None

    findings = []
    if anchor is None and not gap:
        findings.append("unanchored")
    if anchor is not None and kind in KIND_TO_OPERATIONS and anchor not in KIND_TO_OPERATIONS[kind]:
        findings.append(f"kind_mismatch:{kind}")
    return findings
