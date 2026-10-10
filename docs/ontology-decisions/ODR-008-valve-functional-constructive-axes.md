# ODR-008 — Valve Hierarchy: Functional and Constructive Classification Axes

**Status:** Accepted (revised 2026-06-10)
**Date:** 2026-05-02
**Deciders:** Nicolau Santos

---

## Context

Industrial standards classify valves along two orthogonal axes without making the distinction explicit:

- **Functional axis** — what the valve *does* (the identity-giving designed function): control valve, check valve, relief valve, safety valve, isolation valve.
- **Constructive axis** — how it is *built* (the physical differentia): ball valve, gate valve, globe valve, butterfly valve, needle valve, diaphragm valve.

These axes are collapsed in ISO 15926-4, CFIHOS, and DEXPI, which present both types as a flat list under `VALVE`. This produces several modelling problems:

1. **Intersection classes** — a "ball control valve" belongs simultaneously to the functional type (ControlValve) and the constructive type (BallValve). Standards list it as a third class without expressing the relationship.
2. **Shared function names** — `SafetyValve` and `SafetyReliefValve` both bore `SafetyReliefFunction` in the initial enrichment, making them logically equivalent under `equivalent` axiom mode.
3. **Redundant classes** — `ReliefValve` and `PressureReliefValve` are the same device under different names (API 520 vs. common usage).
4. **Wrong axiom mode** — constructive types (BallValve, GateValve, …) cannot use `equivalent` mode: a ball with seats is a necessary condition of being a BallValve, but OWA means any sufficiently described object could satisfy those conditions without being a BallValve.

---

## Source Definitions

**ControlValve**
- ISA 5.1: *"A final control element that directly manipulates the flow of one or more fluid streams."*
- DEXPI: *"A valve that is used to regulate the flow of a process fluid in response to a process control signal."*

**CheckValve**
- ISO 15926-4: *"A self-operating valve that permits fluid flow in one direction only."*
- CFIHOS: *"A self-operating valve designed to prevent reversal of flow in a pipe."*

**ReliefValve / PressureReliefValve**
- ISO 15926-4: *"A self-operating valve that discharges automatically when the preset upstream pressure is exceeded."*
- API 520: *"A pressure relief valve characterised by gradual opening proportional to the increase in pressure over the opening pressure."* — used for liquid service.
- ISA 5.1: tag abbreviation `PRV`.

**SafetyValve**
- ASME VIII Div.1: *"A pressure relief valve characterised by rapid full opening or pop action."* — used for gas/vapour service.
- ISO 15926-4: *"A pressure relief valve that opens by the static pressure on the inlet side and that has a full opening in the form of a pop action."*

**SafetyReliefValve**
- ASME VIII Div.1: *"A pressure relief valve that may be used as either a safety valve or a relief valve, depending on application."* — dual-service device.
- API 520: term used for valves certified for both gas and liquid overpressure service.

**BallValve**
- ISO 15926-4: *"A valve in which the closure device is a sphere."*
- CFIHOS: *"A valve in which the flow-controlling closure member is a ball, with a hole through it that aligns with the flow path when open."*

---

## Decision

### 1. Two orthogonal hierarchies under Valve

```
Valve  (genus = MaterialArtifact, axiom_mode = necessary)  [ODR-013]
│
├── [functional axis]  — axiom_mode = equivalent (designed function is sufficient)
│   ├── ControlValve       function = ProcessControlledFlowFunction *  [revised 2026-06-10]
│   ├── IsolationValve     function = IsolationFunction
│   ├── CheckValve         function = BackflowPreventionFunction
│   ├── ReliefValve        function = PressureReliefFunction        (alias: PressureReliefValve)
│   ├── SafetyValve        function = SafetyVentingFunction
│   ├── SafetyReliefValve  function = SafetyReliefFunction          (see §3)
│   ├── BlowDownValve      function = RapidDepressurizationFunction
│   └── ChokeValve         function = PressureReductionFunction
│
└── [constructive axis] — axiom_mode = necessary (structural differentia are necessary, not sufficient)
    ├── BallValve
    ├── GateValve
    ├── GlobeValve
    ├── ButterflyValve
    ├── NeedleValve
    ├── PlugValve
    └── DiaphragmValve
```

\* See §4 — ControlValve axiom_mode is deferred.

### 2. Intersection classes

Classes that belong to both axes are expressed as OWL intersections. No separate enrichment job is needed; the reasoner infers membership.

```turtle
:BallControlValve      owl:equivalentClass [ owl:intersectionOf (:BallValve      :ControlValve) ] .
:GlobeControlValve     owl:equivalentClass [ owl:intersectionOf (:GlobeValve     :ControlValve) ] .
:ButterflyControlValve owl:equivalentClass [ owl:intersectionOf (:ButterflyValve :ControlValve) ] .
:GateControlValve      owl:equivalentClass [ owl:intersectionOf (:GateValve      :ControlValve) ] .
```

