# COPI Editor

A web-based research tool for building the **Core Ontology for Petroleum Installations (COPI)** — a BFO 2020 / IOF-Core aligned OWL 2 DL ontology of oil & gas production equipment.

The editor automates the tedious parts of ontology engineering (aggregating definitions from standards, drafting axioms, generating OWL, running QC) while keeping the ontologist in full control of every modelling decision.

> **Two products, one workflow.** COPI is the ontology (the scholarly output, hosted at `https://www.inf.ufrgs.br/ontologies/copi`, managed in the [INF-UFRGS-Ontologies/COPI](https://github.com/INF-UFRGS-Ontologies/COPI) GitHub repository under ODK). COPI Editor is this tool — it feeds into that repository.

---

## What the Editor Does

```
Industrial standards  →  Term aggregator  →  Enrichment workbench  →  copi-edit.owl
(ISO, CFIHOS, DEXPI…)    (terms.db)          (LLM + ontologist)        (ODK pipeline)
                                                                              ↓
                                                              GitHub PR → ODK QC → Release
                                                                              ↓
                                                             Static docs → copi/docs
```

At the centre is the **Enrichment Workbench** (`/enrich/`): for each equipment concept (e.g., *valve*, *pump*, *separator*), the editor collects definitions from all relevant standards, sends them to Claude with a structured prompt, and proposes a complete set of OWL axioms following the five-step BFO/IOF-Core method. The ontologist reviews and adjusts each proposal, then exports validated classes to the ODK repository as a pull request.

---

## Quick Start

```bash
cp .env.template .env          # add your ANTHROPIC_API_KEY
docker compose up --build      # builds image, starts on :8765
```

App available at <http://localhost:8765>.

**Two separate databases — never confuse them:**

| File | Contents | Bundled in image? |
|------|----------|-----------------|
| `data/terms.db` | Aggregated terms from standards | **Yes** — pre-populated, no setup needed |
| `data/enrichment.db` | LLM proposals, expert reviews, COPI IDs | No — persisted on PVC / local volume |

---

## Populating the Term Aggregator

`terms.db` ships pre-populated in the Docker image. To rebuild it locally from source:

```bash
make ingest                          # all sources
make ingest-cfihos                   # single source
python -m scripts.ingest --clear     # full re-ingest
```

### Sources

| Source | Format | Scale | Notes |
|--------|--------|-------|-------|
| ISO 15926-4 | RDF/OWL (local files) | ~500 equipment classes | SPARQL endpoints currently down — place files in `data/raw/iso15926/` |
| POSC Caesar RDL | SPARQL (live) | ~2 000 classes | OWL, not SKOS |
| CFIHOS | Excel (.xlsx) | ~600 classes + properties | Required — not publicly available |
| DEXPI | Python DSL (GitLab) | ~200 classes | Auto-fetched; or place copies in `data/raw/dexpi/` |
| SLB Oilfield Glossary | JSON-LD (public web) | ~4 800 definitions | Fallback to local cache |
| ISO 14224 | PDF (pdfplumber) | ~136 terms | Required — not publicly available |
| OnePetro E&P Glossary | JSON cache (Playwright) | ~5 188 definitions | Run `scripts/fetch_onepetro_glossary.py` once |

The aggregator groups terms from all sources by normalised label (lowercased, depluralized). This produces *clusters* — e.g., all definitions of "valve" across every standard in one place. The enrichment workbench operates on these clusters.

---

## The Enrichment Workbench (`/enrich/`)

This is the main interface. It has three zones: the cluster grid (what to work on), the detail editor (how to work on it), and the export panel.

### 1 — Scope Classification

Not every cluster belongs in an equipment ontology. The scope panel decides what to include:

- **Auto-classify** — marks ISO 15926 non-physical types (activities, measurement scales, information objects) and ISA 5.1 coding-scheme terms as out-of-scope automatically, using regex rules over class names and parents.
- **LLM scope classifier** — sends unclassified clusters to Claude Haiku in configurable batches; each response includes a justification and confidence score. Saves cost by using the smaller model only for scope decisions. Supports both synchronous and **Anthropic Batch API** processing for large sets.
- **Manual toggle** — any cluster can be marked in-scope or out-of-scope individually with one click, overriding any automatic classification.

### 2 — The Five-Step Axiomatization Method

Clicking a cluster in the grid triggers the enrichment. Claude receives all cross-source definitions and applies a structured five-step BFO/IOF-Core method:

| Step | What it defines | OWL construct |
|------|----------------|---------------|
| 1 — Identity-giving function | A `DesignedFunction` subtype that constitutes the bearer's identity; realized in a `PlannedProcess` subtype | `FunctionClass ⊑ DesignedFunction`, `∃realizedIn.ProcessClass` |
| 2 — Genus | The nearest known superclass — e.g., `Assembly`, `Valve`, not just the BFO root | `SubClassOf genus` |
| 3 — Differentia specifica | Conditions that distinguish this class from siblings under the same genus | `SubClassOf` or `EquivalentClasses` restriction |
| 4 — Necessary parts | Components present in every instance (`hasComponentPartAtAllTimes`) | `∃hasComponentPartAtAllTimes.PartClass` |
| 5 — Process participation signature | Typed inputs, outputs, and transformation type; grounds disjointness reasoning | `∃hasParticipant.X` restrictions |

**Axiom mode** determines whether the differentia become necessary conditions only or a full equivalence:

| Mode | OWL | When to use |
|------|-----|-------------|
| `necessary` | `Class ⊑ Genus ⊓ differentia` | Constructive classification (ball valve, gate valve) — OWA makes equivalence unsafe |
| `equivalent` | `Class ≡ Genus ⊓ differentia` | Functional classification (control valve, check valve) — the function is necessary and sufficient |
| `mixed` | Equivalence for functional side + necessary-only structural differentia | Both classification bases apply (e.g., centrifugal pump) |

### 3 — The Detail Editor (`/enrich/{id}`)

Each proposal is shown as five collapsible step-cards. Every field is editable:

- **Step cards** show a green "✓ done" badge when their key fields are filled. Rationale fields capture the ontologist's or LLM's justification for each decision.
- **Re-run with notes** — write reviewer notes in the Notes field and click ↺; the current state is snapshotted to Version History before Claude re-runs the analysis incorporating the feedback.
- **Expert review** — each step has an accept / dispute / revise status with a free-text note. The review state is stored per-step in `expert_review` JSON.
- **Version History** (`/{id}/history`) — every re-run creates a snapshot. Any past version can be viewed in full and restored.
- **Competency questions** — if any CQs in the database reference this cluster, they appear in the sidebar with their satisfaction status.
- **Alternative labels** (`skos:altLabel`) and **BFO Qualities** (from CFIHOS properties) can be added manually.
- **Scope toggle** — an ⊘ Out of scope button in the action bar lets the ontologist exclude an already-enriched cluster from the export without deleting it. State is stored in `enrichment.db` and reflected in the dashboard grid.

### 4 — Formal Output in the Editor

Below the step cards, the editor shows three auto-generated outputs that update on every save:

- **Semi-formal axiom** — Aristotelian `genus + differentia` in readable notation.
- **First-Order Logic theory** — a mechanically derived FOL theory panel covering all five steps: `∀x (C(x) ↔ genus(x) ∧ ∃f(F(f) ∧ bearerOf(x,f)) ∧ differentia)`, plus separate axioms for necessary parts and process participation. Updates live; no manual input required.
- **OWL 2 / Turtle** — the actual RDF/Turtle axioms that will be exported, rendered in a dark code block.

---

## Batch Processing (`/enrich/queue`)

For large-scale enrichment, the batch queue processes multiple clusters sequentially without manual intervention:

1. Enter cluster labels (one per line) or select from the unenriched list
2. Click **▶ Run All Pending** — jobs execute in the browser, status updates live (pending → running → done/failed)
3. Each completed job links directly to the new enrichment detail page for review

Supports **Anthropic Batch API** for asynchronous processing of large sets at reduced cost.

---

## Imported Ontology Browser (`/enrich/imported-ontologies`)

An interactive two-panel browser of the upper ontologies COPI imports:

- **BFO 2020** — 36 named classes with SKOS annotations (definition, example, scopeNote, altLabel, dc:identifier)
- **IOF-Core** — 83 named classes with the full `iof-av:` annotation vocabulary (naturalLanguageDefinition, semiFormalNaturalLanguageDefinition, firstOrderLogicDefinition, firstOrderLogicAxiom, primitiveRationale, isPrimitive, synonym, counterExample…)
- Classes present in both are merged and shown with a "★ Both" badge
- Searchable in-page; filterable by source; `owl:disjointWith` declarations shown as chips
- Clicking any BFO root or IOF-Core class label in the enrichment detail editor opens the browser at that class

---

## Ontology Verification (`/enrich/verify`)

Four automated checks run against the combined OWL/Turtle export of all validated classes:

### OOPS! — Pitfall Scan
Submits the combined Turtle to the OOPS! REST API. Detects ~40 common OWL modelling pitfalls across three severity levels (critical, important, minor): missing annotations, unconnected classes, wrong domain/range, missing inverses, etc. Results are shown with per-pitfall fix hints.

> Note: `owl:imports` is stripped before submission because OOPS! cannot resolve external IRIs (BFO, IOF-Core). This causes expected P34 (untyped class) pitfalls for IOF-Core classes — these can be ignored.

### FOOPS! — FAIR Evaluation
Sends the ontology IRI to the FOOPS! REST API for FAIR (Findability, Accessibility, Interoperability, Reusability) compliance scoring. Checks for resolvable IRIs, machine-readable formats, standard annotation properties, license declarations, versioning, and metadata completeness.

### HermiT — OWL 2 DL Consistency
Loads the combined Turtle into `owlready2` and runs the HermiT reasoner (requires Java on the host). Reports:
- Whether the ontology is satisfiable (no unsatisfiable classes)
- All inferred axioms (subclass inferences the reasoner derives)
- Any inconsistencies with a hint about which axioms conflict

### APV — Annotation Property Verification
Runs the **APV** tool (developed by Rafael H. Petry, MSc CS, UFRGS) locally against the combined Turtle. APV reads `apv:` annotation constraints declared in the ontology header itself and checks all classes against them. COPI declares three constraints:

| Constraint | Value | Effect |
|---|---|---|
| `apv:GlobalMinLanguageCoverage` | `en pt` | Every checked annotation must exist in both English and Portuguese |
| `apv:ClassURIFormationRule` | `COPI_[0-9]{7}\|[A-Z][A-Za-z0-9]*` | Flags classes whose IRI does not follow the COPI naming pattern |
| `apv:ClassMinAnnotationCoverage` | `rdfs:label` | Every class must carry `rdfs:label` in both `@en` and `@pt` |

Violations (e.g., missing Portuguese labels on helper classes) are shown per check with collapsible details. Adding more `apv:` annotations to `copi-edit.owl` or to the Turtle generation extends the checks automatically. Tool source: [rhpetry/Web-APV](https://github.com/rhpetry/Web-APV).

### Competency Questions
The verify page also shows the CQ coverage dashboard: which competency questions are linked to validated classes, their satisfaction status (pending / satisfied / not satisfied), and the formal expression used to test each one.

---

## Divergence Matrix (`/enrich/divergences`)

Detects and visualises semantic divergences between how different industrial standards define the same concept. Divergences are auto-detected on every new enrichment and classified into five types:

| Type | Name | Description |
|------|------|-------------|
| T1 | Categorical Placement | Standards place the concept under incompatible parent categories |
| T2 | Granularity | One standard treats it as atomic; another decomposes it into parts |
| T3 | Identity Criteria | Standards use different identity criteria (function vs. topology vs. properties) |
| T4 | Topological vs. Mereological | Disagreement on whether spatial or part-whole relations are defining |
| T5 | Implicit Function | No source formally axiomatizes the identity-giving function |

The dashboard shows a cross-standard divergence matrix grouped by cluster and type. Per-divergence resolution notes can be recorded. The full matrix can be **exported as a LaTeX table** for inclusion in publications (`/divergences/export-latex`).

---

## Alias Manager (`/enrich/api/aliases`)

Detects potential duplicate or alias clusters using string similarity across all enriched labels. Pairs above a configurable threshold (default 0.75) are surfaced as proposals. Each proposal can be accepted (marking the clusters as aliases of each other) or rejected. Accepted aliases are shown as `skos:altLabel` in the OWL export. Clusters with pending alias proposals are flagged in the dashboard grid.

---

## Consequence Viewer (`/enrich/consequences`)

A graph view of the ontology's class hierarchy and entailments — all validated classes rendered as a force-directed graph showing `SubClassOf` edges and inferred relationships. Useful for quickly spotting structural problems (disconnected subgraphs, unexpected subsumptions).

---

## Ontology Q&A (`/enrich/qa`)

A Claude Haiku-powered chat interface that answers natural-language questions about the ontology's formal content. The context injected into every request is built from the live validated classes — their definitions, axiom modes, genus, differentia, and parts. Answers are grounded in what is formally stated (open-world assumption is explicitly communicated), and usage is logged for token/cost tracking. Responds in English or Portuguese depending on the question.

---

## Relations Manager (`/enrich/relations`)

Manages the OWL object and datatype properties defined in COPI (as opposed to the BFO/IOF-Core properties it reuses). Each property record stores:

- IRI, label (EN + PT), property type (ObjectProperty / DatatypeProperty)
- Domain, range, parent property (`rdfs:subPropertyOf`)
- Characteristics: functional, symmetric, transitive, inverse
- Natural language definition (EN + PT) and rationale

Properties appear in the generated OWL and in the static documentation.

---

## Export Pipeline

### Per-class Turtle (`/{id}/turtle`)
Downloads an individual class's axioms as an OWL/Turtle file — useful for quick inspection or import into Protégé.

### Combined Turtle (`/ontology.ttl`)
All validated/exported classes in a single Turtle file with proper ontology header, `owl:imports`, IOF annotation vocabulary, and `dcterms:contributor` / `skos:scopeNote` metadata.

### ODK Export (`/export/odk.owl`)
Generates `copi-edit.owl` in **OWL Functional Syntax** — the exact format required by ODK as its edit file. The file is complete and self-contained:
- `Ontology(...)` wrapper with version IRI (`/YYYY-MM-DD`) and `owl:versionInfo`
- `Import(...)` declarations for BFO 2020 and IOF-Core only
- `Class(COPI_XXXXXXX ...)` declarations with stable 7-digit IRIs, labels, NL definitions, FOL axioms, and IOF annotations
- `SubClassOf` / `EquivalentClasses` axioms translated from the enrichment steps
- `DisjointWith` declarations
- Five annotation properties (COPI_0000045–0000049)

### GitHub Push (`/export/github` — POST)
Pushes the ODK file and the static documentation to the GitHub repository as a **pull request** against `main`:

1. Creates a timestamped feature branch (`enrichment/YYYYMMDD-HHMMSS`)
2. Commits `src/ontology/copi-edit.owl` (full replace)
3. Commits all `docs/` HTML files
4. Opens a PR with class list, docs file count, and instructions for the reviewer
5. Marks all included enrichments as `exported` in the database

ODK CI (`.github/workflows/qc.yml`) runs `make test` automatically on the PR. The ontology maintainer reviews the diff and merges when QC passes. Requires a GitHub PAT with `repo` and `pull_request` write scope.

### Static Documentation Export

`generate_static_docs()` produces self-contained HTML pages hosted at `https://www.inf.ufrgs.br/ontologies/copi/docs`:

- **`docs/docs.html`** — overview with hero stats, class index table, BFO-root-grouped cards, and relations section
- **`docs/classes/COPI_XXXXXXX.html`** — per-class page with NL definitions (EN/PT), FOL theory, OWL/Turtle source, all five decision-log steps, process signature, disjointness, source definitions from the aggregator database, and a Quick Facts sidebar

All pages use Bootstrap 5 (CDN) and inlined CSS — no dependency on the live server. A live preview is available at `/enrich/export/docs`.

### Backup (`/enrich/backup`)
Downloads the current `enrichment.db` as a timestamped ZIP file — useful before migrations or when moving between environments.

---

## Class Documentation (`/enrich/docs`, `/{id}/doc`)

The live documentation pages render the same content as the static export but served directly from the database. Useful for sharing links with collaborators before a GitHub push. The overview page groups classes by BFO root with stats (total classes, relations, axiom count); each class page shows the full decision trail plus source definitions in the sidebar.

---

## Evaluation Metrics (`/enrich/metrics/`)

A read-only API that surfaces the interaction data collected silently during normal ontologist work — designed for reporting in a journal paper. No UI; no performance impact; errors never propagate to the user.

### What is recorded

| Event | Trigger |
|-------|---------|
| `open` | Ontologist opens a class detail page |
| `save` | Any field update (records which fields changed) |
| `step_review` | Expert accept / dispute / revise on a step |
| `rerun_request` / `rerun_complete` | Before / after a re-run LLM call |
| `axiom_mode_change` | Ontologist switches `necessary` ↔ `equivalent` ↔ `mixed` |
| `export_mark` | Class is marked `validated` or `exported` |
| `turtle_preview` | Per-class Turtle download |

Two **axiom snapshots** are stored: one immediately after the LLM call (`llm_initial`) and one when the class is validated (`final_export`). These enable computing how much the ontologist changed the LLM proposal.

### Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /enrich/metrics/summary` | Per-class metrics for all validated/exported classes |
| `GET /enrich/metrics/export?format=csv\|json` | File download for pandas analysis |
| `GET /enrich/metrics/class/{id}` | Detailed per-class view: event timeline + axiom diff |
| `GET /enrich/metrics/aggregate` | Cross-class statistics: mean/median active time, acceptance ratio, HermiT %, IOF-completeness %, total cost, axiom mode distribution |

### Computed metrics

- **Active time** — sum of inter-event gaps shorter than 15 minutes (filters idle periods)
- **Acceptance ratio** — fraction of the five axiom steps unchanged from LLM initial to final export (0.0–1.0)
- **Turtle diff** — lines added/removed between initial and final Turtle
- **IOF-completeness** — whether a class carries NL definition, semi-formal axiom, FOL axiom, and bilingual labels

### Database tables (in `enrichment.db`)

| Table | Purpose |
|-------|---------|
| `eval_interaction_event` | Timestamped event log per enrichment |
| `eval_axiom_snapshot` | Turtle + step-data at `llm_initial` and `final_export` |
| `eval_verification_snapshot` | HermiT/OOPS! results and annotation flags at export time |

---

## API Usage Tracking (`/enrich/api-usage`)

Every LLM call (enrichment, scope classification, Q&A, translation) records input tokens, output tokens, and estimated cost (USD) against the model used. The usage page shows a per-run log and aggregate totals. Cost constants are in `enrichment_service.py` (`_COST_PER_MTOK`); defaults are Claude Sonnet 4 at $3/MTok input, $15/MTok output and Claude Haiku at $0.80/$4.00.

---

## Project Structure

```
config.py                       — SPARQL endpoints, paths, COPI IRI, scope notes
app/
  models.py                     — SQLAlchemy models (Term, Property, Synonym, Hierarchy, Mapping)
  database.py                   — SQLite at data/terms.db; init_db(), get_db()
  main.py                       — FastAPI app + router registration
  routers/terms.py              — Term browser: /, /search, /cluster, /terms/{id}
  routers/ontology.py           — Ontology metadata home and competency questions: /, /requirements
  static/isa5_1/                — ISA 5.1-2022 P&ID symbols (SVG/PNG, bundled in image)
  templates/                    — Jinja2 + Bootstrap 5 (base, index, search, cluster, term)
parsers/
  base.py                       — ParsedTerm / ParsedProperty dataclasses; BaseParser ABC
  iso15926.py                   — SPARQL or local RDF/OWL files
  posc_caesar.py                — SPARQL → rds.posccaesar.org/ontology/sparql
  cfihos.py                     — Excel parser (Extended RDL + Core V2)
  dexpi.py                      — Python DSL from GitLab
  slb_glossary.py               — JSON-LD from SLB public page
  iso14224.py                   — PDF parser (pdfplumber)
  onepetro_glossary.py          — JSON cache from Playwright scrape
scripts/
  ingest.py                     — Typer CLI: ingest all/selected sources into terms.db
  fetch_onepetro_glossary.py    — Playwright scraper for OnePetro (run once)
enrichment/
  enrichment_service.py         — LLM calls, DB CRUD, OWL generation, FOL generation,
                                  scope classification, static docs, token tracking,
                                  validation tests, snapshot/history, divergence detection,
                                  alias detection
  enrichment_routes.py          — All FastAPI routes under /enrich/
  prompts.py                    — System + user prompt templates (five-step method)
  ontology_service.py           — rdflib parser for BFO 2020 + IOF-Core; in-memory index
  verify_service.py             — OOPS!, FOOPS!, HermiT consistency, APV, CQ summary
  apv/                          — APV annotation property verification package (embedded)
  schema_enrichment.sql         — DB schema (enrichment, copi_relation, divergence_log,
                                  cluster_alias, competency_questions, queue, snapshots,
                                  qa_log, annotations, eval_interaction_event,
                                  eval_axiom_snapshot, eval_verification_snapshot)
  evaluation_metrics.py         — Fire-and-forget helpers: log_event, take_axiom_snapshot,
                                  take_verification_snapshot, compute_active_time_minutes,
                                  compute_axiom_diff
  metrics_routes.py             — Read-only metrics API: /summary, /export, /class/{id}, /aggregate
  templates/
    enrichment_dashboard.html   — Cluster grid, scope panel, export buttons
    enrichment_detail.html      — Five-step editor with FOL panel + expert review
    enrichment_doc.html         — Live per-class documentation page
    enrichment_history.html     — Version history viewer
    enrichment_queue.html       — Batch queue dashboard
    ontology_overview.html      — Live ontology docs grouped by BFO root
    ontology_browser.html       — BFO 2020 + IOF-Core class browser
    verification.html           — OOPS! / FOOPS! / HermiT / APV results dashboard
    divergence_matrix.html      — Cross-standard divergence matrix dashboard
    consequences.html           — Class hierarchy consequence graph
    qa.html                     — Ontology Q&A chat interface
    relations.html              — Object/datatype property manager
data/
  terms.db                      — Aggregated terms (bundled in Docker image)
  enrichment.db                 — LLM proposals, expert reviews, COPI IDs (never delete)
  raw/                          — Source files (git-ignored)
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key (`sk-ant-…`) |

See `.env.template` for the full list.

---

## Makefile Commands

```
make install          Create .venv and install dependencies
make run              Start the web app on port 8765
make ingest           Ingest all sources into terms.db
make ingest-cfihos    Ingest a single source (replace 'cfihos' with any source name)
make up               Build image and start container (http://localhost:8765)
make down             Stop container — data in ./data/ is never deleted
make logs             Follow container logs
make clean            Remove .venv and __pycache__
```

---

## Known Issues

- **ISO 15926-4 SPARQL** — both public endpoints are currently unreachable. Place local RDF/TTL/OWL files in `data/raw/iso15926/` to import offline.
- **OnePetro scraping** — the site uses Cloudflare JS challenges; standard HTTP requests fail. Use `scripts/fetch_onepetro_glossary.py` (Playwright) to refresh the cache.
- **OOPS! external imports** — OOPS! cannot resolve BFO/IOF-Core IRIs. `owl:imports` is stripped before submission, which causes P34 (untyped class) pitfalls for IOF-Core classes. These are expected and can be ignored.
- **HermiT** — requires Java on the host (or inside Docker). Without Java, the consistency check returns a graceful error message rather than crashing.
- **Jinja2 3.1.5+ / Python 3.14** — `env.globals` dict causes unhashable type in LRUCache. Fixed by pinning `jinja2==3.1.4` and `cache_size=0` on the Jinja2 Environment.

---

## Adding a New Source

1. Add a parser in `parsers/<name>.py` inheriting `BaseParser`, implementing `parse() → list[ParsedTerm]`
2. Register in `parsers/__init__.py` and `scripts/ingest.py` (`PARSERS` dict)
3. Add label, Bootstrap colour, and scope flag in `app/routers/terms.py` (`SOURCE_LABELS`, `SOURCE_COLORS`, `SOURCE_SCOPE`)
4. Create `data/raw/<name>/`

---

## Research Context

This tool supports a PhD thesis on building a core OWL ontology of oil & gas production plants at INF/UFRGS, Brazil.

- **Research group:** INF-UFRGS-Ontologies
- **Project:** OntoKG / Petrobras
- **Funding:** CNPq INF-UFRGS-ENERGIA
- **Ontology IRI:** `https://www.inf.ufrgs.br/ontologies/copi`
- **ODK repository:** [INF-UFRGS-Ontologies/COPI](https://github.com/INF-UFRGS-Ontologies/COPI)
- **Documentation:** `https://www.inf.ufrgs.br/ontologies/copi/docs`

## Acknowledgments

Thanks to Mara Abel (INF/UFRGS) for supervising the research this tool supports, and to Vicente Pianezzola for his work on deployment.
