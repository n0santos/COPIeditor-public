# ODR-020 — Completion of ODR-010 Migration for Legacy `auto_signature` Fillers

**Status:** Accepted (2026-07-12)
**Date:** 2026-07-10 (proposed); 2026-07-12 (accepted)
**Deciders:** Nicolau Santos; [advisor/team as applicable]
**Related:** refines/completes ODR-010 (participant-type anchoring); depends on ODR-009 (ProcessKind taxonomy) and ODR-015 (release architecture, Phase 2 deferral).

---

## Context

ODR-010 (Accepted, 2026-05-29) established participant-type anchoring for Step 5 process signatures: `iof-core:hasInput` / `iof-core:hasSpecifiedOutput` fillers are admissible only as **MaterialEntity** (the `PortionOfFluid` hierarchy) or **InformationContentEntity** (ICE / MeasurementICE). Energy-as-portion, process-typed, quality-typed, and equipment-part fillers are inadmissible (ODR-010 §5).

ODR-010's implementation depended on three pipeline gates: **Gate A** (update the Step 5 prompt vocabulary), **Gate C** (`participant_anchoring.py`, a deterministic rewrite module consuming the §7 mapping), and **Gate D** (extend the structural validator to enforce admissibility). Verification of the current tree shows **none of the three was completed**:

- **Gate A — not done.** `enrichment/prompts.py:335–346` still advertises the abandoned seven "established types," explicitly listing `ElectricalPower` and `MechanicalPower` as participant types and still permitting ad-hoc `new_participant_type_definitions`.
- **Gate C — never built.** No `enrichment/participant_anchoring.py` exists; no `REVIEW_REQUIRED` rewrite logic is present.
- **Gate D — partial.** `enrichment/verify_service.py:90 check_undeclared_classes` exists (it scans for undeclared COPI IRIs) but does **not** assert the ODR-010 §8 admissibility categories.

This is consistent with ODR-015, whose Phase 1 (2026-06-15) delivered only the release-architecture split (`copi-core` / `copi-vocab` / `copi-enriched`); the COPIeditor generation work that would have carried ODR-010's rewrite was explicitly **deferred to Phase 2** (ODR-015 §"Phase 2 — scope and triggers (deferred)"). ODR-015 §"Readiness already in place" notes the generated `copi-enriched` "inherits" ODR-010 process outputs, but no data-level migration of the pre-existing enrichments was performed.

