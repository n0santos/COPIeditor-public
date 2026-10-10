# ODR-017 — Nível 2 Incremento 1a: Operation Anchors and OntoCAPE Cross-References

**Status:** Accepted  
**Date:** 2026-06-22  
**Scope:** `copi-core` — operation leaf annotations; HeatExchange leaf; OntoCAPE cross-referencing strategy

---

## Context

Nível 2 of the COPI enrichment programme adds formal anchoring for the five Nível 1 operation leaves
(LiquidPressureIncrease, GasPressureIncrease, GasAbsorption, Vaporization) and introduces the
HeatExchange leaf deferred from Nível 1 (ODR-016 §A). Three questions arise:

1. Should COPI rename or reorganise its operation taxonomy to align with OntoCAPE?
2. How should cross-references to OntoCAPE be encoded without breaking OWL 2 DL?
3. Which OntoCAPE classes correspond to the five COPI operations?

---

## Decision A — COPI taxonomy structure is retained; OntoCAPE alignment is by cross-reference only

**Decision:** COPI maintains its organisation by transport phenomenon (momentum, heat, mass transfer;
phase change; mechanical separation; etc.) and does **not** adopt OntoCAPE's `EnthalpyChange`
hierarchy as a structural principle.

**Rationale:**  
OntoCAPE (Marquardt 2010) organises unit operations under `EnthalpyChange → {TemperatureChange,
PhaseChange, PressureChange}`. This is thermodynamically coherent but groups pumping and compression
(mechanical energy transfer) as enthalpy-change operations, which obscures the momentum-transfer
characterisation central to the COPI design (and to the Bird-Stewart-Lightfoot treatment of
transport phenomena).

The two organisations are grounded in different disciplinary traditions — neither is wrong. COPI's
design is *intentionally* grounded in transport phenomena (BSL), complemented by unit-operations
coverage (McCabe-Smith-Harriott, Perry). Renaming or restructuring would invalidate existing ODRs
and break the five Nível 1 classification guards. Alignment is achieved by annotation cross-reference,
not structural reuse.

---

## Decision B — Cross-reference encoding: rdfs:seeAlso as annotation

**Decision:** OntoCAPE correspondences are encoded on each leaf as:
- `iof-av:naturalLanguageDefinition` — full bilingual definition (IOF annotation discipline).
- `dcterms:source` — canonical literature reference.
- `rdfs:seeAlso <OntoCAPEIRI>` — annotation pointing to the closest OntoCAPE class.

`skos:definition` is **not** used. Conformance cleanup (2026-06-22): `skos:definition` entries
added in Incremento 1a were removed — COPI follows IOF annotation discipline where definitions
live exclusively on `iof-av:naturalLanguageDefinition`.

`skos:closeMatch` is **not** used as an OWL object property between COPI and OntoCAPE classes.
`rdfs:seeAlso` is an `owl:AnnotationProperty` in OWL 2 and carries no logical consequences,
preserving the OWL 2 DL profile. A `skos:closeMatch` declared as `owl:ObjectProperty` would be an
inter-ontology axiom and would require importing or asserting the OntoCAPE class hierarchy,
potentially pulling OntoCAPE reasoning into the COPI closure.

---

## Decision C — HeatExchange leaf (COPI_0000089) introduced in Nível 2

**Decision:** A new leaf `HeatExchange (COPI_0000089) ⊑ HeatTransfer (COPI_0000004)` is created
in `copi-core`. The ShellAndTubeHeatExchanger's `HeatTransferFunction (COPI_0000068)` is
re-pointed from `BFO_0000054 some HeatTransfer` to `BFO_0000054 some HeatExchange`.

**Rationale (cf. ODR-016 §A):**  
The STHE function should realise a specific sub-operation of HeatTransfer (two-fluid stream exchange)
rather than the category root. The parent `HeatTransferDevice` equivalentClass axiom uses
`someValuesFrom HeatTransfer`; since `HeatExchange ⊑ HeatTransfer`, HermiT still infers
`STHE ⊑ HeatTransferDevice` — classification guard-12 continues to pass.

**OWL encoding (primitive):**

