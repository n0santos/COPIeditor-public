# Enrichment queue

Candidate clusters for the interactive enrichment pipeline (see CLAUDE.md → *Interactive
enrichment pipeline*), scoped to COPI's **9 function-based equipment categories**.

Compiled 2026-07-06. Check off entries as they reach `validated`.

## Scope reminder

COPI's scope is **not** "any physical equipment" — it is process-industry
unit-operation equipment falling under one of the nine `copi-core` categories:

1. momentum-transfer device · 2. heat-transfer device · 3. mass-transfer device
· 4. mechanical-separation device · 5. chemical reactor · 6. phase-change device
· 7. containment device · 8. flow-control device · 9. measurement instrument

**Cross-source count is a poor proxy for scope.** The corroborating sources
(CFIHOS, POSC Caesar, DEXPI, SLB, OnePetro) cover the *whole plant* — civil,
electrical, IT, drilling/downhole, units, and physical quantities — most of which
are out of COPI scope. Filter by category fit, not by how many sources list a term.

The strongest queue = **missing subtypes of genera already enriched**: they slot
straight into the existing hierarchy and need only genus + one differentia.

## Priority 1 — functional-basis (earn `equivalent` axioms → reasoner classification)

### Flow-control devices (genus ControlValve / Valve)
- [ ] pressure control valve
- [ ] flow control valve
- [ ] pressure relief valve
- [ ] vacuum relief valve
- [ ] conventional relief valve

### Measurement instruments
Analysers:
- [ ] ph analyser
- [ ] redox analyser
- [ ] density analyser
- [ ] viscosity analyser
- [ ] distillation analyser
- [ ] flash point analyser
- [ ] cloud point analyser
- [ ] pour point analyser
- [ ] freezing point analyser
- [ ] cold filter plugging point analyser
- [ ] specific gravity analyser
- [ ] vapour pressure analyser
- [ ] thermal conductivity analyser
- [ ] liquid composition analyser
- [ ] wobbe index meter

Flow meters:
- [ ] turbine flow meter
- [ ] ultrasonic flow meter
- [ ] vortex flow meter
- [ ] orifice meter
- [ ] multiphase meter

Transmitters:
- [ ] concentration transmitter
- [ ] current transmitter
- [ ] voltage transmitter
- [ ] weight transmitter
- [ ] corrosion transmitter
- [ ] dew point transmitter

Field instruments:
- [ ] anemometer
- [ ] magnetometer
- [ ] dynamometer
- [ ] gravimeter
- [ ] hydrometer
- [ ] inclinometer
- [ ] permeameter
- [ ] consistometer
- [ ] calorimeter
- [ ] meter prover (the device)

## Priority 2 — constructive-basis subtypes (`necessary` mode; complete existing genera)

### Momentum-transfer (pump / compressor)
- [ ] axial compressor
- [ ] reciprocating compressor
- [ ] rotary compressor
- [ ] screw pump
- [ ] jet pump
- [ ] mud pump
- [ ] vacuum pump
- [ ] triplex pump
- [ ] duplex pump
- [ ] beam pump
- [ ] rod pump
- [ ] pumpjack

### Heat-transfer (heat exchanger)
- [ ] printed circuit heat exchanger
- [ ] double pipe heat exchanger
- [ ] direct contact heat exchanger
- [ ] plate and frame heat exchanger
- [ ] plate fin heat exchanger
- [ ] spiral heat exchanger
- [ ] spiral tube heat exchanger

### Mass-transfer (column)
- [ ] stripper column
- [ ] stabilizer column
- [ ] process column
- [ ] column (generic)

### Chemical reactor
- [ ] reactor (generic — core-category gap)

### Mechanical-separation (separator)
- [ ] test separator
- [ ] sand trap
- [ ] shale shaker
- [ ] screen

### Valve construction subtypes
- [ ] diaphragm valve subtype family: diaphragm, needle, plug, slide, pinch, poppet,
      multiport, eccentric rotating disc, float, motor operated, block valve
- [ ] wellhead / Christmas-tree valves: master, swab, wing (production wing), casing,
      circulation, standing, traveling, unloading valve

## Priority 3 — colleague mapping requests (batch 2026-09-01/03)

Triaged during the "colega precisa mapear" conversation. Processed 2026-09-08 via the
`enrich-term` skill (`.claude/skills/enrich-term/`), `generation_path='skill_session'`,
`status='proposed'` — review in `/enrich/` before validating.

### Done (`enrichment.id` in parentheses)
- [x] quick acting valve (1114) — genus `Valve`, `RapidActuationFunction`, `equivalent`
- [x] 3-way valve → **three way valve** (1115) — genus `Valve`, reused `FlowControlFunction`,
      `necessary`
- [x] gas chromatograph (1116) — genus `Chromatograph`, `necessary`; `necessary_parts` includes
      `CarrierGasCylinder`, grounded via a real NIST publication (recovered with `pdftotext`
      after WebFetch reported the PDF unreadable)
