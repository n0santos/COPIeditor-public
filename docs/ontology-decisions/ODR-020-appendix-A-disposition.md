# ODR-020 — Appendix A: Legacy Filler Disposition & Impact

Companion to `ODR-020-legacy-filler-migration.md`. Verified against `enrichment.db` and the `status IN ('validated','exported')` combined TTL on 2026-07-10 (iCloud Optimize-Storage disabled; 0 dataless files; `PRAGMA integrity_check = ok`; 183 `auxiliary_class` rows, 272 enrichment rows).

**Counts:** *emitted* = OWL restrictions actually generated in the deployed-relevant (`validated`+`exported`) TTL. *raw* = usages across all statuses. **Total emitted offender restrictions: 88, over 59 distinct validated/exported equipment; 62 unsatisfiable classes when un-stripped.**

**Disposition vocabulary:** `map-§7` (ODR-010 §7 row applies) · `quality-on-equipment` (drop participant + `bearer_of some Quality` on equipment, §4) · `drop-participant` (remove; discrimination via ProcessKind, §5.1/§5.2) · `re-anchor-material` (retype to MaterialEntity portion) · `merge-into-X` · **`MANUAL`** (decision deferred to human — disposition left blank).

**IRI note:** `ElectricalPower`=COPI_0000058, `MechanicalPower`=COPI_0000059, `Temperature`=COPI_0000052, `Pressure`=COPI_0000053 are **already declared as `bfo:Quality` in the ELK-protected `copi-vocab` range (025–060)** — for these, the `bearer_of` target already exists; migration only removes the illegal `hasInput` usage, and the protected IRIs must **not** be re-declared.

---

## A.1 Quality-typed fillers (12)

