# RDL Enrichment Module

LLM-assisted axiomatization of industrial equipment classes using the
BFO/IOF-Core **five-step enrichment method**.

## What This Does

Given the cross-standard definitions aggregated in `terms.db`, this module:

1. **Sends clustered definitions** to Claude (Anthropic API)
2. **Receives structured proposals** for each of the five method steps:
   - Step 1: Identity-giving function (what makes this equipment *this* type)
   - Step 2: Genus (genus proximum — the nearest superclass)
   - Step 3: Differentia Specifica (Aristotelian differentia over the genus)
   - Step 4: Necessary parts (mereological commitments)
   - Step 5: Process participation signature ⟨I, O, T⟩
3. **Presents proposals in an editable UI** where the ontologist validates,
   corrects, and refines each step
4. **Re-runs with reviewer feedback** — the ↺ button injects reviewer notes
   and per-step expert assessments back into the LLM prompt
5. **Generates OWL/Turtle axioms** from validated proposals
6. **Tracks the axiom mode decision** — necessary-only (primitive universal)
   vs. necessary+sufficient (defined class) — with explicit rationale

## Architecture

```
enrichment/
├── schema_enrichment.sql     # DB schema (data/enrichment.db — never delete)
├── prompts.py                # 5-step method encoded as LLM prompts
├── enrichment_service.py     # Core logic: LLM calls, DB, OWL generation
├── enrichment_routes.py      # FastAPI routes under /enrich/
├── verify_service.py         # OOPS!, FOOPS!, HermiT consistency checks
└── templates/
    ├── enrichment_dashboard.html
    ├── enrichment_detail.html
    ├── enrichment_doc.html
    ├── ontology_overview.html   # all validated classes grouped by BFO root
    └── verification.html        # OOPS! / FOOPS! / HermiT dashboard
```

## Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/enrich/` | Enrichment dashboard |
| POST | `/enrich/run` | Trigger LLM enrichment for a cluster |
| POST | `/enrich/rerun/{id}` | Re-run with reviewer notes injected |
| GET | `/enrich/{id}` | Enrichment detail + editing UI |
| POST | `/enrich/{id}/update` | Save edits from the validation form |
| POST | `/enrich/{id}/undo` | Restore most recent history snapshot |
| GET | `/enrich/{id}/history` | Version history viewer |
| GET | `/enrich/{id}/turtle` | Download OWL/Turtle for one class |
| GET | `/enrich/{id}/doc` | Human-readable documentation page |
| GET | `/enrich/ontology.ttl` | Combined OWL/Turtle for all validated classes |
| GET | `/enrich/queue` | Batch processing queue dashboard |
| GET | `/enrich/relations` | OWL object/datatype property management |
| POST | `/enrich/relations/create` | Create a new OWL property |
| POST | `/enrich/relations/{id}/update` | Update an OWL property |
| POST | `/enrich/relations/{id}/delete` | Delete an OWL property |
| POST | `/enrich/scope/{label}` | Mark/unmark a cluster as out-of-scope |
| GET | `/enrich/verify` | Ontology verification dashboard |
| POST | `/enrich/verify/oops` | Run OOPS! pitfall scanner |
| POST | `/enrich/verify/foops` | Run FOOPS! FAIR evaluation |
| POST | `/enrich/verify/consistency` | Run HermiT OWL consistency check (shows inferred axioms) |
| GET | `/enrich/docs` | Full ontology class reference grouped by BFO root |
| GET | `/enrich/api-usage` | LLM token usage and cost log |
| GET | `/enrich/metrics/summary` | Per-class evaluation metrics |
| GET | `/enrich/metrics/export` | Metrics CSV/JSON download |
| GET | `/enrich/metrics/aggregate` | Cross-class aggregate statistics |

## The Five-Step Method

### Step 1 — Identity-Giving Function

The function that individuates this equipment type:

```
XFunction ⊑ DesignedFunction
XFunction ⊑ ∀realizedIn.XProcess
```

### Step 2 — Genus (Genus Proximum)

The nearest superclass. Two fields:
- `genus` — the most specific known parent (e.g., "Valve", not just "MaterialArtifact")
- `genus_bfo_root` — the BFO/IOF-Core root: `Assembly`, `MaterialArtifact`, or `EngineeredSystem`

### Step 3 — Differentia Specifica

The conditions that distinguish *this species* from siblings under the same genus.
**Critical rule**: only state what is NOT already entailed by the genus.

Types of differentia:
- **Functional** — bears a specific function subtype
- **Structural** — has a specific necessary part
- **Relational** — plays a specific role in a process

Stored as:
- `differentia_expression` — formal OWL expression
- `differentia_nl` — natural language statement
- `differentia_rationale` — why these conditions are the correct differentia
- `genus_already_provides` — JSON list of conditions inherited from genus (context only)
- `distinguishes_from` — JSON map `{SiblingClass: "how it differs"}`

