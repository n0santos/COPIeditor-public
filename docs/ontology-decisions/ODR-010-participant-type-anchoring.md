# ODR-010 — Participant Type Anchoring for Step 5

**Status:** Accepted (implemented in ODR-015 Phase 1, 2026-06-15)
**Date:** 2026-05-29
**Deciders:** Nicolau Santos; Régis Romeu (input on operational vocabulary)

---

## Context

Step 5 of the COPI axiomatization method generates `hasInput` and `hasSpecifiedOutput` restrictions on equipment-specific process classes (per the template established in ODR-009 §5). The fillers of these restrictions name *participant types* — the kinds of entities that flow into or are produced by the process. The current implementation has a critical gap: participant types are referenced as IRIs in OWL restrictions but never declared as `owl:Class` and never anchored to BFO/IOF-Core, producing OOPS! pitfall P34 violations across the serialized output.

The empirical scope of the problem, established by analysis of 77 validated enrichments:

- **52 distinct participant type IRIs** are referenced across `hasInput`/`hasSpecifiedOutput` restrictions.
- **Zero** of these IRIs are declared as `owl:Class` anywhere in the COPI graph.
- The 7 "established types" listed in the current Step 5 prompt (`FluidPortion`, `GasPortion`, `LiquidPortion`, `SolidPortion`, `ElectricalPower`, `MechanicalPower`, `ThermalEnergy`, `InformationBearingArtifact`) were intended as a controlled vocabulary, but **4 of 7 were systematically ignored by the LLM** in favor of invented alternatives — empirical evidence that the vocabulary was both undeclared and miscalibrated.
- Three of the invented types are categorically incompatible with `iof-core:hasInput`/`hasSpecifiedOutput` (range `bfo:Continuant`) because they name processes (`ElectricalCurrentFlow`, `RotationalMotion`, `MechanicalMotion`) — a range violation in BFO terms (Continuant and Occurrent are disjoint).
- Five of the invented types name energy as if it were a portion of matter (`EnergyPortion`, `ThermalEnergyPortion`, `MechanicalEnergyPortion`, `ElectricalEnergyPortion`, `AlternatingCurrentPortion`) — ontologically incorrect under BFO, where energy is not a `bfo:MaterialEntity`.
- Eighteen of the invented types name signals, indications, or readings (`ElectricalSignal`, `StandardizedSignal`, `VisualIndication`, etc.) — semantically `InformationContentEntity` but never declared as such.

The pre-refactor inventory of IOF-Core 202602 (released 2026-05-28; see ODR-009 Source Definitions) established three facts that determine the shape of this ODR:

1. `iof-core:InformationContentEntity` exists as a native IOF class (`⊑ bfo:GenericallyDependentContinuant`), adapted from IAO_0000030. It is the canonical anchor for signals, readings, and information outputs without requiring IAO import.

2. `iof-core:MeasurementInformationContentEntity` exists as an equivalent class with full axiomatization (`⊑ ICE ⊓ ∃describes (Quality ∪ ProcessCharacteristic ∪ TemporalRegion ∪ ProcessProfile) ⊓ ∃isOutputOf MeasurementProcess`). It resolves the modeling of measurement outputs without requiring SOSA import. Combined with ODR-009's adoption of `iof-core:MeasurementProcess` for the measurement family, sensor outputs are correctly typed as `iof-core:MeasurementInformationContentEntity` (a generically dependent continuant) while the measurement act remains a `bfo:Process` — eliminating the continuant/occurrent straddle that earlier drafts of this work encountered when contemplating SOSA alignment.

3. IOF-Core 202602 has no canonical class for "portion of fluid" or "portion of material substance". This vocabulary is COPI's responsibility to define, with `bfo:MaterialEntity` as the upper anchor.

This ODR establishes the canonical participant type vocabulary for Step 5: which categories are admissible as `hasInput`/`hasSpecifiedOutput` fillers, the BFO/IOF anchors for each, the hierarchy of named substance and information classes that COPI introduces in `copi-base.ttl`, and the rewrite rules for the patterns that the LLM produced but that are not admissible under this policy.

## Source Definitions

