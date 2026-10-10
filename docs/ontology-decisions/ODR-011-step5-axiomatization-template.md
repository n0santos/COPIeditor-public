# ODR-011 — Step 5 Axiomatization: Dual Taxonomy and OWL Template

**Status:** Accepted (implemented in ODR-015 Phase 1, 2026-06-15; see Implementation Notes for deviations)
**Date:** 2026-06
**Deciders:** Nicolau Santos
**Depends on:** ODR-009 (operation class rooting); ODR-010 (participant type vocabulary)

---

## Context

Step 5 of the COPI axiomatization method generates the process-participation signature
⟨I, O, T⟩ of each equipment universal and serializes it as OWL. This ODR specifies:

- the **dual 9×9 taxonomy** — nine operation-category classes paired with nine equipment
  defined classes, joined by function realization;
- the **OWL template** for leaf universals (function class, equipment class, no
  equipment-specific process class);
- the **property chain** that derives equipment participation from function realization;
- the **selective disjointness** pattern and its justification.

The operation class rooting decision (eight physical kinds under `bfo:Process`;
`Measurement` under `iof:MeasurementProcess ⊑ iof:PlannedProcess`) is governed by
ODR-009 and is taken as given here. The participant type vocabulary used in operation
signatures is governed by ODR-010.

---

## Decision

### 1. The dual taxonomy

COPI's functional layer is organized around two cross-cutting axes linked by function
realization:

- An **operation-category** axis — nine classes denoting physical process kinds (eight
  `⊑ bfo:Process`; one reusing `iof:MeasurementProcess ⊑ iof:PlannedProcess`).
- An **equipment defined-class** axis — nine classes, each the class of artifacts whose
  identity-giving designed function is realized in the paired operation kind.

Identity is carried only at the **leaf level** (equipment universals such as `Pump`,
individuated by their designed function). The nine category pairs are classificatory
groupings: they classify but supply no principle of identity. The duality operates at the
BFO **Object** level — individual equipment items. Systems, units, and trains
(`iof:EngineeredSystem ⊑ bfo:ObjectAggregate`) are handled by the functional-location
layer and are out of scope for these nine categories.

### 2. Operation categories

The nine categories and their direct superclass:

| Category | Superclass | Notes |
|---|---|---|
| `MomentumTransfer` | `bfo:Process` | |
| `HeatTransfer` | `bfo:Process` | |
| `MassTransfer` | `bfo:Process` | |
| `MechanicalSeparation` | `bfo:Process` | |
| `ChemicalReaction` | `bfo:Process` | |
| `PhaseChange` | `bfo:Process` | |
| `MaterialContainment` | `bfo:Process` | |
| `FlowControl` | `bfo:Process` | |
| `Measurement` | `iof:MeasurementProcess` | reused, not redeclared; see ODR-009 §4 |

No intermediate COPI grouping class sits between these and their superclass. The rationale
for `bfo:Process` as the genus for the eight physical categories (rather than
`iof:PlannedProcess`) is in ODR-009.

Each category refines into **operation leaves** named by the physical transformation, not
by the equipment that brings it about. The full set of ~40 leaves grows through enrichment;
the nine categories are fixed. Leaf examples:

```
MomentumTransfer
  ├── LiquidPressureIncrease
  ├── GasPressureIncrease
  └── FluidConveyance

HeatTransfer
  ├── SensibleHeatExchange
  ├── LatentHeatExchange
  └── DirectFiredHeating

MassTransfer
  └── GasAbsorption

MechanicalSeparation
  ├── PhaseSeparation
  └── Filtration

PhaseChange
  └── Vaporization

FlowControl
  └── FlowModulation

Measurement   (⊑ iof:MeasurementProcess)
  ├── TemperatureMeasurement
  ├── PressureMeasurement
  ├── FlowMeasurement
  ├── LevelMeasurement
  └── CompositionMeasurement
```

Operation leaves carry necessary input/output signatures using `iof:hasInput` and
`iof:hasSpecifiedOutput` (fillers from the ODR-010 vocabulary). The signatures are
necessary, not sufficient — the individuating differentia is expressed in FOL, not OWL 2
DL. `hasSpecifiedInput` does not exist in IOF-Core 202602; inputs use `iof:hasInput`.

