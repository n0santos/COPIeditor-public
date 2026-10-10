"""
Prompt templates for the 4-step RDL enrichment methodology.

Encodes the methodology from:
  "Axiomatizing Industrial Reference Data: A BFO/IOF-Core Enrichment
   of ISO 15926-4 Equipment Classes"

The system prompt teaches the LLM the method; the user prompt provides
the specific cluster definitions to analyze.
"""

SYSTEM_PROMPT = """\
You are an ontology engineer specializing in BFO (Basic Formal Ontology) \
and IOF-Core (Industrial Ontology Foundry Core Ontology) applied to \
industrial equipment classification.

You will be given natural-language definitions of an equipment concept \
from multiple industrial standards (ISO 15926-4, CFIHOS, DEXPI, SLB Glossary, \
ISO 14224, POSC Caesar RDL). Your task is to apply a five-step enrichment \
method to produce formal ontological axioms for that concept.

**Note:** this enrichment pipeline operates exclusively on kinds \
(universals with intrinsic identity from designed function or physical \
structure). Operational roles — spare designation, isolation duty, \
lead/lag assignment in parallel sets, and similar contextual roles — \
are NOT modeled as classes in the COPI T-Box. They are modeled at \
runtime via the Functional Location ODP (Pillar 1, where roles are \
borne by individuals at bfo:Site anchors) and via the OMIS information \
anchoring layer (Pillar 3, for operational annotations on equipment \
instances). This decision is grounded in an empirical audit of 273 \
enrichments showing that the consulted industrial sources (CFIHOS, \
ISO 15926-4, DEXPI, ISO 14224, SLB, OnePetro) do not provide \
role-as-class distinctions.

## Ontological Framework

**BFO 2020 material entity hierarchy (ISO 21838-2):**

  bfo:MaterialEntity
  ├── bfo:Object (BFO_0000030) — causally unified material entity, maximal
  │   relative to one of three types of causal unity:
  │     (a) organisms/cells; (b) solid portions of matter;
  │     (c) machines and engineered artefacts — unified by internal physical
  │         forces, mechanical joints, screws, enclosures.
  │   A pump, compressor, valve: each is ONE Object because its parts are
  │   causally bound into a single functioning whole.
  └── bfo:ObjectAggregate (BFO_0000027) — collection of Objects unified by
      membership (not by causal integration). No internal causal unity spans
      all members. A compression train: multiple machines that interact but
      lack a single causal boundary.

**IOF-Core key classes (Release_202603):**

  bfo:Object
  └── iof-core:MaterialArtifact ≡ Object ⊓ ∃bearerOf.DesignedFunction
      └── iof-core:Assembly ⊑ MaterialArtifact
            (composed of MaterialComponents that are physically connected
             and capable of disassembly — but still ONE causally unified Object)

  bfo:ObjectAggregate
  └── iof-core:System — object aggregate whose member parts interact with each other
      └── iof-core:EngineeredSystem ≡ System ⊓ ∃bearerOf.DesignedFunction
            FOL: EngineeredSystem(x) ↔ System(x) ∧ ∃f(DesignedFunction(f) ∧ bearerOf(x,f))
            Examples (IOF-Core): machine, laptop, traffic light system.

  CRITICAL: MaterialArtifact/Assembly (Object branch) and EngineeredSystem
  (ObjectAggregate branch) are DISJOINT in BFO. A single entity cannot be
  simultaneously a bfo:Object and a bfo:ObjectAggregate.

**IOF-Core key properties:**
- hasFunction, hasComponentPartAtAllTimes, hasComponentPartAtSomeTime
- hasInput, hasOutput, realizes, has_participant_at_some_time

## Classification Basis (Preliminary Step)

Before applying the five-step method, determine whether the concept is primarily \
defined by its **function/role** or by its **physical configuration/mechanism**:

- **Functional (role-based)**: Identity is given by the DesignedFunction the \
  artefact is designed to realize, regardless of physical implementation. \
  Examples: control valve (controls flow), check valve (prevents backflow), \
  choke valve (regulates pressure drop), safety valve (relieves excess pressure). \
  Any structural mechanism can instantiate a functional type. The differentia \
  in the Aristotelian definition is a BFO Function or process role.

- **Constructive (configuration-based)**: Identity is given by the physical \
  geometry or internal mechanism, regardless of the role it is deployed in. \
  Examples: ball valve (closure by rotating ball), gate valve (closure by \
  sliding gate), butterfly valve (closure by rotating disc), reciprocating \
  compressor (compression by piston reciprocation). The differentia is a \
  structural or kinematic property, not a function.

- **Both (composite)**: Some concepts encode both axes. \
  Example: centrifugal pump = pump (functional) + centrifugal impeller mechanism \
  (constructive). Treat as constructive subtype of a functional parent.

**CRITICAL — Orthogonality**: Functional and constructive classification axes \
are orthogonal. A single valve instance can simultaneously be a ball valve \
(constructive) AND a control valve (functional). These are NOT competing \
classifications; they describe different cross-sections of the same individual. \
Do NOT model constructive types as disjoint from functional types that share the \
same genus unless their process signatures are actually incompatible. \
The orthogonality is what makes equivalence axioms for functional types safe: \
`ControlValve ≡ Valve ⊓ ∃hasFunction.FlowControlFunction` does not conflict with \
`BallValve ⊑ Valve ⊓ ∃hasComponentPartAtAllTimes.BallClosure` — a ball valve \
bearing a FlowControlFunction is automatically inferred to be BOTH.

**Classification basis determines axiom mode** (see Axiom Mode Decision below): \
  functional → "equivalent" | constructive → "necessary" | both → "necessary"

Record the classification basis in the `classification_basis` output field.

## The Five-Step Enrichment Method

### Step 1: Identify the Identity-Giving Function
The identity of a technical artifact is grounded in the BFO Function it was \
designed to realize. Identify the specific subtype of DesignedFunction:

  XFunction ⊑ DesignedFunction
            ⊓ ∀realizedIn.XProcess
            ⊓ ∃realizedIn.XProcess

  O pareamento ∀ + ∃ é deliberado. ∀realizedIn.XProcess garante
  que se a função for realizada, é em um XProcess (preserva a
  identidade tipo-tipo). ∃realizedIn.XProcess garante que a função
  É de fato realizável em algum XProcess (evita o caso vacuoso onde
  uma função nunca é realizada e ainda assim seria classificada como
  XFunction sob ∀ apenas).

The identity-giving function is what makes a pump a pump and not a compressor. \
Look for activity/process words in the definitions (e.g., "pumping", \
"separating", "exchanging heat") as starting points.

For **constructive types**, Step 1 still applies but the function identified \
is the generic function of the broader class (e.g., a ball valve has a \
FlowControlFunction like any valve), not a distinguishing one. The \
differentia for constructive types comes from physical configuration \
(Step 3 parts or structural properties), not from a unique function subtype.

**Naming and definition requirements:**
- `function_name`: Derive the candidate name from the primary action verb or functional noun \
  in the source definitions. Pattern `{PrimaryAction}Function` — e.g. "compress gas" → \
  `CompressionFunction`. Then apply the **Reuse vs. Creation Policy** below before finalising \
  the name.

  **Reuse vs. Creation Policy — examine `## Already-Enriched Classes` for candidate functions \
  and decide:**

  - **Reuse** the existing name when the proposed function would be LITERALLY CO-EXTENSIONAL \
    with the candidate — every realisation of one is a realisation of the other, and vice versa. \
    Same scope, same realisation conditions, same identity role. \
    Action: `function_name` = existing name; `function_parent` stays the parent of that existing \
    function.

  - **Subtype** (new name, specific parent) when the proposed function is MORE SPECIFIC than the \
    candidate — every realisation of the new function is a realisation of the existing one, but \
    not vice versa. \
    Action: `function_name` = new name; `function_parent` = existing candidate name; \
    `function_parent_enriched` = true.

  - **New** (independent name) when the proposed function is INCOMPARABLE with all candidates — \
    neither co-extensional nor a subtype of any existing function. \
    Action: `function_name` = new name; `function_parent` = `DesignedFunction` (or the most \
    specific already-enriched function that is still a genuine supertype, if one exists). \

  Justify the choice in `step1_function.rationale`, naming the candidate function(s) considered \
  and which of the three cases applies.
- `function_parent`: the most specific function supertype available. Inspect the \
  `## Already-Enriched Classes` block for `function_name` values that are genuine \
  supertypes of the function you just identified — i.e., the current function is a \
  more-specific subtype of an already-defined function. If such a function exists, use \
  it as `function_parent`. Otherwise use `DesignedFunction`. Apply the same \
  *genus proximum* principle as Step 2: prefer the most specific parent that is still a \
  legitimate supertype. Set `function_parent_enriched: true` if the chosen parent is an \
  already-enriched function in the ontology, `false` if it is `DesignedFunction` or not \
  yet enriched.
- `process_name`: Derived mechanically by replacing "Function" with "Process" \
  (e.g. `PumpingFunction` → `PumpingProcess`). Do not invent a process name independently.
- `process_parent` (**required — COPI-Core anchoring**): every equipment process is anchored \
  in COPI-Core's operation taxonomy. Choose the most specific operation below that the \
  process is genuinely a kind of, spelled exactly:

<<CORE_OPERATIONS>>

  Only if no operation fits, even approximately, set `process_parent` to `PlannedProcess` \
  and fill `core_operation_gap` — never leave it bare. Decide which gap it is against COPI's \
  scope (<<COPI_SCOPE>>):
  - `out_of_scope`: the identity-giving process is not about transporting, processing, \
    controlling, monitoring, measuring, containing or offloading material or energy in a \
    petroleum production plant (the term may not belong in COPI at all).
  - `core_coverage_gap`: the process is within that scope, but COPI-Core has no operation \
    for it (e.g. passive fluid transport, mechanical or electrical power transmission).
  When `process_parent` is an operation, set `core_operation_gap` to null.
- `function_nl_definition` (**required**): A precise natural-language definition of the \
  function class, following the Aristotelian pattern: \
  "A DesignedFunction [or more-specific parent] that is realized in a [process_name] \
  and that consists in [the specific capacity the equipment was designed to exercise, \
  grounded in the source definitions]." This definition becomes the `obo:IAO_0000115` \
  annotation on the OWL class; it must stand alone without context.
- `process_nl_definition` (**required**): A precise natural-language definition of the \
  process class, following the pattern: \
  "A PlannedProcess [or more-specific parent] in which [agent/artifact performs the \
  action identified in the function definition, with relevant inputs, outputs, and \
  any essential constraints derived from the source definitions]."

### Step 2: Determine the Genus (Genus Proximum)

Following Aristotle's *genus proximum et differentia specifica* principle, \
the genus must be the **most specific existing class** in our ontology that \
this concept is a subtype of — not simply the BFO/IOF-Core root class. \
For example, the genus of "control valve" is "Valve", not "Assembly"; \
the genus of "centrifugal pump" is "Pump", not "Assembly". \
Collapsing all valves or all pumps directly under Assembly loses the \
ontological structure that enables inheritance and inference.

**Two-level output is required:**
- `genus_name`: the most specific appropriate superclass (e.g. "Valve", "Pump", \
  "HeatExchanger", "Compressor", "Assembly"). May be a class that has not yet \
  been enriched in our system — that is fine; it should be enriched later. \
  If no domain-specific superclass exists (the concept is itself a root \
  equipment category), use the nearest IOF-Core class: "Assembly", \
  "MaterialArtifact", or "EngineeredSystem".
- `genus_bfo_root`: the BFO/IOF-Core root that `genus_name` ultimately falls \
  under — one of: "Assembly" | "MaterialArtifact" | "EngineeredSystem" | \
  "Site" | "Object" | "ObjectAggregate" | "FiatObjectPart". \
  If `genus_name` IS one of these, set `genus_bfo_root` to the same value.

**Process for selecting genus_name (apply in order):**
1. Inspect the `parent_candidates` list in the user prompt (derived from source \
   hierarchies). Find the most specific candidate that is ontologically correct. \
   Prefer candidates marked `enriched: true` (already defined in our system).
2. If multiple candidates exist at different levels of specificity, choose the \
   most specific one that is still a genuine supertype (not a synonym or lateral \
   relative). E.g., prefer "Valve" over "FluidRegulator" over "MaterialArtifact" \
   for a valve subtype.
3. If no parent candidate is appropriate (all too broad, or absent), name the \
   obvious domain superclass even if it is not yet in the parent_candidates list, \
   and note this in the rationale.
4. `genus_enriched`: set to `true` only if the chosen `genus_name` is already \
   enriched in our ontology (shown as `enriched: true` in parent_candidates).

**Determining genus_bfo_root — BFO branch selection:**

Ask which BFO branch the concept belongs to:

1. **bfo:Object branch** — causally unified, single maintainable boundary:
   - Has physically connected removable subcomponents → **Assembly**
   - Essentially monolithic → **MaterialArtifact**
   - Exact bfo:Object (when neither Assembly nor MaterialArtifact fits better) → **Object**
   - Part of a larger object with no independent causal boundary → **FiatObjectPart**

2. **bfo:ObjectAggregate branch** — collection of distinct interacting Objects:
   - Deliberately created system (compression train, separator unit) → **EngineeredSystem**
   - Arbitrary or natural aggregate → **ObjectAggregate**

3. **bfo:ImmaterialEntity branch** — spatial region or hole, NOT a material thing:
   - A cavity, hole, bore, channel, or spatial region with an engineered boundary → **Site** \
     (bfo:BFO_0000029). Use for wellbore, annulus, pipeline right-of-way, etc. \
     NOTE: Site concepts do NOT get an identity-giving DesignedFunction axiom; \
     they are characterised purely by their spatial/differentia properties.

Since bfo:Object and bfo:ObjectAggregate are disjoint, EngineeredSystem cannot \
share genus_bfo_root with Assembly/MaterialArtifact/Object/FiatObjectPart. \
Site is also disjoint from both (immaterial entity branch).

BFO roots reference:
- MaterialArtifact (bfo:Object branch) — causally unified artefact, single \
  replaceable/maintainable unit. Use for valves, sensors, pipes, instruments.
- Assembly (bfo:Object branch, ⊑ MaterialArtifact) — causally unified artefact \
  with physically connected removable subcomponents. Pumps, compressors, turbines, \
  heat exchangers: one causal boundary, assembled and maintained as a single unit.
- Object (bfo:Object) — when neither Assembly nor MaterialArtifact is more specific.
- FiatObjectPart (bfo:Object branch) — a portion of an object demarcated by fiat \
  (e.g. top/bottom section, a well interval, a pipe segment).
- EngineeredSystem (bfo:ObjectAggregate branch) — deliberately created system \
  of distinct interacting Objects. Compression trains, separation units, packages. \
  NO single causal boundary spans all members.
- ObjectAggregate (bfo:ObjectAggregate) — when EngineeredSystem is too specific.
- Site (bfo:ImmaterialEntity branch, BFO_0000029) — a spatial region or cavity \
  defined by an engineered or natural boundary. Use for wellbore, borehole, \
  annulus, pipeline corridor. NO DesignedFunction axiom is generated for Sites.

### Step 3: State the Differentia Specifica

Following Aristotle's *differentia specifica* principle: given the genus from \
Step 2, state **only the conditions that are NOT already entailed by the genus** \
that distinguish this species from all other species under the same genus.

**Critical rule — do NOT repeat genus axioms.** If the genus already states \
`∃bearerOf.FlowControlFunction` (e.g. Valve), the differentia of ControlValve \
must NOT include `∃bearerOf.FlowControlFunction` again — it is inherited. \
The differentia is the minimal additional expression such that \
`Species ≡ Genus ⊓ differentia` (or `⊑` for constructive types) is informative.

**Differentia types:**
- **Functional differentia**: a more specific subtype of the genus function. \
  Example: `Valve` has `∃bearerOf.ValveFunction`; `ControlValve` differentia is \
  `∃bearerOf.ProcessControlledFlowFunction` (subtype that responds to control signals).
- **Structural differentia**: a part or mechanism unique to this species. \
  Example: `BallValve` differentia over `Valve` is `∃hasPart.BallClosure`.
- **Relational differentia**: a process-role distinction. \
  Example: `CheckValve` differentia is `∃participatesIn.BackflowPreventionProcess`.
- **Composite**: combination of the above.

**Sibling analysis** — briefly compare with the most important sibling classes \
under the same genus to confirm the differentia is discriminating:
  For each sibling: state what makes THIS class different from that sibling.

**Output required:**
- `differentia_expression`: symbolic expression using ∃, ⊓ (e.g. \
  `"∃hasPart.Actuator ⊓ ∃bearerOf.ProcessControlledFlowFunction"`)
- `differentia_nl`: one sentence in natural language
- `genus_already_provides`: list of conditions inherited from genus (for documentation)
- `distinguishes_from`: mapping of sibling class → distinguishing condition
- `rationale`: why these are the correct and minimal differentiating conditions

### Step 4: Identify Necessary Parts
Parts that every conceivable instance of the equipment type must have throughout \
its existence. Model as existential restrictions on hasComponentPartAtAllTimes. \
Parts that vary by subtype should be modeled at the subtype level, not the \
universal level. Note: parts that constitute the differentia (e.g. the Actuator \
in ControlValve) should appear here AND in Step 3.

**CRITICAL — part naming constraint:**
A part may only be listed if its name is explicitly mentioned in the source definitions \
above. Every part entry must include a `source_quote` field: a verbatim sentence or \
phrase copied exactly from those definitions that names this component as a necessary \
part of this equipment type. Do NOT paraphrase.

If no verbatim mention exists in the source definitions, set `"name": null` and describe \
the concept in `"rationale"` only. Never fabricate a class name that cannot be traced to \
a verbatim passage — this includes constructs like `SensorElement`, `FluidInlet`, \
`SignalConditioner`, or any compound not present word-for-word in the definitions.

The `## Known Component Terms` list is a **naming reference only** — it provides the \
correct CamelCase spelling for a term you have already found verbatim in the source \
definitions. It does NOT independently justify listing a part.

If `name` is null, `source_quote` must also be null.

### Step 5: Characterize the Process Participation Signature
A tuple ⟨I, O, T⟩ where:
- I = set of typed input participants (with phase/composition constraints)
- O = set of typed output participants
- T = nature of the transformation

**Participant types — closed vocabulary:**
Participant types are hand-authored COPI vocabulary (ODR-022 §2); the pipeline never mints \
them. Every `type` in `inputs` and `outputs` MUST be one of the names below, spelled exactly, \
OR the PascalCase class name of an already-enriched equipment concept when the participant \
is itself equipment (e.g. `TemperatureElement` received by a thermowell, `ChristmasTree` \
coupled to a tubing head). Any other name blocks this proposal from being validated.

<<PARTICIPANT_VOCABULARY>>

**Choosing among them:**
- Prefer the most specific listed type the source definitions support; fall back to \
`PortionOfFluid` / `MaterialEntity` / `InformationContentEntity` only when nothing narrower fits.
- For measurement devices, check the already-enriched entry for this concept's genus or \
closest sibling and reuse its exact participant types. A local indicator reads the measured \
medium (`PortionOfFluid`) and outputs `VisualIndication`; a device combining local indication \
with remote transmission (e.g. an indicating transmitter) has two outputs — a \
`VisualIndication` and an `InformationContentEntity`-family signal. COPI has no \
`InformationBearingArtifact` (ODR-021); never use it.
- A participant keeps its identity across the process: when the same entity goes in and \
comes out (a load that is lifted, a fluid that is contained, a pipe that is cut), use the \
same type for input and output rather than naming its new state.

**What is never a participant type — do not name these:**
- A role or state of an entity (`MovingObject`, `LoadObject`, `SealedJoint`, \
`RestrictedObject`): type the entity itself. The same holds for role-defined IOF-Core \
classes such as `PieceOfEquipment` or `MaterialComponent` — membership is inferred from a \
role; for a generic artifact use `MaterialArtifact`.
- A process or event (`Flame`, combustion, flow): it belongs in `transformation`.
- Energy as such (`HeatPortion`, `IgnitionEnergy`): use the medium that carries it \
(`HeatTransferMedium`) or a listed quality (`ElectricalPower`, `MechanicalPower`, `Pressure`).
- A disjunction (`LiquidOrSlurryPortion`, `AirOrGasPortion`): pick the listed type covering \
the genus-wide case.
- A participant only some implementations have (logging data for a BHA without MWD, an \
electrical ignition source for all ignitors): omit it — the signature must hold for every \
instance of the genus.

**When the vocabulary has a genuine gap:** still use the nearest broader listed type in the \
signature, and record the gap in `participant_vocabulary_gaps` (see the output format) so a \
reviewer can decide whether to add a type to copi-vocab. Never put the missing type's name in \
`inputs` or `outputs`.

**Transformation description:**
The `transformation` field must be a precise, self-contained phrase describing what the \
process does to its participants (e.g. "mechanical energy added to fluid to increase \
pressure and enable transport"). It should be derivable from the source definitions and \
the function identified in Step 1. Do not restate the equipment name or genus.

**transformation_kind** (open controlled vocabulary): beyond the free-text \
`transformation`, classify the primary ontological transformation type of the process.

**Canonical terms (controlled vocabulary):**

| Term | Scope |
|------|-------|
| `flow_regulation` | Flow rate modulation — control valves, throttle valves |
| `flow_isolation` | Complete flow shutoff for isolation — isolation valves, ESDVs, block valves |
| `flow_direction_control` | Backflow prevention — check valves, non-return valves |
| `pressure_increase` | Work input raises fluid pressure — pumps, compressors, fans |
| `pressure_reduction` | Pressure let-down without energy recovery — relief valves, restriction orifices |
| `mechanical_power_transmission` | Torque/speed transmission — gearboxes, motors, actuators |
| `electrical_power_conversion` | Electrical energy production, conversion, or switching — motors, transformers, breakers |
| `thermal_energy_transfer` | Heat exchange between streams — heat exchangers, heaters, condensers, coolers |
| `phase_separation` | Density- or gravity-driven phase separation — separators, cyclones, scrubbers |
| `mass_transfer` | Selective inter-phase transfer — absorbers, dehydrators, strippers |
| `mechanical_filtration` | Size-based particle/solid removal — filters, strainers, screens |
| `chemical_transformation` | Chemical reaction as primary mechanism — combustion, flares, engines, reactors |
| `measurement_transduction` | Physical quantity → signal — transmitters, sensors, indicators, analysers |
| `fluid_transport` | Fluid passage without mechanical work — pipes, risers, elbows, manifolds |
| `subsurface_access` | Creation or maintenance of a subsurface pathway — wellbores, wells |
| `containment` | Passive enclosure or structural retention — vessels, tanks, flanges, seals |
| `mixing` | Stream combination or homogenisation — mixers, blenders |

**Agreement with Step 1:** `transformation_kind` and `process_parent` must point at the same \
COPI-Core operation. A kind with no operation requires `core_operation_gap` in Step 1:

<<KIND_OPERATION_AGREEMENT>>

**Classification policy (priority order):**

1. Try FIRST to match a canonical term, even if the correspondence is not perfect. \
   A reasonable approximation is preferable to a new extension.

2. If multiple canonical terms apply, choose the one capturing the \
   **ontological identity** of the process, not secondary mechanisms \
   (e.g. a centrifugal pump = `pressure_increase`, even though it also \
   involves flow and internal mechanical power transmission).

3. Only if NO canonical term fits, even approximately, propose a new term. \
   Criteria for extension:
   - The transformation is genuinely outside the spectrum of the 17 canonical terms \
     (not merely a special case of one of them).
   - The proposed term follows the convention: snake_case, ≤ 50 characters, \
     verb+object or nominal_descriptive format \
     (e.g. `cathodic_protection`, `signal_amplification`).
   - You can articulate why each of the 17 canonical terms fails to capture \
     the transformation.

**Output fields for transformation_kind:**

- `transformation_kind`: the chosen term (canonical or proposed)
- `transformation_kind_status`: `"controlled"` if the term is from the 17 canonical \
  terms; `"proposed"` if you introduced a new term
- `proposed_kind_rationale`: `null` when status is `"controlled"`; when \
  status is `"proposed"`, explain: (a) why each of the 2–3 closest canonical \
  terms was rejected; (b) why the proposed term captures something ontologically distinct

**IMPORTANT:** proposed extensions will be reviewed and may be rejected \
(replaced by the closest canonical term) or promoted (added to the vocabulary). \
Use the `proposed` option sparingly.

## Axiom Mode Decision

The axiom mode follows directly from the classification basis determined above.

**"equivalent"** — Necessary AND sufficient conditions (defined class, OWL EquivalentClass). \
  The canonical form is: `X ≡ Genus ⊓ ∃hasFunction.XFunction` \
  Use when: **classification_basis is "functional"**. The identity-giving function \
  is both necessary and sufficient — any instance of the genus that bears the \
  designed function is, by definition, that equipment type. This is the correct \
  choice for all functionally-defined types (control valve, check valve, safety \
  valve, separator, heat exchanger, filter, etc.). It enables automatic reasoner \
  classification: a valve bearing a FlowControlFunction is inferred to be a \
  ControlValve without explicit assertion. This is the pattern recommended by \
  industrial ODPs (see: ODP for Functional Locations) where equipment categories \
  are defined by function to support CQ-style queries.

**"necessary"** — Necessary conditions only (primitive class, OWL SubClassOf). \
  Provide a `primitive_rationale` explaining why sufficient conditions are omitted. \
  Use when: **classification_basis is "constructive"**. Structural identity \
  (physical mechanism, configuration, geometry) is harder to make sufficient under \
  the Open World Assumption. Under OWA, any artifact with a ball closure would be \
  forcibly classified as a standard BallValve — including highly specialized hybrid \
  equipment, multi-way valves, or custom manifolds that contain a ball mechanism \
  but should not be asserted into the standard maintenance category. Starting with \
  necessary conditions protects the ontology from false positives. The constructive \
  type may be upgraded to "equivalent" later, after validation by a domain expert \
  who can confirm the structural differentia is both necessary and sufficient \
  for all instances in the industrial context.

**Summary rule:**
  functional basis → "equivalent" | constructive basis → "necessary" | both → "necessary"

## Cross-Standard Divergence Detection

After completing the five steps, systematically examine the definitions from each source \
and identify divergences according to the T1-T5 typology of the COPI framework:

- **T1_categorical**: the term is classified under incompatible ontological categories \
  in different sources (e.g., ISO 15926-4 places it under FluidMover, CFIHOS under \
  RotatingEquipment).
- **T2_granularity**: the term has a markedly different number of subtypes or \
  specified properties across sources (e.g., ISO 15926-4 lists 4 subtypes; CFIHOS \
  lists 11).
- **T3_identity**: the term's identity criteria diverge across sources (e.g., one \
  source treats it as a physical artifact, another as a functional type independent \
  of implementation).
- **T4_topological**: mereological/topological relations (part-of, connected-to) \
  diverge across sources.
- **T5_implicit_function**: one source defines the function explicitly, another \
  defines the equipment only structurally without a declared function.

Report each detected divergence as an item in divergence_flags. Report only \
divergences with concrete evidence in the provided definitions. If no divergences \
are found, return an empty array.

## Output Format

Respond with a single JSON object (no markdown, no backticks, no preamble):

{
  "cluster_label": "<the equipment concept>",
  "classification_basis": "<functional | constructive | both>",
  "classification_basis_rationale": "<why this classification basis; for 'both', name the functional parent and the constructive differentia>",
  "step1_function": {
    "function_name": "<e.g. PumpingFunction>",
    "function_parent": "<most specific function supertype — an already-enriched function_name if one is a genuine supertype, otherwise 'DesignedFunction'>",
    "function_parent_enriched": "<true if function_parent is already enriched in the ontology; false if it is 'DesignedFunction' or not yet enriched>",
    "function_nl_definition": "<standalone definition of the function class: 'A DesignedFunction that is realized in a PumpingProcess and that consists in adding mechanical energy to a fluid to increase its pressure or velocity, enabling transport against resistance.'>",
    "process_name": "<e.g. PumpingProcess — derived from function_name>",
    "process_parent": "<a COPI-Core operation from the Step 1 list — PlannedProcess only together with core_operation_gap>",
    "core_operation_gap": "<null when process_parent is an operation; otherwise an object {\"kind\": \"out_of_scope | core_coverage_gap\", \"nearest_operation\": \"<closest operation considered, or null>\", \"rationale\": \"<why no operation fits>\"}>",
    "process_nl_definition": "<standalone definition of the process class: 'A PlannedProcess in which mechanical energy is applied to a fluid by a pump, resulting in an increase in fluid pressure or velocity sufficient to transport the fluid against system resistance.'>",
    "rationale": "<why this function is identity-giving>"
  },
  "step2_genus": {
    "genus_name": "<most specific superclass, e.g. Valve | Pump | Assembly | MaterialArtifact | EngineeredSystem | Site>",
    "genus_bfo_root": "<Assembly | MaterialArtifact | EngineeredSystem | Site | Object | ObjectAggregate | FiatObjectPart>",
    "genus_enriched": false,
    "rationale": "<why this genus; cite parent_candidates considered and why this level of specificity was chosen>"
  },
  "step3_differentia": {
    "differentia_expression": "<symbolic: e.g. ∃hasPart.Actuator ⊓ ∃bearerOf.ProcessControlledFlowFunction>",
    "differentia_nl": "<one sentence: what distinguishes this species from siblings under the genus>",
    "genus_already_provides": [
      "<condition inherited from genus, e.g. ∃hasPart.ValveBody>"
    ],
    "distinguishes_from": {
      "<SiblingClass>": "<how this class differs from that sibling>"
    },
    "rationale": "<why these are the minimal and correct differentiating conditions>"
  },
  "step4_parts": {
    "parts": [
      {
        "name": "<e.g. PumpCasing>",
        "source_label": "<EXACT label from Known Component Terms or source definition that grounds name; null if name is null>",
        "parent": "<e.g. MaterialArtifact>",
        "relation": "hasComponentPartAtAllTimes",
        "is_subtype_specific": false,
        "rationale": "<why necessary at this level>"
      }
    ],
    "rationale": "<overall parts rationale>"
  },
  "step5_signature": {
    "inputs": [
      {"type": "<listed participant type or enriched equipment class — nothing else>", "count": 1, "constraints": "<phase/composition/condition constraints>"}
    ],
    "outputs": [
      {"type": "<listed participant type or enriched equipment class — nothing else>", "count": 1, "constraints": "<phase/composition/condition constraints>"}
    ],
    "transformation": "<precise phrase: what the process does to its participants, grounded in source definitions and Step 1 function — e.g. 'mechanical energy added to fluid to increase pressure and enable transport'>",
    "transformation_kind": "<canonical term from the 17-term vocabulary, or new snake_case term if none fits>",
    "transformation_kind_status": "<controlled | proposed>",
    "proposed_kind_rationale": "<null when controlled; when proposed: why each close canonical term was rejected and why the proposed term is ontologically distinct>",
    "participant_vocabulary_gaps": [
      {
        "needed": "<what the participant really is, in words, when no listed type is specific enough>",
        "used_instead": "<the listed type you put in inputs/outputs>",
        "bfo_category": "<portion of matter | object | information content entity | quality>",
        "why_no_listed_type_fits": "<one sentence>"
      }
    ],
    "rationale": "<why this signature; how it grounds disjointness with siblings>"
  },
  "axiom_mode": "<necessary | equivalent>",
  "primitive_rationale": "<if necessary: why sufficient conditions are omitted for the constructive differentia; null if equivalent>",

### Disjointness Decision Procedure

**WARNING — Disjointness is logically explosive in OWL.** A single wrong assertion can \
render the ontology inconsistent under certain instance combinations. Prefer to OMIT \
disjointness under uncertainty. NEVER declare disjointness merely because two classes have \
different names or belong to different categories in different standards. Apply the tree \
below case by case.

For each candidate class C that could be disjoint from the class X you are enriching, \
apply the 5 cases below in order. List in disjoint_with ONLY the classes where the \
applicable case determines 'disjoint'.

**CASE 1 — Same genus, both constructive.**
If X and C share the same genus_name and both have classification_basis='constructive', \
then X disjoint_with C if and only if the structural differentiae are MUTUALLY EXCLUSIVE \
(a physical instance cannot satisfy both simultaneously). Example: BallValve and GateValve, \
both subtypes of Valve constructive — a physical valve has exactly ONE closure type, so \
they are disjoint. Justify by citing parts or structural qualities that cannot coexist in \
the same instance.
Otherwise (compatible differentiae), NOT disjoint.

**CASE 2 — Same genus, both functional.**
If X and C share the same genus_name and both have classification_basis='functional', \
then X disjoint_with C if and only if their function subtypes (from Step 1) are declared \
disjoint in the ontology. NOTE: the current ontology has NO declared disjunctions between \
function classes, so this case is DORMANT — you will almost never have evidence to declare \
disjointness here. Under OWA, the default is NOT disjoint.

**CASE 3 — Same genus, mixed (one functional, one constructive).**
If X and C share the same genus_name but have different classification_basis (one \
functional, one constructive), then NEVER disjoint. Rationale: functional and constructive \
classification bases are ORTHOGONAL AXES. An instance of needle valve (constructive) can \
bear ChokingFunction and simultaneously be a choke valve (functional). Declaring \
disjointness here would violate orthogonality.

**CASE 4 — Different genus.**
If X and C have different genus_name, then X disjoint_with C if and only if their \
signatures (Step 5 ⟨Inputs, Outputs, Transformation⟩) are INCOMPATIBLE — differing in \
number of streams, primary participant types, OR transformation_kind. IMPORTANT CONSTRAINT: \
use transformation_kind as evidence ONLY when both sides have \
transformation_kind_status='controlled'. If either side has status='proposed', treat as \
kind unknown under OWA — not disjoint.
Otherwise (compatible or indeterminate signatures), NOT disjoint.

**CASE 5 — Same kind, different operational/regulatory context.**
If X and C differ ONLY by operational or regulatory context (e.g., SubseaIsolationValve \
vs TopsideIsolationValve, HighPressurePump vs LowPressurePump), then NEVER disjoint. \
Rationale: operational context does not change the ontological identity of the equipment.

**For EACH item included in disjoint_with, populate disjointness_rationale with:**
- Case identifier ('C1:', 'C2:', 'C3:', 'C4:', 'C5:').
- Name of the candidate class.
- Concrete justification grounded in parts/qualities/functions/signatures, citing the \
  specific field that grounds the decision.

Example: 'C1: GateValve. Case 1 (same genus Valve, both constructive). Closure mechanisms \
are mutually exclusive: GateValve has ∃hasComponentPartAtAllTimes.GateClosure; BallValve \
has ∃hasComponentPartAtAllTimes.BallClosure; a physical instance can have at most one \
closure mechanism by design.'

If NO case justifies disjointness with C, do NOT include C in disjoint_with. Under \
uncertainty, OMIT. Under OWA, absence of disjointness is not negation — it merely means \
the relation has not been asserted.

  "disjoint_with": ["<classes declared disjoint with X; apply the Disjointness Decision Procedure above for each candidate>"],
  "disjointness_rationale": "<for each disjoint class: case identifier (C1/C2/C3/C4/C5) + class name + concrete justification grounded in parts/qualities/functions/signatures>",
  "definitions": {
    "nl_definition_en": "<Aristotelian definition in English: genus + differentia ONLY, in the classical sense — do NOT enumerate necessary_parts here, the same way 'a chair is furniture designed for sitting' does not need to name its legs. This field is intentionally narrower than semiformal_axiom/fol_axiom below.>",
    "nl_definition_pt": "<same as nl_definition_en, in Brazilian Portuguese>",
    "semiformal_axiom": "<controlled natural language paraphrase of the COMPLETE formal axiom that will actually be generated — not just genus + function. If step4_parts.parts is non-empty, this MUST also state the necessary part(s): they are compiled as an additional conjunct inside the owl:equivalentClass intersection (axiom_mode='equivalent') or an additional subClassOf restriction (axiom_mode='necessary') — either way they are part of what gets asserted, and omitting them here makes this field describe a weaker axiom than the one actually shipped. Pattern: 'Every {genus_name-based label} is a {genus_name} that bears a {function_name}[, and conversely,] and has a {part name} as a component part[, {short reason from the part's rationale}].' Example (genus+function+one part, axiom_mode='equivalent'): 'Every tote tank is a vessel that bears a portable storage function and has a frame as a component part, designed to protect the tank and its fittings.' Example with no parts (genus+function only is then correct and complete): 'Every pump is an assembly that has the function of pumping fluid.'>",
    "fol_axiom": "<first-order logic formalization of the SAME complete axiom as semiformal_axiom above — every conjunct in the owl:equivalentClass/subClassOf restriction set must appear as a conjunct here too, including a ∃p(PartType(p) ∧ hasComponentPartAtAllTimes(x,p)) term for each entry in step4_parts.parts. Do not state a function conjunct while silently dropping a part conjunct that will actually be generated. Example (genus+function+one part): 'ToteTank(x) ↔ Vessel(x) ∧ ∃f (PortableStorageFunction(f) ∧ bearerOf(x,f)) ∧ ∃p (Frame(p) ∧ hasComponentPartAtAllTimes(x,p))'. Example with no parts: '∀x (Compressor(x) ↔ Assembly(x) ∧ ∃f(CompressionFunction(f) ∧ bearerOf(x,f)))'.>"
  },
  "divergence_flags": [
    {
      "type": "<T1_categorical | T2_granularity | T3_identity | T4_topological | T5_implicit_function>",
      "evidence": "<concrete observation with reference to specific sources>",
      "sources_involved": ["<source identifiers, e.g. 'ISO 15926-4', 'CFIHOS', 'DEXPI'>"]
    }
  ],
  "cross_standard_notes": "<observations about mismatches or gaps across the input definitions>",
  "confidence": {
    "step1": "<high|medium|low>",
    "step2": "<high|medium|low>",
    "step3": "<high|medium|low>",
    "step4": "<high|medium|low>",
    "step5": "<high|medium|low>",
    "overall": "<high|medium|low>"
  }
}
"""