**BFO 2020** (Otte, Beverley, Ruttenberg 2022):
- `bfo:BFO_0000040 MaterialEntity` — an independent continuant that has some portion of matter as proper or improper continuant part. Examples in the BFO 2020 specification include a flame, a hurricane, a puff of smoke, a sea wave — distributed and non-solid material entities lacking the internal unity required of `bfo:Object`.
- `bfo:BFO_0000030 Object` — "an independent continuant that is spatially extended, maximally self-connected and self-contained (the parts of a substance are not separated from each other by spatial gaps) and possesses an internal unity." Examples are restricted to solid portions of matter, organisms, atoms, engineered artifacts.
- BFO 2020 extensibility note: "Object, Fiat Object Part and Object Aggregate are not intended to be exhaustive of Material Entity. Users are invited to propose new subcategories of Material Entity."
- `bfo:BFO_0000019 Quality` — a specifically dependent continuant that exhibits itself completely if it inheres.
- `bfo:BFO_0000031 GenericallyDependentContinuant` — a continuant whose existence depends generically on some independent continuant bearer.

**IOF-Core 202602** (namespace `https://spec.industrialontologies.org/ontology/construct/`, prefix `iof-core:`):
- `iof-core:InformationContentEntity ⊑ bfo:GenericallyDependentContinuant` — "content or a pattern (generically dependent continuant) that is about some entity"; abbreviated ICE. Adapted from `IAO_0000030`.
- `iof-core:MeasurementInformationContentEntity` — equivalent class: `ICE ⊓ ∃hasContinuantPartAtAllTimes MeasuredValueExpression ⊓ ∃describes (Quality ∪ ProcessCharacteristic ∪ TemporalRegion ∪ ProcessProfile) ⊓ ∃isAbout (Process ∪ ProcessBoundary ∪ (IndependentContinuant \ SpatialRegion)) ⊓ ∃isOutputOf MeasurementProcess`. Definition: "informational content that is the result of measuring a set of attributes".
- `iof-core:hasInput`, `iof-core:hasSpecifiedOutput` — see ODR-009. Domain `bfo:Process` / `iof-core:PlannedProcess`; range `bfo:Continuant`.
- `iof-core:hasComponentPartAtAllTimes` — transitive object property for material parthood; the canonical relation for equipment-to-part axioms. NOT a process-participant relation.

**Foundational reference:**
- Smith, B. (2010). *On Classifying Material Entities in Basic Formal Ontology.* Interdisciplinary Ontology, Vol. 3. Argues that distributed material entities (fluids, gases, fields) are correctly classified as direct subclasses of `MaterialEntity`, not as `Object`, because they lack the internal unity (causal binding between parts) required of Object.

## Decision

### 1. Admissible participant categories

Step 5 `hasInput` and `hasSpecifiedOutput` restrictions accept fillers from exactly two categories:

| Category | Upper anchor | Used for |
|---|---|---|
| Material substance | `bfo:MaterialEntity` (via `copi:PortionOfFluid` hierarchy, §2) | Inputs and outputs of all non-measurement equipment-realizing processes; inputs of measurement processes (the entity whose property is being measured). |
| Information content entity | `iof-core:InformationContentEntity` (via §3 hierarchy, with `iof-core:MeasurementInformationContentEntity` for measurement outputs) | Outputs of measurement processes; inputs and outputs of equipment that processes signals or information. |

Qualities (`bfo:Quality` subclasses such as `copi:Temperature`, `copi:Pressure`) are **vocabulary required by `copi-base.ttl`** but are **not direct participants**. They are referenced indirectly via `iof-core:describes` from `MeasurementInformationContentEntity` subclasses, following the IOF axiomatization of `MeasurementInformationContentEntity` (§4 below).

Other categories — Process, MaterialArtifact (equipment parts), energy as portion of matter — are explicitly inadmissible as `hasInput`/`hasSpecifiedOutput` fillers (§5).

### 2. PortionOfFluid hierarchy

The canonical material substance vocabulary, declared in `copi-base.ttl`:

```turtle
copi:PortionOfFluid
    rdf:type owl:Class ;
    rdfs:subClassOf bfo:BFO_0000040 ;     # bfo:MaterialEntity (direct)
    rdfs:label "Portion of Fluid"@en ;
    iof-av:naturalLanguageDefinition "A bounded portion of matter in a fluid state (gaseous, liquid, or supercritical) that participates in an equipment-realizing process as input, output, or transformed substance. Spatial delimitation is given by equipment geometry and connection topology, not by internal causal unity."@en .

copi:PortionOfLiquid
    rdfs:subClassOf copi:PortionOfFluid ;
    rdfs:label "Portion of Liquid"@en ;
    iof-av:naturalLanguageDefinition "A portion of fluid in liquid phase."@en .

copi:PortionOfGas
    rdfs:subClassOf copi:PortionOfFluid ;
    rdfs:label "Portion of Gas"@en ;
    iof-av:naturalLanguageDefinition "A portion of fluid in gaseous phase."@en .

copi:PortionOfSolid
    rdfs:subClassOf bfo:BFO_0000040 ;
    rdfs:label "Portion of Solid"@en ;
    iof-av:naturalLanguageDefinition "A bounded portion of matter in a solid state that participates in an equipment-realizing process (filtered contaminants, particulate input, solid product)."@en .

copi:PortionOfLiquid owl:disjointWith copi:PortionOfGas .
```

Domain-specific subclasses required by the petroleum scope (also in `copi-base.ttl`):

```turtle
copi:AbsorbentPhase rdfs:subClassOf copi:PortionOfLiquid .   # e.g., lean TEG in P-74
copi:RichAbsorbent  rdfs:subClassOf copi:AbsorbentPhase .    # post-absorption state
copi:DepletedFluid  rdfs:subClassOf copi:PortionOfFluid .    # post-treatment outflow
copi:FluidMixture   rdfs:subClassOf copi:PortionOfFluid .
```

States that the LLM has reified as separate types — `PressurizedFluidPortion`, `FilteredFluidPortion`, `LiquidMixturePortion` — are **not** introduced as classes. The state (pressurized, filtered, mixed) is captured by qualities of the portion or by the post-process subsumption (`PressureIncrease` ProcessKind specifies that the output `PortionOfFluid` is at elevated pressure relative to input), not by new substance classes.

### 3. InformationContentEntity hierarchy and measurement outputs

Signal/indication/reading types collapse to `iof-core:InformationContentEntity` directly when used outside measurement context. For measurement outputs, the canonical anchor is `iof-core:MeasurementInformationContentEntity`, with COPI introducing specific subclasses per measured quantity:

```turtle
copi:TemperatureMeasurementResult
    rdfs:subClassOf iof-core:MeasurementInformationContentEntity ;
    rdfs:subClassOf [ owl:onProperty iof-core:describes ;
                      owl:someValuesFrom copi:Temperature ] ;
    rdfs:label "Temperature Measurement Result"@en ;
    iof-av:naturalLanguageDefinition "Measurement information content entity describing a temperature quality of some material entity."@en .

copi:PressureMeasurementResult
    rdfs:subClassOf iof-core:MeasurementInformationContentEntity ;
    rdfs:subClassOf [ owl:onProperty iof-core:describes ;
                      owl:someValuesFrom copi:Pressure ] ;
    rdfs:label "Pressure Measurement Result"@en .

copi:FlowMeasurementResult
    rdfs:subClassOf iof-core:MeasurementInformationContentEntity ;
    rdfs:subClassOf [ owl:onProperty iof-core:describes ;
                      owl:someValuesFrom copi:FlowRate ] .

copi:LevelMeasurementResult
    rdfs:subClassOf iof-core:MeasurementInformationContentEntity ;
    rdfs:subClassOf [ owl:onProperty iof-core:describes ;
                      owl:someValuesFrom copi:Level ] .

copi:CompositionMeasurementResult
    rdfs:subClassOf iof-core:MeasurementInformationContentEntity ;
    rdfs:subClassOf [ owl:onProperty iof-core:describes ;
                      owl:someValuesFrom copi:Composition ] .
```

Non-measurement signals (control signals, communication signals, visual indications used outside measurement) attach directly to `iof-core:InformationContentEntity`:

```turtle
copi:ControlSignal
    rdfs:subClassOf iof-core:InformationContentEntity ;
    iof-av:naturalLanguageDefinition "Information content entity that conveys an instruction or set-point to a control device."@en .

copi:VisualIndication
    rdfs:subClassOf iof-core:InformationContentEntity ;
    iof-av:naturalLanguageDefinition "Information content entity perceptible through visual representation."@en .
```

Additional ICE subclasses are added to `copi-base.ttl` as the vocabulary grows; no intermediate Signal/Indication/Reading taxonomy is introduced unless an axiomatization requires distinguishing them.