```turtle
copi:LiquidPressureIncrease rdfs:subClassOf copi:MomentumTransfer ,
    [ owl:onProperty iof:hasInput          ; owl:someValuesFrom copi:PortionOfLiquid ] ,
    [ owl:onProperty iof:hasSpecifiedOutput ; owl:someValuesFrom copi:PortionOfLiquid ] .

copi:GasPressureIncrease rdfs:subClassOf copi:MomentumTransfer ,
    [ owl:onProperty iof:hasInput          ; owl:someValuesFrom copi:PortionOfGas ] ,
    [ owl:onProperty iof:hasSpecifiedOutput ; owl:someValuesFrom copi:PortionOfGas ] .
```

`LiquidPressureIncrease` and `GasPressureIncrease` are asserted disjoint (§5).

### 3. Equipment defined classes

Each of the nine categories is paired with an equipment defined class — the class of
artifacts whose identity-giving designed function is realized in that category:

```turtle
copi:MomentumTransferEquipment owl:equivalentClass [
    owl:intersectionOf (
        iof:MaterialArtifact
        [ owl:onProperty iof:hasFunction ; owl:someValuesFrom [
            owl:intersectionOf (
                iof:DesignedFunction
                [ owl:onProperty bfo:BFO_0000054 ;
                  owl:someValuesFrom copi:MomentumTransfer ] ) ] ] ) ] .
```

The nine pairs:

| Operation category | Equipment defined class | Example leaf universals |
|---|---|---|
| MomentumTransfer | MomentumTransferEquipment | Pump, Compressor, Fan, Pipe, Mixer |
| HeatTransfer | HeatTransferEquipment | ShellTubeHeatExchanger, FiredHeater, Reboiler |
| MassTransfer | MassTransferEquipment | GasAbsorber, Stripper, DistillationColumn |
| MechanicalSeparation | MechanicalSeparationEquipment | ThreePhaseSeparator, Cyclone, Filter |
| ChemicalReaction | ChemicalReactor | CSTR, PlugFlowReactor |
| PhaseChange | PhaseChangeEquipment | Evaporator, Condenser, Crystallizer |
| MaterialContainment | ContainmentEquipment | StorageTank, PressureVessel, Accumulator |
| FlowControl | FlowControlEquipment | ControlValve, ShutoffValve, ReliefValve |
| Measurement | MeasurementInstrument | TemperatureTransmitter, PressureTransmitter |

**The genus is `iof:MaterialArtifact`** (BFO Object), not a disjunction with
`iof:EngineeredSystem`. `iof:Assembly ⊑ iof:MaterialArtifact`, so multi-part equipment is
covered. No `copi:Equipment` class is minted. `iof:PieceOfEquipment` is not referenced in
COPI axioms — a deployed equipment instance that bears an `EquipmentRole` is classified as
`PieceOfEquipment` by IOF's own definition at the instance level.

Equipment universals are **not asserted** as subclasses of these defined classes; the
reasoner classifies them by inference from the function alone.

### 4. Realization bridge and property chain

The identity-giving function of a leaf universal is `iof:DesignedFunction` carrying a
closure on its realization:

```turtle
copi:PumpingFunction rdfs:subClassOf iof:DesignedFunction ,
    [ owl:onProperty bfo:BFO_0000054 ; owl:someValuesFrom copi:LiquidPressureIncrease ] ,
    [ owl:onProperty bfo:BFO_0000054 ; owl:allValuesFrom  copi:LiquidPressureIncrease ] .
```

The `allValuesFrom` closure (realized *only* in the paired leaf) is required for the
disjointness argument in §5.

Equipment participation in the realizing process is derived, not asserted, via a property
chain on a COPI sub-property of `bfo:participates_in`:

```turtle
copi:participatesIn rdfs:subPropertyOf bfo:BFO_0000056 .

copi:participatesIn owl:propertyChainAxiom
    ( iof:hasFunction bfo:BFO_0000054 ) .
```