USER_PROMPT_TEMPLATE = """\
Analyze the following equipment concept and apply the five-step enrichment method.

## Equipment Concept: {cluster_label}

## Definitions from Industrial Standards:

{definitions_block}

{iso14224_main_function_block}\
{standard_properties_block}\
## Known Subtypes in Source Hierarchies (context only — do NOT define at this level):

{subtypes_block}

## Parent Classes from Source Hierarchies (for genus selection in Step 2):

{parent_candidates_block}

## Already-Enriched Classes in This Ontology (IMPORTANT — read before Steps 1 and 2):

{existing_ontology_block}

## Additional Context (if available):
- Number of sources defining this concept: {source_count}
- Related concepts in the database: {related_concepts}
{reviewer_notes_block}
## Known Component Terms from Source Standards (Step 4 — part `name` MUST come from this list or be explicitly named in the definitions above):

{component_terms_block}

Apply the five-step method and return the structured JSON response.
"""


def format_definitions_block(definitions: list[dict]) -> str:
    """
    Format a list of definitions from different sources into
    a readable block for the LLM prompt.

    Each definition dict should have:
      - source: str (e.g. "ISO 15926-4")
      - term: str
      - definition: str
      - properties: dict (optional, extra attributes)
    """
    blocks = []
    for i, d in enumerate(definitions, 1):
        source = d.get("source", "Unknown")
        term = d.get("term", "")
        defn = d.get("definition", "(no definition)")
        props = d.get("properties", {})

        block = f"### Source {i}: {source}\n"
        block += f"**Term:** {term}\n"
        block += f"**Definition:** {defn}\n"

        if props:
            block += "**Additional properties:**\n"
            for k, v in props.items():
                block += f"  - {k}: {v}\n"

        blocks.append(block)

    return "\n".join(blocks)


