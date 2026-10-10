# ODR-019 — Nível 2 Incremento 2b: Structural Differentia for HeatExchanger and STHE

**Status:** Accepted  
**Date:** 2026-06-22  
**Scope:** `copi-core` — `iof-av:firstOrderLogicAxiom` on COPI_0000092 (heat exchanger); `copi-enriched-nivel1` — `iof-av:firstOrderLogicAxiom` + `iof-av:naturalLanguageDefinition` on COPI_0000074 (shell and tube heat exchanger); `enrichment_service.py` — annotation emission; `enrichment.db` — fol_axiom correction

---

## Context

Nível 2 Incremento 2a (ODR-018) introduced three structural genus classes
(PressureVessel/0090, Instrument/0091, HeatExchanger/0092) as primitive OWL classes with
genus-only `rdfs:subClassOf` and NLD structural differentia. The FOL axiom on HeatExchanger
was deferred: `"HeatExchanger(x) → PressureVessel(x)"` (genus-only).

Incremento 2b formalises the structural differentia as `iof-av:firstOrderLogicAxiom` (→),
keeping the OWL genus-only encoding and `isPrimitive true` for both HeatExchanger and STHE.

---

## Decision A — Structural differentia uses → (necessary condition), not ↔

**Decision:** Both HeatExchanger and STHE structural axioms use `iof-av:firstOrderLogicAxiom`
(necessary condition, →). `iof-av:firstOrderLogicDefinition` (↔) is NOT used.
`isPrimitive true` is retained on both classes.

**Rationale:**  
The thesis treats designed function as the identity-giving differentia for equipment classes.
STHE is already functionally identified by `HeatTransferFunction → HeatTransferDevice`.
Encoding the structural form also as ↔ would create a second, coextensive necessary-and-sufficient
condition, making a strong empirical claim that the structural form (TubeBundle-in-Shell) and the
functional role are exactly coextensive. The → reading is correct: having the structural form is
necessary for being an STHE, but the primacy of functional identification is preserved.

Full `equivalentClass` axiomatisation with structural differentia is deferred to Incremento 2c.

---

## Decision B — Structural predicates are FOL-only (no OWL declaration)

**Decision:** `SolidHeatTransferSurface`, `TubeBundle`, `Shell` are FOL-only class predicates
with no COPI IRI and no OWL class declaration. `spatiallyContains` is a FOL-only relation predicate.
`hasComponentPartAtAllTimes` (IOF-Core, `iof-constr:`) is the only structural relation with an OWL IRI.

**Rationale:** This is the established COPI precedent for FOL-only predicates: `Fluid`, `Liquid`,
`Gas`, `Vapour` appear in the operation axioms without OWL class declarations; `sameSubstance` and
`derivesFrom` appear as FOL-only relation predicates. Declaring TubeBundle and Shell as OWL classes
would require 2–3 new COPI IRIs, genus axioms, bilingual labels, and a literature source, with
benefit only if OWL part-structure reasoning is required. That is deferred to a dedicated increment.

---

## Decision C — spatiallyContains retained as FOL-only (not replaced by BFO locatedIn)

**Decision:** The STHE structural axiom uses `spatiallyContains(s,tb)` as a FOL-only predicate.
It is NOT replaced by `BFO_0000171` (`locatedIn`).

**Rationale:** `locatedIn` in BFO captures that the spatial region occupied by one continuant
is a sub-region of the spatial region occupied by another. However, a TubeBundle sits inside the
cavity of a Shell; the Shell's material spatial extent does NOT contain the TubeBundle's spatial
extent — only the Shell's enclosed cavity does. `locatedIn` would therefore be semantically
false for the shell-side spatial relationship. `spatiallyContains` expresses the intended
cavity-containment without importing BFO's mereotopological commitments. Analogy: `sameSubstance`
in operation axioms is also a FOL-only predicate not present in IOF-Core or BFO.

---

## Decision D — Grammar correction: bare variable (no ∀x(...) wrapper)

**Decision:** The STHE `fol_axiom` in `enrichment.db` was corrected to remove the `∀x(...)`
wrapper, for consistency with the canonical COPI FOL grammar established in operation axioms:

**Before:** `∀x(ShellAndTubeHeatExchanger(x) → HeatExchanger(x) ∧ ...)`  
**After:** `ShellAndTubeHeatExchanger(x) → HeatExchanger(x) ∧ ...`

All operation axioms in copi-core.ttl use bare variables with implicit universal quantification
(e.g., `LiquidPressureIncrease(x) ↔ MomentumTransfer(x) ∧ ...`). The `∀x(...)` wrapper is
redundant and inconsistent with the house style.

---

## Decision E — Fix: genus 'Instrument' → 'instrument' (label case consistency)

**Decision:** The `genus` field for the `temperature element` row in `enrichment.db` was corrected
from `'Instrument'` (capital I) to `'instrument'` (lowercase), matching the `rdfs:label` of
COPI_0000091. The corresponding key in `_GENUS_TTL` in `enrichment_service.py` was updated to
`"instrument"`. The logical output (`copi:COPI_0000091`) is unchanged.

