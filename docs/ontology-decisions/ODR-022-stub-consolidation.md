# ODR-022 — Readable-Name Stub Consolidation

**Status:** **Executed 2026-08-07** (see §11). Ratchet open on 15 pipeline-bound components.
**Date:** 2026-08-06
**Depends on:** ODR-010 (participant type anchoring), ODR-020 (legacy filler migration)
**Blocks / blocked by:** ODR-021 (`InformationBearingArtifact` re-typing) — see §4.3

---

## Context

`copi-enriched.owl` (2026-07-23) declares **764 classes in the `copi:` namespace: 372 numeric
`COPI_*` IRIs and 442 readable-name stubs** that `copi-iri-map.tsv` never mapped. All 442 are
live at `https://www.inf.ufrgs.br/ontologies/copi/copi.ttl` (published 2026-07-17); the local
and published stub sets are identical.

The stubs are not uniformly a problem. **253 of them** (151 processes + 102 functions) are
mechanically generated 1:1 from each enrichment entry's `process_name` / `function_name`; they are
inconsistent rather than wrong, and §6 deals with them. The remaining ~190 are participant fillers
and component parts, and this is where the defects are.

**The core finding:** `copi-vocab` already declares the canonical ODR-010 participant vocabulary
as `COPI_0000037–0000060` (portion of fluid/liquid/gas/solid, fluid mixture, control signal,
visual indication, the five measurement-result classes, the quality vocabulary). The enriched
module ships a **complete parallel vocabulary that duplicates it** — 64 `BFO_0000024`-anchored
portion stubs and 37 ICE stubs, carrying 432 restriction references between them. ODR-020's
migration made every filler *category-admissible* (Material or ICE) but did not map any of them
onto the canonical classes. Three ODR-010 prohibitions are violated in the shipped artifact.

---

## 1. Defects, in severity order

### 1.1 Energy typed as matter — ODR-010 §5.1 explicitly inadmissible

Five stubs are declared `⊑ bfo:BFO_0000024` (fiat object part, hence `MaterialEntity`), asserting
that energy is a portion of matter:

| Stub | Restriction uses |
|---|---|
| `EnergyPortion` | 6 |
| `MechanicalEnergyPortion` | 6 |
| `ThermalEnergyPortion` | 3 |
| `ThermalEnergy` | 3 |
| `ElectricalEnergyPortion` | 2 |

ODR-010 §5.1 names four of these five verbatim as inadmissible. They survived ODR-020 precisely
*because* the migration checked category admissibility — and a fiat object part **is** formally a
material entity, so the check passed while the ontological error remained.

### 1.2 Wrong BFO anchor for the whole portion hierarchy

Every portion stub is `⊑ bfo:BFO_0000024` (fiat object part). ODR-010 §2, citing Smith (2010),
anchors `copi:PortionOfFluid` at `bfo:BFO_0000040` (material entity) *directly*, on the grounds
that fluids lack the internal unity BFO requires of `Object` and its fiat parts. `COPI_0000037`
in `copi-vocab` is anchored correctly; the 64 stubs are not.

### 1.3 State reifications — ODR-010 §2 explicitly inadmissible

ODR-010 §2 states that `PressurizedFluidPortion`, `FilteredFluidPortion` and
`LiquidMixturePortion` are "**not** introduced as classes". All three ship. Twelve more of the
same shape ship alongside them (§3, group P2).

### 1.4 Namespace shadows of IOF/BFO classes

Four stubs mint a `copi:` IRI for a class that already exists upstream. `copi:MaterialArtifact`
is the worst case: it is declared `⊑ bfo:BFO_0000030` and used in 6 restrictions, while
`iof-core:MaterialArtifact` is used 80 times in the same file — two IRIs, one concept.

| Stub | Uses | Canonical target |
|---|---|---|
| `copi:MaterialArtifact` | 6 | `iof-core:MaterialArtifact` |
| `copi:MaterialComponent` | 2 | `iof-core:MaterialComponent` |
| `copi:PhysicalObject` | 2 | `bfo:BFO_0000030` |
| `copi:EquipmentItem` | 2 | `iof-core:PieceOfEquipment` (confirm vs `MaintainableMaterialItem`) |
| `copi:InformationContentEntity` | 1 | `iof-core:InformationContentEntity` |

### 1.5 Dead stubs shadowing real equipment classes

`copi:PressureReliefValve` and `copi:SurfaceSafetyValve` have zero restriction uses and zero
subclasses, while the real classes exist with numeric IRIs: `COPI_0000145` (relief valve),
`COPI_0000147` (safety relief valve), `COPI_0000148` (safety valve), `COPI_0000112` (downhole
safety valve). Delete both.

### 1.6 Typo in a published IRI

`copi:VacuumReferenceeChamber` (double `e`). One use.

---

## 2. Policy

**No class in the published ontology carries a readable-name IRI, and no concept is declared
twice.** Every surviving stub is either merged into an existing class, retargeted to its upstream
BFO/IOF equivalent, deleted, or allocated a numeric `COPI_*` IRI. The full allocation is in §7 and
the generator changes that keep it true are in §8.

The one exception is §O6 — two equipment classes that bypassed the enrichment pipeline and must be
enriched rather than numbered.

---

## 3. Portion stubs: 65 → 5 existing + 15 new

(64 as shipped, plus `ProcessFluidSample` retyped in from the ICE group — §4.3.)

### P1 — synonyms of existing canonical classes (18 stubs, 280 uses) → remap, no new IRIs

| Stub | Uses | → |
|---|---|---|
| `FluidPortion` | 191 | `COPI_0000037` portion of fluid |
| `ProcessFluidPortion` | 0 | `COPI_0000037` (orphan — delete outright) |
| `PressurizedFluidPortion` | 1 | `COPI_0000037` |
| `HighPressureFluidPortion` | 1 | `COPI_0000037` |
| `FilteredFluidPortion` | 2 | `COPI_0000037` |
| `LiquidPortion` | 28 | `COPI_0000038` portion of liquid |
| `GasPortion` | 23 | `COPI_0000039` portion of gas |
| `GaseousPortion` | 2 | `COPI_0000039` |
| `VaporPortion` | 6 | `COPI_0000039` |
| `WaterVapor` | 1 | `COPI_0000039` |
| `SolidPortion` | 11 | `COPI_0000040` portion of solid |
| `FluidMixturePortion` | 1 | `COPI_0000044` fluid mixture |
| `MixedFluidPortion` | 1 | `COPI_0000044` |
| `LiquidMixturePortion` | 2 | `COPI_0000044` |
| `GasMixturePortion` | 1 | `COPI_0000044` |
| `MultiphaseFluidPortion` | 2 | `COPI_0000044` |
| `MaterialPortion` | 6 | `bfo:BFO_0000040` (no copi class needed) |
| `ProcessFluidSample` | 1 | `COPI_0000037` — retyped from ICE, see §4.3 |

> `VaporPortion` / `WaterVapor` → `portion of gas` is the conservative reading. If the separation
> axioms need vapour distinguished from gas as a phase, mint one class instead and say so — this
> is the one P1 row worth a second opinion.

### P2 — state reifications (12 stubs, 12 uses) → collapse to the base portion

`CompressedGasPortion`, `ExpandedGasPortion`, `CleanedGasPortion` → `COPI_0000039`.
`CompressedAirPortion`, `DryAirPortion`, `HumidAirPortion` → `COPI_0000386` (portion of air, §P4).
`DensePhase`, `LightPhase` → `COPI_0000037`.
`DriedMaterial`, `WetMaterial` → `bfo:BFO_0000040`.
`SeparatedSolidLiquidPortion` → `COPI_0000044`.
`CooledHeatingMedium` → `COPI_0000397` (heat transfer medium, §P4).

The state that each of these names is carried by the process kind and the output's qualities, not
by a substance class — ODR-010 §2.

### P3 — energy as matter (5 stubs, 20 uses) → delete and rewrite

| Stub | Rewrite |
|---|---|
| `ElectricalEnergyPortion` | drop from process I/O; equipment gets `bearer_of some COPI_0000058` (electrical power) or `COPI_0000383` (electrical current) |
| `MechanicalEnergyPortion` | drop; `bearer_of some COPI_0000059` (mechanical power) or `COPI_0000384` (mechanical force) |
| `EnergyPortion` | drop; case-by-case — 6 uses need individual review |
| `ThermalEnergy`, `ThermalEnergyPortion` | drop; the output is the heated `COPI_0000037` portion, temperature change carried by `COPI_0000052` |

`EnergyPortion`'s 6 uses are the only rows in this ODR that cannot be rewritten mechanically.

### P4 — genuine domain substances (30 stubs → 15 new classes)

All `⊑ COPI_0000037` unless noted.