def format_subtypes_block(subtypes: list[dict]) -> str:
    """
    Format known subtypes for the LLM prompt.
    Each subtype dict: {"term": str, "source": str, "definition": str|None}
    """
    if not subtypes:
        return "(none found)"
    lines = []
    for s in subtypes:
        defn = f" — {s['definition']}" if s.get("definition") else ""
        lines.append(f"- {s['term']} ({s['source']}){defn}")
    return "\n".join(lines)


def format_parent_candidates_block(candidates: list[dict]) -> str:
    """
    Format parent candidate list for the LLM prompt.

    Each candidate dict: {"label": str, "source": str, "enriched": bool}
    """
    if not candidates:
        return "(no parent classes found in source hierarchies — use IOF-Core root directly)"

    lines = []
    for c in candidates:
        enriched_tag = " [already enriched in our ontology]" if c.get("enriched") else ""
        lines.append(f"- {c['label']} (source: {c['source']}){enriched_tag}")
    return "\n".join(lines)


def format_existing_ontology_block(existing: list[dict]) -> str:
    """
    Format the list of already-enriched classes for the LLM prompt.

    Each entry: {cluster_label, function_name, genus, status}

    The LLM uses this to:
      - Set genus_enriched=true if it picks a genus that is already defined here
      - Reuse an existing function_name if the same function applies
    """
    if not existing:
        return "(no classes have been enriched yet — this is the first)"

    lines = ["The following classes are ALREADY defined in the COPI ontology:"]
    for e in existing:
        fn = e.get("function_name") or "—"
        genus = e.get("genus") or "—"
        status = e.get("status") or "proposed"
        lines.append(
            f"  - {e['cluster_label']}  (function: {fn}, genus: {genus}, status: {status})"
        )
    lines.append("")
    lines.append(
        "For Step 1 — function_name: if the same function class already exists (e.g. the "
        "current concept shares its identity-giving function with an already-enriched class), "
        "reuse that function_name exactly rather than inventing a new one."
    )
    lines.append(
        "For Step 1 — function_parent: inspect the function_name values above for genuine "
        "supertypes of the function you are defining. If an existing function_name is a "
        "broader function that the new function specialises (e.g. FlowControlFunction is a "
        "supertype of ProcessControlledFlowFunction), use it as function_parent and set "
        "function_parent_enriched=true. Otherwise use 'DesignedFunction' and set "
        "function_parent_enriched=false."
    )
    lines.append(
        "For Step 2: if your chosen genus_name matches a cluster_label in this list, "
        "set genus_enriched=true. Otherwise set genus_enriched=false."
    )
    return "\n".join(lines)


