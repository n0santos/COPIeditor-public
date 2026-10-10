# ODR-009 (revised): Ontological rooting of the operation classes

- **Status:** Accepted (implemented in ODR-015 Phase 1, 2026-06-15)
- **Date:** 2026-06
- **Related:** I2 (axiomatization method); dual 9×9 taxonomy; ISO 14224 failure-mode mapping; ODR for equipment categories

## Context

COPI defines nine operation classes (MomentumTransfer, HeatTransfer, MassTransfer,
MechanicalSeparation, ChemicalReaction, PhaseChange, MaterialContainment, FlowControl,
Measurement). v1 rooted all nine under `iof:PlannedProcess` (the "plant-operations
reading"), on the grounds that the installation is engineered and every operation occurs
by design ("no spontaneous filtration in a plant"). The rejected alternative was the
"transformation reading" (rooting under `bfo:Process`), motivated by anomalous events such
as leaks, runaway reactions, and flashing.

Group review (Jun 2026) re-raised the transformation reading with a stronger argument:
rooting under `PlannedProcess` makes anomalous/unplanned processes unrepresentable, yet
these are exactly the processes that **ISO 14224 failure modes** — a COPI motivating use
case — concern. A runaway reaction is a chemical reaction that is not planned; flashing is
an unplanned phase change; a leak is a loss of containment. Under v1 none of these can
instantiate a COPI operation, so COPI's failure-mode motivation contradicts its own
process rooting.

## Decision (hybrid, option c)

1. Root the eight physical operation classes (all but Measurement) under **`bfo:Process`
   (BFO_0000015)**, not under `iof:PlannedProcess`. They denote physical process *kinds*,
   independent of whether a given instance is planned.
2. Treat planned-ness as **orthogonal**: the *designed* operation is the operation kind
   co-classified as `iof:PlannedProcess`. An equipment's designed function is `realizedIn`
   a planned process of the corresponding kind — preserving the
   DesignedFunction ⇄ PlannedProcess and DesignSpecification ⇄ PlanSpecification parallels
   for the normal (by-design) case.
3. Represent anomalies as instances of the relevant kind that are **not** planned
   (runaway = `ChemicalReaction ⊓ ¬planned`; flashing = `PhaseChange ⊓ ¬planned`), or, where
   the anomaly is a genuinely distinct kind, under a dedicated class (`LossOfContainment`
   for leaks) that is also `⊑ bfo:Process` and not planned.
4. **Measurement keeps its IOF reuse:** `copi:Measurement` stays aligned with
   `iof:MeasurementProcess (⊑ iof:PlannedProcess)`. The asymmetry is principled — a
   measurement is an intentional, planned act, whereas physical transformations can occur
   unplanned.

## Rationale

- Recovers coverage of failure/abnormal processes (ISO 14224), excluded by construction in
  v1 — removing the tension between COPI's failure-mode motivation and its rooting.
- Ontologically more faithful: a runaway reaction is the same reaction kind gone
  uncontrolled, not a different kind. Rooting the kind under `Process` lets the same
  universal cover planned and unplanned instances.
- Keeps the design story intact for the normal case: the by-design realization of an
  equipment's function is still a `PlannedProcess`, so the DesignedFunction ⇄ PlannedProcess
  parallel and the "EquipmentRole realized in a planned process" reading survive for the
  designed operation.
- The equipment defined classes are unaffected: their bridge axiom refers to the operation
  *kind* (`realizedIn.MassTransfer`), which resolves whether the kind sits under `Process`
  or `PlannedProcess`.

## Consequences

- The "every operation occurs by design" framing is narrowed: it describes the *designed*
  operation, not the operation *kind*. Slides/paper that asserted the nine ⊑ PlannedProcess
  must change to ⊑ `bfo:Process` + planned-ness as a layer, with Measurement as the noted
  exception.
- Introduce (a) the orthogonal planned/unplanned classification and (b) at least one
  anomalous kind (`LossOfContainment`) plus a relation linking anomalies to the
  operation/equipment they afflict (for ISO 14224 mapping).
- Re-run the HermiT consistency check after re-rooting (not yet executed).

## Alternatives considered

- **v1 plant-operations-only** (all nine ⊑ PlannedProcess): rejected — excludes failure
  processes; conflicts with the ISO 14224 use case.
- **Conservative add-on** (keep nine ⊑ PlannedProcess; add a separate `AnomalousProcess`
  branch with a distinct class for every anomaly): not adopted as the primary route because
  it duplicates kinds (RunawayReaction ≠ ChemicalReaction) and loses the fact that anomalies
  are often the same kind unplanned. Retained only for genuinely distinct anomalies
  (`LossOfContainment`).

---

## Amendment A (2026-06-18): `copi:Operation` as explicit root universal; genus correction

### Context
ODR-009 enumerated the operation categories but never explicitly introduced their
common superclass, `copi:Operation`, which is nonetheless declared in `copi-core`
as the root of the operation taxonomy. A provenance review (ODR-015 §9) surfaced it
as a class present in the published core without a recorded decision. Separately,
`copi:Operation` was asserted `rdfs:subClassOf bfo:Process`, which under-commits
relative to its own definition.

### Decision
**A1 — Introduce `copi:Operation` as a primitive root universal**, not a grouping of
convenience. Its essence: *a planned process that an item of process-industry
equipment is designed to bring about or take part in* — i.e., a process-industry
unit operation. The COPI-native operation categories specialise it; measurement is
handled by reusing `iof-constr:MeasurementProcess` (a sibling `PlannedProcess`),
giving nine operation classes in total.

**A2 — Correct the genus** from `bfo:Process` to `iof-constr:PlannedProcess`. The
categories remain `⊑ copi:Operation`. `copi:LossOfContainment` remains
`⊑ bfo:Process`, outside `Operation`, as an unplanned anomalous process.

### Rationale
- **Universal, not grouping.** Members are unit operations in the chemical-
  engineering tradition (cf. each category's `adaptedFrom`), sharing a typed
  participation signature (material inputs/outputs) and differing by the
  transformation they effect. A primitive class asserting only its genus in OWL
  (`Operation(x) → Process(x)`) is not demoted by that — primitive universals with a
  natural-language definition and an OWL-inexpressible differentia are standard BFO
  practice. `Operation` carries the shared unit-operation frame the flat alternative
  would force onto each category in isolation.
- **A2 — Genus is `iof-constr:PlannedProcess`, not `bfo:Process`.** In the process
  industries the plant is itself an engineered artifact whose intended operation is
  specified, simulated, and prescribed before construction (process flow diagrams,
  P&IDs, dynamic process simulation, operating procedures). That body of
  specification is a `PlanSpecification`, and the operations the equipment performs
  are its prescribed executions. An operation is thus two facets of one occurrent:
  the realization of the equipment's `DesignedFunction` (the realization bridge) and
  the execution of the plant's process plan. The general gap between function
  realization and plan prescription — a heart realizes its pumping function with no
  plan prescribing it — closes in this domain because the bearer's design and the
  process plan are co-specified. The universal commitment (every `Operation` is
  `prescribedBy` some `PlanSpecification`) is kept true by excluding genuine,
  undesigned anomalies such as `LossOfContainment`, which remain outside `Operation`
  directly under `bfo:Process`.
- **What rests on the root:** it is the occurrent counterpart in the dual taxonomy
  and the relatum the realisation bridge pairs each equipment defined class against;
  and the single referable kind — "the operations of a process industry" — that lets
  the layer transfer to an unrelated industry. The broad `PlannedProcess`
  (maintenance, inspection, administrative processes) cannot serve as that anchor.

### Consequences
- Edit `copi:Operation` in `copi-core.ttl`: `rdfs:subClassOf` → `iof-constr:PlannedProcess`.
- Replace its `iof-av:primitiveRationale` ("abstract superclass … not by a single
  formal condition") with a statement of the unit-operation essence above; keep
  `iof-av:isPrimitive true`.
- **Re-validate (DL + HermiT)** after the genus change: tightening to `PlannedProcess`
  interacts with whatever `PlannedProcess` asserts — confirm OWL 2 DL and HermiT
  consistency, and that `PlannedProcess` carries no OWL restriction the operations
  fail to satisfy.

### Provenance
This amendment is the `dcterms:source` for `copi:Operation` under ODR-015 §9.