In the enrichment schema, intersection classes carry `genus = control valve` (the functional genus, primary axis) and note the constructive genus in `differentia_expression`.

### 3. SafetyValve / SafetyReliefValve / ReliefValve disambiguation

Three distinct classes grounded in ASME VIII and API 520:

| Class | Function | Opening behaviour | Typical service |
|---|---|---|---|
| `ReliefValve` | PressureReliefFunction | Modulating (proportional to overpressure) | Liquid |
| `SafetyValve` | SafetyVentingFunction | Snap-acting (full-open at set pressure) | Gas/vapour |
| `SafetyReliefValve` | SafetyReliefFunction | Either (certified dual-service) | Gas or liquid |

`SafetyReliefValve` is the intersection `SafetyValve ⊓ ReliefValve` in OWL semantics but is treated as an independent enriched class because its dual-certification status is a defining characteristic, not derivable from the combination alone.

### 4. ControlValve function name and axiom_mode

**Revised 2026-06-10.** The original ODR proposed `SignalledFlowControlFunction` as the target name and deferred the rename. The LLM enrichment independently converged on `ProcessControlledFlowFunction` with `function_parent = FlowControlFunction` across multiple independent runs. This ODR adopts the LLM's name.

**Adopted:** `function_name = ProcessControlledFlowFunction`, `function_parent = FlowControlFunction`.

**Rationale for the name:** a process-controlled flow function is the role of a final control element in a closed-loop process variable control loop. The differentia `process-controlled` (vs. `signalled`) deliberately excludes motor-operated isolation valves (MOVs): MOVs receive a signal but do not regulate a process variable continuously — they are binary open/close actuators. `ProcessControlledFlowFunction ⊑ FlowControlFunction` holds in the OWL (emitted via `function_parent`).

**axiom_mode stays `necessary`.** The promotion condition for `equivalent` is:

1. The isolation valve family is fully validated (≥ 1 validated row per functional subtype in the DB with `status='validated'`).
2. The guard check `IsolationValve ⊄ ControlValve` passes in `verify_owl.sh` (ensures the two functional types remain disjoint after promotion).

Until both conditions hold, `necessary` mode is the safe interim. The guard is already in `verify_owl.sh` and trivially passes today.

### 5. PressureReliefValve merged into ReliefValve

`PressureReliefValve` (enrichment id 148) is deleted. The label is recorded as an `exactMatch` alias of `ReliefValve` in `cluster_alias`. Rationale: no normative source defines a distinction between the two terms — ISO 15926-4 uses "relief valve", API 520 uses "pressure relief valve" for the same device.

---

## Rationale

### Why functional axis = equivalent, constructive axis = necessary

The functional axis supports `equivalent` mode because the designed function is **both necessary and sufficient** to identify the class: anything that bears `BackflowPreventionFunction` is, by definition, a check valve — no structural constraint is needed for classification. The reasoner can automatically classify instances.

The constructive axis requires `necessary` mode because structural features are **necessary but not sufficient** under OWA: a ball with seats and a body meets the description of a BallValve, but an object with those parts described in a knowledge base could be a prototype or a model — not necessarily a real BallValve. The constructive type is asserted, not inferred.

### Why MaterialArtifact for Valve, Assembly for ControlValve

`Valve` uses `genus = MaterialArtifact` per ODR-013 (reverted from ODR-007). `ControlValve` explicitly asserts `rdfs:subClassOf iof-core:Assembly` via `additional_parents` because body + actuator + positioner is a definitional composition for the kind. Other valve subclasses use `MaterialArtifact` by default; Assembly requires explicit justification per ODR-013.

---

## Changes Applied

| ID | Class | Change |
|---|---|---|
| all valve subtypes with `MaterialArtifact` | — | `genus_bfo_root` → `Assembly` |
| 106 | safety valve | `function_name` SafetyReliefFunction → `SafetyVentingFunction` |
| 164 | butterfly control valve | `genus` Valve → `control valve` |
| 166 | ball control valve | `genus` ControlValve → `control valve` (lowercase) |
| 148 | pressure relief valve | deleted; alias `exactMatch` → relief valve added |

---

## Consequences

- `Valve` genus = `MaterialArtifact` (ODR-013); `ControlValve` additionally asserts `⊑ iof:Assembly` via `additional_parents`.
- Functional valve classes are candidates for `equivalent` mode; constructive classes must use `necessary`.
- `ControlValve` currently uses `necessary` mode. Promotion to `equivalent` requires isolation valve family validation + `IsolationValve ⊄ ControlValve` guard passing in `verify_owl.sh`.
- `ProcessControlledFlowFunction ⊑ FlowControlFunction` is emitted via `function_parent` in the serializer (generic fix, not a special case).
- Future intersection-type valve classes (e.g., `GlobeControlValve`) do not need separate enrichment jobs — they are defined by genus + differentia referencing both axes.
- OWL export regenerated (verify_owl.sh confirms).