- [x] bi-metal thermometer → **temperature measuring instrument - bimetal** (1117) — genus
      `AnalogueTemperatureIndicator`, `necessary`; `necessary_parts` includes `BimetallicCoil`
- [x] glass level gauge — **merged**, not a new row: added as `alt_labels` on the already-enriched
      `level sight glass` (id 59). ISO 15926-4 has two near-duplicate terms for the same
      equipment (`LEVEL GAUGE GLASS` vs `LEVEL SIGHT GLASS`) — a T1/T3 divergence within the
      standard itself, same pattern as the `ElectricalConnection`/`ElectricalConnector`
      redundancy fixed 2026-09-04
- [x] siphon / syphon (1118) — genus `Pipe`, new `SiphonicTransferFunction`, `equivalent`;
      short-leg/long-leg/crest structure intentionally **not** modeled as `necessary_parts`
      (fiat-demarcated regions of one tube, not separable components)
- [x] sample cooler (1119) — genus `Cooler`, `necessary`; `SampleCoil` filed to
      `candidate_parts` (not `necessary_parts`) because its only source quote hedged on
      "usually" — needs a reviewer to confirm genus-wide applicability
- [x] concentric reducer → **pipe reducer concentric** (1120) — real ISO 15926-4 anchor found
      (`PIPE REDUCER CONCENTRIC`, parent `PIPE REDUCER`), superseding the original plan to
      enrich an unanchored "concentric reducer"; `alt_labels` carries the colleague's term
- [x] analyzer probe → **probe** (1121) — genus `Instrument`, new `ProbingFunction`,
      `equivalent`; "analyzer probe"/"analyser probe" have no `terms.db` anchor of their own,
      added as `alt_labels`. SLB Glossary's own "probe" entry is an unrelated geophysical-
      logging sense (T1_categorical divergence, not used)
