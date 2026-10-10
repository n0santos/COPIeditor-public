# ODR-018 — Nível 2 Incremento 2a: Structural Genera

**Status:** Accepted  
**Date:** 2026-06-22  
**Scope:** `copi-core` — three new primitive structural genus classes; `copi-enriched-nivel1` — re-genusing of three equipment classes; `enrichment_service.py` — serializer genus resolution

---

## Context

Nível 1 of COPI defines five equipment classes (Pump, Compressor, ShellAndTubeHeatExchanger,
GasAbsorber, TemperatureSensor) purely via the functional axis: each is an intersection of a genus
from IOF-Core and a `hasFunction someValuesFrom` restriction. The functional genus used for all five
was either `iof-constr:Assembly` or `iof-constr:MaterialArtifact` — the coarsest possible structural
anchor available in IOF-Core.

Nível 2 Incremento 2a introduces a **structural axis** that is orthogonal to the existing functional
axis. Three structural genera are declared; each captures the physical form of an artifact class
independently of what function it is designed to perform.

---

## Decision A — Dual taxonomy: structural and functional axes are orthogonal

**Decision:** COPI maintains two independent classification axes:

1. **Functional axis** — device categories defined by `hasFunction` restrictions (ODR-012).
2. **Structural axis** — structural genera capturing physical form, declared as primitive classes.

An artifact may simultaneously be classified on both axes. For example, a shell-and-tube heat
exchanger is both a `PressureVessel` (structural: closed shell rated for differential pressure) and
a `HeatTransferDevice` (functional: designed to perform heat transfer). This is intended and not a
modelling defect — it reflects the genuine multi-classification of engineering artifacts in petroleum
installations.

**Rationale:**  
OWL open-world semantics support multiple classification. The IOF-Core `hasFunction` chain works
regardless of which structural genus is used, provided the structural genus is a subclass of
`iof-constr:MaterialArtifact` (which all three structural genera are, directly or transitively via
`iof-constr:Assembly ⊑ iof-constr:MaterialArtifact`). All five device category `equivalentClass`
axioms use `iof-constr:MaterialArtifact` as structural genus; any subclass satisfies those axioms
by entailment. The functional classification chain is therefore preserved (certified by HermiT —
see certification table below).

---

## Decision B — Three structural genera declared (Machine not declared)

**Decision:** Three primitive classes are introduced in `copi-core`:

| IRI | Label | Genus | Rationale |
|---|---|---|---|
| `COPI_0000090` | pressure vessel | `iof-constr:Assembly` | Closed shell + mechanical stress specification |
| `COPI_0000091` | instrument | `iof-constr:MaterialArtifact` | Sensing/measuring material artifact |
| `COPI_0000092` | heat exchanger | `copi:COPI_0000090` (PressureVessel) | Pressure vessel with solid heat-transfer surface |

A `Machine` class is **not** declared. Pump (COPI_0000072) and Compressor (COPI_0000073) retain
`iof-constr:Assembly` as their structural genus in the enriched layer.

**Rationale for no Machine:**  
`Machine` would serve only Pump and Compressor; both are already correctly classified as
`MomentumTransferDevice` (certified). Introducing `Machine` at this stage would require deciding
its genus (IOF-Core has no `Machine`; BFO has none either), its differentia (rotating mechanism?
energy conversion?), and its relationship to PressureVessel (compressors have pressure housings).
These questions are deferred to a dedicated ODR. The structural differentia for Pump and Compressor
is not needed to satisfy any current classification requirement.

---

## Decision C — HeatExchanger ⊑ PressureVessel (Opção B chosen)

**Decision:** `HeatExchanger (COPI_0000092)` is declared as a subclass of
`PressureVessel (COPI_0000090)`, not of `iof-constr:Assembly` or `iof-constr:MaterialArtifact`
directly.

**Alternatives considered:**

| Option | Genus | Verdict |
|---|---|---|
| A | `iof-constr:Assembly` | Too broad; loses the pressure-vessel structural constraint |
| **B** | `copi:COPI_0000090` (PressureVessel) | **Chosen** |
| C | `iof-constr:MaterialArtifact` | Too broad; loses even the assembly nature |

**Rationale for B:**  
A shell-and-tube heat exchanger is always housed in a pressure vessel (shell-side rated for
differential pressure). Encoding this as `HeatExchanger ⊑ PressureVessel` entails the transitive
chain `STHE ⊑ HeatExchanger ⊑ PressureVessel ⊑ Assembly ⊑ MaterialArtifact`, which satisfies
all device category axioms. The `enrichment.db` already proposed `"heat exchanger"` as the genus
label for STHE, confirming domain-model intent. The structural differentia (solid heat-transfer
surface separating two fluid circuits) is expressed in the NLD; the genus-only OWL encoding defers
full FOL axiomatisation to Incremento 2b.