The chain is placed on `copi:participatesIn` rather than directly on `bfo:BFO_0000056` to
avoid globally affecting all `participates_in` reasoning. Either placement is DL-feasible
provided the property is not used in cardinality restrictions (the chain makes it
non-simple). To be confirmed under HermiT on the pilot set.

### 5. Step 5 OWL template

For each equipment universal E with identity-giving function F realized in operation leaf P
(genus is `iof:MaterialArtifact` or `iof:Assembly`; parts are Pᵢ):

```turtle
# Function class
copi:<F> rdfs:subClassOf iof:DesignedFunction ,
    [ owl:onProperty bfo:BFO_0000054 ; owl:someValuesFrom copi:<P> ] ,
    [ owl:onProperty bfo:BFO_0000054 ; owl:allValuesFrom  copi:<P> ] .

# Equipment universal
copi:<E> rdfs:subClassOf <genus> ,
    [ owl:onProperty iof:hasFunction ;
      owl:someValuesFrom copi:<F> ] ,
    [ owl:onProperty iof:hasComponentPartAtAllTimes ;
      owl:someValuesFrom copi:<Pᵢ> ] ...
```

There is **no equipment-specific process class** and **no `participatesIn` axiom on the
equipment** — participation is derived via the chain in §4. The operation leaf P is shared
across all equipment that realize that operation; no `PumpingProcess`-per-equipment is
emitted.

Worked example — Pump (genus Assembly):

```turtle
copi:PumpingFunction rdfs:subClassOf iof:DesignedFunction ,
    [ owl:onProperty bfo:BFO_0000054 ; owl:someValuesFrom copi:LiquidPressureIncrease ] ,
    [ owl:onProperty bfo:BFO_0000054 ; owl:allValuesFrom  copi:LiquidPressureIncrease ] .

copi:Pump rdfs:subClassOf iof:Assembly ,
    [ owl:onProperty iof:hasFunction ;
      owl:someValuesFrom copi:PumpingFunction ] ,
    [ owl:onProperty iof:hasComponentPartAtAllTimes ;
      owl:someValuesFrom copi:PumpCasing ] ,
    [ owl:onProperty iof:hasComponentPartAtAllTimes ;
      owl:someValuesFrom copi:DisplacingElement ] ,
    [ owl:onProperty iof:hasComponentPartAtAllTimes ;
      owl:someValuesFrom copi:FluidInlet ] ,
    [ owl:onProperty iof:hasComponentPartAtAllTimes ;
      owl:someValuesFrom copi:FluidOutlet ] .

# Reasoner infers: copi:Pump ⊑ copi:MomentumTransferEquipment
```

Part restrictions use `someValuesFrom` only — `hasComponentPartAtAllTimes` is non-simple
(transitive closure), making qualified cardinality restrictions DL-unsafe.

### 6. Selective disjointness

The nine categories are **not** asserted pairwise disjoint — some operations genuinely
co-occur (reactive absorption is simultaneously MassTransfer and ChemicalReaction; a
reboiler is simultaneously HeatTransfer and PhaseChange). The partition is underwritten by
two conditions together:

1. each artifact has exactly **one** identity-giving function, fixing a single primary
   category; and
2. for genuinely competing pairs, the operation differentiae are incompatible.

Equipment-level disjointness is **asserted on competing pairs**, not entailed globally. The
pump/compressor case is the worked instance of the four-step argument:

1. `LiquidPressureIncrease ⊓ GasPressureIncrease ⊑ ⊥` (disjoint leaves, per §2)
2. → `PumpingFunction` and `CompressionFunction` are *entailed* disjoint (each realized
   only in its leaf, via the `allValuesFrom` closure)
3. → `Pump ⊓ Compressor ⊑ ⊥` is *asserted* as a domain claim that the entailed
   function-disjointness renders coherent rather than ad hoc

Function realization alone leaves `Pump ⊓ Compressor` satisfiable (an artifact may bear a
secondary function), which is why equipment disjointness is asserted, not derived.

A multi-function artifact (e.g., a reboiler) classifies into multiple equipment categories
intentionally — it is inferred into both `HeatTransferEquipment` and `PhaseChangeEquipment`.
This preserves both failure modes in a reliability record rather than forcing a single
category.