| New IRI | Label | Absorbs (uses) |
|---|---|---|
| `COPI_0000386` | portion of air | `AirPortion` (5), `CompressedAirPortion`, `DryAirPortion`, `HumidAirPortion` |
| `COPI_0000387` | portion of water | `WaterPortion` (2) |
| `COPI_0000388` | portion of oil | `OilPortion` (1) |
| `COPI_0000389` | hydrocarbon fluid | `HydrocarbonFluid` (2) |
| `COPI_0000390` | formation fluid | `FormationFluidPortion` (2), `WellFluid` (2) |
| `COPI_0000391` | drilling fluid | `DrillingFluidPortion` (5), `DrillingFluid` (1) |
| `COPI_0000392` | hydraulic fluid | `HydraulicFluidPortion` (4), `HydraulicFluid` (2) |
| `COPI_0000393` | fuel portion | `FuelPortion` (3), `GaseousFuelPortion`, `ChemicalFuelPortion`, `DieselFuel` |
| `COPI_0000394` | exhaust gas | `ExhaustGasPortion` (3), `ExhaustGas` (1) — `⊑ COPI_0000039` |
| `COPI_0000395` | combustion product | `CombustionProducts`, `CombustionProductPortion`, `CombustionGasPortion` |
| `COPI_0000396` | waste material | `WasteGasPortion`, `WasteMaterialPortion` — `⊑ bfo:BFO_0000040` |
| `COPI_0000397` | heat transfer medium | `CoolantPortion` (2), `HeatingMedium` (1), `CooledHeatingMedium` |
| `COPI_0000398` | carrier fluid | `CarrierFluid` (1) |
| `COPI_0000399` | rock cuttings | `RockCuttings`, `CuttingsAndFluid` — `⊑ COPI_0000040` |
| `COPI_0000400` | removed material | `RemovedMaterial`, `CorrosionProducts`, `FilteredContaminants`, `FilteredConstituents` — `⊑ bfo:BFO_0000040` |

**Net: 64 stubs → 15 new numeric classes + 5 existing + 2 upstream anchors.**

---

## 4. Information content entities: 36 → 7 existing + 2 upstream anchors + 3 new

### I1 — collapse to `iof-core:InformationContentEntity` (10 stubs, 34 uses)

`ElectricalSignal` (19), `StandardizedSignal` (4), `StandardizedElectricalSignal` (3),
`DetectionSignal` (2), `Signal`, `InformationSignal`, `DiscreteElectricalSignal`,
`PolyphaseElectricalSignal`, `InformationBearingEntity`, `copi:InformationContentEntity`.

ODR-010 §3: "no intermediate Signal/Indication/Reading taxonomy is introduced unless an
axiomatization requires distinguishing them." None of these 34 restrictions does. `ElectricalSignal`
at 19 uses is the single largest ICE stub and collapses cleanly.

### I2 — remap to existing canonical (20 stubs, 25 uses)

| → | Absorbs |
|---|---|
| `COPI_0000045` control signal | `ManualControlSignal`, `ReferenceSignal` |
| `COPI_0000046` visual indication | `VisualInformation` (3), `VisualSignal` (2), `PhaseSequenceIndication` |
| `COPI_0000047` temperature measurement result | `TemperatureSignal` (2), `LocalTemperatureDisplay` |
| `COPI_0000048` pressure measurement result | `PressureSignal` (2), `PressureReading`, `LocalPressureDisplay`, `DifferentialPressureIndication`, `LowPressureSignal`, `HighPressureSignal`, `PressureSignalPair` |
| `COPI_0000049` flow measurement result | `MassFlowRateSignal`, `FlowMeasurement` |
| `COPI_0000050` level measurement result | `LevelSignal`, `LevelInformation` |
| `COPI_0000051` composition measurement result | `ChromatographicSignal`, `CompositionAnalysisData` |

### I3 — generic measurement (3 stubs, 7 uses) → `iof-core:MeasurementInformationContentEntity`

`MeasurementSignal` (4), `ProcessVariable` (2), `PhysicalVariable` (1).

### I4 — new classes (3)

| New IRI | Label | Absorbs | Note |
|---|---|---|---|
| `COPI_0000401` | vibration measurement result | `VibrationSignal` | `describes some COPI_0000057` (vibration quality already exists) |
| `COPI_0000402` | position measurement result | `PositionSignal` | needs a `position` quality — allocate `COPI_0000403` |
| `COPI_0000403` | position | — | `⊑ bfo:BFO_0000019` |

### 4.3 — resolved and flagged

- **`ProcessFluidSample`** (1 use, entry 224 `chromatograph`) was declared
  `⊑ iof-core:InformationContentEntity`. A fluid sample is matter, not information — a typing
  error, not a naming one, and it changed what the axiom asserted.
  **Fixed 2026-08-06** in `enrichment.db`: `auxiliary_class.bfo_category` `InformationContentEntity`
  → `FiatObjectPart`, matching its sibling input `CarrierFluid`. Verified by re-running
  `generate_combined_turtle()` — it now emits `⊑ bfo:BFO_0000024`. Under §P1 it maps onward to
  `COPI_0000037` with the rest of the portion family. Counts in §4 below are stated **before**
  this fix; the section header states the post-fix count of 36.
- **`LoggingData`** (1 use) — descriptive vs measurement ICE is genuinely ambiguous; needs a call.
- **`copi:InformationBearingArtifact`** — 0 uses and 0 subclasses *in the shipped file only*,
  because the 9 IBA restrictions are quarantined by `regen_enriched_owl.py` step 4. It is not
  dead; it is stripped. **This is exactly ODR-021's subject** (re-typing IBA → ICE) and resolving
  it retires the last strip and 3 unsatisfiable classes. Out of scope here; sequence ODR-021
  before or with this ODR.

---

## 5. Objects and parts: 71 stubs

### O1 — delete, no replacement (2)

`PressureReliefValve`, `SurfaceSafetyValve` — 0 uses, 0 subclasses, real classes already exist
(§1.5).

### O2 — retarget to upstream, delete stub (4)

Per §1.4: `MaterialArtifact`, `MaterialComponent`, `PhysicalObject`, `EquipmentItem`.

### O3 — deferred to ODR-021 (1)

`copi:InformationBearingArtifact` — 0 uses and 0 subclasses *in the shipped file only*, because
the 9 IBA restrictions are quarantined by `regen_enriched_owl.py` step 4. It is not dead; it is
stripped. This is exactly ODR-021's subject (re-typing IBA → ICE), and resolving it retires the
last strip and the 3 unsatisfiable classes. **Sequence ODR-021 first.**

### O4 — state reifications among objects (ODR-010 §2 applied to the object group, 11 → 5)

The same defect as §P2 recurs here: states and process outcomes reified as classes.

| Merge into | Absorbs |
|---|---|
| `Surface` | `CleanedSurface`, `ContaminatedSurface` — cleaned/contaminated are process outcomes |
| `TubingString` | `SupportedTubingString` |
| `ElectricalCable` | `SupportedElectricalCable` |
| `PipelinePig` | `PipePig`, `CapturedPig`, `PigFromPipeline` — one concept, two spellings and two states |
| `SensingElement` | `TemperatureSensingElement`, `ProtectedTemperatureSensingElement` |

`RestrictedObject`, `MovingObject` and `SealedJoint` are the same shape but their single uses each
need reading before merging — flagged, not merged.

### O5 — other duplicate pairs (4 → 2)

| Merge into | Absorbs | Rationale |
|---|---|---|
| suction port | `SuctionInlet`, `HydraulicPumpInlet` | `HydraulicPumpInlet`'s own definition reads "constitutes the suction inlet port" |
| tube bundle | `TubeBundle`, `TubingBundle` | same concept, two spellings |

Also `VacuumReferenceeChamber` → `VacuumReferenceChamber` (typo, §1.6).

### O6 — standard terms that bypassed the pipeline (15) — **do not just number these**

`MasterValve` and `WingValve` are the visible case: declared `⊑ COPI_0000077` (Valve), present in
`terms.db` from SLB and OnePetro, and grounded by the christmas tree definition as components of
it — yet neither has a function, differentia or process signature. They entered as bare stubs
from another entry's axioms.

Under §10.2 they are not special. They are two of **15 standard-term components** that meet the
admission test (in a standard, and explicitly stated by that standard to be a component of a
particular equipment) but never passed through the 5-step method. Minting IRIs for any of them
would launder the bypass.

**Route all 15 through the enrichment pipeline**; they receive numeric IRIs on export like any
other entry. The full list, with the equipment each is stated to be a component of, is in §10.2.
The generator must refuse to emit an undeclared stub parented to an equipment class rather than
inventing one silently (§8.3).

### O7 — number the rest (38)

Every object and part stub that is **not** a standard term gets a numeric IRI in `copi-vocab` —
the 15 that are standard terms go to the pipeline instead (§O6, §10.2). This block covers the
reusable parts (`FluidPort`, `MeasuringElement`, `SensingElement`, `SealingSystem`, `PipelinePig`,
`Surface`, suction port, discharge port, `PressureSensor`) and the entry-specific ones
(`WellheadSpool`, `ShearingBlade`, `RotatingVanes`, `MovingVane`, `BraidedConductor`, `RaisedEdge`,
`ContinuousBase`, `DivergingChannel`, `SeparateVapourSpace`, `FlexibleDiaphragm`,
`AxialDisplacementMeasuringProbe`, `PumpChamber`, `VacuumReferenceChamber`, `ControlIndicator`,
`SideOutlet`, `FluidOpening`, `DrillString`, `DrillingTool`, `DownholeToolAssembly`, `SteelPipe`,
`MetallicStructure`, `MechanicalSupport`, `CompressorInternals`, `ChristmasTreeConnectionPoint`,
`MatingSurface`, `SealedJoint`, `TurbineSection`, and the rest).