### Step 4 — Necessary Parts

`hasComponentPartAtAllTimes` restrictions universal to every instance:

```json
[{"name": "PumpCasing", "parent": "MaterialArtifact",
  "relation": "hasComponentPartAtAllTimes"}]
```

### Step 5 — Process Participation Signature

Typed input/output participants and transformation type:

```json
{"inputs": ["Fluid"], "outputs": ["Fluid"], "transformation": "PressureIncrease"}
```

## Axiom Mode Decision

The axiom mode is determined by the classification basis:

| Basis | Mode | OWL | Rationale |
|-------|------|-----|-----------|
| Functional | `equivalent` | `≡` | DesignedFunction is necessary and sufficient; enables automatic classification |
| Constructive | `necessary` | `⊑` | Structural differentia are necessary-only; OWA makes equivalence unsafe |
| Both | `mixed` | Both | Functional side uses equivalence; constructive differentia is necessary-only |

When `necessary` is chosen, the system generates `iof-av:isPrimitive true` and
`iof-av:primitiveRationale` — following IOF conventions.

## Scope Filtering

Sources are classified as `equipment` (CFIHOS, DEXPI, ISO 15926-4, POSC Caesar, ISO 14224, ISA 5.1) or `glossary` (SLB Glossary, OnePetro). The enrichment dashboard hides clusters whose terms come exclusively from glossary sources, keeping the workbench focused on in-scope equipment classes. Clusters can also be manually marked out-of-scope via the **✕ out-of-scope** button on each card; the state is stored in the `cluster_scope` table in `enrichment.db`. A toggle shows/hides all out-of-scope clusters without a page reload.

The search page (`/search`) has a matching **Scope** filter (All / Equipment only).

## Enrichment Extras

Beyond the five core steps, each class can carry:

- **Alternative labels** (`skos:altLabel`) — comma-separated, language auto-detected (pt/en)
- **BFO Qualities** — sourced from CFIHOS/DEXPI properties; generates `owl:someValuesFrom bfo:BFO_0000086` restrictions and Quality stub classes
- **Custom axioms** — freeform OWL/Turtle restrictions inserted verbatim into the class definition

## OWL Relations

`/enrich/relations` manages the OWL object and datatype properties defined in COPI. Each property records name, type (ObjectProperty/DatatypeProperty), domain, range, parent property, characteristics (functional/symmetric/transitive), labels, definition, and status. Validated/exported properties are included in the combined Turtle export.

## Verification

`verify_service.py` provides three checks:

- **OOPS!** (`run_oops_check`): strips `owl:imports`, POSTs to OOPS REST API, parses XML pitfall report
- **FOOPS!** (`run_foops_check`): POSTs ontology IRI to FOOPS API, returns FAIR check scores by category
- **HermiT** (`run_consistency_check`): loads TTL via owlready2, runs Java-based HermiT reasoner for OWL 2 DL satisfiability; returns inferred subClassOf, equivalentClass, and unsatisfiable axioms for `copi:` classes

## Prompt Engineering

The system prompt (`prompts.py`) encodes the full methodology. Key design decisions:

- Functions modelled as `XFunction ⊑ DesignedFunction ⊓ ∀realizedIn.XProcess`
- Differentia must not repeat genus axioms (explicitly enforced in prompt)
- Parts use `hasComponentPartAtAllTimes` (with OWL 2 DL transitivity/cardinality caveat)
- Process signatures use the formal ⟨I, O, T⟩ tuple structure
- Reviewer notes and per-step expert feedback are injected on re-runs
- Confidence is reported per step (high/medium/low)

## Generated OWL Structure

```turtle
copi:PumpingFunction rdf:type owl:Class ;
    rdfs:subClassOf iof-core:DesignedFunction ;
    rdfs:subClassOf [ owl:onProperty bfo:BFO_0000054 ;
                      owl:allValuesFrom copi:PumpingProcess ] .

copi:Pump rdf:type owl:Class ;
    rdfs:subClassOf iof-core:EngineeredSystem ;
    rdfs:subClassOf [ owl:onProperty iof-core:hasFunction ;
                      owl:someValuesFrom copi:PumpingFunction ] ;
    rdfs:subClassOf [ owl:onProperty iof-core:hasComponentPartAtAllTimes ;
                      owl:someValuesFrom copi:PumpCasing ] ;
    iof-av:naturalLanguageDefinition "..."@en ;
    iof-av:isPrimitive "true"^^xsd:boolean ;
    iof-av:primitiveRationale "..."@en .
```

Ontology IRI: `https://www.inf.ufrgs.br/ontologies/copi`