### 7. Operation leaf naming convention

Leaves are named by the **physical transformation**, not by the equipment or function:
`LiquidPressureIncrease`, not `PumpingProcess`; `GasAbsorption`, not `GasAbsorberProcess`.
This keeps the disjointness arguments legible and maintains the unit-operations anchor of
the operation axis independently of the equipment axis.

Baseline names migrated from the FOIS baseline (`coppp-equipment-anon_3.ttl`):

| Baseline name | Canonical leaf name | Category |
|---|---|---|
| PumpingProcess | LiquidPressureIncrease | MomentumTransfer |
| GasCompressionProcess | GasPressureIncrease | MomentumTransfer |
| PassiveTransportProcess | FluidConveyance | MomentumTransfer |
| PhaseSeparationProcess | PhaseSeparation | MechanicalSeparation |
| FiltrationProcess | Filtration | MechanicalSeparation |
| FlowRegulationProcess | FlowModulation | FlowControl |
| MassTransferProcess / GasAbsorptionProcess | GasAbsorption | MassTransfer |
| MeasurementObservationProcess | (→ iof:MeasurementProcess subclasses) | Measurement |

### 8. Annotation requirements

Every operation category and leaf introduced under this ODR carries:
- `rdfs:label` in `@en` and `@pt-BR`.
- `iof-av:naturalLanguageDefinition` in `@en` and `@pt-BR` (not `obo:IAO_0000115`).
- Where applicable: `iof-av:semiFormalNaturalLanguageAxiom`, `iof-av:firstOrderLogicAxiom`,
  `iof-av:isPrimitive`, `iof-av:primitiveRationale`, `iof-av:explanatoryNote`,
  `iof-av:adaptedFrom`, `iof-av:synonym`.
- Cross-standard references via `skos:exactMatch` / `skos:closeMatch` to ISO 15926-4,
  CFIHOS, DEXPI, PCA RDL, ISO 14224 where established (preserving the 21 references from
  the FOIS baseline).

---

## Rationale

**No equipment-specific process class.** A ball control valve, a globe control valve, and
a pneumatic control valve all realize `FlowModulation` — one shared operation leaf. Minting
`BallControlValveFlowControlProcess` would mirror the equipment axis onto the operation
axis, destroying the independence that makes the dual taxonomy useful.

**No `participatesIn` asserted on equipment.** The property chain derives participation
from function-bearing alone. Asserting it redundantly would require manual maintenance and
creates inconsistency risk if the chain is not applied.

**`allValuesFrom` closure on functions.** Without the closure, `PumpingFunction realized_in
LiquidPressureIncrease` is compatible with the function also being realized in
`GasPressureIncrease`. The closure makes the disjointness argument valid.

**`iof:MaterialArtifact` as genus, not the disjunction.** The disjunction
`MaterialArtifact ⊔ EngineeredSystem` crosses the BFO Object/ObjectAggregate boundary.
COPI's nine categories classify individual machines (Objects); the aggregate level belongs
to the functional-location layer.

**Selective, not total, disjointness.** Real operations co-occur; a total partition would
be false to the domain. The objectivity of the partition rests on uniqueness of the
identity-giving function plus genuine signature incompatibility on specific competing pairs.

---

## Consequences

**`copi-base.ttl`** (artifact to be created in `src/ontology/components/`):
- Nine operation categories with their `rdfs:subClassOf` declarations (per ODR-009).
- Operation leaves with necessary input/output signatures (per ODR-010 participant vocab).
- Nine equipment defined classes.
- `copi:participatesIn` sub-property with the `hasFunction ∘ realized_in` chain.
- `Measurement` reuses `iof:MeasurementProcess` — not redeclared.
- IOF-Core import pinned to 202602 across all emission sites (config.py, TTL serializer,
  OFN serializer — fixing the current three-way inconsistency: `202601` in config,
  `202502` in OFN, unversioned in TTL context).

**COPIeditor serializer changes** (`enrichment/enrichment_service.py`):
- Stop emitting equipment-specific process classes and `participatesIn` axioms on equipment.
- Emit the §5 template: function with `someValuesFrom + allValuesFrom` on `BFO_0000054`;
  equipment with `hasFunction` + parts (no cardinality).