They have no standard definition to ground them, so there is nothing for the pipeline's
source-definition steps to work from — hand-authored vocabulary is the correct home.

The reusable/entry-specific distinction still matters for *modelling* — it decides what gets a
parent class and what sits directly under `MaterialArtifact` — but it no longer decides who gets a
number. Everyone does.

**Net: 71 stubs → 38 numeric classes + 4 upstream anchors + 2 deletions + 15 routed to the pipeline.**

---

## 6. Process and function stubs: 253 → all numeric

Recount, correcting the §Context figure: the process/function family is **253**, not 225. The
`PlannedProcess` (136) and `DesignedFunction` (89) groups miss 28 more that hang off COPI parents
rather than the IOF roots — `GravitySeparationProcess ⊑ SeparationProcess`,
`FiredHeatingFunction ⊑ COPI_0000190`, `ConductivityTransmissionProcess ⊑ COPI_0000035`, and so
on. Total: **151 processes, 102 functions.**

All 253 get numeric IRIs. They are 1:1 with enrichment entries, so allocation is mechanical:
extend `regen_enriched_owl.py` to allocate on first emission and write the row back to
`copi-iri-map.tsv`, exactly as equipment IRIs are handled today. The `HeatTransferProcess →
COPI_0000004` alias precedent stays: where a stub must satisfy a base-module definition, the map
points it at the protected-range IRI instead of allocating a new one.

This closes the inconsistency where ~30% of published COPI IRIs were name-based while equipment
IRIs were opaque, and it removes the silent-breakage risk where renaming a `function_name` in the
DB changed a published IRI.

---

## 7. Allocation

Next free numeric IRI is **`COPI_0000386`**. `COPI_0000379` and `COPI_0000380` remain unreclaimed
phantoms from the 2026-07-17 realignment and are **not** reused.

| Block | Count | Contents |
|---|---|---|
| `COPI_0000386–0000400` | 15 | domain substances (§P4) |
| `COPI_0000401–0000403` | 3 | vibration / position measurement results, position quality (§I4) |
| `COPI_0000404–0000441` | 38 | objects and parts (§O7) |
| `COPI_0000442–0000543` | 102 | functions (§6) |
| `COPI_0000544–0000694` | 151 | processes (§6) |
| — | 15 | standard-term components — allocated on enrichment export, not here (§O6, §10.2) |

**Total: `COPI_0000386–0000694`, 309 new IRIs**, plus 15 allocated on enrichment export.

All of it lands in `copi-vocab` except the process/function blocks, which stay in `copi-enriched`
where they are generated. Substances, ICE and parts go to `copi-vocab` — operation-layer
vocabulary, consistent with the ODR-020 precedent that put `COPI_0000383–0000385` there.

---

## 8. Generator changes required

Consolidation without generator changes regresses on the next run. Four changes:

1. **Allocate-on-emit, through the TSV.** `copi-iri-map.tsv` is the authoritative
   readable-name → numeric registry; **all allocation goes through it**, and nothing else assigns
   an IRI. Any stub emitted without a row gets one allocated at the next free number and written
   back. No readable-name IRI reaches the output.
2. **Reject inadmissible fillers at emit time.** The ODR-010 §5 rewrite rules exist but are not
   enforced at generation — that is how the energy-as-matter stubs (§1.1) and state reifications
   (§1.3, §O4) survived. Gate D should fail the build, not warn.
3. **Refuse silent equipment stubs.** A stub parented to an equipment class (`⊑ COPI_0000077` and
   siblings) means an entry is missing from the pipeline. Fail with the stub name (§O6).
4. **Block `copi:` shadows of upstream classes.** Emitting `copi:MaterialArtifact` when
   `iof-core:MaterialArtifact` is in scope should be an error (§1.4).

Without (2) in particular, this ODR is a one-time cleanup that decays.

---

## 9. Impact and sequencing

**Net effect:** 442 readable-name IRIs in the published artifact → **0**. Restriction references
retargeted: 432 (portions and ICE) plus the object/part and process/function references. Classes
deleted with no replacement: 6. Classes routed back to the enrichment pipeline: 15.

**This is an IRI-breaking change against a published artifact.** `copi.ttl` has been live since
2026-07-17. Nothing is known to consume these stub IRIs externally, which is the argument for
doing it now rather than after the FOIS 2026 presentation in September.

Suggested order:

1. **ODR-021** (IBA re-typing) — already the blocker for retiring the strip; §O3 depends on it.
2. **§3 portions** — largest single win; 279 of the 432 filler references collapse onto five
   classes that already exist.
3. **§4 ICE**, then **§5 objects and parts**.
4. **§8 generator changes** — land before §6, so the 253 process/function IRIs are allocated by
   the new code path rather than by hand.
5. **§6 process/function numbering.**
6. Regenerate, run `scripts/verify_owl.sh` (must stay at 10 green, and 0 unsat once ODR-021
   lands), redeploy — the published `copi.ttl` is 3 weeks stale regardless.

Migration mechanics: the §3 and §4 remaps are `copi-iri-map.tsv` rows plus new class declarations
in `copi-vocab.ttl`. The deletions (§P3, §O1, §O2) and the merges (§P2, §O4, §O5) need the
`auxiliary_class` rows and the `enrichment.db` `process_signature` JSON rewritten at source, so
regeneration does not re-emit them — as was done for `ProcessFluidSample` (§4.3).

---

## 10. Standing constraints (adopted 2026-08-06)

These three constraints outlive the consolidation. §3–§7 clear the existing debt; these stop it
returning.

### 10.1 Nothing deploys without a numeric IRI — **implemented**

**Every class in a deployable artifact carries a numeric `COPI_*` IRI.** No readable-name class
IRI is published, ever.

Enforced by a gate in `scripts/verify_owl.sh` (Step 1b), which scans the generated artifact for
`owl:Class` subjects in the `copi:` namespace that do not match `COPI_\d+` and exits
`E_STUB_IRI` (5).

**`copi-iri-map.tsv` is the registry the gate works against.** A readable name reaching the output
means it has no row in the TSV, so on failure the gate reads the TSV, computes the next free
number, and prints paste-ready rows:

```
	https://www.inf.ufrgs.br/ontologies/copi/SomeName	https://www.inf.ufrgs.br/ontologies/copi/COPI_0000386
```

It also detects the inverse failure — a name that **does** have a TSV row but still reached the
output, meaning the remap did not fire because the key does not match the emitted local-name.
That is the exact defect behind the 2026-07-17 realignment (`GasAbsorber`→`Absorber`,
`TemperatureSensor`→`TemperatureElement`, `InlineFilter`→`InLineFilter`) which left
`COPI_0000379`/`COPI_0000380` as unreclaimed phantoms. It was silent then; it fails the build now.

The baseline file and the TSV are complementary and verified disjoint: 383 TSV rows (names that
get remapped) and 427 baseline names (names that do not), no overlap.

Because 427 stubs are already published, the gate runs as a **ratchet rather than a cliff**:
`scripts/stub-iri-baseline.txt` grandfathers exactly those 427 names. Any readable-name class not
in the baseline fails the build immediately, so the count can only fall. As ODR-022 lands, names
are removed from the ontology and then pruned from the baseline; when the file is empty the gate
enforces zero unconditionally and the ratchet is complete. A gate that failed on all 427 from day
one would have been disabled on day one.

`--skip-iri-gate` exists for local iteration. **CI and the publish path must never pass it**, and
`regen_enriched_owl.py` should call `verify_owl.sh` without it before writing to the COPI repo.

Verified behaviour:

| Scenario | Result |
|---|---|
| Current artifact vs current baseline | pass — 427 grandfathered |
| New stub introduced | **fail**, names the stub |
| Stub removed from ontology + baseline | pass — count ratchets down |
| Baseline pruned prematurely | **fail**, message names both possible causes |
| Empty baseline, all-numeric ontology | pass — `stubs=0` |
| Name has a TSV row but was not remapped | **fail**, flags the key mismatch |

### 10.2 Standard terms go through the axiomatization pipeline

**A term drawn from a source standard is admitted to the ontology only via the 5-step enrichment
method** — never as a side effect of appearing in another entry's axioms. `MasterValve` and
`WingValve` (§O6) are the current violations: both are in `terms.db` from SLB and OnePetro, both
are declared `⊑ COPI_0000077`, neither has a function, differentia or process signature.

The generator must fail rather than invent (§8.3). A stub parented to an equipment class means an
entry is missing from the queue.

**Scope qualification.** 27 of the 174 participant/part stubs match a `terms.db` label exactly.
They do not all belong in the pipeline, because the 5-step method presupposes an identity-giving
`DesignedFunction` — which portions of matter and information content entities do not bear. The
mandate therefore applies by **entity kind**, not by mere presence in a standard:

| Kind | Route |
|---|---|
| Equipment / artifact universals (bear a DesignedFunction) | enrichment pipeline → `copi-enriched` |
| Participants — portions, ICE, qualities | hand-authored vocabulary → `copi-vocab` |

So `MasterValve`, `WingValve`, `PressureReliefValve` → pipeline. `CarrierFluid`, `DrillingFluid`,
`ThermalEnergy`, `Signal`, `ProcessVariable` → vocabulary (and `ThermalEnergy` is deleted outright
under §P3 regardless of its ISO 15926 provenance — a standard naming something does not make it a
material entity).