```turtle
copi:COPI_0000089 a owl:Class ;
    rdfs:subClassOf copi:COPI_0000004 ;
    rdfs:label "heat exchange"@en , "troca de calor"@pt-br ;
    iof-av:naturalLanguageDefinition "A heat-transfer operation in which thermal energy is exchanged between two or more fluid streams, typically separated by a solid heat-transfer surface, without mixing those streams."@en , ...@pt-br ;
    iof-av:firstOrderLogicDefinition "HeatExchange(x) ↔ HeatTransfer(x) ∧ ∃f1,f2,f3,f4(hasInput(x,f1) ∧ Fluid(f1) ∧ hasInput(x,f2) ∧ Fluid(f2) ∧ f1≠f2 ∧ hasOutput(x,f3) ∧ Fluid(f3) ∧ hasOutput(x,f4) ∧ Fluid(f4) ∧ f3≠f4 ∧ derivesFrom(f3,f1) ∧ derivesFrom(f4,f2) ∧ ¬∃c3(hasConstituent(f3,c3) ∧ ¬∃c1(hasConstituent(f1,c1) ∧ sameSubstance(c1,c3))) ∧ ¬∃c4(hasConstituent(f4,c4) ∧ ¬∃c2(hasConstituent(f2,c2) ∧ sameSubstance(c2,c4))))" ;
    rdfs:seeAlso <http://www.theworldavatar.com/ontology/ontocape/chemical_process_system/CPS_function/process.owl#TemperatureChange> .
```

**Incremento 1b (FOL completion):** The genus-only `firstOrderLogicAxiom` (→) was upgraded to a
full `firstOrderLogicDefinition` (↔) with two-fluid-stream input/output pairing and constituent
conservation via `sameSubstance`. OWL encoding remains genus-only (`rdfs:subClassOf HeatTransfer`)
— the pairwise `derivesFrom` linkage and cross-stream composition conservation exceed OWL 2 DL
expressivity. The constituent predicate uses `sameSubstance(c_a, c_b)` (not identity `c_a = c_b`)
following the per-portion constituent model of COPI_0000013. `iof-av:isPrimitive true` is set.

The two-fluid-stream constraint is captured in FOL only. Promotion to `equivalentClass` is deferred
to a later Nível 2 increment once the structural differentia (surface-separated streams) is
formalised.

---

## Mapping table — 5 COPI operations vs OntoCAPE

| COPI IRI | COPI label | OntoCAPE class | Match type | Status |
|---|---|---|---|---|
| COPI_0000011 | liquid pressure increase | `process.owl#PressureChangeOfLiquid` | closeMatch | ✓ confirmed |
| COPI_0000012 | gas pressure increase | `process.owl#PressureChangeOfGas` | closeMatch | ✓ confirmed |
| COPI_0000013 | gas absorption | `process_extensionTGL25001.owl#Absorption` | closeMatch (different genus: Separation vs MassTransfer; identical gas→liquid scope) | ✓ confirmed |
| COPI_0000014 | vaporization | `process_extensionTGL25001.owl#Vaporization` | closeMatch | ✓ confirmed |
| COPI_0000089 | heat exchange | `process.owl#TemperatureChange` | closeMatch (COPI more specific: two-fluid constraint) | ✓ confirmed |

**Match notes:**

- **0011 / 0012 (closeMatch):** OntoCAPE `PressureChange{OfLiquid,OfGas}` are subclasses of
  `EnthalpyChange`, while COPI's are under `MomentumTransfer`. The labels align (pressure increase
  = pressure change with positive sign), but the parent categories differ.
- **0013 (closeMatch):** OntoCAPE `Absorption ⊑ Separation`; COPI `GasAbsorption ⊑ MassTransfer`.
  Both correctly describe gas-into-liquid absorption with identical operational scope. The genus
  differs (organisational axis: separation vs mass transfer) but the extension is the same —
  closeMatch is appropriate. Verified against source: `Absorption` declared in
  `process_extensionTGL25001.owl` with parent `Separation`.
- **0014 (closeMatch):** Identical definition; OntoCAPE places it under
  `PhaseChange → PhaseChangeOfLiquids → Vaporization`. Verified against source: `Vaporization`
  declared in `process_extensionTGL25001.owl` with parent `PhaseChangeOfLiquids`.