- Reference operation leaves from `copi-base` by IRI; do not redeclare them per enrichment.
- Do not assert `E ⊑ EquipmentCategory` — leave to inference.
- Migrate from `obo:IAO_0000115` to `iof-av:naturalLanguageDefinition` for all
  natural-language definitions.

**`enrichment/prompts.py`**:
- Rename `transformation_kind` → `process_kind`; constrain values to operation leaf IRIs
  from `copi-base` (plus a `proposed` escape).

**`enrichment/verify_service.py`**:
- Extend `check_undeclared_classes` to validate template conformance: every axiomatized
  universal must have a function class with `someValuesFrom + allValuesFrom` on
  `BFO_0000054`, referencing a leaf from `copi-base`.

**Baseline migration** (`coppp-equipment-anon_3.ttl`):
- Rename operation classes per §7 migration table.
- Add `allValuesFrom` realization closure to all function classes.
- Add the nine category classes and nine equipment defined classes (absent in the baseline).
- Preserve all `skos:exactMatch`/`closeMatch`, bilingual labels, and IOF annotations.
- Recommended path: scripted rdflib transform + manual review.

**HermiT check**: re-run consistency after adding the nine equipment defined classes and the
property chain. Confirm DL-safety of the chain placement on `copi:participatesIn`.

---

## Implementation Notes (ODR-015 Phase 1, 2026-06-15)

### Deviation §4 — Property chain placed on `obo:BFO_0000056` — RESOLVED (PR #10, 2026-06-18)

This ODR specifies (§4) that the `hasFunction ∘ realizedIn` chain be placed on a
**`copi:participatesIn` sub-property** of `bfo:BFO_0000056`. The Phase 1 implementation
had placed it directly on `obo:BFO_0000056`, making BFO's `participates_in` non-simple
globally. This was corrected in COPI PR #10.

Current state in `copi-core.ttl` (conforms to spec):

```turtle
copi:participatesIn a owl:ObjectProperty ;
    rdfs:subPropertyOf obo:BFO_0000056 ;
    owl:propertyChainAxiom ( iof-constr:hasFunction obo:BFO_0000054 ) .
```

The chain entailment (`bfo:participatesIn` inferred for any bearer of a realized function)
was verified empirically via a witness-class approach (HermiT: `MomentumTransferDevice ⊑
∃obo:BFO_0000056.MomentumTransfer`) and is protected by guard-11
(`guard-11-chain-participates-in.sparql`, merged in COPI PR #12). The guard reports a
violation if the chain or the `subPropertyOf obo:BFO_0000056` link is removed.

---

## Amendment (2026-10-10) — Step 5 output property is `hasOutput`, not `hasSpecifiedOutput`

Wherever this ODR writes `iof:hasSpecifiedOutput` (the Decision text and the two Turtle
examples above), the property emitted since this amendment is **`iof-core:hasOutput`**.

**Why.** In IOF-Core 202602, `hasSpecifiedOutput` is a sub-property of `hasOutput` whose
domain is `iof:PlannedProcess` and which presupposes an `ObjectiveSpecification` that
specifies the output. Step 5 only asserts that a process of this kind yields a participant of
a given type; it carries no objective specification. `hasOutput` (domain `bfo:Process`) says
exactly that and mirrors `hasInput`. The generated FOL already used `hasOutput`, so the OWL
and the FOL disagreed. Tracked in issue #50.

**Scope of the change.**
- `generate_turtle()` emits `iof-core:hasOutput` (283 restrictions in `copi-enriched.owl`).
- Inputs are unchanged (`iof-core:hasInput`).
- The `MeasurementProcess` constraint (`hasSpecifiedOutput only MeasurementInformationContentEntity`,
  see `docs/findings/measurement-process-output-typing-conflict.md`) is a property of the
  upstream IOF class and is not touched here; it no longer interacts with COPI's Step 5
  output restrictions because those are now on the super-property.

**Verification.** `scripts/verify_owl.sh` (all gates, HermiT) passes on the regenerated
component; OOPS! was not run for this change.