**Component parts follow the same rule, with an evidence bar.** A component part goes through the
enrichment pipeline — *in addition to* carrying its `hasComponentPartAtAllTimes` relationship —
when both hold:

1. it is a term in a source standard (`terms.db` label match); **and**
2. the standard **explicitly states it is a component of a particular equipment**, evidenced by a
   verbatim `source_quote` in the owning entry's `necessary_parts`.

Condition (2) is what stops the rule from admitting every noun that appears in a glossary. The
machinery already exists: `validate_necessary_parts_quotes()` in `enrichment_service.py` enforces
quote presence and verbatim match at save time, and the OWL generator skips any part lacking one
(implemented per the 2026-06-28 source-grounding plan). This ODR reuses it as the admission test
rather than adding a second mechanism.

**Current state against the rule — 37 standard-term component references, 36 grounded:**

| Bucket | Count | Disposition |
|---|---|---|
| Already an enrichment entry | 19 | Nothing to do — the rule is already de facto practice |
| In standards, grounded, still a stub | **15** | **Enrichment queue additions** |
| In standards, **not** grounded | 1 | `StuffingBox` (of `lubricator`) — ground it or drop it |

The 19 that already passed through the pipeline — `Actuator`, `Anode`, `CentrifugalCompressorCasing`,
`DifferentialPressureMeasuringElement`, `DriveShaft`, `FlowMeasuringElement`, `GearCasing`,
`GearWheel`, `HeatTransferPlate`, `InputShaft`, `OutputShaft`, `PigLauncher`, `PigReceiver`,
`Pipe`, `Port`, `PumpCasing`, `SolenoidActuator`, `ThinPlate`, `ValveSeat` — establish that
components are already treated as enrichable universals. This ODR makes that explicit and closes
the gap for the remaining 15.

**Queue additions (15).** Each is a standard term with an explicit component quote naming its
owning equipment:

| Component | Stated component of | Standards |
|---|---|---|
| `MasterValve` | christmas tree | OnePetro, SLB |
| `WingValve` | christmas tree | OnePetro, SLB |
| `DrillBit` | bottom hole assembly | ISO 15926, OnePetro, SLB |
| `Piston` | diesel engine | ISO 15926 |
| `Shell` | shell and tube heat exchanger | CFIHOS |
| `TubeBundle` | shell and tube heat exchanger | ISO 15926 |
| `FinnedTube` | finned tube heat exchanger | ISO 15926 |
| `FilterMedium` | filter press | SLB |
| `Panel` | switchboard | ISA 5.1, ISO 15926, POSC Caesar |
| `ElectricalSwitch` | switchboard | CFIHOS, ISO 15926 |
| `StatorWinding` | stator | ISO 15926 |
| `Chamber` | manifold | CFIHOS, DEXPI, ISO 15926 |
| `CableBundle` | umbilical | POSC Caesar |
| `TubingBowl` | tubing head | OnePetro |
| `GasDetectingMeasuringElement` | gas detector | ISO 15926 |

**Consequences for this ODR.** These 15 move **out of §O7** (number them in `copi-vocab`) and into
`copi-enriched` via the pipeline, shrinking the §O7 block from 53 to 38 and the §7 parts
allocation from `COPI_0000404–0000456` to `COPI_0000404–0000441`. They receive numeric IRIs on
enrichment export like any other entry, so the §10.1 gate is satisfied either way. `MasterValve`
and `WingValve` are no longer a special case (§O6) — they are simply the first two of these 15,
and their grounding quote is the christmas tree definition.

`TubeBundle`/`TubingBundle` and `MasterValve`/`WingValve` still need the §O5 duplicate merge
applied *before* enrichment, so the pipeline does not create two entries for one universal.

**Parts that are NOT standard terms stay in `copi-vocab`** and are numbered under §O7 —
`WellheadSpool`, `ShearingBlade`, `RotatingVanes`, `DivergingChannel`, `SeparateVapourSpace`,
`RaisedEdge`, `ContinuousBase`, and the rest. They have no standard to ground them, so there is
nothing for the pipeline's source-definition steps to work from.

### 10.3 Module hosting rule — provenance, not IRI range

Which component hosts a class is determined by **how the class was produced**, not by its number:

| Component | Hosts | Stability |
|---|---|---|
| `copi-core` | the FOMI/FOIS paper core: 9 operation categories, 9 equipment categories, identity/analysis classes (`COPI_0000001–0000024`) | **Frozen.** Paper-aligned. No additions from this ODR or the pipeline. |
| `copi-vocab` | everything **not** produced by the enrichment pipeline and not core: participant substances, ICE, qualities, component parts, and the function/process *parent* hierarchy | Grows by hand, deliberately, one ODR at a time. |
| `copi-enriched` | everything produced **by** the pipeline: the enriched equipment universals and the per-entry function and process classes generated from them | Regenerated wholesale on every run. |

The `copi-enriched → copi-vocab → copi-core` import chain is unchanged.

Two consequences worth stating explicitly, because both are easy to get wrong:

- **Function/process parents live in `copi-vocab`; function/process leaves live in
  `copi-enriched`.** `COPI_0000025–0000036` are hand-authored parents (ODR-006). The 253 leaves
  (§6) are generated 1:1 from entries and belong with the entries that produce them.
- **IRI number does not imply module.** `COPI_0000383–0000385` sit in `copi-vocab` despite falling
  in the 066+ range, and the strip logic in `regen_enriched_owl.py` step 3 already special-cases
  them. Under this rule that is not an anomaly to be tidied away — it is the rule working
  correctly. Allocation blocks are contiguous for bookkeeping convenience only.

Applied to this ODR's allocation (§7): the 15 substances, 3 ICE/quality classes and 53 parts go to
`copi-vocab` (hand-authored, not pipeline output); the 102 functions and 151 processes stay in
`copi-enriched` (generated). This is what §7 already specifies — 10.3 supplies the reason.

---

## Open questions

- `VaporPortion` / `WaterVapor` — merge into portion of gas, or mint a phase class? (§P1)
- `EnergyPortion`'s 6 uses — no mechanical rewrite; each needs reading. (§P3)
- `EquipmentItem` → `iof-core:PieceOfEquipment` or `MaintainableMaterialItem`? (§O2)
- `LoggingData` — descriptive or measurement ICE? (§4.3)
- `RestrictedObject`, `MovingObject`, `SealedJoint` — merge as state reifications or keep? (§O4)
- ~~`PressureSensor` (⊑ Assembly)~~ — **resolved**: not a `terms.db` label, so §10.2 does not
  route it to the pipeline. It is a component of `absolute pressure transmitter` with a quote
  ("pressure is applied to one side of the sensor while the other side has a vacuum chamber"), so
  it keeps its part relationship and is numbered under §O7.
- `StuffingBox` (of `lubricator`) — the one standard-term component with no `source_quote`. Ground
  it and enrich, or drop the part. (§10.2)


---

## 11. Execution record — 2026-08-07

Executed end to end. `copi-enriched.owl` regenerated; `scripts/verify_owl.sh --skip-oops`
passes with **0 unsatisfiable classes** and every ODR guard green.

**Result: 427 readable-name classes → 15.** The 15 that remain are exactly the standard-term
components of §O6, held back deliberately.

| Step | Outcome |
|---|---|
| Source rewrite (`scripts/migrations/odr022_canonical_names.py`) | 228 entries rewritten, 100 `auxiliary_class` rows dropped, 20 energy-as-matter participants deleted |
| `copi-vocab.ttl` | +18 classes (`COPI_0000386–0000403`); both copies byte-identical |
| `copi-iri-map.tsv` | 383 → 704 rows; 296 allocated on emit (`COPI_0000404–0000699`); no duplicate keys, no gaps |
| `copi-enriched.owl` | 613 classes — 598 numeric, 15 readable; 10,295 triples |
| Baseline | 427 → 15 |

### What changed in the code

- **`allocate_missing_iris()`** (§8.1) — allocates through `copi-iri-map.tsv` on first emission.
- **`PROTECTED_EXTRA`** — the protected strip is no longer a single `<= 60` bound; vocab-owned
  383–403 are stripped too. IRI number does not imply module (§10.3).
- **`remove_upstream_declarations()`** (§8.4) — drops declarations whose subject is BFO/IOF-Core.
  Removed 34 triples on 7 upstream classes that the canonical-name remap would otherwise have
  re-declared.
- **Alias emission** — a source-system label is now `skos:altLabel` on the target class instead of
  a minted `copi:` pseudo-class. This removed all 34 alias pseudo-classes including the all-caps
  `ACTUATOR`/`COMPRESSOR` family and `PressureReliefValve`.

### Two defects found and fixed during execution

Both would have shipped silently:

1. **The IBA quarantine stopped firing.** `remove_process_io_restrictions()` matched the *readable*
   IRI `copi:InformationBearingArtifact`. The moment allocation gave it `COPI_0000553` the match
   failed and the step reported "nothing to quarantine" — which would have returned the 3 ODR-021
   unsatisfiable classes to the release. Now resolves the name through the map and matches either
   form.
2. **The numeric IRI gate had a false pass.** It regex-matched `^copi:Name`, but rdflib binds the
   copi namespace to the **empty** prefix, so it saw `:Chamber` and counted zero stubs while 15
   were present. A gate that passes when it should fail is worse than no gate. It now parses the
   graph with rdflib, which is prefix-agnostic. Re-verified: reports 15 on the current closure and
   412 ungrandfathered on the pre-consolidation file.