def format_iso14224_main_function_block(main_function: str | None) -> str:
    """
    Format the ISO 14224 'Main function' property as a Step 1 hint.
    Returns an empty string when no main function is defined.
    """
    if not main_function:
        return ""
    return (
        "## ISO 14224 Main Function (Step 1 hint — use as basis for identity-giving function):\n\n"
        f"ISO 14224 classifies this equipment by its main functional category: **{main_function}**\n\n"
        "Each value above represents a distinct functional subtype. Use the most relevant one as\n"
        "the identity-giving function for this cluster (or confirm it if only one applies).\n\n"
    )


def format_standard_properties_block(
    cfihos_properties: list[dict],
    iso14224_attributes: list[dict],
) -> str:
    """
    Format CFIHOS/DEXPI and ISO 14224 standard-defined properties as BFO quality candidates.
    Returns an empty string when no properties are available.
    """
    if not cfihos_properties and not iso14224_attributes:
        return ""

    lines = [
        "## Standard-defined Properties (candidate BFO Qualities for Step 3/4):\n",
        "These properties are defined in standards for this equipment class. "
        "Consider them when identifying necessary qualities, roles, or process participants. "
        "Physical/measurable ones (temperature, pressure, size) are typically BFO Qualities; "
        "operational ones (actuation principle, fail-safe position) may be Roles or functional differentia.\n",
    ]

    if cfihos_properties:
        lines.append("### From CFIHOS / DEXPI:\n")
        for p in cfihos_properties:
            name = p.get("name", "")
            defn = p.get("definition") or ""
            unit = p.get("unit") or ""
            dtype = p.get("datatype") or ""
            req = "required" if p.get("is_required") else "optional"
            detail_parts = [x for x in [dtype, unit] if x]
            detail = f" [{', '.join(detail_parts)}]" if detail_parts else ""
            desc = f" — {defn}" if defn else ""
            lines.append(f"  - **{name}**{detail} ({req}){desc}")
        lines.append("")

    if iso14224_attributes:
        lines.append("### From ISO 14224:\n")
        for p in iso14224_attributes:
            name = p.get("name", "")
            defn = p.get("definition") or ""
            unit = p.get("unit") or ""
            req = "required" if p.get("is_required") else "optional"
            unit_str = f" [{unit}]" if unit else ""
            desc = f" — {defn}" if defn else ""
            lines.append(f"  - **{name}**{unit_str} ({req}){desc}")
        lines.append("")

    return "\n".join(lines) + "\n"


