# ODR-016 — STHE Nível 1 Encoding: op-leaf and axiom_mode decisions

**Status:** Accepted  
**Date:** 2026-06-21  
**Scope:** `enrichment` — Nível 1, cluster `shell and tube heat exchanger`

---

## Context

The shell-and-tube heat exchanger (STHE) is the fifth equipment leaf added in Nível 1.  
Two encoding decisions arise that differ from the four prior leaves (Pump, Compressor,
GasAbsorber, TemperatureSensor) and require explicit justification.

---

## Decision A — op-leaf = HeatTransfer directly (COPI_0000004), no specialised leaf

**Decision:** The `HeatTransferFunction` for STHE is encoded as:

```turtle
copi:COPI_0000068  rdfs:subClassOf  [ BFO_0000054  some  copi:COPI_0000004 ] .
```

`COPI_0000004` (`HeatTransfer`) is used directly as the operation target — there is no
intermediate leaf class (e.g. `HeatExchange ⊑ HeatTransfer`) created at this level.

**Rationale:**  
The four prior leaves all have purpose-specific sub-operations already present in
`copi-core` (e.g. `LiquidPressureIncrease ⊑ MomentumTransfer`). No such sub-operation
exists under `HeatTransfer` in the current core. Creating `HeatExchange` as a Nível 1
leaf solely to satisfy symmetry would add an under-specified class with no modelling
gain: the STHE differentia (TubeBundle/Shell structure) is a structural constraint, not
an operational one, and does not narrow the process category meaningfully at this stage.

**Acknowledged asymmetry:** Nível 1 has STHE realising the category root (`HeatTransfer`)
rather than a leaf. This is temporary. A `HeatExchange ⊑ HeatTransfer` leaf (or similar
specialisation such as `SensibleHeatTransfer`) is deferred to Nível 2, where additional
heat-transfer equipment (air coolers, plate exchangers, fired heaters) will be modelled
and a shared leaf can be grounded in genuine operational distinctions.

---

## Decision B — axiom_mode = necessary (primitive class)

**Decision:** `ShellAndTubeHeatExchanger` (COPI_0000074) is encoded as a primitive class:

```turtle
copi:COPI_0000074  rdfs:subClassOf  iof-constr:Assembly ;
                   rdfs:subClassOf  [ iof-constr:hasFunction  some  copi:COPI_0000068 ] .
```

No `owl:equivalentClass` is asserted.

**Rationale:**  
The identity conditions for STHE include a structural differentia not yet formalised in
the ontology: `∃hasComponentPartAtAllTimes.TubeBundle ⊓ ∃hasComponentPartAtAllTimes.Shell
⊓ ∃spatiallyContains.(TubeBundle ⊓ ∃spatiallyContainedIn.Shell)`. A defined class
(`owl:equivalentClass`) must capture sufficient conditions. Asserting equivalence without
formalising the shell-and-tube structure would make the boundary under-defined — any
assembly bearing a `HeatTransferFunction` would satisfy the definition, conflating the
STHE with plate exchangers, air coolers, etc.

The primitive encoding is correct here: it asserts that STHE *is* an Assembly with a
HeatTransferFunction (necessary conditions only). HermiT still infers
`STHE ⊑ HeatTransferDevice` from the `HeatTransferDevice` equivalentClass in core.

The structural differentia (TubeBundle/Shell parts) will be axiomatised in Nível 2 using
a `hasComponentPart`-style property, at which point the axiom_mode may be promoted to
`equivalent`.

---

## Classification outcome (Nível 1 certified)

| Entailment | Result |
|---|---|
| COPI_0000074 ⊑ COPI_0000017 (STHE ⊑ HeatTransferDevice) | ✓ inferred by HermiT |
| OWL 2 DL valid | ✓ |
| HermiT consistent | ✓ |
| No unsatisfiable classes | ✓ |