### Remaining

- **15 standard-term components** must be enriched (§O6). `regen_enriched_owl.PIPELINE_REQUIRED`
  refuses to allocate IRIs for them and the build lists them every run; they stay grandfathered in
  the baseline until their entries export. The ratchet closes when the baseline is empty.
- **ODR-021** (IBA → ICE) still open; the 9-restriction quarantine still ships.
- `StuffingBox` still lacks a `source_quote` (§10.2).
- The §Open questions below are unchanged — none blocked execution.

---

## 12. Follow-up — 2026-08-08

### ODR-021 resolvido: COPI não tem InformationBearingArtifact

Decisão do orientador: COPI não deve ter essa classe. A investigação confirmou de forma mais
forte do que o ODR-021 supunha — **os 8 usos nomeiam conteúdo informacional, nenhum é artefato
material**. O texto de constraint diz isso em cada caso: "visual information", "measurement
signal", "control signal", "data streams", "communication signal".

O esboço original do ODR-021 era re-tipar IBA → ICE. Deletar é mais limpo: re-tipar manteria uma
classe COPI duplicando `iof-core:InformationContentEntity` e o vocabulário de sinais do ODR-010 —
exatamente a duplicação que o ODR-022 removeu em todo o resto.

Cada uso foi mapeado para a classe mais específica que seu próprio texto sustenta
(`scripts/migrations/odr021_retire_iba.py`):

| entry | lado | constraint diz | → |
|---|---|---|---|
| 388 sight glass | out | "visual information about fluid state" | `VisualIndication` (COPI_0000046) |
| 403 flow measuring element | out | "measurement signal ... flow rate" | `FlowMeasurementResult` (COPI_0000049) |
| 405 rotary actuator | in | "control signal" | `ControlSignal` (COPI_0000045) |
| 410 display | in / out | "data streams" / "visual presentation" | ICE / `VisualIndication` |
| 411 diaphragm actuator | in | "control signal" | `ControlSignal` |
| 413 transmitter housing | out | "protected signal transmission" | ICE |
| 428 port | in / out | "communication signal" / "interface response" | ICE |

**A quarentena foi retirada.** Ela existia por um motivo só: IBA era `bfo:Object` num processo que
forçava saídas `MeasurementICE`, um choque IndependentContinuant ⊓ GDC. Sem a causa, o contorno
sai junto — **todas as restrições de participante agora publicam sem strip**, completando o
objetivo do ODR-020 §6. No lugar dela ficou `assert_no_information_bearing_artifact()`, uma
guarda que falha o build se IBA reaparecer.

Resultado: **0 classes insatisfatíveis** com o strip totalmente aposentado.

### Os 15 componentes: 14 enriquecidos, 1 era duplicata

`scripts/migrations/odr022_enrich_15_components.py` — inseridos com `status='proposed'`,
`llm_model='claude-opus-5'`. Revisão pericial em `/enrich/` é o próximo passo; só
`validated`/`exported` chegam ao gerador, então eles **continuam no baseline até serem
revisados** — que é o portão pretendido.

| modo | entradas |
|---|---|
| `equivalent` (base funcional) | drill bit, electrical switch |
| `necessary` (base construtiva ou posicional) | master valve, wing valve, finned tube, tube bundle, chamber, stator winding, cable bundle, gas detecting measuring element, panel, piston, filter medium, tubing bowl |

`necessary_parts = []` nos 14: nenhuma definição de fonte nomeia sub-componente, e
`validate_necessary_parts_quotes()` exige `source_quote` verbatim. Inventar peças aqui é
precisamente o que a regra de ancoragem existe para impedir.