- **0089 (closeMatch):** OntoCAPE `TemperatureChange` covers "transport heat content from one
  material to another for heating or cooling". COPI `HeatExchange` adds the two-fluid-stream
  constraint — COPI is strictly more specific.

---

## OntoCAPE source verification (2026-06-22)

IRIs verified against the actual OWL files in `~/Downloads/OntoCAPE/` (RWTH Aachen official
download). File `process_extensionTGL25001.owl` confirmed — not `TGL25000` or any other variant.

| COPI class | OntoCAPE file | Declared local name | Declared parent |
|---|---|---|---|
| COPI_0000011 | `CPS_function/process.owl` | `PressureChangeOfLiquid` | `PressureChange` |
| COPI_0000012 | `CPS_function/process.owl` | `PressureChangeOfGas` | `PressureChange` |
| COPI_0000013 | `CPS_function/process_extensionTGL25001.owl` | `Absorption` | `Separation` |
| COPI_0000014 | `CPS_function/process_extensionTGL25001.owl` | `Vaporization` | `PhaseChangeOfLiquids` |
| COPI_0000089 | `CPS_function/process.owl` | `TemperatureChange` | `EnthalpyChange` |

OntoCAPE IRI scheme: `http://www.theworldavatar.com/ontology/ontocape/` replaces the local
`file:///C:/OntoCAPE/OntoCAPE/` prefix used in the downloaded files.

---

## Literature sources added (dcterms:source)

| Operation category | Source added |
|---|---|
| MomentumTransfer (COPI_0000003) | Bird, Stewart & Lightfoot, Transport Phenomena, 2nd ed. (Wiley, 2002) — Part I |
| HeatTransfer (COPI_0000004) | Bird, Stewart & Lightfoot, Transport Phenomena, 2nd ed. (Wiley, 2002) — Part II |
| MassTransfer (COPI_0000005) | Bird, Stewart & Lightfoot, Transport Phenomena, 2nd ed. (Wiley, 2002) — Part III |
| LiquidPressureIncrease (COPI_0000011) | McCabe, Smith & Harriott, Unit Operations of Chemical Engineering, 8th ed. §3 |
| GasPressureIncrease (COPI_0000012) | McCabe, Smith & Harriott, Unit Operations of Chemical Engineering, 8th ed. §3 |
| GasAbsorption (COPI_0000013) | Perry's Chemical Engineers' Handbook, 9th ed. §14 |
| Vaporization (COPI_0000014) | McCabe, Smith & Harriott, Unit Operations of Chemical Engineering, 8th ed. §16 |
| HeatExchange (COPI_0000089) | Perry's Chemical Engineers' Handbook, 9th ed. §11 |

---

## Certification outcome (Nível 2 Incremento 1a + 1b + cross-ref closure)

| Check | Result |
|---|---|
| OWL 2 DL valid | ✓ (robot validate-profile --profile DL) |
| HermiT consistent | ✓ (exit 0) |
| Pump ⊑ MomentumTransferDevice | ✓ |
| Compressor ⊑ MomentumTransferDevice | ✓ |
| GasAbsorber ⊑ MassTransferDevice | ✓ |
| TemperatureSensor ⊑ MeasurementInstrument | ✓ |
| ShellAndTubeHeatExchanger ⊑ HeatTransferDevice (via HeatExchange ⊑ HeatTransfer) | ✓ |
| HeatExchange ⊑ HeatTransfer | ✓ |
| No unsatisfiable classes | ✓ (HermiT exit 0) |
| iof-av:naturalLanguageDefinition on all 5 leaves (no skos:definition) | ✓ |
| iof-av:firstOrderLogicDefinition (↔) on COPI_0000089 | ✓ |
| sameSubstance constituent predicate on COPI_0000089 FOL | ✓ |
| rdfs:seeAlso on all 5 leaves — IRIs verified against OntoCAPE source | ✓ |
| Zero TODO markers in copi-core.ttl (TGL cross-refs) | ✓ |
| rdfs:seeAlso well-formed (owl:AnnotationProperty, no logical consequence) | ✓ |

**PARA** — gate antes de push/merge/publish.