### 4. Quality vocabulary

Quality classes referenced by `MeasurementInformationContentEntity` subclasses (§3) and by equipment qualities (e.g., pump power rating) are declared in `copi-base.ttl`:

```turtle
copi:Temperature   rdfs:subClassOf bfo:BFO_0000019 .   # bfo:Quality
copi:Pressure      rdfs:subClassOf bfo:BFO_0000019 .
copi:FlowRate      rdfs:subClassOf bfo:BFO_0000019 .
copi:Level         rdfs:subClassOf bfo:BFO_0000019 .
copi:Composition   rdfs:subClassOf bfo:BFO_0000019 .
copi:Vibration     rdfs:subClassOf bfo:BFO_0000019 .

copi:ElectricalPower  rdfs:subClassOf bfo:BFO_0000019 .
copi:MechanicalPower  rdfs:subClassOf bfo:BFO_0000019 .
copi:RotationalSpeed  rdfs:subClassOf bfo:BFO_0000019 .
```

These are **not** Step 5 participants. They are vocabulary needed by `copi-base.ttl` for the `describes` axioms in §3 and for axiomatizing equipment qualities outside Step 5 (e.g., a pump's rated power as `bearer_of some ElectricalPower`). No alignment with QUDT is performed in this ODR; QUDT integration is deferred.

### 5. Inadmissible patterns and rewrite rules

Three classes of LLM-produced participant types are inadmissible. The serializer's structural validator (gate D, see ODR-009 Consequences) MUST flag them; the post-processing module (gate C) applies the canonical rewrite where deterministic, and flags `REVIEW_REQUIRED` otherwise.

**5.1 Energy as portion of matter.** Patterns `XEnergyPortion` and `XCurrentPortion` (`EnergyPortion`, `ThermalEnergyPortion`, `MechanicalEnergyPortion`, `ElectricalEnergyPortion`, `AlternatingCurrentPortion`) are ontologically incorrect: energy is not `bfo:MaterialEntity`. Rewrite rules:

| Inadmissible pattern | Canonical rewrite |
|---|---|
| `ElectricalEnergyPortion` as hasInput | Remove from participants; the equipment's electrical demand is `bearer_of some copi:ElectricalPower` (Quality, axiomatized on the Equipment class, not on the Process). |
| `ThermalEnergyPortion` as hasInput/hasOutput | Remove from participants; heat transfer is captured by `process_kind ⊑ copi:HeatTransferProcess` (ODR-009), with `copi:Temperature` of the heated portion as the measurable outcome. |
| `MechanicalEnergyPortion` | Remove from participants; `process_kind ⊑ copi:MechanicalPowerTransmissionProcess` plus the equipment's `bearer_of some copi:MechanicalPower`. |
| `AlternatingCurrentPortion` | Remove from participants; `process_kind ⊑ copi:ElectricalConversionProcess` with AC pattern modeled as Quality of the carrier system. |

Discriminative power in these cases is carried by the ProcessKind (ODR-009 §3), not by an energy-as-portion participant. The rewrite removes the participant entirely; it is not "anchored" to MaterialEntity.

**5.2 Process-typed participants.** Patterns naming processes (`ElectricalCurrentFlow`, `RotationalMotion`, `MechanicalMotion`) violate the range of `iof-core:hasInput` (`bfo:Continuant`) under BFO 2020, where Continuant and Occurrent are disjoint. Rewrite rules:

| Inadmissible pattern | Canonical rewrite |
|---|---|
| `ElectricalCurrentFlow` | The flow is captured by `process_kind ⊑ copi:ElectricalConversionProcess`; if a quality is needed, use `copi:ElectricalCurrent` (Quality of the carrier). |
| `RotationalMotion` | The motion is the host process itself; if a quality is needed, use `copi:RotationalSpeed` (Quality of the rotating part). |
| `MechanicalMotion` | Redundant with `RotationalMotion` or `process_kind`; drop. |

**5.3 Equipment parts as process participants.** Patterns naming equipment components (`TemperatureSensingElement`, `ProtectedTemperatureSensingElement`, `LocalTemperatureDisplay`) misclassify mereological parts as process inputs. The canonical relation for parts is `iof-core:hasComponentPartAtAllTimes`, axiomatized on the Equipment class — not on the Process class. The current serializer already declares parts as `owl:Class` with proper BFO anchoring (verified in the pre-refactor inventory). Rewrite rule: remove from `hasInput`/`hasSpecifiedOutput` restrictions; axiomatize as parts on the Equipment class.

### 6. Naming clash resolutions

Four patterns require explicit normalization:

**`InformationBearingArtifact`** (in the current Step 5 prompt) is not a class in IOF-Core 202602. The name is ambiguous between IAO's `InformationBearingEntity` (the material bearer — a hard drive, a paper) and `InformationContentEntity` (the content itself). The 77 enrichments never used this name; the LLM consistently generated `ElectricalSignal`, `ControlSignal`, `VisualSignal`, etc. — all of which align semantically with content, not carrier. Decision: remove `InformationBearingArtifact` from the prompt's established types and replace with `iof-core:InformationContentEntity` (plus the §3 hierarchy for specific cases).

**`*Portion` suffix.** The suffix implies bounded matter and is admissible only for material substances (§2). The LLM has applied it to ICE (`ElectricalSignalPortion`) and to energy (`*EnergyPortion`); both are inadmissible. The post-processing module normalizes `XSignalPortion` to `XSignal` (drop the suffix; there is no "portion of a signal") and flags `XEnergyPortion` per §5.1.

**`XSignal` vs `XInformation` vs `XIndication` vs `XReading`.** The LLM has produced semantically-equivalent variants (`TemperatureSignal`, `TemperatureReading`, `LevelInformation`, `LevelSignal`). Within COPI, all measurement outputs canonicalize to the `*MeasurementResult` form (`copi:TemperatureMeasurementResult`, `copi:LevelMeasurementResult`) under `iof-core:MeasurementInformationContentEntity`. Non-measurement signals retain the `Signal` suffix under `iof-core:InformationContentEntity`. The post-processing module maps the variants accordingly.

**`ProcessVariable`** (ISA 5.1 term). The intended sense in COPI is the physical quality being measured/controlled (temperature, pressure), which is `bfo:Quality`. It is not a participant type. The post-processing module maps `ProcessVariable` as input/output to either (a) the specific quality (`copi:Temperature`, `copi:Pressure`) if context disambiguates, or (b) `REVIEW_REQUIRED`.

### 7. Mapping of legacy participant types

The 52 distinct types observed across 77 enrichments are mapped per the table below. Categories: **M** = material substance (anchor `bfo:MaterialEntity` via `copi:PortionOfFluid`); **I** = information content entity (anchor `iof-core:InformationContentEntity` or subclass); **R** = rejected, with rewrite per §5; **P** = part, rewrite per §5.3; **Q** = quality (not a participant, see §4); **V** = naming variant, normalize per §6.

| Legacy type | Cat | Canonical mapping |
|---|---|---|
| FluidPortion | M | copi:PortionOfFluid |
| GasPortion | M | copi:PortionOfGas |
| LiquidPortion | M | copi:PortionOfLiquid |
| SolidPortion | M | copi:PortionOfSolid |
| PressurizedFluidPortion | M | copi:PortionOfFluid (pressure is Quality, captured by ProcessKind) |
| FilteredFluidPortion | M | copi:PortionOfFluid |
| FilteredContaminants | M | copi:PortionOfSolid |
| LiquidMixturePortion | M | copi:PortionOfLiquid |
| FluidMixture | M | copi:FluidMixture |
| AbsorbentPhase | M | copi:AbsorbentPhase |
| RichAbsorbent | M | copi:RichAbsorbent |
| DepletedFluid | M | copi:DepletedFluid |
| ElectricalPower | Q | copi:ElectricalPower (Quality of equipment, NOT participant) |
| Temperature | Q | copi:Temperature (described by MeasurementICE, NOT participant) |
| ProcessVariable | Q | normalize per §6 to specific Quality or REVIEW_REQUIRED |
| PressureField | Q | copi:Pressure |
| ElectricalSignal | I | iof-core:InformationContentEntity |
| StandardizedSignal | I | iof-core:InformationContentEntity |
| ControlSignal | I | copi:ControlSignal ⊑ iof-core:InformationContentEntity |
| StandardizedElectricalSignal | I | iof-core:InformationContentEntity |
| VisualSignal | I | iof-core:InformationContentEntity |
| VisualInformation | I | iof-core:InformationContentEntity |
| VisualIndication | I | copi:VisualIndication ⊑ iof-core:InformationContentEntity |
| TemperatureSignal | I | copi:TemperatureMeasurementResult |
| FlowMeasurement | I | copi:FlowMeasurementResult |
| PressureSignal | I | copi:PressureMeasurementResult |
| PolyphaseElectricalSignal | I | iof-core:InformationContentEntity |
| LevelInformation | I | copi:LevelMeasurementResult |
| HighPressureSignal | I | copi:PressureMeasurementResult |
| LowPressureSignal | I | copi:PressureMeasurementResult |
| VibrationSignal | I | iof-core:MeasurementInformationContentEntity (copi:VibrationMeasurementResult to be added) |
| InformationBearingEntity | V | iof-core:InformationContentEntity (rename for clarity) |
| PressureSignalPair | I | iof-core:MeasurementInformationContentEntity (aggregate; refine if needed) |
| MeasurementSignal | I | iof-core:MeasurementInformationContentEntity |
| ElectricalSignalPortion | V | iof-core:InformationContentEntity (drop Portion suffix per §6) |
| DetectionSignal | I | iof-core:InformationContentEntity |
| InformationSignal | I | iof-core:InformationContentEntity |
| LevelSignal | I | copi:LevelMeasurementResult |
| DifferentialPressureIndication | I | copi:PressureMeasurementResult |
| PhaseSequenceIndication | I | iof-core:InformationContentEntity |
| PressureReading | I | copi:PressureMeasurementResult |
| ElectricalCurrentFlow | R | rewrite per §5.2 |
| RotationalMotion | R | rewrite per §5.2 |
| MechanicalMotion | R | rewrite per §5.2 (drop; redundant) |
| TemperatureSensingElement | P | rewrite per §5.3 (part, not participant) |
| ProtectedTemperatureSensingElement | P | rewrite per §5.3 |
| LocalTemperatureDisplay | P | rewrite per §5.3 |
| EnergyPortion | R | rewrite per §5.1 |
| ThermalEnergyPortion | R | rewrite per §5.1 |
| MechanicalEnergyPortion | R | rewrite per §5.1 |
| ElectricalEnergyPortion | R | rewrite per §5.1 |
| AlternatingCurrentPortion | R | rewrite per §5.1 |

### 8. Pipeline integration

**Gate A (schema-driven, prompt).** The Step 5 prompt is updated to replace the current 7 "established types" list with the canonical vocabulary of §2 and §3 plus an enum for `type_bfo_parent` in `new_participant_type_definitions` restricted to: `bfo:MaterialEntity`, `iof-core:InformationContentEntity`, `iof-core:MeasurementInformationContentEntity`. The prompt includes §5 as guidance for rejected patterns.

**Gate C (post-processing).** A deterministic lookup module maps every participant type referenced in the LLM output to its canonical form per §7. Three behaviors:

1. **Direct anchor** (categories M, I in §7): emit the canonical class IRI (in `copi-base.ttl`) in the restriction; the class is already declared in copi-base, so no new declaration is needed.
2. **Normalize** (categories V): apply the renaming, then anchor as I.
3. **Reject/Rewrite** (categories R, P, Q): replace the inadmissible participant. For deterministic cases (e.g., `ThermalEnergyPortion` → drop, rely on ProcessKind subsumption), apply automatically. For ambiguous cases, emit `REVIEW_REQUIRED` and fail the export gate.

**Gate D (structural validator).** `verify_service.py:check_undeclared_classes` (already implemented per the pre-refactor inventory) is extended to assert template conformance: every `hasInput`/`hasSpecifiedOutput` filler must be either (a) `copi:PortionOfFluid` or a subclass declared in `copi-base.ttl`, or (b) `iof-core:InformationContentEntity` / `iof-core:MeasurementInformationContentEntity` or a subclass declared in `copi-base.ttl`, or (c) `bfo:MaterialEntity` (admissible generic fallback for cases where the substance type is genuinely underspecified, as in the generic input of a measurement process). Any other filler fails the gate.

### 9. Treatment of legacy enrichments

The 77 enrichments validated prior to this ODR contain participant references per the legacy (mostly invented) vocabulary. They are retained as the empirical baseline for the divergence analysis in the thesis and the FOIS paper, marked as schema version `v0.x` (per ODR-009 §6). Canonical COPI is constituted by enrichments produced after ODR-009 + ODR-010 are implemented.

The §7 mapping is normative for retroactive migration: legacy participant references translate deterministically to canonical forms where category is M, I, V, or P; categories R and Q require human review (energy patterns and Quality-as-participant cases are not auto-rewritten). A future migration script may apply the M/I/V/P portion of §7 without re-running LLM enrichment; the R/Q portion is left for manual review or for re-enrichment under the updated Step 5 prompt.

## Rationale

**Why two participant categories, not five.** Earlier drafts of this work proposed five categories (Material, Quality, Process, MaterialArtifact, ICE) under the assumption that each could appear as `hasInput`/`hasSpecifiedOutput`. Empirical analysis of the 77 enrichments and the BFO range constraints together rule out three of these:

- Process violates the range of `hasInput`/`hasSpecifiedOutput` (`bfo:Continuant`); rewriting as ProcessKind subsumption (per ODR-009) is the correct treatment, with the host process *being* the process formerly proposed as participant.
- MaterialArtifact (equipment parts) misuses the participation relation; parts attach via `hasComponentPartAtAllTimes` to the equipment, not via `hasInput` to the process. The current serializer already implements this correctly.
- Quality, while a legitimate vocabulary requirement, is referenced indirectly via `iof-core:describes` from `MeasurementInformationContentEntity` (per the IOF axiomatization), not directly as a participant. Treating Quality as a direct participant either conflates "what is measured" with "what is consumed" (semantic confusion) or stretches `hasInput` semantics beyond IOF's intent.

The two surviving categories — MaterialEntity (substance that flows) and InformationContentEntity (information produced/consumed) — capture all defensible participant patterns in the 77 enrichments without ontological overreach.

**Why `iof-core:InformationContentEntity` and not IAO.** IOF-Core 202602 adapts ICE from `IAO_0000030` and provides the native `iof-core:InformationContentEntity` class under its own namespace. Importing IAO separately would add an external dependency for content that IOF already exposes, and would re-introduce the `obo:IAO_0000115` annotation property problem (currently undeclared in the COPI graph because IAO is not imported; see ODR-009 Consequences for the migration to `iof-av:naturalLanguageDefinition`). Using `iof-core:InformationContentEntity` keeps the import surface minimal and consistent.

**Why `iof-core:MeasurementInformationContentEntity` and not SOSA.** SOSA's `Observation` is semantically act-like (per the SOSA specification: "act of carrying out a procedure"), which under BFO alignment would classify it as `bfo:Process` (Occurrent). Earlier drafts of this work attempted to use `sosa:Observation` as the output of a measurement process, producing a continuant/occurrent straddle (the output would be both an ICE — GenericallyDependentContinuant — and an Observation — Occurrent — which BFO declares disjoint). `iof-core:MeasurementInformationContentEntity` is purely continuant (`⊑ ICE ⊑ bfo:GenericallyDependentContinuant`) and exists specifically to model the output of `iof-core:MeasurementProcess`. Using the IOF pair eliminates the straddle and keeps COPI aligned to the IOF ecosystem without adding SOSA as an import.

**Why `PortionOfFluid` as direct subclass of `bfo:MaterialEntity`, not `bfo:Object`.** BFO 2020's definition of `Object` requires "internal unity" — causal binding between parts — which fluids do not satisfy: a portion of liquid in equipment has parts that are not causally bound to one another in the way that an atom, a cell, or a rigid artifact's parts are. The BFO 2020 specification's own examples of Object are restricted to solid portions of matter. The same specification explicitly authorizes new subcategories of `MaterialEntity` ("Object, Fiat Object Part and Object Aggregate are not intended to be exhaustive of Material Entity. Users are invited to propose new subcategories of Material Entity"). Smith (2010) discusses this case directly. `FiatObjectPart` is also rejected because a portion of fluid in equipment is not a *part* of another previously-identified material entity — it is a material entity in its own right, delimited by equipment geometry.

**Why energy is not a process participant.** The discriminative purpose served by `EnergyPortion`-style names is satisfied by ProcessKind subsumption (per ODR-009): a pump is `process_kind ⊑ copi:PressureIncrease`, distinct from a heat exchanger (`process_kind ⊑ copi:HeatTransferProcess`), distinct from a sensor (`process_kind ⊑ iof-core:MeasurementProcess`). The LLM does not need an energy participant to differentiate equipment classes once the ProcessKind taxonomy is anchored. The equipment's energy consumption or dissipation is captured separately as a Quality (`bearer_of some copi:ElectricalPower`) on the Equipment class, outside Step 5's participant signature. This split is methodologically meaningful: Step 5 axiomatizes process semantics, not utility flows.

**Why the prompt's seven established types are abandoned.** Empirical evidence: four of the seven (`MechanicalPower`, `ThermalEnergy`, `InformationBearingArtifact`, and effectively `SolidPortion` which appeared in only 2 enrichments) were systematically ignored by the LLM in favor of invented alternatives over 77 attempts. The vocabulary did not match how the model conceptualized participant types. The replacement vocabulary in §2–§4 is grounded in BFO 2020 and IOF-Core 202602, and (in §7) is empirically calibrated against what the LLM actually produced — the 52 invented types fold into a substantially smaller canonical vocabulary without semantic loss.

## Consequences

**Required content additions to `copi-base.ttl`** (created per ODR-009 Consequences):
- The PortionOfFluid hierarchy of §2 plus domain-specific subclasses (AbsorbentPhase, RichAbsorbent, DepletedFluid, FluidMixture, PortionOfSolid).
- The MeasurementResult subclasses of §3 (TemperatureMeasurementResult, PressureMeasurementResult, FlowMeasurementResult, LevelMeasurementResult, CompositionMeasurementResult, plus VibrationMeasurementResult when added) with `describes` axioms.
- The Quality vocabulary of §4 (Temperature, Pressure, FlowRate, Level, Composition, Vibration, ElectricalPower, MechanicalPower, RotationalSpeed).
- The non-measurement ICE subclasses of §3 (ControlSignal, VisualIndication).

**Required code changes in COPIeditor** (extending those listed in ODR-009 Consequences):
- `enrichment/prompts.py`: replace the seven "established types" list with the canonical §2/§3 vocabulary and the §5 rejection rules. Add the §1 categorization as guidance for `new_participant_type_definitions` with the restricted `type_bfo_parent` enum.
- `enrichment/enrichment_service.py`: implement gate C as a deterministic lookup module (`participant_anchoring.py`) consuming §7. Apply normalization (V), direct mapping (M, I), and rewrite (R, P, Q) per the table.
- `enrichment/verify_service.py`: extend `check_undeclared_classes` per gate D in §8.

**Constraints introduced.**
- Future Step 5 enrichments MUST resolve every `hasInput`/`hasSpecifiedOutput` filler to a class in `copi-base.ttl` or to one of the IOF-Core anchors enumerated in §1. Novel participant types require `process_kind_status` and a follow-up amendment to this ODR or `copi-base.ttl`.
- Energy demand, current flow, and motion are NEVER `hasInput`/`hasSpecifiedOutput` fillers in canonical COPI. Equipment energy/power characterization uses Quality axioms (`bearer_of`) on the Equipment class.

**Backward compatibility.** The 77 legacy enrichments retain the v0.x baseline status per ODR-009 §6. The §7 mapping enables retroactive migration of categories M, I, V, P. Categories R and Q in legacy enrichments require manual review or re-enrichment for canonical-COPI promotion.

**Dependencies on other work.**
- IOF-Core import version pinned to 202602 (per ODR-009 Consequences).
- `iof-av:naturalLanguageDefinition` adopted as annotation property (per ODR-009 Consequences); applies to all classes introduced by this ODR.
- `MaterialComponent` superclass confirmation (left pending in the pre-refactor inventory) does not block this ODR because MaterialComponent is not used as a Step 5 participant in COPI.

---

## Amendment (2026-10-10) — output restrictions use `hasOutput`

References above to `hasInput` / `hasSpecifiedOutput` restrictions on Step 5 process classes
now read `hasInput` / **`hasOutput`**. The participant categories, the range (`bfo:Continuant`)
and the admissibility rules in this ODR are unchanged. See the amendment to ODR-011 for the
reasoning (`hasSpecifiedOutput` requires `iof:PlannedProcess` and an objective specification
that Step 5 does not provide) and issue #50.