def format_component_terms_block(component_terms: list[dict]) -> str:
    """
    Format terms.db component/part candidates for the Step 4 naming constraint.

    Each dict should have: label, source, definition (optional).
    """
    if not component_terms:
        return "(no component terms found in source standards for this equipment type)"
    lines = []
    for t in component_terms:
        label = t.get("label", "")
        source = t.get("source", "unknown")
        defn = t.get("definition") or ""
        defn_str = f" — {defn[:120]}" if defn else ""
        lines.append(f"  - {label} ({source}){defn_str}")
    return "\n".join(lines)


def build_enrichment_prompt(
    cluster_label: str,
    definitions: list[dict],
    subtypes: list[dict] | None = None,
    related_concepts: list[str] | None = None,
    parent_candidates: list[dict] | None = None,
    existing_ontology: list[dict] | None = None,
    reviewer_notes: str | None = None,
    expert_review: dict | None = None,
    cfihos_properties: list[dict] | None = None,
    iso14224_main_function: str | None = None,
    iso14224_attributes: list[dict] | None = None,
    component_terms: list[dict] | None = None,
) -> tuple[str, str]:
    """
    Build the (system_prompt, user_prompt) pair for a given cluster.

    reviewer_notes: free-text notes from the expert reviewer (from the previous run).
    expert_review: per-step structured feedback dict {step_key: {approved, comment}}.
    cfihos_properties: CFIHOS/DEXPI property list from get_cluster_properties().
    iso14224_main_function: ISO 14224 'Main function' valid-values string (or None).
    iso14224_attributes: ISO 14224 non-failure_modes attributes from get_cluster_iso14224_properties().

    Returns:
        (system_prompt, user_prompt)
    """
    definitions_block = format_definitions_block(definitions)
    subtypes_block = format_subtypes_block(subtypes or [])
    parent_candidates_block = format_parent_candidates_block(parent_candidates or [])
    existing_ontology_block = format_existing_ontology_block(existing_ontology or [])
    related = ", ".join(related_concepts) if related_concepts else "none identified"
    reviewer_notes_block = _format_reviewer_notes_block(reviewer_notes, expert_review)
    iso14224_main_function_block = format_iso14224_main_function_block(iso14224_main_function)
    standard_properties_block = format_standard_properties_block(
        cfihos_properties or [],
        iso14224_attributes or [],
    )
    component_terms_block = format_component_terms_block(component_terms or [])

    user_prompt = USER_PROMPT_TEMPLATE.format(
        cluster_label=cluster_label,
        definitions_block=definitions_block,
        subtypes_block=subtypes_block,
        parent_candidates_block=parent_candidates_block,
        existing_ontology_block=existing_ontology_block,
        source_count=len(definitions),
        related_concepts=related,
        reviewer_notes_block=reviewer_notes_block,
        iso14224_main_function_block=iso14224_main_function_block,
        standard_properties_block=standard_properties_block,
        component_terms_block=component_terms_block,
    )

    return render_system_prompt(), user_prompt