As a result, the enrichment database retains **25 legacy `auto_signature` fillers** in inadmissible categories — **13 `Process`-typed** and **12 `Quality`-typed** — every one `status = validated`, `source = auto_signature`, and carrying **no `label` or `definition`** (bare BFO-typed stubs). In the deployed-relevant set (`status IN ('validated','exported')`, the same filter `generate_combined_turtle()` uses), these fillers produce **88 `hasInput`/`hasSpecifiedOutput` OWL restrictions across 59 distinct equipment classes**. (Two of the 25 — `Flame`, `WellborePressure` — appear only on non-validated entries and emit zero restrictions today. `WellborePressure` is dropped-on-promotion; `Flame`'s retype is **deferred** as a blocked ontological decision — see debt-(g).)

Reasoning over the un-stripped combined TTL (`validated + exported`) yields **62 unsatisfiable classes** — the 59 equipment cascading to their identity functions (`∃realizedIn`) and process classes (`∃hasFunction`). (Note the earlier audit figure "~70+ usages" mixed statuses; the precise deployed-relevant figures are 88 restrictions / 59 equipment / 62 unsat classes. The `build_consequence_graph()` view reports fewer *disjointness* violations because it surfaces only unsat classes that also participate in a `disjointWith` axiom.)

The deployed ontology is currently satisfiable **only** because an export-time strip step — `scripts/regen_enriched_owl.py` (tracked in git since commit `22ec77d`) — removes the offending restrictions before publication. The validation path (`generate_combined_turtle()` → reasoner) does **not** strip, producing the persistent "62 unsat / N violations" the editor's Validate tab reports. This ODR replaces the strip with **data-level migration**, so the validation path and the export path reason over the same admissible axiom set and the strip becomes unnecessary.

## Source Definitions

Verbatim from **ODR-010 — Participant Type Anchoring** (Accepted 2026-05-29):

**§4 Quality vocabulary** — "These are **not** Step 5 participants. They are vocabulary needed by `copi-base.ttl` for the `describes` axioms in §3 and for axiomatizing equipment qualities outside Step 5 (e.g., a pump's rated power as `bearer_of some ElectricalPower`)." Declares `copi:ElectricalPower`, `copi:MechanicalPower`, `copi:Temperature`, `copi:Pressure`, etc. `⊑ bfo:BFO_0000019` (Quality).

**§5.1 Energy as portion of matter** — "Patterns `XEnergyPortion` and `XCurrentPortion` (`EnergyPortion`, `ThermalEnergyPortion`, `MechanicalEnergyPortion`, `ElectricalEnergyPortion`, `AlternatingCurrentPortion`) are ontologically incorrect: energy is not `bfo:MaterialEntity`." Rewrite: remove the participant; discrimination "is carried by the ProcessKind (ODR-009 §3), not by an energy-as-portion participant"; the equipment's demand is "`bearer_of some copi:ElectricalPower` (Quality, axiomatized on the Equipment class, not on the Process)."

**§5.2 Process-typed participants** — "Patterns naming processes (`ElectricalCurrentFlow`, `RotationalMotion`, `MechanicalMotion`) violate the range of `iof-core:hasInput` (`bfo:Continuant`) under BFO 2020, where Continuant and Occurrent are disjoint." Rewrite: `ElectricalCurrentFlow` → ProcessKind `⊑ copi:ElectricalConversionProcess` (or Quality `copi:ElectricalCurrent`); `RotationalMotion` → "the motion is the host process itself" (or Quality `copi:RotationalSpeed`); `MechanicalMotion` → "Redundant … drop."

**§7 Mapping of legacy participant types** — rows directly naming our fillers:
- `ElectricalPower | Q | copi:ElectricalPower (Quality of equipment, NOT participant)`
- `Temperature | Q | copi:Temperature (described by MeasurementICE, NOT participant)`
- `PressureField | Q | copi:Pressure`
- `ElectricalCurrentFlow | R | rewrite per §5.2`
- `RotationalMotion | R | rewrite per §5.2`
- `MechanicalMotion | R | rewrite per §5.2 (drop; redundant)`
- `EnergyPortion / ThermalEnergyPortion / MechanicalEnergyPortion / ElectricalEnergyPortion | R | rewrite per §5.1`

**§9 Treatment of legacy enrichments** — "categories R and Q require human review (energy patterns and Quality-as-participant cases are not auto-rewritten)."

Supporting: **ODR-009 (revised) — Ontological rooting of the operation classes** (Accepted): establishes the ProcessKind / `transformation_kind` taxonomy that carries process discrimination once participant fillers are removed. **BFO 2020**: `bfo:BFO_0000019 Quality` and `bfo:BFO_0000015 Process` are `SpecificallyDependentContinuant` / `Occurrent` respectively, both disjoint with the `bfo:Continuant` range of `hasInput`/`hasSpecifiedOutput`.

## Decision

1. **Migrate all 25 legacy fillers** per the disposition table (Appendix A), applying ODR-010 §7 canonical mappings where a row names the filler.

2. **Fillers without a §7 row** receive per-entry manual disposition under ODR-010 §9, recorded in Appendix A with rationale. Quality fillers default to *drop-participant + `bearer_of` Quality on the equipment class* (§4); process/motion fillers default to *drop-participant + rely on ProcessKind* (§5.1/§5.2), **subject to the manual-review flags in Appendix A**.

3. **Discrimination lost by participant removal is carried by** (a) ProcessKind subsumption (ODR-009 via `transformation_kind`), and (b) `bearer_of some <Quality>` axioms on the **equipment** class wherever the signature encoded a power/force/load characteristic.

4. **Empty-signature processes.** Analysis at the **process-class** level (restrictions accumulate on the shared class across all sharing equipment, not per equipment) finds **13 process classes** that lose *all* `hasInput`/`hasSpecifiedOutput` after migration, and **28 "exception" classes** that retain at least one admissible (Material/ICE) participant contributed by some sharing equipment and therefore **must not be merged** (Appendix A.3). The 13 truly-empty classes are **merged into their ProcessKind** (per `transformation_kind`, ODR-009), except where a ProcessKind target is unresolved or conflicting (Appendix A.3 flags `ElectricalConductionProcess`, whose two equipment carry divergent `transformation_kind`). The per-equipment "25 empties" figure in earlier drafts was computed before accounting for class-level sharing and is superseded.

5. **The `firstOrderLogicAxiom` / `semiFormalNaturalLanguageAxiom` annotations are stored per-entry** (DB columns `fol_axiom` / `semiformal_axiom`, emitted verbatim by the TTL serializer and OFN export) — they are **not** regenerated from `process_signature`. Removing/re-typing a filler therefore will **not** update the NL/logic text, causing silent drift. **Decision: FOL/semiformal annotations that reference a removed participant are flagged `FOL_STALE` for regeneration or manual review before the next release** (automatic regeneration is out of scope until Phase 2 wires a signature→FOL generator; today the text is LLM-authored and stored).

   **Suppression (amendment).** Until the regeneration pass (debt-(c)) clears the flag, any entry carrying a `fol_stale` divergence flag has **both** its `firstOrderLogicAxiom` **and** `semiFormalNaturalLanguageAxiom` annotations **excluded from emission on both release paths** — the TTL serializer (`enrichment_service.py`, `generate_turtle`, ~L2488–2492) and the OWL-Functional-Syntax export (`generate_owl_functional`, ~L3788–3791). Both guards call a single helper, `_fol_annotations_suppressed(e)`. **Rationale: in a released artifact an *absent* annotation is safer than a *provably-false* one** that still names a migrated-away participant. The suppression is a pure emission-time guard; it does not alter the stored text (which the FOL regeneration pass will rewrite before the flag is cleared).

6. **Retire the export strip.** Once migration is complete and the `validated + exported` combined TTL reasons to zero unsat classes, `scripts/regen_enriched_owl.py`'s participant-stripping step is removed, and the CLAUDE.md prose describing it is deleted. The validation path and export path then reason over one identical axiom set.

   **Status: PARTIALLY FULFILLED (2026-07-12, at execution gate 5).** Reasoning the *un-stripped* migrated artifact surfaced **3 unsatisfiable classes** — `VisualInspectionFunction`, `COPI_0000085` (SightGlass), `COPI_0000130` (LevelSightGlass) — rooted in `hasSpecifiedOutput some InformationBearingArtifact` (IBA is typed `bfo:Object` ⊑ IndependentContinuant, while `VisualInspectionFunction ⊑ COPI_0000029` forces a `MeasurementProcess` whose outputs are `MeasurementICE`-only, a GenericallyDependentContinuant → IC⊓GDC disjointness). This is an **ODR-021** residual (`InformationBearingArtifact` §6 → ICE), *not* one of the 25. The blunt strip of all `hasInput`/`hasSpecifiedOutput` was therefore **narrowed to a scoped IBA quarantine** (501 → **9** restrictions); the **492** admissible Material/ICE participant restrictions now ship un-stripped, and the artifact reasons to **0 unsat** (HermiT, guard-01 pass). **Full retirement of the strip is blocked on ODR-021** (re-typing IBA → ICE); until then the 9-restriction quarantine remains in `remove_process_io_restrictions`.

## Rationale

**Why realign to ODR-010 rather than supersede it.** ODR-010 is Accepted and its core claim is ontologically sound: energy, motion, force, and power are not `bfo:Continuant` and cannot be `hasInput`/`hasSpecifiedOutput` fillers under BFO 2020. Reifying them as continuant "energy portions" (the alternative considered) is exactly the `*EnergyPortion` pattern ODR-010 §5.1 rejects by name. Governance flows ODR → data, not data → ODR: the correct fix is to finish the migration the accepted decision already specifies, not to overturn it to legalize the legacy data.

**Why discrimination survives removal.** The pseudo-participants provided *zero* discrimination to begin with. Reasoned un-stripped, all **62 affected classes were equivalent to `owl:Nothing`** (unsatisfiable) — and every class equivalent to `owl:Nothing` is equivalent to every *other* such class, so the 62 were mutually equivalent: an inconsistent class distinguishes nothing from anything. Removing an axiom set that collapses every bearer to the empty class therefore **cannot lose discriminative content, because there was none to lose**; migration moves each class from `owl:Nothing`-equivalence to a satisfiable identity (its genus + identity-giving function) plus its `transformation_kind`. The discriminative work these pseudo-participants *appeared* to do is instead carried by the ProcessKind taxonomy (ODR-009): a shaft's `PowerTransmissionProcess`, a transformer's `ElectricalPowerTransformationProcess`, and a pump's `PressureIncrease` are distinct ProcessKinds independent of any energy participant — **with the caveat that those ProcessKind classes are not yet declared (debt-(e)); until they are, discrimination rests on class identity and the stored `transformation_kind` value.** Power/force characteristics that are genuinely properties of the equipment move to `bearer_of some Quality` on the equipment class, where they belong.

**Why a single axiom set matters.** The current strip produces a *validate-vs-publish divergence*: the editor perpetually reports 62 unsat while the shipped ontology is clean, so the Validate tab cannot be trusted and the strip is an unversioned single point of failure gating every release. Migrating at the data level collapses the two views, makes `guard-01-no-unsat` pass on the un-stripped output, and removes the strip as a release dependency.

**Why FOL is flagged, not regenerated.** The FOL/semiformal text is human-readable LLM output stored per entry, not a projection of the signature fields. Silent regeneration risks fabricating axioms that no longer match the (now-migrated) formal restrictions; flagging `FOL_STALE` keeps a human in the loop until a signature→FOL generator exists (Phase 2).

## Consequences

**Required content additions.**
- Confirm/declare the Quality vocabulary ODR-010 §4 assumes: `copi:ElectricalPower`, `copi:MechanicalPower`, `copi:Temperature`, `copi:Pressure` (present in ODR-010 §4); **new Qualities likely needed**: `copi:MechanicalForce`, `copi:MechanicalLoad`, `copi:MechanicalDisplacement`, `copi:StructuralForce`, `copi:StructuralDisplacement`, `copi:ACElectricalPower`(or reuse `ElectricalPower`), `copi:WeightOnBit`, `copi:WellborePressure`, and (if kept) `copi:RotationalSpeed`, `copi:ElectricalCurrent` — see Appendix A per-row.
- `copi-iri-map.tsv` entries for any surviving/renamed classes (offender and portion names already have 5 mapped rows there; new Qualities need entries to receive numeric IRIs).
- Annotation completion (`iof-av:naturalLanguageDefinition`, labels) for any class that survives — the current portion/quality stubs have none, which itself violates ODR-010's annotation requirement.

**Code changes.**
- `auxiliary_class`: `UPDATE`s (retype/retire) per Appendix A. *(Data change — a separate, reviewed session; NOT this task.)*
- Both emitter paths must be kept consistent: TTL serializer `enrichment_service.py` ~L2383–2401, and OWL-Functional-Syntax export ~L3720–3777.
- `fol_axiom` / `semiformal_axiom` handling: add the `FOL_STALE` flag pass (Decision §5).
- `scripts/regen_enriched_owl.py`: remove the participant-strip step (Decision §6); delete the corresponding CLAUDE.md prose.
- **Gate A (in scope for this effort):** update `enrichment/prompts.py:332–347` so future enrichments cannot emit Process/Quality/energy-portion participants (draft diff: `migration/odr020_gateA_prompts.diff`). **Gates C (`participant_anchoring.py`) and D (`verify_service.py` admissibility enforcement) are deferred to a follow-up.**
- `bearer_of` axioms are stored as `custom_axioms` JSON entries (`{"turtle": "rdfs:subClassOf [ owl:onProperty bfo:BFO_0000196 ; owl:someValuesFrom :<Quality> ]"}`) on the **equipment** row — emitted verbatim at `enrichment_service.py:2519–2522`. The `qualities` column (an alternative, per-equipment-inhering-quality mechanism) is **empty across the entire DB** and is not used.
- Prior partial-migration scripts exist and should be reviewed/reconciled, not duplicated: `scripts/bulk_classify_aux.py`, `scripts/fix_aux_class_signatures.py`.

**Scope boundary (residual ODR-010 gap).** This migration removes the **25 unsat-causing** Process/Quality fillers. It does **not** address other ODR-010-inadmissible fillers that are `FiatObjectPart`/ICE-typed and therefore *satisfiable* (no reasoner violation) but still rejected by ODR-010 §5.1/§5.3/§6 — notably the energy-as-portion family (`EnergyPortion`, `ThermalEnergyPortion`, `MechanicalEnergyPortion`, `ElectricalEnergyPortion`), `InformationBearingArtifact` (§6 → ICE), `ProcessVariable` (§6/§7 → Quality/normalize), and part-fillers (§5.3). These survive migration on several *exception* processes (Appendix A.3) and require a **follow-up pass** to fully close ODR-010. The post-migration verifier reports both: the 25-filler count (must reach 0) and the residual inadmissible-filler count (expected > 0, currently **29**).

**Prerequisite completed (2026-07-11).** The three new curated Quality classes required as `bearer_of` targets are now declared in `copi-vocab` — `COPI_0000383 ElectricalCurrent`, `COPI_0000384 MechanicalForce`, `COPI_0000385 MechanicalLoad` (full house-style annotations mirroring `COPI_0000058`), with `copi-iri-map.tsv` rows in both repo copies. `ElectricalPower`/`MechanicalPower` reuse existing `COPI_0000058`/`COPI_0000059`; `RotationalSpeed` already exists at `COPI_0000060`. Because the vocab range 025–065 is full, these took the next free numbers (383–385); the migration's `bearer_of` axioms reference the **numeric** vocab IRI directly (`:COPI_00000NN`), so no readable-name stub is created, nothing duplicates into `copi-enriched`, and **no `regen_enriched_owl.py` strip-range change is needed.** The superseded `auxiliary_class` stubs (`ElectricalCurrent`/`MechanicalForce`/`MechanicalLoad`) are deleted by the migration.

### Deferred work (debt register)

- **(a) ODR-021 — residual inadmissible fillers.** The 29 satisfiable-but-inadmissible fillers still in signatures (energy-portion family, `InformationBearingArtifact`, `ProcessVariable`, part-fillers per §5.1/§5.3/§6) are **out of scope here** and become the scope of a follow-up **ODR-021**. **Priority raised (2026-07-12):** `InformationBearingArtifact` is now the **sole blocker of full validate-vs-publish collapse** — it is the only residual that is actually *unsatisfiable* under the un-stripped artifact (3 unsat, see Decision §6 status), so it alone keeps the (now 9-restriction) strip alive. Precise spec for ODR-021, from `robot explain`: `VisualInspectionProcess ⊑ hasSpecifiedOutput some InformationBearingArtifact`; `InformationBearingArtifact ⊑ bfo:Object ⊑ MaterialEntity ⊑ IndependentContinuant`; but `VisualInspectionFunction ⊑ COPI_0000029 ⊑ hasRealization some MeasurementProcess ⊑ hasSpecifiedOutput only MeasurementICE (⊑ GenericallyDependentContinuant)` → IC ⊓ GDC = ∅. **Candidate fixes (ODR-021 design questions — do NOT hotfix in ODR-020):** (i) re-type/remodel the IBA output as a `MeasurementInformationContentEntity` (ICE); or (ii) reclassify `VisualInspectionFunction` out of the instrumentation-function genus (a sight glass arguably outputs *no* ICE at all — the observer does the informational work). Resolving either removes the last strip dependency and lets Decision §6 complete.
- **(b) MeasurementICE `describes` rewiring.** For the measurement-route qualities (`Temperature`, `PressureField`, `MechanicalDisplacement`, `WeightOnBit`, `WellborePressure`) this migration only **drops** the participant; wiring the measured quantity as `MeasurementInformationContentEntity describes some <Quality>` on the sensor is a separate modelling change (ODR-010 §3), not performed by the script.
- **(c) FOL regeneration pass.** Every touched entry is marked `fol_stale`; the stored `fol_axiom` / `semiformal_axiom` text still references removed participants. A dedicated regeneration/review pass (Phase 2 signature→FOL generator, or manual) must clear the `fol_stale` markers before the text is trusted.
- **(d) Gates C & D.** ODR-010's rewrite module (`participant_anchoring.py`, Gate C) and the admissibility enforcement in `verify_service.py` (Gate D) remain unbuilt; only Gate A (prompt) is fixed here.
- **(e) ProcessKind classes (blocks the merges).** The per-`transformation_kind` ProcessKind classes required to merge the 13 empty processes **do not exist** in any artifact (see Appendix A.3.1); the merges are blocked on ODR-009 ProcessKind implementation.
- **(f) Rationale-vs-`transformation_kind` consistency audit.** The TK_FIX precedent (Appendix A.3.3: `electrical connection` was tagged `electrical_power_conversion` while its own rationale said "conduction rather than conversion") shows LLM-authored `transformation_kind` values can contradict their own prose. A one-off audit across **all** enrichment entries — comparing each stored `transformation_kind` against its signature/rationale text — should run to catch further mislabels **before** the ProcessKind merges (debt-(e)) come to rely on those tags. Out of scope for this migration.
- **(g) Ontological status of `Flame` (blocked decision).** The `Flame` `auxiliary_class` retype (A.4 #25) is **deferred** (human decision 2026-07-12): the intended target `'MaterialEntity'` is not an admissible `bfo_category` CHECK-enum value, and the correct *concrete* BFO category for a flame is a genuinely contested question — a flame is a process-like object (cf. Galton & Mizoguchi 2009, *Applied Ontology*). Candidate analyses: gas-portion-qua-participant; remodel the flame as a `CombustionProcess` output; or an `initiates some CombustionProcess` pattern. `Flame` emits 0 restrictions today (ignitor is `proposed`), so this blocks nothing now, but **must be resolved before `ignitor` is promoted to `validated`** (at which point a `Process`-typed output would be inadmissible).

**Constraints.**
- ELK-protected IRI ranges (COPI_0000001–0000060, base-module declared) must not be re-declared; new Qualities take enriched-range or vocab IRIs per `copi-iri-map.tsv`.
- No re-declaration of `copi-core`/`copi-vocab` vocab IRIs (BFO disjointness / conflicting axioms under ELK).

**Backward compatibility.**
- The deployed `copi.owl` currently carries the legacy restrictions in stripped-away form; the migrated axiom set replaces them at the next release. The 77-enrichment v0.x baseline (ODR-009 §6 / ODR-010 §9) is retained for the thesis/FOIS divergence analysis.
- Competency-question impact: the ORSD (`../copi/requirements/orsd.md`) defines **8 CQs, CQ-01…CQ-08**. The SWJ paper is understood to verify a **subset of 6** of these against the live endpoint, but **that subset cannot be confirmed from the repository tree**: `copi/requirements/cqs.csv` holds a single unrelated row ("What is a valve?"), the SWJ manuscript source is not present under `submission/` (nor elsewhere in-tree), and there is no per-CQ SPARQL/verification artifact. *To confirm which 6, the SWJ paper's evaluation section (or its CQ query set) must be added to the tree and reconciled against CQ-01…CQ-08.* Regardless of the subset, **the no-regression claim is asserted against the full 8: none of CQ-01…CQ-08 query process-level `hasInput`/`hasSpecifiedOutput`.** The closest, **CQ-06** ("topological connections (inlet/outlet) between this equipment and other material entities"), operates on equipment-to-equipment connection relations, not the process participant restrictions being migrated — no result change is expected, but **CQ-06 must be re-run against the migrated endpoint post-release** to confirm.
- Guard impact: **`guard-01-no-unsat`** is the guard materially affected — positively: migration removes the unsat cause so it passes on the un-stripped output. `guard-11-chain-participates-in` tests the `hasFunction ∘ realizedIn ⊑ participatesIn` chain against a dedicated test ABox and does **not** reference `hasInput`/`hasSpecifiedOutput`; it is unaffected.

**Rollback.** The migration script has **no `--rollback` flag**; its only automatic safety is a transaction `conn.rollback()` if an exception is raised *during* `--commit`. Recovery after a committed run is therefore:
1. **Enrichment-row changes** (the 59 `process_signature` / `custom_axioms` / `divergence_flags` edits) are reversible from `enrichment_history`: each `--commit` writes a pre-state snapshot with `trigger = 'odr020_migration'` (keys `process_signature`, `custom_axioms`, `divergence_flags`). Manual restore (one snapshot row per id for a single committed run):
   ```sql
   UPDATE enrichment SET
     process_signature = json_extract(s.snapshot_json, '$.process_signature'),
     custom_axioms     = json_extract(s.snapshot_json, '$.custom_axioms'),
     divergence_flags  = json_extract(s.snapshot_json, '$.divergence_flags')
   FROM (SELECT enrichment_id, snapshot_json FROM enrichment_history
         WHERE trigger = 'odr020_migration') AS s
   WHERE enrichment.id = s.enrichment_id;
   ```
2. **`auxiliary_class` changes are NOT snapshotted** in `enrichment_history` — the three stub `DELETE`s (`ElectricalCurrent` / `MechanicalForce` / `MechanicalLoad`) and the `Flame` `Process → MaterialEntity` retype are recoverable **only from an external pre-commit copy** of the DB.
   
Therefore **`--commit` MUST be preceded by an external file-level backup** of `data/enrichment.db` (e.g. `cp data/enrichment.db data/enrichment.db.bak.$(date +%Y%m%d)`), which is the authoritative full-restore path and covers both change classes. This is consistent with the never-delete rule for `enrichment.db` in CLAUDE.md.

**Dependencies.** ODR-009 (ProcessKind), ODR-010 (participant anchoring), ODR-015 (Phase 2 generation, still deferred — this ODR can proceed as a data migration ahead of Phase 2).

---

*Appendix A (per-filler disposition table + impact appendix) is in `ODR-020-appendix-A-disposition.md`.*