---

## Decision D — All structural genera are primitive (genus-only OWL, NLD differentia)

**Decision:** All three structural genera use `iof-av:isPrimitive true`. OWL carries only the
`rdfs:subClassOf` genus axiom. Structural differentiæ are expressed in
`iof-av:naturalLanguageDefinition` (bilingual EN/PT-BR) and `iof-av:primitiveRationale`.
Full FOL `equivalentClass` axioms are deferred to Incremento 2b.

**Rationale:**  
Structural differentiæ for PressureVessel (shell rating, mechanical stress spec), Instrument
(sensing vs measuring distinction), and HeatExchanger (surface-separated circuits) involve
quantification over parts and material properties that exceed OWL 2 DL expressivity in their
general form. Declaring them primitive now, with a clear NLD, satisfies the Nível 2a goal of
anchoring structural form without introducing undecidable axioms.

---

## Decision E — Serializer updated to use `genus` field before `genus_bfo_root`

**Decision:** `enrichment_service.py → generate_nivel1_enriched()` now selects the `genus` field
from `enrichment.db` and uses it as the primary lookup into `_GENUS_TTL`, falling back to
`genus_bfo_root` only when no specific genus is found or when the genus value is not in `_GENUS_TTL`.

**Bug fixed:** The SELECT query previously omitted the `genus` column, causing `row.get("genus")`
to return `None` and silently using `genus_bfo_root` for all classes. This meant newly registered
specific genera (pressure vessel, Instrument, heat exchanger) were never applied.

**`_GENUS_TTL` additions:**
```python
"pressure vessel":  "copi:COPI_0000090",
"Instrument":       "copi:COPI_0000091",
"heat exchanger":   "copi:COPI_0000092",
```
Note: `"Instrument"` uses a capital I to match the exact value stored in the DB `genus` field for
the temperature sensor cluster.

---

## IRIs allocated

| IRI | Label (EN) | Label (PT-BR) | Genus |
|---|---|---|---|
| `COPI_0000090` | pressure vessel | vaso de pressão | `iof-constr:Assembly` |
| `COPI_0000091` | instrument | instrumento | `iof-constr:MaterialArtifact` |
| `COPI_0000092` | heat exchanger | trocador de calor | `copi:COPI_0000090` |

Next free IRI: `COPI_0000093`.

---

## Re-genusing in copi-enriched-nivel1.ttl

| Equipment | Old genus | New genus | Axiom mode |
|---|---|---|---|
| GasAbsorber (COPI_0000075) | `iof-constr:Assembly` | `copi:COPI_0000090` (PressureVessel) | `equivalentClass` (intersection) |
| TemperatureSensor (COPI_0000076) | `iof-constr:MaterialArtifact` | `copi:COPI_0000091` (Instrument) | `equivalentClass` (intersection) |
| ShellAndTubeHeatExchanger (COPI_0000074) | `iof-constr:Assembly` | `copi:COPI_0000092` (HeatExchanger) | `rdfs:subClassOf` (primitive) |
| Pump (COPI_0000072) | `iof-constr:Assembly` | — (unchanged) | `equivalentClass` |
| Compressor (COPI_0000073) | `iof-constr:Assembly` | — (unchanged) | `equivalentClass` |

---

## Certification outcome (Nível 2 Incremento 2a)

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
| STHE ⊑ HeatExchanger (new structural) | ✓ |
| GasAbsorber ⊑ PressureVessel (new structural) | ✓ |
| TemperatureSensor ⊑ Instrument (new structural) | ✓ |
| STHE ⊑ PressureVessel (transitive chain via HeatExchanger) | ✓ |
| No device category unsatisfiable | ✓ (no equivalentClass owl:Nothing in reasoned output) |

**PARA** — gate antes de push/merge/publish.

---

## Open items (deferred)

- **Incremento 2b** — Full `equivalentClass` + FOL differentia for PressureVessel, HeatExchanger, Instrument.
- **Machine class** — Dedicated ODR when Pump/Compressor structural differentia is needed.
- **copi-enriched.owl sync** — `components/copi-enriched.owl` (OWL/XML format) is outdated and does not reflect Nível 2 changes. Must be regenerated from `copi-enriched-nivel1.ttl` before publishing.