- [x] moisture analyser → **moisture meter** (1122) — genus `Instrument`, new
      `MoistureMeasurementFunction`, `equivalent` (deliberately not reusing `humidity
      analyser`'s function — ISO 15926-4 splits MOISTURE from HUMIDITY); `necessary_parts`
      includes `MoistureSensingElement` and `DigitalDisplay`, both named verbatim in the
      primary definition itself
- [x] sampling cylinder → two rows: **sample vessel** (1123, genus `Vessel`, new
      `SampleCollectionFunction`, `equivalent`) as the cross-source generic base, and
      **sample bomb** (1124, genus `SampleVessel`, `necessary`, `alt_labels: ["sampling
      cylinder"]`) as the pressure-cylinder constructive subtype, with `SampleCylinderValve`
      as a triangulated `necessary_parts` entry
- [x] blind flange (1125) — genus `Flange` but a new, independent `PipeEndClosureFunction`
      (**not** a subtype of `Flange`'s own `ConnectionFunction` — closing and connecting are
      near-opposite purposes), `equivalent`; no fluid participants in the process signature
- [x] threaded cap → three rows building a proper `Cap` genus family: **cap** (1126, genus
      `MaterialArtifact`, new `ClosureFunction`, `equivalent`) → **pipe cap** (1127, genus
      `Cap`, `necessary`, differentia = fits over/on the end, not inside) → **threaded pipe
      cap** (1128, genus `PipeCap`, `necessary`, `alt_labels: ["threaded cap"]`). `PipeCap` is
      now available as the genus for `quick connection cap` whenever that term gets its own
      source-standard anchor (see below)
- [x] quick connector / quick connection (1129) — genus `MaterialArtifact` (matching the
      `electrical connector` precedent, not an intermediate `Connector` genus), new
      `QuickConnectionFunction`, `equivalent`; secondary source ISO 7241:2023 (real standard,
      free iTeh preview, recovered via `pdftotext`) confirms "quick-action coupling" as the
      standard terminology but its priced body added no construction detail

### Resolved 2026-09-10 (previously blocked — found better anchors, or an acceptable generic fallback)
Re-checked against `terms.db` with broader queries; found real anchors for 3 of the original 5,
and filed the remaining 2 (plus `drum`) as `alt_labels` on the most generic correct existing
class rather than leaving them un-enriched, per direction to resolve every backlog term to
something acceptable even without a dedicated anchor.
- [x] transmitter with indicator → **process variable transmitter** (1130) — genus `Transmitter`
      (per user direction — anchor to an existing COPI cluster, not an unenriched intermediate),
      new `IndicatingTransmissionFunction`, `equivalent`; generalizes the already-enriched
      `pressure indicating transmitter` pattern across any process variable, corroborated by the
      5 real ISA-5.1 tag-abbreviation entries (`AIT`/`FIT`/`LIT`/`PIT`/`TIT`)
- [x] coalescer filter → **coalescent filter** (1131) — real ISO 15926-4 anchor found (spelling
      variant), genus `Filter`, `necessary`; `CoalescingFilterMedia` filed to `candidate_parts`
      (hedge word "generally" in both triangulated patent quotes)
- [x] end of line terminator → **blanking cap pipe union** (1132) — real ISO 15926-4 anchor
      found (`BLANKING CAP PIPE UNION`), genus `Cap`, `necessary`; `necessary_parts` includes
      `FemaleUnionSub`; deliberately does **not** re-declare this session's own `ThreadedPipeCap`
      (1128) as a second necessary_parts stub even though the definition names a "threaded cap"
      verbatim — would risk a redundant/competing `owl:Class` declaration for the same IRI,
      documented in prose instead
- [x] quick connection cap — **merged**, no new row: added as `alt_labels` on `pipe cap` (1127);
      still no anchor of its own
- [x] drainage collector → **sump** (1133) — real cross-source anchor found (ISO 15926-4 +
      CFIHOS, "collect the heavier phase... by making use of gravity"), genus `Vessel`, new
      `GravityCollectionFunction`, `equivalent`. Supersedes the earlier `drain pot` candidate,
      which turned out to be a mismatch (its own definition types it as a liquid outlet *port*,
      not a collection vessel)
- [x] drum (generic, unqualified) — **merged**, no new row: added as `alt_labels` on `vessel`
      (id 49). Confirmed 2026-09-04 the colleague means a generic process vessel, not ISO
      15926-4's bulk-cargo-container `DRUM`; no anchor exists for a generic process-vessel drum
      distinct from the already-enriched `flash drum`/`knock out drum` (genus `Separator`), so
      filed on the most generic correct fallback

### Needs clarification before triage
- [ ] equip — likely an abbreviation for "Equipment" used as a P&ID tag/legend label, not a
      terminological entry on its own; still unresolved as of 2026-09-04 (colleague didn't
      know) — ask again before triage, or drop it if it turns out to be a non-terminological
      tag

### Correctness fix applied 2026-09-10 to all 16 original entries (1114–1129)
None of the original 16 had their process anchored into a real copi-core operation category —
all fell back to the generic `PlannedProcess` default. Fixed via direct `process_parent` UPDATE
(history-snapshotted first; `process_parent` is a real column but is not in
`update_enrichment()`'s allowlist, same class of gap as `source_definitions_used`/
`candidate_parts`): functional-basis-reused entries now anchor to whatever their reused parent
function already anchors to (`FlowControl`, `HeatTransfer`, `MomentumTransfer`,
`MaterialContainment`, per the existing `valve`/`cooler`/`pipe`/`vessel` pattern); genuinely new
functions (`ProbingFunction`, `MoistureMeasurementFunction`, `PipeEndClosureFunction`,
`ClosureFunction`) anchor to `MeasurementProcess` or `MaterialContainment` by the same reasoning
used for the new batch below. `quick connector`'s `QuickConnectionFunction` (parent
`ConnectionFunction`) was anchored to `MomentumTransfer` as a judgment call — note that `flange`/
`coupling`/`port`'s own `ConnectionFunction`/`InterfacingFunction` processes remain ungrounded at
`PlannedProcess` in the pre-existing population, a separate gap not fixed here.

## Explicitly OUT of scope (surface in queries but do not enrich)

- **Quantities / properties:** meter factor, meter slippage, pumpability, density,
  viscosity, porosity, pressure, hardness, etc.
- **Activities / documents:** core analysis, nodal analysis, risk analysis,
  transportation analysis report, "pumping"
- **Components, not equipment:** pump barrel, pump manifold, mesh, seat, gasket
- **Wrong domain:** electrical reactor, busbar, capacitor, junction box (electrical);
  computer, wireless access point (IT); bridge, foundation, derrick (civil/structural);
  kelly, drill collar, slips, casing hanger (drilling/downhole)
- **ISO 15926-4 FunctionalObject non-equipment roots:** agent/roles (author, manager,
  engineer…), information objects (document, message, method…), abstract
  functions/systems (functional mapper, network, system…). See conversation of
  2026-07-06 for the full 232-term triage.
- **P&ID drafting/notation symbols, not physical equipment:** Instr. Arrow — a diagram
  symbol for instrument signal direction / off-page connection (analogous to DEXPI's
  `SignalOffPageConnector`), not an artefact that bears a `DesignedFunction`. Flagged
  2026-09-01.

## Re-check what is still un-enriched

```sql
-- from COPIeditor root
ATTACH DATABASE 'data/enrichment.db' AS edb;
SELECT COUNT(DISTINCT source) n, LOWER(preferred_label) lbl,
       GROUP_CONCAT(DISTINCT source) srcs
FROM terms
WHERE lower(preferred_label) IN (
  'pressure control valve','flow control valve', /* …paste queue labels… */ )
  AND NOT EXISTS (SELECT 1 FROM edb.enrichment e
                  WHERE LOWER(e.cluster_label)=LOWER(terms.preferred_label))
GROUP BY LOWER(preferred_label) ORDER BY lbl;
```