| # | Filler | bfo (cur) | emit | raw | Equipment / process (slot) | §7 target | Disposition | Resulting axiom change | Manual? |
|---|---|---|---|---|---|---|---|---|---|
| 1 | **MechanicalPower** | Quality | 24 | 25 | 14 eqpt: input/output/pump/drive shafts, gear wheel, rotor, valve stem/seat, actuators (solenoid/manual/rotary/diaphragm), gas turbine, diesel engine, hydraulic pump, wellbore — mostly `PowerTransmissionProcess` (in+out) | §4 (`copi:MechanicalPower`, not participant) | quality-on-equipment | drop 24 restrictions; add `<Eqpt> ⊑ bearer_of some COPI_0000059` where power is intrinsic | ⚠️ **empty-sig** for all shaft/gear `PowerTransmissionProcess` (see A.3) |
| 2 | **ElectricalPower** | Quality | 23 | 23 | transmitters (flow/pressure/level/position/conductivity), switches (level/flow), actuators (electric/solenoid/rotary), switchboard, connectors, switch contact, transformer windings — mostly `[in]`, some `[in+out]` | **`ElectricalPower | Q | copi:ElectricalPower (Quality, NOT participant)`** | quality-on-equipment | drop 23; add `bearer_of some COPI_0000058` on equipment needing operating power | ⚠️ **empty-sig**: switchboard, connectors, windings, switch contact, solenoid actuator |
| 3 | **MechanicalForce** | Quality | 7 | 7 | sheave (in+out), load cell (in), wireline (out), hydraulic actuator (out), compensator (in+out) | none | quality-on-equipment | drop 7; add `bearer_of some COPI_0000384` on equipment (curated quality **already declared** 2026-07-11; superseded `auxiliary_class` stub deleted) | ⚠️ **empty-sig**: sheave, compensator |
| 4 | **ACElectricalPower** | Quality | 6 | 6 | power transformer, transformer, ups unit — `ElectricalPowerTransformationProcess`/`UPSProcess` (in+out) | none (cf. §5.1 `AlternatingCurrentPortion`=R) | quality-on-equipment | **reuse `COPI_0000058`** (A.4 decision — no new class); drop 6; add `bearer_of some COPI_0000058` | ⚠️ **empty-sig**: transformers, ups |
| 5 | **MechanicalDisplacement** | Quality | 2 | 2 | axial displacement transmitter (in), DP measuring element (out) | none | MANUAL | *(sensor: displacement is measured → likely `MeasurementICE describes copi:MechanicalDisplacement`, not `bearer_of`)* | ⚠️ **MANUAL** (measured-quality vs equipment-quality) |
| 6 | **MechanicalLoad** | Quality | 1 | 1 | bearing / `SupportingProcess` (in) | none | quality-on-equipment | drop 1; add `Bearing ⊑ bearer_of some COPI_0000385` (curated quality **already declared** 2026-07-11; superseded stub deleted) | — |
| 7 | **PressureField** | Quality | 1 | 1 | pressure element / `PressureSensingProcess` (in) | **`PressureField | Q | copi:Pressure`** | map-§7 | measured quality → `MeasurementICE describes COPI_0000053`; drop 1 | — |
| 8 | **Temperature** | Quality | 1 | 1 | temperature indicator / `TemperatureIndicationProcess` (in) | **`Temperature | Q | copi:Temperature (described by MeasurementICE)`** | map-§7 | measured quality → `describes COPI_0000052`; drop 1 | — |
| 9 | **StructuralForce** | Quality | 1 | 1 | expansion joint / `ThermalExpansionAccommodationProcess` (in) | none | MANUAL | *(thermal-expansion force; candidate `bearer_of` new Quality, or drop→ProcessKind)* | ⚠️ **MANUAL**; ⚠️ **empty-sig** (expansion joint) |
| 10 | **StructuralDisplacement** | Quality | 1 | 1 | expansion joint / `ThermalExpansionAccommodationProcess` (out) | none | MANUAL | *(pairs with #9; expansion joint has only these two)* | ⚠️ **MANUAL**; ⚠️ **empty-sig** (expansion joint) |
| 11 | **WeightOnBit** | Quality | 1 | 1 | bottom hole assembly / `BottomHoleDrillingProcess` (in) | none | MANUAL | *(drilling parameter; BHA also inputs RotationalMotion — see #12 A.2)* | ⚠️ **MANUAL** |
| 12 | **WellborePressure** | Quality | 0 | 1 | lubricator / `LiveWellToolDeploymentProcess` (in) — *not validated/exported* | none | MANUAL | *(0 emitted; migrate on promotion)* | ⚠️ **MANUAL** |

## A.2 Process-typed fillers (13)

| # | Filler | bfo (cur) | emit | raw | Equipment / process (slot) | §7 target | Disposition | Resulting axiom change | Manual? |
|---|---|---|---|---|---|---|---|---|---|
| 13 | **RotationalMotion** | Process | 3 | 3 | gearbox `PowerTransmissionProcess` (in+out), bottom hole assembly `BottomHoleDrillingProcess` (in) | **`RotationalMotion | R | §5.2`** ("motion is host process"; Quality `RotationalSpeed`) | map-§7 → drop-participant | drop 3; ProcessKind carries it; optional `bearer_of copi:RotationalSpeed` | ⚠️ **empty-sig**: gearbox |
| 14 | **ElectricalCurrent** | Process | 5 | 5 | fuse `CurrentInterruptionByFusing` (in+out), anode `ElectrochemicalOxidationProcess` (in+out), cathodic protection system `CathodicProtectionProcess` (in) | none (cf. §5.2 `ElectricalCurrentFlow`) | MANUAL | *(current-as-process; §5.2 suggests Quality `copi:ElectricalCurrent` or ProcessKind — anode/CP electrochemistry may need current as genuine participant-analog)* | ⚠️ **MANUAL**; ⚠️ **empty-sig**: fuse |
| 15 | **MechanicalWork** | Process | 2 | 2 | turbine `EnergyExtractionProcess` (out), pneumatic actuator `ActuationProcess` (out) | none (cf. §5.1 energy-occurrent) | drop-participant | drop 2; ProcessKind `mechanical_power_transmission` carries it | — |
| 16 | **ElectricalCurrentFlow** | Process | 2 | 4 | circuit breaker `ElectricalCurrentInterruptionProcess` (in+out, exported); circuit-breaker `CircuitProtectionProcess` (in+out, proposed) | **`ElectricalCurrentFlow | R | §5.2`** (`copi:ElectricalConversionProcess`) | map-§7 → drop-participant | drop 2; ProcessKind | ⚠️ **empty-sig**: circuit breaker |
| 17 | **KineticMotion** | Process | 1 | 1 | actuator `ActuationProcess` (out) | none (cf. §5.2 motion) | drop-participant | drop 1; ProcessKind | — |
| 18 | **MechanicalMotion** | Process | 1 | 1 | limit switch `PositionLimitDetectionProcess` (in) | **`MechanicalMotion | R | §5.2 (drop; redundant)`** | map-§7 → drop-participant | drop 1 | — |
| 19 | **MechanicalMovement** | Process | 1 | 1 | electric actuator `ActuationProcess` (out) | none (cf. §5.2 motion) | drop-participant | drop 1; ProcessKind | — |
| 20 | **MechanicalRotation** | Process | 1 | 1 | pneumatic motor `PneumaticEnergyConversionProcess` (out) | none (cf. §5.2 motion) | drop-participant | drop 1; ProcessKind | — |
| 21 | **ElectromagneticRadiation** | Process | 1 | 1 | flame detector `FlameDetectionProcess` (in) — *sensed occurrent* | none | MANUAL | *(sensed-event input; options: (a) `MeasurementICE`/ICE input of the sensed medium; (b) re-anchor to a radiant `MaterialEntity` portion; (c) `participatesIn` the combustion — pros/cons in A.4)* | ⚠️ **MANUAL** |
| 22 | **DisturbanceSource** | Process | 1 | 1 | damper `DampingProcess` (in) | none | MANUAL | *(LLM-invented occurrent; likely drop → ProcessKind)* | ⚠️ **MANUAL**; ⚠️ **empty-sig**: damper |
| 23 | **SuppressedDisturbance** | Process | 1 | 1 | damper `DampingProcess` (out) | none | MANUAL | *(pairs with #22; damper has only these two)* | ⚠️ **MANUAL**; ⚠️ **empty-sig**: damper |
| 24 | **PhysicalPhenomenon** | Process | 1 | 1 | detector `DetectionProcess` (in) | none | MANUAL | *(vague LLM artifact; likely drop; the detector's target should be a specific ICE/quality)* | ⚠️ **MANUAL** |
| 25 | **Flame** | Process | 0 | 1 | ignitor `IgnitionProcess` (out) — *not validated/exported* | none | MANUAL | *(a flame is a BFO `MaterialEntity` example, but typed `Process` here; options: re-anchor-material as ignitor output, or drop; 0 emitted)* | ⚠️ **MANUAL** |

## A.3 Empty-signature processes — CLASS-LEVEL analysis (supersedes per-equipment view)

Restrictions accumulate on the **shared** process class across all sharing equipment (e.g. `ActuationProcess` is shared by 8 actuators; `PowerTransmissionProcess` by 8). Emptiness must therefore be judged per class, not per equipment. Recomputed over `validated`+`exported`:

### A.3.1 Truly-empty classes → MERGE into ProcessKind (13) — ⚠️ BLOCKED
All `hasInput`/`hasSpecifiedOutput` are offenders; nothing admissible remains. Intended merge target = the class's `transformation_kind` (ODR-009 ProcessKind). **CONFIRMED 2026-07-11: the per-`transformation_kind` ProcessKind classes DO NOT EXIST** in `copi-vocab`, `copi-core`, or `copi-enriched`. Only the 9 ODR-009 *operation* classes (`COPI_0000001–024`: MomentumTransfer, HeatTransfer, …) exist, and there is **no declared `transformation_kind → operation-class` mapping**. Therefore the merges are **blocked on ODR-009 ProcessKind implementation**; `--enable-merge` refuses to run (script guard). The table below records the intended targets for when ProcessKinds are declared.

| Empty process class | #eqpt | offenders dropped | `transformation_kind` → merge target |
|---|---|---|---|
| `PowerTransmissionProcess` | 8 | MechanicalPower, MechanicalForce, RotationalMotion | `mechanical_power_transmission` |
| `ElectricalPowerTransformationProcess` | 4 | ElectricalPower, ACElectricalPower | `electrical_power_conversion` |
| `ElectricalConductionProcess` | 2 | ElectricalPower | ✅ **RESOLVED via TK_FIX** → `electrical_power_transmission` (see A.3.3; `electrical connection`'s mislabeled tag corrected 2026-07-11). No longer a merge conflict. |
| `CurrentInterruptionByFusing` | 1 | ElectricalCurrent | `electrical_power_conversion` |
| `DampingProcess` | 1 | DisturbanceSource, SuppressedDisturbance | `mechanical_power_transmission` |
| `ElectricalCircuitControlProcess` | 1 | ElectricalPower | `flow_direction_control` |
| `ElectricalConnectionProcess` | 1 | ElectricalPower | `electrical_power_conversion` |
| `ElectricalCurrentInterruptionProcess` | 1 | ElectricalCurrentFlow | `flow_isolation` |
| `ForceTransmissionProcess` | 1 | MechanicalPower | `mechanical_power_transmission` |
| `MovementCompensationProcess` | 1 | MechanicalForce | `mechanical_energy_absorption` |
| `RotationalEnergyTransferProcess` | 1 | MechanicalPower | `mechanical_power_transmission` |
| `ThermalExpansionAccommodationProcess` | 1 | StructuralForce, StructuralDisplacement | `mechanical_force_accommodation` |
| `UninterruptedPowerSupplyProcess` | 1 | ACElectricalPower | `electrical_power_conversion` |

### A.3.2 Exceptions → DO NOT merge (28)
Retain ≥1 admissible participant from some sharing equipment; migration only drops the offender(s). Examples: `ActuationProcess` (keeps ControlSignal/ElectricalSignal/HydraulicFluidPortion), `EnergyExtractionProcess` (keeps FluidPortion), `FlameDetectionProcess`/`DetectionProcess`/`PositionLimitDetectionProcess` (keep ElectricalSignal), `MechanicalEnergyGenerationProcess`/`TurbomachineryPowerGenerationProcess` (keep fuel/air/exhaust portions), all the transmitter/switch measurement processes (keep signal ICE), `SupportingProcess` (keeps MechanicalSupport), `HydraulicPumpingProcess` (keeps HydraulicFluid), `CathodicProtectionProcess`/`ElectrochemicalOxidationProcess` (keep MetallicStructure/CorrosionProducts), `BottomHoleDrillingProcess` (keeps DrillingFluidPortion/RockCuttings/Wellbore). Full list generated by the script's `--report` mode.

> ⚠️ **Scope-gap flag:** several A.3.2 "kept" participants are themselves ODR-010-inadmissible but **outside the 25-filler scope** (they are `FiatObjectPart`/ICE-typed → satisfiable, so not in the 62-unsat set): `EnergyPortion`, `ThermalEnergyPortion`, `MechanicalEnergyPortion` (§5.1 R), `InformationBearingArtifact` (§6 → ICE), `ProcessVariable` (§6/§7), and part-fillers like `LocalTemperatureDisplay` (§5.3). This migration does **not** touch them; closing ODR-010 fully needs a follow-up pass (noted in ODR-020 Consequences → Scope boundary).

### A.3.3 `ElectricalConductionProcess` merge conflict — HUMAN DECISION REQUIRED (not decided)

The class is shared by 2 equipment whose `transformation_kind` disagree, so it cannot be auto-merged to one ProcessKind. Both signatures are pure `ElectricalPower`→`ElectricalPower` conduction:

| Equipment | transformation_kind | inputs → outputs | rationale (verbatim, abridged) |
|---|---|---|---|
| **switch contact** | `electrical_power_transmission` | ElectricalPower ("incoming electrical current") → ElectricalPower ("conducted electrical current") | "pure conduction — maintaining electrical continuity with minimal loss." |
| **electrical connection** | `electrical_power_conversion` | ElectricalPower ("from source apparatus") → ElectricalPower ("to destination apparatus") | "pure electrical conduction … **conduction rather than conversion**, distinguishing it from transformers, motors …" |

**RESOLVED (human decision, 2026-07-11): Option (1).** The `electrical connection` rationale explicitly says "conduction rather than conversion," so its `electrical_power_conversion` tag was an LLM mislabel. Its `transformation_kind` is corrected to **`electrical_power_transmission`** (matching its sibling `switch contact`), so both equipment of `ElectricalConductionProcess` agree and the class is no longer a merge conflict. Implemented in the migration script as `TK_FIX = {"electrical connection": "electrical_power_transmission"}` (applied at `--commit`, with snapshot + `fol_stale`); `ElectricalConductionProcess` moved from `MERGE_CONFLICTS` into `PROCESSKIND_MAP` (→ `electrical_power_transmission`). Merge candidates: 12 → **13**, conflicts skipped: **0**. *(The merge still cannot execute until the ProcessKind classes exist — A.3.1.)* Both dropped `ElectricalPower` participants remain handled (drop + `bearer_of some :COPI_0000058`).

*Options considered but not taken: (2) keep both, don't merge; (3) invent a single `ElectricalConduction` ProcessKind distinct from both tags.*

---

## A.4 Manual-review items — FINALIZED (human decisions, 2026-07-10)

| Filler | Decision | Resulting axiom change |
|---|---|---|
| **ElectricalCurrent** (#14) | **drop participant; `bearer_of` curated Quality on equipment** (ODR-010 §5.2, current-as-Quality) | drop 5 `hasInput/Output` restrictions; add `custom_axioms` `bearer_of some :COPI_0000383` on fuse/anode/cathodic-protection-system. The legacy `Process`-typed `auxiliary_class.ElectricalCurrent` stub is **DELETED** (not retyped), superseded by the **already-declared** `copi-vocab` quality **`COPI_0000383 ElectricalCurrent`** (main doc, "Prerequisite completed (2026-07-11)"). No new declaration needed. |
| **ElectromagneticRadiation** (#21) | **drop participant; ProcessKind carries semantics** | drop 1 `hasInput` on `FlameDetectionProcess` (class retains `ElectricalSignal` → NOT empty). |
| **DisturbanceSource** (#22), **SuppressedDisturbance** (#23), **PhysicalPhenomenon** (#24) | **drop** | drop the restriction; `DampingProcess` becomes empty → A.3.1 merge; `DetectionProcess` retains `ElectricalSignal` → NOT empty. |
| **Flame** (#25) | **DEFERRED — blocked ontological decision** (must be resolved before `ignitor` is promoted to `validated`) | Retype **not performed**: `'MaterialEntity'` is not in the `auxiliary_class.bfo_category` CHECK enum, and the correct concrete BFO category for a flame is genuinely contested (a flame is a process-like object; cf. Galton & Mizoguchi 2009, *Applied Ontology*) — see debt-(g). Flame stays `Process`-typed and is **kept** (undropped) on `IgnitionProcess`; 0 emitted today (ignitor not validated/exported), so no output impact now. |
| **MechanicalDisplacement** (#5), **WeightOnBit** (#11), **WellborePressure** (#12) | **drop participant; measurement semantics via MeasurementICE `describes`** | drop the `hasInput/Output`; the measured quantity is carried by the sensor's `MeasurementICE describes some <Quality>` (existing sensor pattern, not a process participant). |
| **StructuralForce** (#9), **StructuralDisplacement** (#10) | **drop; optional `bearer_of` Quality on expansion joint** | drop both from `ThermalExpansionAccommodationProcess` (→ A.3.1 merge, `mechanical_force_accommodation`); optionally add `custom_axioms` `bearer_of some :StructuralForce`/`:StructuralDisplacement` on `expansion joint` (new Quality classes; **optional**, default OFF in script). |
| **ACElectricalPower** (#4) | **reuse `COPI_0000058` (ElectricalPower); do NOT mint new class** | drop 6 restrictions; add `custom_axioms` `bearer_of some :ElectricalPower` on power transformer/transformer/ups; `ElectricalPowerTransformationProcess`/`UninterruptedPowerSupplyProcess` → A.3.1 merge. |

Remaining Quality dispositions from A.1 (already unambiguous): `ElectricalPower`(#2), `MechanicalPower`(#1), `MechanicalForce`(#3), `MechanicalLoad`(#6) → drop participant + `bearer_of` on equipment (existing `COPI_0000058`/`COPI_0000059` for the first two; the curated `COPI_0000384`/`COPI_0000385` — **already declared** 2026-07-11, stubs deleted — for the latter two). `PressureField`(#7)→`describes :Pressure` (COPI_0000053); `Temperature`(#8)→`describes :Temperature` (COPI_0000052). Process/motion fillers (#13,15–20) → drop; ProcessKind (ODR-009) carries discrimination.

**Bearer-of target Qualities — status (prerequisite completed 2026-07-11).** The three curated qualities are **already declared** in `copi-vocab` (see main doc): **`COPI_0000383 ElectricalCurrent`**, **`COPI_0000384 MechanicalForce`**, **`COPI_0000385 MechanicalLoad`** — each with full house-style annotations (`⊑ bfo:BFO_0000019`, `iof-av:naturalLanguageDefinition`) and `copi-iri-map.tsv` rows in both repo copies. The migration's `bearer_of` axioms reference them by **numeric IRI**, and the three superseded `auxiliary_class` stubs are deleted by the script. `ElectricalPower`/`MechanicalPower` reuse the existing `COPI_0000058`/`COPI_0000059`. `:StructuralForce` / `:StructuralDisplacement` (A.4 #9/#10) are **optional and default-OFF**: the script emits no `bearer_of` for them, so **no declaration is required by this migration** — they would need one only if the optional flag is later enabled (deferred). No further vocab/TTL work is a prerequisite for the migration as configured.

---

## A.5 Impact appendix (Task 3)

### Collateral references (grep across this repo + `../copi`, excl. `.venv`/`.git`/`prompts_backup`/ODR-010/scratchpad)
Files referencing the 25 filler names and/or `*EnergyPortion` (by hit count):

| File | Hits | Nature / action |
|---|---|---|
| `../copi/copi.{ttl,owl}`, `copi-simple.{ttl,owl}`, `copi-full.{ttl,owl}`, `copi-base.{ttl,owl}` | 69 each | **Published release artifacts** — carry the names as `firstOrderLogicAxiom` text + the ODR-010 §4 Quality declarations. Regenerate on next release; FOL text is `FOL_STALE` (ODR-020 §5). |
| `../copi/src/ontology/components/copi-enriched.owl` | 49 | Same — regenerated by `regen_enriched_owl.py`. |
| `validation/terms/*.md` (77 files; circuit-breaker 21, power-transformer 17, limit-switch 6, gearbox 5, …) | — | Per-term validation reports; **become stale** after migration. Docs — update or annotate, non-blocking. |
| `scripts/bulk_classify_aux.py` (18), `scripts/fix_aux_class_signatures.py` (16) | — | **Prior aux-class migration scripts.** Review/reconcile before writing new migration code — do not duplicate. |
| `enrichment/prompts.py` | 2 | Gate A — still lists `ElectricalPower`/`MechanicalPower` as established types (L338–339). Update to close ODR-010. |
| `enrichment/ontologies/copi-context/copi-iri-map.tsv` + `../copi/src/ontology/copi-iri-map.tsv` | 5 each | `ElectricalPower`→COPI_0000058, `MechanicalPower`→COPI_0000059, `Temperature`→COPI_0000052, `Pressure`→COPI_0000053 (protected vocab range). Surviving new Qualities need entries here. |
| `enrichment/ontologies/copi-context/copi-vocab.ttl` | 2 | Quality declarations for the mapped IRIs. |
| `enrichment/output/copi-merged.ttl` | 4 | Generated artifact; regenerates. |
| `scripts/regen_enriched_owl.py` | 2 | The strip step to be retired (ODR-020 §6). |
| `CLAUDE.md` | 2 | Prose describing the strip — delete on §6 completion. |

**Ontop / VKG:** no `.obda` files exist in either repo; **the `vkg-ontop` stack does not reference these fillers** — no mapping impact.

### Competency-question impact
ORSD (`../copi/requirements/orsd.md`) defines **8 CQs (CQ-01…CQ-08)**. The SWJ paper's reported "6 verified CQs" subset **could not be confirmed in-tree** (no SWJ manuscript source, no per-CQ query set; `copi/requirements/cqs.csv` is a 1-row stub) — see ODR-020 → Backward Compatibility for what is needed to reconcile. **None of CQ-01…CQ-08 query process-level `hasInput`/`hasSpecifiedOutput`.** Closest is **CQ-06** ("topological connections (inlet/outlet) between this equipment and other material entities"), which uses equipment-to-equipment *connection* relations, not the process participant restrictions being migrated → **no expected result change**; re-run CQ-06 against the migrated endpoint post-release to confirm.

### Guard impact (`../copi/src/sparql/guards/`, 12 guards)
- **`guard-01-no-unsat`** — materially affected, **positively**: migration removes the unsat cause, so it passes on the *un-stripped* output (today it passes only because the strip hides the 62 unsat classes).
- **`guard-11-chain-participates-in`** — tests `hasFunction ∘ BFO_0000054 ⊑ copi:participatesIn` against a dedicated test ABox; does **not** reference `hasInput`/`hasSpecifiedOutput` → **unaffected**.
- Guards 02–10, 12 — valve/instrument/operation-anchor TBox checks; unrelated to process I/O.

### ODR-015 Phase 1 vs. Gates C/D (accuracy for Context)
ODR-015 (Accepted 2026-06-15) Phase 1 delivered **only** the release-architecture split (`copi-core`/`copi-vocab`/`copi-enriched`, `copi-base.ttl` dissolution). The COPIeditor generation + ODR-010 participant rewrite was **explicitly deferred to Phase 2** (still deferred). Verified gate status today:
- **Gate A (prompt):** not done — `prompts.py:335–346` still uses the abandoned 7 established types.
- **Gate C (`participant_anchoring.py`):** never built (file absent, no `REVIEW_REQUIRED` logic).
- **Gate D (validator):** partial — `verify_service.py:90 check_undeclared_classes` exists but does not enforce ODR-010 §8 admissibility categories.

This confirms ODR-020's premise: the migration ODR-010 specified was never executed; the deployed ontology is protected only by the unversioned-in-effect strip, and the DB still holds the full legacy (v0.x) filler set.