**`Shell` não foi enriquecido — era duplicata.** A definição CFIHOS ("a layer or surface
surrounding a space, typically the cylindrical part of a vessel") é o mesmo universal que a
entrada já exportada `vessel shell` (COPI_0000374, "the outer pressure-containing structural
boundary of a vessel"), e a cadeia fecha: shell and tube heat exchanger ⊑ HeatExchanger ⊑
PressureVessel ⊑ Vessel. Criar entrada nova teria produzido duas classes para um universal.
A referência foi repontada (`odr022_repoint_shell.py`), preservando o `source_quote` —
stub retirado sem IRI nova nenhuma.

### Colisões de função evitadas

Três entradas foram rebaixadas de `equivalent` para `necessary` na revisão, porque a mesma função
já era condição suficiente de outra classe — o padrão que o CLAUDE.md alerta ("same-genus
same-function → must use necessary"), aqui na variante parte/todo:

- **gas detecting measuring element** — `gas detector` já é equivalente em `GasDetectionFunction`.
  Um elemento de medição é componente do instrumento, não uma instância dele.
- **filter medium** — recebeu `SelectivePermeabilityFunction` em vez de `FiltrationFunction`,
  que já é a condição suficiente de `filter`.
- **chamber** — `ContainmentFunction` é portada por vaso, tanque e pipeline; equivalência
  arrastaria todos.

### Estado

| | |
|---|---|
| `copi-enriched.owl` | 611 classes — **597 numéricas, 14 legíveis** |
| baseline | 14 |
| insatisfatíveis | **0**, com strip aposentado |
| ODR-021 | **resolvido** |

Os 14 saem do baseline conforme forem validados. O ratchet fecha em zero quando o último exportar.

### Aberto

- **`MeasuringElement`** é termo ISO 15926 e genus de `gas detecting measuring element`, mas
  entrou como stub numerado (§O7) e não pela pipeline. Não apareceu na varredura porque é genus,
  não `necessary_parts` nomeado. Pela §10.2 provavelmente deveria ser enriquecido — vale decidir.
- `vessel shell` (COPI_0000374, exportada) usa `∃hasFunction.` na differentia; a regra 1 do
  CLAUDE.md manda `∃bearerOf.`. Defeito pré-existente, não introduzido aqui.
- `StuffingBox` continua sem `source_quote` (§10.2).

---

## 13. Auditoria de cobertura da pipeline — 2026-08-08

Varredura de **todas as 692 classes COPI** declaradas em `copi-core` + `copi-vocab` +
`copi-enriched` (não só as que aparecem como `necessary_parts`, que foi o recorte estreito que
deixou o `MeasuringElement` passar). Nomes numéricos resolvidos de volta pelo `copi-iri-map.tsv`,
funções e processos excluídos (são gerados 1:1, não são termos).

**290 classes são termo de alguma norma. 20 não têm entrada de enriquecimento.** A regra §10.2 vale
por tipo de entidade, e o `term_type` do ISO 15926 faz a triagem quase sozinho:

| categoria | n | veredito |
|---|---|---|
| `SinglePropertyDimension` → qualidades | 7 | **correto** — `bfo:Quality` não porta `DesignedFunction`; `copi-vocab` |
| porções de matéria | 3 | **correto** — participantes ODR-010; `copi-vocab` |
| `ClassOfActivity` → ocorrentes | 4 | **correto** — categorias de operação do paper; `copi-core` congelado |
| `ClassOfFeature` | 1 | defeito de ancoragem, corrigido abaixo |
| artefatos | 5 | 1 correto (core congelado), **4 lacunas reais** |

Qualidades: `Temperature` (052), `Pressure` (053), `FlowRate` (054), `Vibration` (057),
`MechanicalPower` (059), `RotationalSpeed` (060), `Position` (403).
Porções: `FormationFluid` (390), `DrillingFluid` (391), `CarrierFluid` (398).
Ocorrentes: `HeatTransfer` (004), `MechanicalSeparation` (006), `GasAbsorption` (013),
`HeatExchange` (089) — todos `copi-core`.
`ChemicalReactor` (020) é categoria de equipamento do paper, congelada por §10.3.

### As 4 lacunas reais

Artefatos em `copi-enriched` que portam função mas entraram como stub numerado:

| classe | IRI | norma | tipo ISO |
|---|---|---|---|
| `MeasuringElement` | COPI_0000573 | ISO 15926, DEXPI | ClassOfFunctionalObject |
| `FluidPort` | COPI_0000536 | ISO 15926 | ClassOfFunctionalObject |
| `DrillString` | COPI_0000480 | ISO 15926, OnePetro, SLB | ClassOfInanimatePhysicalObject |
| `ElectricalCable` | COPI_0000489 | ISO 15926 | ClassOfInanimatePhysicalObject |

`ClassOfFunctionalObject` é literalmente a classe ISO das coisas que portam função — sinal forte
de que `MeasuringElement` e `FluidPort` são material de pipeline. `MeasuringElement` é ainda genus
de `gas detecting measuring element`, então hoje um genus não-enriquecido sustenta uma entrada
enriquecida.

**Não enriquecidas aqui** — a decisão foi enriquecer os 15 componentes, e estas 4 são um conjunto
distinto que merece decisão explícita (`FluidPort` e `MeasuringElement` são componentes;
`DrillString` e `ElectricalCable` são mais próximos de equipamento).

### Falso positivo corrigido na própria auditoria

A primeira passada acusou `SelfOperatingValve` (COPI_0000149) como lacuna. **Não é**: a entrada
existe como `self-operating valve` (id 62, exported) e o casamento por rótulo não tratava hífen.
A varredura foi refeita normalizando ambos os lados (minúsculas, sem hífen/espaço), o que também
revelou `HeatExchange` — que o casamento ingênuo perdia. Números acima são da passada corrigida.

### Defeito corrigido: `Surface` sem âncora BFO

`Surface` (COPI_0000661) publicava como `⊑ owl:Thing`. Introduzido pela fusão §O4
(`CleanedSurface` + `ContaminatedSurface` → `Surface`): o gerador cai em `owl:Thing` quando não há
linha em `auxiliary_class`, e a fusão criou o nome sem criar a linha. Era a **única** classe sem
âncora no artefato (verificado). Ancorada em `FiatObjectPart` — ISO 15926 a define como
`ClassOfFeature`, "the face of a physical object", e o uso real é como participante do processo de
`scraper`, onde a região tratada tem espessura. Regenerado: **0 classes `⊑ owl:Thing`**.

Lição para a §8: a validação de fusões deveria exigir linha em `auxiliary_class` para todo nome-alvo
novo, do mesmo modo que a §8.1 exige linha no TSV para todo nome emitido.

---

## 14. As 4 lacunas enriquecidas + guarda de ancoragem — 2026-08-08

### Definições: todas as 4 têm

| classe | fontes | definição |
|---|---|---|
| `MeasuringElement` | ISO 15926, DEXPI | "used for the measurement of a Property … defined independently from a MEASURING INSTRUMENT" / "An artefact used for the measurement of a Property" |
| `FluidPort` | ISO 15926 | "a PORT that allows for the entry or exit of substances that behave as fluids, i.e. gases, liquids and fluidized solids" |
| `DrillString` | ISO 15926, OnePetro, SLB | "an assembly of drill pipe with attached tool joints" / "All the equipment in a drilling BHA plus the drill pipe" / "…used to make the drill bit turn at the bottom of the wellbore" |
| `ElectricalCable` | ISO 15926 | "consists of one or more CABLE CONNECTORs, held together with an overall sheath, and is used to distribute electricity" |

Inseridas com `status='proposed'` (`odr022_enrich_4_gaps.py`). As 4 **já tinham IRI numérica** —
isto não mexe no mapa, só fornece a axiomatização que faltava.

| classe | genus | modo | função |
|---|---|---|---|
| measuring element | MaterialArtifact | `equivalent` | PropertyMeasurementFunction |
| fluid port | **Port** (genus enriquecido) | `equivalent` | FluidEntryExitFunction |
| drill string | Assembly | `necessary` | DrillingPowerTransmissionFunction |
| electrical cable | MaterialArtifact | `necessary` | ElectricalDistributionFunction |

**Colisão evitada:** `ElectricalCable` **não** reusa `ElectricalConductionFunction` — a entrada
`electrical connection` já é equivalente nessa função com o mesmo genus `MaterialArtifact`, e
compartilhá-la faria o raciocinador inferir que todo cabo é uma conexão elétrica e vice-versa.
Recebeu `ElectricalDistributionFunction`, que é o que o ISO de fato diz ("used to distribute
electricity"). Este é o terceiro caso do mesmo padrão nesta rodada — ver §12.

`MeasuringElement` deixa de ser um genus não-enriquecido sustentando `gas detecting measuring
element`; `FluidPort` ganha o genus `Port`, que já era enriquecido.

### Guarda de ancoragem (§8.5)

`assert_all_classes_anchored()` falha o build se qualquer classe COPI ficar sem pai nomeado.
Fecha exatamente a lacuna que deixou o `Surface` publicar como `⊑ owl:Thing`: o gerador cai em
`owl:Thing` silenciosamente quando um nome não tem linha em `enrichment` nem em
`auxiliary_class`, e fusões criam nomes-alvo novos sem criar a linha.

Calibração importante: contar só `rdfs:subClassOf` nomeado acusou **8+ falsos positivos** —
entradas em modo `equivalent` colocam o genus dentro do `owl:equivalentClass` e não têm
`subClassOf` separado. A guarda aceita as duas formas. Verificado nos dois sentidos: com a linha
do `Surface` removida acusa `COPI_0000661` e só ela; com a linha presente, "all anchored" nas 597
classes numéricas.

Espelhada em `verify_owl.sh` para que o fecho verificado seja o mesmo que publica.

### Estado

| | |
|---|---|
| `copi-enriched.owl` | 611 classes — 597 numéricas, 14 legíveis |
| classes `⊑ owl:Thing` | **0** (guarda ativa) |
| insatisfatíveis | **0** |
| entradas `proposed` aguardando revisão | 18 (14 componentes §12 + 4 lacunas §13) |
| ODR-021 | resolvido |

### Aberto

- `vessel shell` (COPI_0000374) usa `∃hasFunction.` na differentia; regra 1 do CLAUDE.md manda
  `∃bearerOf.`. Pré-existente.
- `StuffingBox` sem `source_quote` (§10.2).
- A hierarquia de elementos de medição é plana: `temperature/flow/differential pressure measuring
  element` têm genus próprio (`TemperatureElement`, `FlowElement`, `PressureElement`) e não
  `MeasuringElement`, então não classificam sob ele. Vale decidir se as funções específicas
  deveriam ser subclasses de `PropertyMeasurementFunction`.

---

## 15. Duplicatas cross-standard — 2026-08-13

Varredura sistemática (agente dedicado): 289 entradas reais, 41.616 pares pontuados por
identidade de `function_name`, disjunção de fontes, morfologia de rótulo, similaridade de
definição e identidade genus+differentia. O discriminador decisivo foi: **alguma norma sozinha
define os dois rótulos?** Se sim, são irmãos legítimos; se não, é o mesmo universal nomeado por
duas normas.

### Decisão: remover, não depreciar

COPI ainda não tem consumidor externo, então a classe fundida é **removida por completo** em vez
de virar `owl:deprecated` + `IAO_0100001`. Um redirecionamento que ninguém vai seguir é só
sujeira. O registro da decisão fica no banco (`deprecated_in_favor_of`), e o nome removido passa a
**aliasar a IRI numérica canônica** em `copi-iri-map.tsv`, para nada ficar pendurado. Os números
liberados ficam sem alocação.

### Fundidas (3)

| removida | canônica | por quê |
|---|---|---|
| `flow measuring element` (ISO) COPI_0000082 | `flow element` (CFIHOS+POSC) COPI_0000116 | mesma `FlowMeasurementFunction`; a differentia da removida era **idêntica à do próprio genus** — não acrescentava condição nenhuma |
| `temperature measuring element` (ISO) COPI_0000358 | `temperature element` (CFIHOS+POSC) COPI_0000076 | `TemperatureSensingFunction` vs `TemperatureMeasurementFunction` são o mesmo ato para um elemento primário |
| `seat` (SLB) COPI_0000080 | `valve seat` (ISO) COPI_0000371 | definições quase verbatim; `valve seat` é canônica: ISO a tipa como VALVE COMPONENT, o rótulo é inequívoco, e ela já é peça de `gate valve`/`plug valve` — `Seat` não tinha referência alguma |

Canônicas escolhidas por suporte de fontes (2 contra 1) e por casarem com o "primary element" da
ISA 5.1 (tags FE/TE).

### Removidas por outros motivos (2)

- **`wellbore` id 259** — linha duplicada de re-run da pipeline, `source_definitions_used`
  idênticas à id 100. Não é caso cross-standard.
- **`cable bundle`** — POSC Caesar declara o rótulo **sem definição**. Sem definição de origem não
  há o que enriquecer (§10.2), então a entrada foi removida e `CableBundle` saiu de
  `PIPELINE_REQUIRED`: continua como vocabulário com IRI numérica, como qualquer peça sem norma
  que a fundamente.

### Afirmação do agente que foi refutada

O agente relatou que `safety valve` (COPI_0000148) e `safety relief valve` (COPI_0000147)
colapsariam sob ELK, por terem genus `Valve` e differentia `∃bearerOf.SafetyReliefFunction`
idênticos. **Não colapsam.** O OWL é construído a partir de `function_name`, não de
`differentia_expression`:

```
COPI_0000147 ≡ Valve ⊓ ∃hasFunction.COPI_0000032   (safety relief function)
COPI_0000148 ≡ Valve ⊓ ∃hasFunction.COPI_0000168   (safety venting function)
```

Fillers distintos, e as duas funções só são `⊑ DesignedFunction`, sem equivalência entre si.

O agente achou um defeito real mas errou a gravidade: a `differentia_expression` do `safety valve`
cita `SafetyReliefFunction` enquanto seu `function_name` é `SafetyVentingFunction` — regra 3 de
correção do CLAUDE.md. Corrompe a anotação FOL, não o raciocínio.

### Defeito pego no próprio teste da migração

A primeira versão do repoint de prosa reescrevia o rótulo por extenso em qualquer texto. Para
`seat` — palavra comum em inglês — isso transformaria "the seat of the valve" em "the valve seat
of the valve", e na linha da própria classe-alvo produziria "valve valve seat". A migração agora
só reescreve prosa quando o rótulo tem **duas ou mais palavras**, e nunca na linha do alvo. A
forma PascalCase continua sempre segura, por ser referência a classe.

### Alerta preventivo

ISO 15926 também define `LEVEL MEASURING ELEMENT` e `PRESSURE MEASURING ELEMENT`, contrapartes
exatas de `level element` e `pressure element` (já enriquecidos via CFIHOS/POSC). Se a fila os
pegar, os dois primeiros merges se reproduzem. **Bloquear esses dois rótulos ISO na fila.**

### Achado adjacente — erro oposto, mesma raiz

Entradas que **fundem dois universais diferentes** porque a ingestão agrupou homônimos por rótulo:
`casing` cita OnePetro/SLB (revestimento de poço) junto com CFIHOS/ISO (carcaça de máquina);
`basin` cita bacia sedimentar junto com contentor; `impeller` cita uma entrada SLB que define
impedância elétrica; idem `indicator`, `stack`, `lubricator`, `filter`.

Não é limpeza de stub — é qualidade de dado na ingestão, admissão por rótulo em vez de por
definição. **Não tratado aqui.**

### Estado

| | |
|---|---|
| `copi-enriched.owl` | **606 classes — 593 numéricas, 13 legíveis** |
| `owl:deprecated` no artefato | 0 (removidas, não depreciadas) |
| insatisfatíveis | 0 |
| baseline | 13 |

### Aberto

- ~~10 entradas `proposed` com `source_definitions_used` vazio~~ — **afirmação incorreta**,
  corrigida em §18. O campo estava preenchido em formato legado que a auditoria não lia.
- 49 linhas de fixture de teste (`pump-t*`, `stale-test-*`, `undo-*`, `np-guard-*`) poluem a
  tabela `enrichment`.
- `valve seat` porta `FlowControlFunction`; ambas as definições de origem descrevem vedação, não
  controle de fluxo. A removida `seat` portava `SealingFunction`. Deixei a axiomatização da
  canônica intacta — o merge é para tirar duplicação, não para re-axiomatizar.
- 9 entradas com `∃hasFunction.` na differentia (regra 1 do CLAUDE.md manda `∃bearerOf.`).

---

## 16. Limpeza de fixtures, aliases ISO e correção do valve seat — 2026-08-13

### 49 linhas de fixture removidas

`pump-t*`, `stale-test-*`, `undo-test-*`, `undo-unit-*`, `np-guard-*` — resíduo de execuções de
teste na tabela `enrichment`. Todas `proposed`, portanto nenhuma chegava ao OWL; a migração aborta
se alguma estiver `validated`/`exported`. 6 linhas órfãs em `enrichment_history` limpas junto.
Tabela: 336 → 287 linhas.

### Os dois rótulos ISO registrados como alias, não enriquecidos

`LEVEL MEASURING ELEMENT` e `PRESSURE MEASURING ELEMENT` (ISO 15926) são o mesmo universal que
`level element` e `pressure element` (CFIHOS/POSC), já enriquecidos. Entraram em `cluster_alias`
como `exactMatch` aceito, o que o gerador emite como **`skos:altLabel` na classe canônica**
(comportamento estabelecido em §12).

Isso resolve as duas coisas de uma vez: registra a equivalência cross-standard e impede que a fila
os enriqueça separadamente, reproduzindo os merges de §15. Preferível a "bloquear os rótulos",
porque a informação fica no artefato em vez de numa lista externa.

### `valve seat` → `SealingFunction`, e o bloqueador que apareceu

Ambas as definições de origem descrevem vedação, não controle de fluxo: o assento fornece a
superfície contra a qual o obturador se apoia. Controlar fluxo é função da válvula inteira, da
qual o assento é apenas parte. `FlowControlFunction` estava errada.

**A troca direta não funcionava.** `gasket` era `≡ MaterialArtifact ⊓ ∃hasFunction.SealingFunction`
— equivalência, portanto condição *suficiente*. Dar `SealingFunction` ao `valve seat` (mesmo genus)
faria o raciocinador inferir `ValveSeat ⊑ Gasket`.

A causa real é o `gasket`, não o `valve seat`. Sua definição é construtiva — "deformable material
arranged in closed loops" — e essas condições vivem só em `differentia_expression`, que **não
chega ao OWL**. Então a equivalência afirmava muito mais do que a entrada pretendia: qualquer
artefato com função de vedação virava junta. Base construtiva → `necessary`, exatamente a regra do
CLAUDE.md.

Corrigido em dois passos: `gasket` de `equivalent` para `necessary`, e `valve seat` de
`FlowControlFunction` para `SealingFunction` (adotada da entrada `seat` removida em §15).

**Verificado com HermiT**, não por inspeção: mesclado o fecho completo (enriched + vocab + core +
IOF + BFO) e raciocinado — `ValveSeat ⊑ Gasket` é **False**, e `Gasket` não tem nenhuma subclasse
inferida. Confirma que a equivalência anterior era ampla demais e que agora não é.

Nota de método: este é o quarto caso da mesma família nesta rodada — uma função genérica usada como
condição suficiente engolindo classes que apenas a portam. Os outros foram `electrical connection`
(§14), `filter`/`gas detector` (§12). Vale um guard: **nenhuma entrada `equivalent` deve ter
differentia que só restate sua própria `function_name`**, salvo se a função for exclusiva daquela
classe.

### Estado

| | |
|---|---|
| `copi-enriched.owl` | 607 classes — 594 numéricas, 13 legíveis |
| entradas na `enrichment` | 287 (era 336) |
| insatisfatíveis | 0 |
| `ValveSeat ⊑ Gasket` | False (verificado com HermiT) |

---

## 17. Guard: subsunção não intencional sob classe `equivalent` — 2026-08-13

### O padrão

Uma entrada `equivalent` afirma

```
C ≡ Genus ⊓ ∃hasFunction.F
```

o que torna "ser um Genus e portar F" condição **suficiente** para ser um C. Qualquer outra
coisa sob aquele genus que porte aquela função é então inferida como C — inclusive partes,
componentes e universais sem relação que apenas por acaso vedam, filtram ou detectam.

Esta família foi encontrada **quatro vezes** durante o ODR-022, sempre à mão, sempre uma de cada
vez: `gasket` engoliria `valve seat` (§16); `filter` engoliria `filter medium`, seu próprio
componente (§12); `gas detector` engoliria `gas detecting measuring element`, sua própria peça
(§12); `electrical connection` engoliria `electrical cable` (§14).

`assert_no_unintended_function_subsumption()` pega a família inteira.

### O critério

Sinaliza quando **D seria inferida ⊑ C mas nada na ontologia diz isso** — D não nomeia C em
lugar nenhum da sua cadeia de genus. Um subtipo legítimo (`centrifugal pump` sob `pump`) declara
seu genus, então a inferência é intencional e o check fica quieto. Uma não intencional não
declara, e essa lacuna é exatamente o sinal.

Lê tanto `owl:equivalentClass` quanto `rdfs:subClassOf`, porque entradas `necessary` e
`equivalent` diferem apenas em como empacotam genus e função — o check não deve depender de
`axiom_mode`.

### Dois falsos positivos corrigidos no teste

**(1) Qualidades tratadas como funções.** A primeira versão aceitava qualquer filler de
`bearer_of`. Mas `bearer_of` carrega **qualidades** além de funções (`bearer_of some
ElectricalPower`), e o check passou a acusar todo par de dispositivos elétricos — 30+ ocorrências
como `Switchboard -> Transformer`, `Rotor -> DriveShaft`. Compartilhar qualidade não é o defeito.
O filler agora precisa descender de `iof-core:DesignedFunction` ou `bfo:Function`
(`_is_function_class`). Depois do filtro: 14 casos.

**(2) Teste de genus por interseção em vez de subconjunto.** Uma classe definida é
`C ≡ G1 ⊓ … ⊓ Gn ⊓ ∃f.F`, então D só é absorvida se satisfizer **todos** os conjuntos. O teste
usava interseção (bastava um genus casar), o que reportou `Sheave` e `PumpShaft` — ambas apenas
`⊑ MaterialArtifact` — como absorvidas por `DriveShaft`, que é `≡ Assembly ⊓ MaterialArtifact ⊓ …`.
Não são. Idem `Shaft`, `Gearbox` e `DifferentialPressureGauge`. Corrigido para teste de
subconjunto: **14 → 9 casos reais**.

Vale registrar o método: eu ia corrigir a ontologia com base nesses 14. Cinco eram bug do meu
próprio check. Verificar o instrumento antes de agir sobre o que ele reporta evitou cinco
alterações indevidas no modelo.

### Os 9 resolvidos — ratchet fechado em zero

Duas causas distintas, dois tratamentos:

**(a) Equivalência ampla demais → `necessary`.** A definição carrega conteúdo estrutural ou
extra-funcional que o nome da função sozinho não carrega, logo genus+função não é condição
suficiente (base construtiva, regra do CLAUDE.md):

| classe | o que a definição acrescenta | absorvia |
|---|---|---|
| `flow meter` | "measure **and** produce indications" | `flow element`, `orifice plate` |
| `flare` | "at an elevated location" | `flare tip` — seu próprio componente |
| `drive shaft` | "consists in a shaft-based system" | `gear wheel`, `input shaft`, `output shaft` |
| `electrical connection` | conexão é o *juntar*; conduzir é necessário, não suficiente | `switch contact` |

**(b) Subtipo genuíno, só faltava declarar → genus explícito.** A inferência estava certa, apenas
não escrita:

- `cooling tower` genus `HeatExchanger` → **`Cooler`**
- `flange` genus `MaterialArtifact` → **`Coupling`**

**Verificado com HermiT**, não por inspeção: `CoolingTower ⊑ Cooler` e `Flange ⊑ Coupling` são
**True** (subsunções pretendidas, agora declaradas); `GearWheel`, `InputShaft`, `OutputShaft`
`⊑ DriveShaft`, `FlareTip ⊑ Flare`, `SwitchContact ⊑ ElectricalConnection`, `OrificePlate` e
`FlowElement ⊑ FlowMeter` são todas **False**.

`scripts/equivalent-subsumption-baseline.txt` está **vazio** — o check enforça zero.


---

## 18. Toda axiomatização é fundamentada — correção de uma afirmação minha — 2026-08-13

### A afirmação estava errada

Relatei em §13 e §16 que 10 entradas `proposed` (`aerator`, `converter`, `conveyor`,
`enclosure`, `evaporator`, `gauge`, `ignitor`, `lifting device`, `lubricator`, `stack`) não
tinham definição de origem, e portanto não poderiam ser enriquecidas. **Não é verdade.**

`source_definitions_used` estava preenchido nas 10, num **formato diferente**: lista de strings
`"iso15926:AERATOR — A FunctionalObject que ..."` em vez da lista de objetos
`{"source": "iso15926", "term": "AERATOR"}` usada pelas outras 277. Minha auditoria só tratava
o formato objeto e descartava strings silenciosamente, reportando as 10 como sem fonte.

Medição correta: **287 entradas, 287 com definição de origem. Nenhuma sem.**

E as axiomatizações de fato rastreiam as normas — algumas quase verbatim:

| entrada | norma |
|---|---|
| `evaporator` "heat exchanger designed to evaporate moisture or solvents to obtain a concentrate" | CFIHOS: "A heat exchanger that is intended to evaporate moisture or solvents in order to obtain a concentrate" |
| `lifting device` "raise or lower loads vertically, with or without horizontal displacement" | POSC Caesar: "intended for the lifting of loads, with or without horizontal displacement" |
| `ignitor` "initiate the ignition of a combustible mixture by generating a spark" | CFIHOS/POSC: "intended to initiate a spark that ignites a combustible mixture" |

### Formato normalizado

As 10 foram convertidas para o formato objeto (`odr022_normalize_source_definitions.py`), com
verificação de que cada par `(source, term)` resolve de fato em `terms.db` — e resolvendo caixa,
porque as strings legadas minusculavam alguns rótulos (`onepetro_glossary:lubricator` para um
termo gravado como `Lubricator`). O texto da definição não se perde: vive em `terms.db`,
chaveado por `(source, term)`.

Agora **287/287 no formato objeto**, e a auditoria de fundamentação passa a ser confiável.

### Um homônimo real, encontrado ao ler as fontes

Citar uma definição que descreve **outro universal** é pior do que não citar nenhuma: parece
fundamentação, mas aponta para a coisa errada.

`lubricator` citava três fontes. A entrada axiomatiza o sentido de cabeça de poço — "vaso
cilíndrico pressurizado instalado acima do wellhead que permite introduzir ferramentas em poço
vivo" — conforme SLB e OnePetro. Mas também citava **ISO 15926 LUBRICATOR**, "a FunctionalObject
that has the capability of LUBRICATING": um lubrificador, universal completamente diferente que
por acaso divide o rótulo.

Excluído via `excluded_definition_ids`, o mecanismo que a própria UI de revisão já usa
(`enrichment_routes.py:1992`). É a mesma família de conflação de homônimos apontada em §15
(`casing`, `basin`, `impeller`) — aqui tratada no ponto em que importa, a evidência da entrada.

### Ainda em aberto: `stack`

`stack` cita ISO 15926 ("capability of EXHAUSTING a flue gas") e CFIHOS ("a support structure
intended to support a flare or vent pipe"). A entrada axiomatiza o sentido ISO — exaustão. O
sentido CFIHOS é o *suporte*, plausivelmente outro universal. Não excluí: diferente do
`lubricator`, onde os sentidos não têm relação, aqui os dois descrevem partes do mesmo arranjo
físico e a chamada é do especialista.

### Achado colateral: diffs do artefato são irrevisáveis

Ao verificar se a regeneração pós-normalização mudara o artefato, medi o contrário: uma
regeneração **sem nenhuma mudança semântica** produz diff de **21.864 linhas**
(10.932 inserções + 10.932 remoções). O rdflib emite IDs de blank node novos a cada
serialização, e o `copi-enriched.owl` tem ~10 mil triplas com blank node (restrições,
intersecções, listas RDF).

Consequência prática: **não dá para distinguir mudança real de ruído no diff**. Neste caso a
única diferença de conteúdo era uma tripla — `owl:versionInfo` — enterrada em 21 mil linhas.
Precisei escrever um diff semântico ad hoc (comparar triplas sem blank node) para descobrir isso,
e a primeira versão dele também errou, por incluir linhas cujo *sujeito* é blank node.

Isso torna a revisão do artefato no PR ineficaz e esconde regressões — foi exatamente assim que a
quarentena do IBA passou despercebida ao parar de funcionar (§12).

Correção disponível: serializar com IDs de blank node determinísticos (skolemização estável, ou
`rdflib` com `canonicalize`/algoritmo de rotulagem canônica) para que a mesma entrada produza
sempre o mesmo arquivo. Não implementado aqui — é mudança na pipeline de build, fora do escopo
desta rodada, mas de valor alto.

Por ora: o artefato **não foi recommitado** após a normalização, porque a única diferença era o
carimbo de versão. O conteúdo publicado continua correto.

---

## 19. Revisão do Bloco 1 — as 4 entradas `equivalent` — 2026-08-14

Das 17 propostas, quatro afirmam condição suficiente e por isso foram revisadas primeiro. Para
cada uma foi feita a checagem que o guard do §17 **não** faz: ele acusa colisão já existente, não
colisão potencial com termos que ainda não entraram na fila.

| entrada | decisão |
|---|---|
| `fluid port` | **aprovada** — ISO dá o genus explícito (`a PORT that allows for the entry or exit of substances that behave as fluids`) e definição puramente funcional. O que seria absorvido — `SuctionPort`, `DischargePort`, `BranchPort` — já declara `FluidPort` como pai. Absorção correta e declarada. |
| `electrical switch` | **aprovada** — CFIHOS e ISO dão a mesma definição funcional, sem restrição construtiva. |
| `drill bit` | **aprovada com risco anotado** — as três fontes concordam e nenhuma restringe construção. Mas ISO 15926 define `BOREHOLE REAMER`, "used to crush or cut rock in order to enlarge an undergauge hole": um alargador corta rocha e **não** é broca. Se entrar na fila, será absorvido — e o guard do §17 acusa quando isso acontecer. |
| `measuring element` | **corrigida** — ver abaixo. |

### `measuring element`: genus errado e âncora ausente

A proposta original era `MaterialArtifact ⊓ ∃bearerOf.PropertyMeasurementFunction`, equivalente.
Dois erros, e o segundo só apareceu porque o orientador perguntou se não havia sobreposição com a
`MeasurementInstrument` da `copi-core`.

**Genus.** O COPI já trata elementos primários como instrumentos: `temperature element`,
`pressure element`, `flow element` e `level element` **todos** têm genus `Instrument`. O genus
correto é `Instrument`, não `MaterialArtifact`.

**Âncora.** `PropertyMeasurementFunction` era um stub pelado (`⊑ DesignedFunction`) e seu processo
ficou em `PlannedProcess`. É *só por isso* que o raciocinador não colocava a classe sob
`MeasurementInstrument` — acidente, não decisão. O padrão que funciona é o `InstrumentationFunction`
(COPI_0000029), que declara `∃realizedIn.MeasurementProcess` e `∀realizedIn.MeasurementProcess`;
é essa âncora que faz `Instrument ⊑ MeasurementInstrument`. `function_parent` passou a
`InstrumentationFunction`, tornando a classificação explícita.

**Modo.** `necessary`. A função identificadora do elemento é o sensoreamento que o genus já porta,
então equivalência colapsaria os dois. E o que ISO usa para distinguir — "defined independently
from a MEASURING INSTRUMENT that is handling that measurement result" — é condição relacional,
não suficiente sob OWA.

### Aberto por consequência: ODR-023

A pergunta sobre sobreposição descobriu que `Instrument ⊑ MeasurementInstrument` está
**invertido** em relação ao que as normas dizem — ISA 5.1 define `instrument` incluindo
controladores, elementos finais de controle, chaves e botoeiras, nenhum dos quais mede. A causa é
o `allValuesFrom MeasurementProcess` em `InstrumentationFunction`. Registrado em
**ODR-023**; não bloqueia o Bloco 1 porque `measuring element` fica correto sob `Instrument` nas
duas leituras possíveis.

### Fila

- **`switching device`** (ISO 15926) — ISO põe `ELECTRICAL SWITCH` e `CIRCUIT BREAKER` como
  **irmãos** sob ele, não um sob o outro. Se a hierarquia elétrica for arrumada, é este o gênero
  a enriquecer, não pendurar disjuntor em chave.
- **`borehole reamer`** (ISO 15926) — quando entrar, precisa de função própria
  (`HoleEnlargementFunction` ou similar), senão é absorvido por `drill bit`.