**Rationale:** All other genus values in the DB use the lowercase form of the rdfs:label
(`"pressure vessel"`, `"heat exchanger"`). `"Instrument"` was an inconsistency introduced during
the 2a implementation that had been worked around by matching the DB value in `_GENUS_TTL`.

---

## FOL axioms formalised

### HeatExchanger (COPI_0000092) — added to copi-core.ttl

```
HeatExchanger(x) → PressureVessel(x) ∧ ∃s(SolidHeatTransferSurface(s) ∧ hasComponentPartAtAllTimes(x,s))
```

**Predicate inventory:**
- `PressureVessel` — COPI_0000090 (OWL class, copi-core)
- `SolidHeatTransferSurface` — FOL-only predicate, no OWL IRI
- `hasComponentPartAtAllTimes` — `iof-constr:hasComponentPartAtAllTimes` (IOF-Core, TransitiveProperty)

**NLD (unchanged from ODR-018):**  
"A pressure vessel in which two fluid circuits are separated by a solid heat-transfer surface, so
that thermal energy passes between them without the circuits mixing."@en

---

### ShellAndTubeHeatExchanger (COPI_0000074) — emitted in copi-enriched-nivel1.ttl

```
ShellAndTubeHeatExchanger(x) → HeatExchanger(x) ∧
  ∃tb(TubeBundle(tb) ∧ hasComponentPartAtAllTimes(x,tb)) ∧
  ∃s(Shell(s) ∧ hasComponentPartAtAllTimes(x,s) ∧ spatiallyContains(s,tb))
```

**Predicate inventory:**
- `HeatExchanger` — COPI_0000092 (OWL class, copi-core)
- `TubeBundle`, `Shell` — FOL-only predicates, no OWL IRI
- `hasComponentPartAtAllTimes` — `iof-constr:hasComponentPartAtAllTimes` (IOF-Core)
- `spatiallyContains` — FOL-only predicate (cavity containment; see Decision C)

**NLD:**  
"A shell and tube heat exchanger is a heat exchanger that has a tube bundle spatially contained
within a surrounding shell."@en

---

## Serializer changes (enrichment_service.py)

- **`@prefix iof-av:`** added to the prefix block in `generate_nivel1_enriched()`.
- **SELECT query** extended with `fol_axiom, nl_definition_en, nl_definition_pt`.
- **Equipment class emission** (both `equivalent` and `necessary` modes): `iof-av:naturalLanguageDefinition`
  emitted for all clusters with a non-empty `nl_definition_en`/`nl_definition_pt`; `iof-av:firstOrderLogicAxiom`
  emitted only when the `fol_axiom` uses `→` without `↔` (structural axiom filter — excludes the
  pre-existing functional ↔ fol_axiom entries for pump, compressor, absorber, temperature element).

---

## Certification outcome (Nível 2 Incremento 2b)

Certified against merged artefact: IOF-Core.rdf + bfo-2020.ttl + copi-core.ttl + copi-enriched-nivel1.ttl (imports stripped).

| Check | Result |
|---|---|
| OWL 2 DL valid | ✓ (robot validate-profile --profile DL, exit 0) |
| HermiT consistent | ✓ (robot reason --reasoner HermiT, exit 0) |
| Pump ⊑ MomentumTransferDevice | ✓ |
| Compressor ⊑ MomentumTransferDevice | ✓ |
| GasAbsorber ⊑ MassTransferDevice | ✓ |
| TemperatureSensor ⊑ MeasurementInstrument | ✓ |
| STHE ⊑ HeatTransferDevice | ✓ |
| STHE ⊑ HeatExchanger | ✓ |
| GasAbsorber ⊑ PressureVessel | ✓ |
| TemperatureSensor ⊑ Instrument | ✓ |
| Classifications identical to Incremento 2a | ✓ (annotation-only diff; zero new logical axioms) |
| firstOrderLogicAxiom present on HeatExchanger (COPI_0000092) | ✓ |
| firstOrderLogicAxiom present on STHE (COPI_0000074) in enriched | ✓ |
| naturalLanguageDefinition present on all 5 equipment classes in enriched | ✓ |
| spatiallyContains in STHE FOL (FOL-only, no OWL declaration) | ✓ |
| No class unsatisfiable | ✓ |

**PARA** — gate antes de push/merge/publish.

---

## Open items (deferred)

- **Incremento 2c** — Full `equivalentClass` + structural `firstOrderLogicDefinition` (↔) for
  HeatExchanger and STHE, once the decision on structural identity is made.
- **TubeBundle and Shell as OWL classes** — deferred to Incremento 2c or later.
- **Machine class** — deferred (Pump, Compressor structural differentia not yet needed).
- **copi-enriched.owl sync** — ✓ Done (pre-publish, 2026-06-22). `components/copi-enriched.owl`
  regenerated from `copi-enriched-nivel1.ttl` (COPI repo commit 113cc06, branch nivel2/incremento-1a-1b).
  Local build certified: DL ✓, HermiT ✓, 8 subsumptions ✓, no unsatisfiable classes ✓.