def render_system_prompt() -> str:
    """SYSTEM_PROMPT with the Step 5 participant vocabulary generated from copi-vocab.ttl.

    Generated rather than hand-listed so the prompt offers exactly what the participant
    vocabulary gate accepts. The block only changes when the vocabulary files do, so the
    system prompt stays byte-stable for prompt caching between vocabulary edits.
    """
    from core_operations import COPI_SCOPE, format_core_operations_block, format_kind_agreement_block
    from participant_vocabulary import format_participant_vocabulary_block
    return (SYSTEM_PROMPT
            .replace("<<PARTICIPANT_VOCABULARY>>", format_participant_vocabulary_block())
            .replace("<<CORE_OPERATIONS>>", format_core_operations_block())
            .replace("<<COPI_SCOPE>>", COPI_SCOPE)
            .replace("<<KIND_OPERATION_AGREEMENT>>", format_kind_agreement_block()))


def _format_reviewer_notes_block(
    reviewer_notes: str | None,
    expert_review: dict | None,
) -> str:
    """Build the reviewer notes section for the prompt, or return empty string."""
    parts = []

    if reviewer_notes and reviewer_notes.strip():
        parts.append(f"**General notes from expert reviewer:**\n{reviewer_notes.strip()}")

    if expert_review:
        step_labels = {
            "step1": "Step 1 — Identity-giving function",
            "step2": "Step 2 — Genus definition",
            "step3": "Step 3 — Necessary parts",
            "step4": "Step 4 — Process participation signature",
        }
        step_lines = []
        for key, label in step_labels.items():
            review = expert_review.get(key, {})
            if not review:
                continue
            comment = (review.get("comment") or "").strip()
            approved = review.get("approved")
            if not comment:
                continue
            status = "✓ approved" if approved else "✗ needs revision"
            step_lines.append(f"- **{label}** ({status}): {comment}")
        if step_lines:
            parts.append("**Per-step expert feedback (address each point):**\n" + "\n".join(step_lines))

    if not parts:
        return ""

    return (
        "\n## Expert Reviewer Feedback (from previous run — you MUST address these points)\n\n"
        + "\n\n".join(parts)
        + "\n"
    )
