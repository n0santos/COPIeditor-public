# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Origin

This project is an extended copy of the local project **agregador-termos**. Changes made here should not be back-ported to the original unless explicitly intended. When in doubt, treat this as an independent project.

## Project purpose

PhD research tool that aggregates terms, definitions, and properties from industrial standards as input for building a core OWL ontology of oil & gas production plants. Active sources: **ISO 15926-4**, **POSC Caesar RDL**, **CFIHOS**, **DEXPI**, **SLB Glossary**, **ISO 14224**, **ISA-5.1**, **OnePetro E&P Glossary**, and **PPDM**.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Common commands

**Ingestion** (populates `data/terms.db`):
```bash
python -m scripts.ingest                            # all sources
python -m scripts.ingest --source cfihos            # single source
python -m scripts.ingest --source cfihos --source dexpi --clear
```

> **IMPORTANT — two separate databases:**
> - `data/terms.db` — ingestion pipeline only (terms, synonyms, properties, hierarchy). Safe to delete and re-create.
> - `data/enrichment.db` — LLM enrichment proposals, expert reviews, token usage. **Never delete this file.** Re-running ingestion does NOT touch it.

**Web app** (http://localhost:8765):
```bash
docker compose up --build -d   # rebuild image and start
docker compose up -d           # start without rebuilding
docker compose restart         # restart without rebuilding (Python/template changes need --build)
```

## Architecture

```
config.py                  — SPARQL endpoints, paths, pagination
app/
  models.py                — Term, Property, Synonym, Hierarchy, Mapping (SQLAlchemy)
  database.py              — SQLite at data/terms.db; init_db(), get_db()
  main.py                  — FastAPI app, startup hook
  routers/terms.py         — HTML routes: GET /, /search, /cluster, /terms/{id}
  templates/               — Jinja2 + Bootstrap 5 (base, index, search, cluster, term)
parsers/
  base.py                  — ParsedTerm / ParsedProperty dataclasses; BaseParser ABC
  iso15926.py              — SPARQL (endpoint currently down) or local RDF files
  posc_caesar.py           — SPARQL → rds.posccaesar.org/ontology/sparql (OWL, not SKOS)
  cfihos.py                — Excel parser, handles both Extended RDL and Core V2 formats
  dexpi.py                 — Fetches Python DSL files from GitLab; parses class/property defs
  slb_glossary.py          — Fetches JSON-LD embedded in SLB glossary HTML (~4 800 terms)
  iso14224.py              — PDF parser: section 3 definitions + Table A.4 equipment classes
  isa5_1.py                — PDF parser: section 3 definitions + Table 4.1 letter codes + tag abbreviations
  onepetro_glossary.py     — JSON cache parser (Cloudflare-protected page; scrape offline)
  ppdm.py                  — PDF parser: ~9 core well-component definitions ("What is a Well?")
scripts/ingest.py          — Typer CLI; calls parsers → upserts DB; Rich progress output
data/raw/
  iso15926/                ← .rdf/.ttl/.owl  (SPARQL endpoint is currently unreachable)
  posc_caesar/             ← .rdf/.ttl/.owl  (or leave empty to use SPARQL)
  cfihos/                  ← .xlsx files (required — not publicly available)
  dexpi/                   ← .py copies from GitLab (or leave empty to auto-fetch)
  slb_glossary/            ← optional local cache: slb_glossary.json or *.html
  iso14224/                ← ISO14224-2016.pdf (required — not publicly available)
  isa5_1/                  ← ISA-5.1-2022.pdf (required — not publicly available; any *.pdf works)
  onepetro_glossary/       ← onepetro_glossary.json (required — generate via scripts/fetch_onepetro_glossary.py)
  ppdm/                    ← "What is a Well?" PDF (required — not publicly available; any *.pdf works)
```

## Data model key points

- Every term has a unique `(source, source_id)` pair; ingestion upserts on this key.
- `Hierarchy` stores `subClassOf` edges within a source.
- `Mapping` is for cross-source equivalences; currently empty — for future ontology alignment work.
- CFIHOS and DEXPI terms carry `Property` rows; ISO 15926-4 and POSC Caesar typically do not.

## Search and clustering

- Search ranking (exact → starts-with → contains → definition-only) is implemented via SQLAlchemy `case()` in `routers/terms.py`.
- Results are grouped by `_normalize_label()` which lowercases and depluralize the last word (`_depluralize()`), so "Pumps" and "pump" cluster together.
- A **boost query** runs after pagination to pull in plural/singular variants that ranked outside the current page window but share a normalized key with a term on the page.
- `/cluster?name=<label>` renders a dedicated aggregate page showing all sources for a normalized term.

## Source-specific notes

**POSC Caesar**: endpoint moved from `data.posccaesar.org/sparql` to `rds.posccaesar.org/ontology/sparql`. Now uses OWL (`owl:Class` + `rdfs:subClassOf`), not SKOS. Namespaces: `plm/rdl/PCA_*` and `lis14/rdl/`.

**ISO 15926-4**: both previously known public SPARQL endpoints are currently unreachable. Place local RDF/TTL/OWL files in `data/raw/iso15926/` to import offline.

**CFIHOS**: two complementary files are expected — Extended RDL (`C-ST-001-*`) as primary, Core V2 (`CORE-CFIHOS-V2.0-*`) as supplement. Parent classes are resolved by name, not ID. Properties are joined from the `property` sheet.

**DEXPI**: source is the Python DSL at `gitlab.com/dexpi/Specification`. Files are fetched at runtime from GitLab (6 modules). Place local `.py` copies in `data/raw/dexpi/` to run offline. The DEXPI PDF in `data/raw/dexpi/` is not parsed — the GitLab source is authoritative.

**SLB Glossary**: the public page embeds a full JSON-LD block (`DefinedTermSet`) with ~4 800 terms — no API key needed. Falls back to a local `*.json` or `*.html` file in `data/raw/slb_glossary/` if present.

**ISO 14224**: PDF parser using `pdfplumber`. Extracts section 3 (~58 definitions) and Table A.4 (~79 equipment classes). Term boundaries in section 3 are detected via a garbled "SOURCE" regex (`_SOURCE_RE`) — pdfplumber interleaves the next term number into the word "SOURCE" (e.g., `[3S.6OURCE:` marks the boundary before term 3.6). Equipment class categories are detected by cropping the category column (x=0..130) and finding `(A.2.X)` annex references, then using `find_tables()` row bboxes for precise per-row category assignment. `term_type` is set to `"Equipment — {category}"`. Requires `pip install pdfplumber`.

**ISA-5.1**: PDF parser (`pdfplumber`) over ISA-5.1-2022 (Instrumentation Symbols and Identification). Extracts section 3 definitions (~60 instrument/automation terms, `term_type="ISA Definition"`), the Table 4.1 letter-code table (first-letter and succeeding-letter meanings, `term_type="ISA Letter Code — ..."`), and built-in tag abbreviation expansions derived from the letter codes (e.g. FCV = Flow Control Valve, `term_type="ISA Tag Abbreviation"`). Graphical P&ID symbols are not extractable from PDF and are not included. Place the PDF at `data/raw/isa5_1/` (any `*.pdf` works).

**OnePetro E&P Glossary**: ~5 200 terms originating from SPE's PetroWiki project, hosted at `onepetro.org/pages/glossary`. The page is Cloudflare-protected, so a local JSON cache is required — generate it with `python -m scripts.fetch_onepetro_glossary` (or a manual Playwright scrape) and place it at `data/raw/onepetro_glossary/onepetro_glossary.json`.

**PPDM**: PDF parser (`pdfplumber`) over the PPDM Association's "What is a Well?" (R-2.4, September 2014). Extracts ~9 core well-component definitions (Well Set, Well, Well Origin, Wellbore, Wellbore Segment, Wellbore Contact Interval, Wellbore Completion, Wellhead Stream, Well Reporting Stream), each combining Definition + Key Concept(s) + Clarification. Place the PDF in `data/raw/ppdm/` (any `*.pdf` file found there is used).

## Enrichment methodology

The `/enrich/` workbench applies a 5-step BFO/IOF-Core axiomatization method to equipment clusters:

1. **Identity-giving function** — subtype of `DesignedFunction` that realises in a `PlannedProcess` subtype.
2. **Genus definition (genus proximum)** — the most specific known superclass, not just an IOF-Core root. Stored as two fields: `genus` (e.g. "Valve") and `genus_bfo_root` (Assembly / MaterialArtifact / EngineeredSystem). Parent candidates are sourced from the hierarchy table and shown to the LLM.
3. **Differentia** — the OWL restriction(s) distinguishing the class from its genus siblings (`differentia_expression` / `differentia_nl`).
4. **Necessary parts** — `hasComponentPartAtAllTimes` restrictions universal to every instance.
5. **Process participation signature** — typed input/output participants and transformation type; grounds disjointness. The process type is derived from the controlled `transformation_kind` field (snake_case vocabulary in `TRANSFORMATION_KINDS_CONTROLLED`), **not** the free-text `transformation` prose.

**Axiom mode is determined by classification basis:**
- `functional` basis (control valve, check valve, separator) → `equivalent` — the DesignedFunction is both necessary and sufficient; enables automatic reasoner classification.
- `constructive` basis (ball valve, gate valve, reciprocating compressor) → `necessary` — structural differentia are necessary conditions only; OWA makes equivalence unsafe (false positives).
- `both` (centrifugal pump) → `mixed` — functional side uses equivalence, constructive differentia is necessary-only.

## Interactive enrichment pipeline (Claude Code session)

A batch enrichment pipeline runs interactively inside a Claude Code session, avoiding separate Anthropic API costs. Each session can process ~20–30 terms before context fills.

### Workflow

**Step 1 — find candidates** (terms in `terms.db` not yet in `enrichment.db`):
```sql
ATTACH DATABASE 'data/enrichment.db' AS edb;
WITH RECURSIVE fo_tree AS (
  SELECT id FROM terms WHERE id = 7870  -- FunctionalObject root in ISO 15926-4
  UNION ALL
  SELECT h.child_term_id FROM hierarchy h JOIN fo_tree ft ON ft.id = h.parent_term_id
)
SELECT t.id, t.preferred_label, t.definition,
       COUNT(DISTINCT t2.source) AS source_count,
       GROUP_CONCAT(DISTINCT t2.source) AS sources
FROM terms t
JOIN fo_tree ON fo_tree.id = t.id
LEFT JOIN terms t2 ON LOWER(t2.preferred_label) = LOWER(t.preferred_label)
WHERE t.source = 'iso15926'
  AND NOT EXISTS (SELECT 1 FROM edb.enrichment e
                  WHERE LOWER(e.cluster_label) = LOWER(t.preferred_label))
GROUP BY t.id ORDER BY source_count DESC;
```

**Step 2 — fetch cross-source definitions** for the chosen batch:
```sql
SELECT preferred_label, source, definition, term_type
FROM terms
WHERE LOWER(preferred_label) IN ('stack','conveyor', ...) -- chosen labels
ORDER BY preferred_label, source;
```
The batch is drawn from `terms.db` cross-source hits only. For a term with `source_count = 1`
(the exact case this method exists to help — most ISO 15926-4 FunctionalObject terms have no
cross-source match at all), Step 2 returns nothing and Step 2b below is not optional — it's the
only source of secondary evidence.

**Step 2b — secondary (correlated standard / curated dictionary), always attempted first**: when
the primary definition alone is thin (tautological differentia, no structural detail), search for
a correlated technical standard or curated domain dictionary that describes the same artifact
class under another lens (dimensional, functional, safety) — **before** ever reaching for
tertiary. Three rounds of held-out testing (`experiments/2026-09-05-heldout-lineage/`,
`experiments/2026-09-06-corrections-c3-verdict/`) converged on one finding above all others:
forcing tertiary "just in case" is what produces redundant or genus-contaminating content (see
2c); the single highest-leverage step in the whole method is finding the *right* secondary source.
A real, freely-hostable secondary source exists more often than it looks — DNV standards (free
since 2010, try `rules.dnv.com` direct PDF paths), NIST Special Publications (always free,
`nvlpubs.nist.gov`), NORSOK mirrors, and ISO/IEC "sample preview" PDFs at
`cdn.standards.iteh.ai` (short dimensional/vocabulary/scope-only standards sometimes appear nearly
complete in the free sample) are worth trying before falling back to an encyclopedia.

*Extraction discipline — ask by category, not "quote verbatim" in general.* Explicitly check the
source against each of these 7 categories and tag whatever you extract with the one it belongs to:
`structure` (parts/components), `profile` (shape/cross-section/geometry), `mechanism` (causal
how-it-works), `function` (purpose), `application` (context/domain of use), `subtype` (documented
variants), `parameter` (characteristic quantities, thresholds, grades/classes). This is not
busywork: in the held-out tests, every documented "the info was on the page but nobody asked for
it" miss (an involute tooth profile, an RC circuit's structure, a piston application) was fixed by
asking per-category instead of asking generically. If a category is genuinely absent from a
source, that's a real finding — note it, don't silently skip it.

*Access discipline — prefer `WebFetch` with an explicit "quote verbatim, no paraphrasing" prompt
over trusting `WebSearch`'s own synthesized summary.* When `WebFetch` fails to extract readable
text from a PDF ("corrupted/encoded/compressed stream"), do **not** mark it failed yet — `WebFetch`
still saves the binary PDF locally even when its own extraction fails (the save path is in the tool
result). Run `pdftotext <saved-path> -` via Bash first; if that returns nothing (a pure image scan,
not a compressed-text stream), try `pdftoppm` + `tesseract` OCR before giving up. Across both
held-out rounds this recovered over a third of all evidence collected — PDFs from real standards
bodies are usually not actually inaccessible, just compressed or scanned in a way the tool's own
summarizer can't read. Only mark `access: "failed"` after trying both fallbacks and getting
nothing usable; never substitute the search engine's own summary for a failed fetch. Record every
source used in `source_definitions_used` as:
```json
{"tier": "primary" | "secondary" | "tertiary",
 "source_type": "standard" | "curated_dictionary" | "encyclopedia" |
                 "manufacturer_page" | "patent" | "web_glossary",
 "citation_mode": "verbatim" | "summary",
 "access": "raw_fetch" | "recovered_after_403" | "failed",
 "categories_covered": ["structure", "parameter", ...],
 "source": "iso15926" | "ISO 7241" | "John Zink" | "US4526689A" | ...,
 "term": "...",   // only when resolvable in terms.db (primary/secondary standard entries)
 "url": "...",    // only for entries not in terms.db
 "quote": "..."}
```
The `terms.db`-resolved entry that anchored the cluster (today always the `iso15926` term from
Step 1) is `tier: "primary"`; every other entry is `tier: "secondary"` unless it's a
manufacturer/patent/web-glossary find (see 2c). Set the row's `secondary_coverage` field once 2b
is done by calling `compute_secondary_coverage(source_definitions_used)` in
`enrichment_service.py` — do **not** eyeball it. The rule is deterministic (`"full"` requires a
`tier:"secondary"` entry with `citation_mode:"verbatim"` whose `categories_covered`, unioned
across all secondary entries, spans ≥4 of the 7 categories; any secondary entry short of that is
`"partial"`; no secondary entry at all is `"none"`) precisely so the field stays comparable across
runs instead of becoming a per-session judgment call.

**Contradicts vs. supplements the primary definition.** Occasionally the evidence doesn't just
fill a gap in the ISO 15926-4 primary definition — it contradicts it (the primary's own genus or
scope reads as wrong once a real correlative standard is in hand). This happened twice in held-out
testing: a scope mismatch (a lead standard turned out not to define the queried term's genus at
all) and an over-narrow primary (a real standard's own working definition was broader than what
the ISO 15926-4 text implied). When this happens, record it in `primary_definition_conflict`
(free text describing the discrepancy) — this is different from, and doesn't go in,
`differentia_rationale` or `reviewer_notes`; it needs its own field so it surfaces as a distinct
signal in the `/enrich/` UI (a warning banner on the detail page, a marker on the dashboard list)
rather than getting lost in prose. Leave it `NULL` when evidence only supplements the primary
definition, which is the ordinary case. This is likely the pipeline's most immediate practical
payoff beyond axiomatization itself: a free byproduct audit trail for cases where ISO 15926-4's
own text may need a correction filed against it, not just an enrichment recorded around it.

**Step 2c — tertiary (manufacturer / patent / web glossary), only if a gap remains**: after 2b,
if a discriminating condition still has no grounding (e.g. an operation mode or retention
mechanism that no standard states structurally), search for it — this is where tertiary sources
earn their keep; forcing tertiary on every term mostly produces redundant confirmation of what
secondary already gave, or worse, surfaces an implementation-specific detail of one subtype that
doesn't generalize. Two safeguards, both required before a tertiary finding may back an axiom:

1. **Triangulation** — at least 2 independent tertiary entries (`tier: "tertiary"`) are required.
   Independence key: for `source_type: "patent"`, the patent number itself (two different patents
   hosted on the same domain, e.g. `patents.google.com`, still count as independent; the same
   patent cited twice does not); for everything else, the URL's registrable domain. Enforced by
   `validate_tertiary_triangulation()` in `enrichment_service.py`, called from
   `update_enrichment_route()` (save-time, 422 on failure) and from the `push_to_github()`
   preflight.
2. **Genus-wide applicability check** — before writing a tertiary finding to `necessary_parts`,
   ask: does *every* instance of the genus have this, or only some documented
   implementations/subtypes? If uncertain, write it to `candidate_parts` instead (same element
   shape as `necessary_parts` — `{"name": ..., "source_quote": ...}`) — it stays visible to the
   reviewer in the `/enrich/` UI ("Candidate parts (unconfirmed)", with a promote button) but is
   never fed to OWL generation. This caught real cases in testing: a storage tank's "frangible
   roof joint" and a check valve's specific disc-centering mechanisms both triangulated cleanly
   across patents but are subtype-specific, not universal to the genus.
3. **Automatic hedge check (`validate_part_universality()`)** — the held-out tests found that this
   judgment call is the one place self-assessment during extraction reliably misses things: a
   part's own source can already hedge it ("typically", "usually", "in most designs", "commonly",
   a specific product/model/patent name) and still get written to `necessary_parts` unblocked,
   because the hedge was noticed when reasoning about the axiom but never propagated back to where
   the part gets filed. `validate_part_universality()` in `enrichment_service.py` scans every
   `necessary_parts[].source_quote` for hedge language and returns a 422 (same call sites as
   `validate_necessary_parts_quotes`) telling you to move it to `candidate_parts` instead. It
   exempts hedges that qualify an incidental attribute of a part already stated to exist ("the
   Bonnet is *typically* dome-shaped" hedges the shape, not whether every instance has a Bonnet)
   — retroactively run against all 78 named `necessary_parts` already in `enrichment.db`, it fired
   on 1 (1.3%), and that one was a genuine existence hedge ("*Usually* consisting of braided
   cables..."). Re-run that check (see `tests/test_part_universality_guard.py` for the exact
   examples) if you ever change the hedge or exemption word lists, so this stays a low, honest
   trigger rate rather than a source of nuisance rejections on the normative-correlative text
   Step 2b now searches for more aggressively.

   **This check is not a substitute for the rest of the genus-wide review.** In the held-out
   experiment that motivated it, 21 of 138 claims needed a level correction on adversarial review;
   only 5 of those 21 were the exact claim↔axiom inconsistency this mechanical check targets. The
   other 16 (mostly `web-specialist`-sourced claims, and `normative-correlative` claims hedged in
   ways this word list doesn't catch) had no automatic safeguard at all and were only caught by a
   second, independent reader. Passing `validate_part_universality()` means one specific failure
   mode was checked, not that the part is confirmed genus-wide — the human review step in
   `/enrich/` is still where the other ~75% of that error budget gets caught, and treating this
   check as sufficient on its own would silently drop that coverage.

ODR-022 still applies unchanged: a tertiary source never admits a *new* standard term — Step 1's
`terms.db` anchor is what admits a term into scope; tertiary only enriches a term already admitted
that way.

**A methodological note on measuring this pipeline.** The held-out experiments used recall against
a single independently-chosen "rich" reference definition to validate the method during
development. That metric turned out to measure something narrower than it looks like: how much the
*specific* secondary source the search happened to land on overlaps in *angle* with the *specific*
reference definition someone else happened to pick — two independently arbitrary choices. Two
documented cases (`oil_immersed_type_transformer`, `tower_silo` in
`experiments/2026-09-06-corrections-c3-verdict/`) found a completely real, legitimate normative
source and still scored recall under 0.2 against the held-out reference, because the source
covered a different — not worse — angle of the same artifact than the reference did. **Do not use
recall-against-a-single-reference as an acceptance metric for a real enrichment in production.**
It was a development-time tool for validating corrections to the method, not a quality gate for
individual proposals. What *is* worth tracking permanently in production is `secondary_coverage`,
the `access` value that worked per source, and `categories_covered` per source (see the Step 2b
JSON shape) — these describe the pipeline's own behavior and don't depend on picking a reference
definition at all.

**Step 3 — generate and insert proposals**: Claude produces `INSERT INTO enrichment (...)` statements with all 5 BFO/IOF-Core axiomatization fields populated. Inserted with `status='proposed'` and `llm_model='claude-sonnet-4-6'`.

**Step 4 — expert review** in the `/enrich/` web UI as usual.

### Fields populated per proposal

| Field | Content |
|---|---|
| `cluster_label` | lowercase, space-separated label |
| `label_pt` | Brazilian Portuguese label |
| `function_name` / `process_name` | CamelCase BFO DesignedFunction / PlannedProcess subtype |
| `genus` / `genus_bfo_root` | most specific known superclass + BFO root |
| `differentia_expression` | OWL restriction string |
| `differentia_nl` | natural language explanation |
| `axiom_mode` | `equivalent` (functional basis) or `necessary` (constructive) |
| `necessary_parts` | JSON array of `hasComponentPartAtAllTimes` parts, each vetted as genus-wide |
| `candidate_parts` | JSON array, same shape as `necessary_parts` — triangulated tertiary findings not yet vetted as genus-wide (see Step 2c); never reaches OWL generation until a reviewer promotes it |
| `process_signature` | JSON with typed inputs, outputs, transformation |
| `nl_definition_en` | proposed natural language definition |
| `source_definitions_used` | JSON array of layered-source provenance entries — see Step 2b/2c for the `{tier, source_type, citation_mode, access, categories_covered, source, term/url, quote}` shape |
| `secondary_coverage` | `"full"` \| `"partial"` \| `"none"` — computed by `compute_secondary_coverage()`, not eyeballed; a permanent pipeline-health signal, not tied to any reference definition (see the methodological note after Step 2c) |
| `primary_definition_conflict` | Free text, `NULL` in the ordinary case — set only when evidence contradicts the ISO 15926-4 primary definition, not just supplements it (see Step 2b) |

### Differentia correction rules (applied when validating existing proposals)

When reviewing `proposed` clusters, apply these fixes before marking `validated`:

1. `∃hasFunction.X` → `∃bearerOf.X` — object-level axioms use `bearerOf`, not `hasFunction`
2. `∃hasInput.X` / `∃hasOutput.X` in object axiom → `∃participatesIn.XProcess` — these are process-level relations; replace with the `process_name` field value
3. Function class in differentia differs from `function_name` field → align to `function_name`
4. `∃realizes.X` where X is a function/capability → `∃bearerOf.X`

Always write to `enrichment_history` before any UPDATE:
```sql
INSERT INTO enrichment_history (enrichment_id, snapshot_at, trigger, snapshot_json)
SELECT id, datetime('now'), 'manual_validation',
  json_object('cluster_label',cluster_label,'status',status,
              'differentia_expression',differentia_expression,'updated_at',updated_at)
FROM enrichment WHERE id = <id>;
```

## Publishing copi-enriched.owl to the COPI repo

After validating new enrichment entries (or changing `axiom_mode`, `genus`, or `function_name`), regenerate the OWL component and push it:

```bash
# From COPIeditor root (with .venv active):
python -m scripts.regen_enriched_owl
bash scripts/verify_owl.sh          # must pass — never with --skip-iri-gate

# Then in the COPI repo:
cd ../copi
git add src/ontology/components/copi-enriched.owl
git commit -m "feat(ontology): ..."
git push
```

### The `/enrich/` dashboard's Export → GitHub PR button

`enrichment_routes.push_to_github()` (`POST /enrich/export/github`) does the same thing as the
CLI steps above, as a PR instead of a direct push: it calls the exact same
`generate_enriched_owl_rdfxml()` (in `scripts/regen_enriched_owl.py`) to build the OWL, writes it
to `components/copi-enriched.owl`, then actually runs `bash scripts/verify_owl.sh` as its
preflight gate (plus an OOPS-critical check as an extra layer, since this route pushes
unattended) before opening the PR. It also regenerates `docs/docs.html` and every
`docs/classes/COPI_*.html` page via `generate_static_docs()`, and `requirements/cqs.csv`.

**`docs/docs.html` is the canonical filename** (not `docs/index.html` — that name was retired in
commit `25161dd` in the COPI repo; every back-link across all class pages was hand-fixed to point
to `docs.html` at the same time). If you ever touch `_overview_page()`, `_class_page()`, or
`generate_static_docs()`, grep for `"index.html"` first — reintroducing it silently orphans the
real file again, which is exactly what happened between 2026-07-13 and 2026-09-03: nobody
touched the generator, so the drift was invisible until someone actually ran the export.

**There must be exactly one ontology generator.** Until 2026-09-03, `generate_owl_functional()`
was a second, independent generator that only `push_to_github()` and `/enrich/export/odk.owl`
called — never the CLI path. It silently drifted out of sync with `regen_enriched_owl.py`'s
pipeline (no `copi-iri-map.tsv` remap, so 357 readable-name IRIs shipped unmapped; the
`copi-core`/`copi-vocab`/`copi-enriched` import chain was replaced with 915 inlined declarations)
because nobody was exercising it to notice. It was deleted; both the dashboard and the CLI now
call the same `generate_enriched_owl_rdfxml()`. **Never add a second one** — if the dashboard
needs OWL content, it calls into `scripts/regen_enriched_owl.py`, full stop.

### Deployment constraints (ODR-022)

**1. Nothing deploys with a readable-name IRI.** Every class in a published artifact carries a
numeric `COPI_*` IRI. Enforced by the numeric IRI gate in `scripts/verify_owl.sh` (Step 1b,
exit code 5). `copi-iri-map.tsv` is the **authoritative registry** — all allocation goes through
it, and the gate prints paste-ready rows at the next free number when it fails.

Because 427 stubs were already published, the gate runs as a ratchet:
`scripts/stub-iri-baseline.txt` grandfathers exactly those names, and anything not in it fails
immediately. Prune the baseline as ODR-022 lands — **remove the class from the ontology first,
then prune** — and when the file is empty the gate enforces zero. `--skip-iri-gate` is for local
iteration only; CI and the publish path must never pass it.

**2. Standard terms enter only via the enrichment pipeline.** A term from a source standard is
never admitted as a side effect of another entry's axioms. This applies to equipment/artifact
universals (which bear a `DesignedFunction`); participant types — portions, ICE, qualities —
are hand-authored vocabulary instead, since the 5-step method presupposes a function they do
not bear.

**Component parts are included**, and additionally keep their `hasComponentPartAtAllTimes`
relationship. A component is admitted when both hold: (a) it is a term in a source standard, and
(b) the standard **explicitly states it is a component of a particular equipment**, evidenced by
a verbatim `source_quote` in the owning entry's `necessary_parts`. Condition (b) is enforced by
the existing `validate_necessary_parts_quotes()` in `enrichment_service.py` — no second mechanism.
A part with no standard definition to ground it has nothing for the pipeline's source-definition
steps to work from and stays in `copi-vocab`.

**Processes are anchored in COPI-Core, and it is enforced.** An entry's process must reach one of
COPI-Core's operations (the 8 subclasses of Operation `COPI_0000001`, or `iof-core:MeasurementProcess`
for the measurement-instrument category) through its own `process_name` or its `process_parent`
chain — or record `core_operation_gap` (`out_of_scope` | `core_coverage_gap`, with rationale). Its
controlled `transformation_kind` must agree with the anchor (`KIND_TO_OPERATIONS` in
`enrichment/core_operations.py`; `fluid_transport`, `mechanical_power_transmission`,
`electrical_power_conversion`, `subsurface_access` have no operation). The Step 1 prompt lists the
operations generated from the TTL; the save route (422), the `push_to_github()` preflight and
`scripts/check_core_anchoring.py` in `verify_owl.sh` (exit 10, ratchet over
`scripts/core-anchoring-baseline.txt`) enforce it. `docs/findings/core-expansion-literature-scoping.md`
covers the uncovered clusters (power generation, electrical, mechanical power transmission).

**Participant types are enforced, not just documented.** A `process_signature` input/output type
must resolve to a class declared in `copi-core`/`copi-vocab`, a `copi-iri-map.tsv` redirect to
BFO / IOF-Core, or a validated equipment class. Otherwise `allocate_missing_iris()` would mint it a
COPI IRI — this is how 16 LLM-invented types (`MovingObject`, `Surface`, `SteelPipe`, …) were
published before the check existed. Enforced by `validate_participant_vocabulary()` at save time
(422 when the effective status is validated/exported), in the `push_to_github()` preflight, and by
`scripts/check_participant_vocabulary.py` in `verify_owl.sh` (exit 9; ratchet over
`scripts/participant-vocabulary-baseline.txt` — prune, never add). `auxiliary_class.status` is not a
safeguard: 74 of its 80 rows were bulk-validated by name pattern. The Step 5 prompt offers the same
closed vocabulary: `enrichment/participant_vocabulary.py` generates it from `copi-vocab.ttl` + the
redirect rows at render time (`prompts.render_system_prompt()`), and a test asserts every offered
name passes the gate. Never hand-list participant types in `prompts.py` again — add the class to
`copi-vocab.ttl` and it appears. When nothing fits, the LLM uses the nearest broader type and records
`participant_vocabulary_gaps` in the signature (shown on the detail page). To fix a flagged
signature, use the `model-participant` skill (`.claude/skills/model-participant/`): it inspects the
entry, looks up candidates, and writes through `apply_signature.py` (history snapshot, dry run by
default). Separately,
`allocate_missing_iris()` refuses any readable name that is a BFO / IOF-Core class (local name or
label) and asks for a redirect row instead — a class from another ontology never gets a COPI IRI.

**3. Module hosting follows provenance, not IRI number.**

| Component | Hosts |
|---|---|
| `copi-core` | paper core, `COPI_0000001–0000024`. **Frozen** — no pipeline output, no ODR additions |
| `copi-vocab` | everything *not* pipeline-produced and not core: participants, qualities, component parts, function/process **parents** |
| `copi-enriched` | everything pipeline-produced: enriched equipment universals and the per-entry function/process **leaves** generated from them |

IRI number does not imply module — `COPI_0000383–0000385` correctly live in `copi-vocab` despite
falling in the 066+ range. Allocation blocks are contiguous for bookkeeping only.

### COPI component structure (3 modules)

COPI ships as **three OWL components** with an import chain
`copi-enriched → copi-vocab → copi-core`:

- **`copi-core`** — the FOMI 2026 paper's core: intentionally **small and cross-domain**. Declares `COPI_0000001–0000024` (the 9 operation categories, 9 equipment categories, identity/analysis classes). Do **not** add domain-specific function/process classes here — keep it paper-aligned. (Pressure Vessel `COPI_0000090`, Heat Exchanger `COPI_0000092`, and Instrument `COPI_0000091` — same commit that added all three as ODR-018 structural anchors — were formerly hand-declared here, but their IRIs fall in the enriched 066–204 range and they are also entries in `enrichment.db`; they now live only in `copi-enriched` with their pipeline-generated functional-equivalent definitions — do not re-declare them here, or the reasoner sees two competing definitions for the same IRI. PV/HX were fixed in commit `b42a398`; Instrument's identical twin block sat right between them in the file and was missed until `verify_owl.sh` Step 1d below caught it, fixed 2026-09-03.)
- **`copi-vocab`** — the function parent hierarchy (ODR-006), process parent stubs, and participant type vocabulary (ODR-010). Declares `COPI_0000025–0000060` (flow-control / instrumentation / signal-transmission / safety-relief functions, their processes, and fillers like ControlSignal, ElectricalPower) **plus `COPI_0000383–0000385`** (ODR-020 qualities `ElectricalCurrent` / `MechanicalForce` / `MechanicalLoad`, added out-of-block because 025–065 was full — used as `bearer_of` targets). Imports `copi-core`.
- **`copi-enriched`** — the ~150+ enriched leaf equipment universals from the pipeline (`COPI_0000066–0000204`+). Imports `copi-vocab`.

Both `copi-core.ttl` and `copi-vocab.ttl` exist twice, kept byte-identical: `enrichment/ontologies/copi-context/` (this repo) and `src/ontology/components/` (COPI repo). Anything that reasons over `copi-enriched` **must load `copi-vocab` too** (not just `copi-core`), or the `COPI_0000025–0000060` classes appear absent — this is why `scripts/verify_owl.sh` merges both base modules.

`scripts/verify_owl.sh` Step 1d (added 2026-09-03, after the Instrument incident above) scans `copi-core.ttl`/`copi-vocab.ttl`/`copi-enriched.owl` for any numeric `COPI_*` IRI carrying axiom-bearing triples in more than one of the three, and fails the build (exit 7) if it finds one — this class of bug no longer requires a human to notice a stale-looking definition.

The script (`scripts/regen_enriched_owl.py`) applies four transformations:
1. Calls `generate_combined_turtle()` from `enrichment_service.py`.
2. Remaps readable-name IRIs → numeric COPI IRIs using `copi-iri-map.tsv`.
3. Removes all triples with subjects COPI_0000001–0000060 (declared in the base modules — `copi-core` for 001–024, `copi-vocab` for 025–060; re-declaring them causes BFO disjointness violations or conflicting `allValuesFrom` targets under ELK). Classes 066–204 have only bare `owl:Class` in the base modules and **must** carry their axioms from `copi-enriched.owl` — **except `COPI_0000383–0000385`** (ODR-020 qualities), which carry full axioms in `copi-vocab` despite falling in the 066+ numeric range; they are referenced only by numeric IRI (`bearer_of some :COPI_00000NN`), so no readable-name stub is generated and the 001–060 strip range needs no change.
4. Quarantines **only** the `InformationBearingArtifact` `iof-core:hasInput` / `iof-core:hasSpecifiedOutput` restrictions (9 total). After the ODR-020 migration (2026-07-12) every other participant restriction is admissible (Material/ICE) and ships **un-stripped**; the IBA ones remain unsatisfiable (IBA is typed `bfo:Object` but its `VisualInspectionProcess` is forced to a `MeasurementProcess` whose outputs are only `MeasurementICE` — 3 unsat: `VisualInspectionFunction`, `COPI_0000085`, `COPI_0000130`). This is a scoped stopgap; **full strip retirement (ODR-020 Decision §6) is blocked on ODR-021** (re-typing `InformationBearingArtifact` → ICE). The former blunt strip of *all* process I/O was narrowed 501→9 on 2026-07-12.

### Enrichment constraints that affect OWL correctness

**Same-genus same-function → must use `necessary`**: If entry A has `genus = B` AND the same `function_name` as B, setting `axiom_mode = 'equivalent'` causes ELK to infer A ≡ B (the subtype adds no differentiating condition). Use `axiom_mode = 'necessary'` for all constructive subtypes.

**Valve (COPI_0000077) genus is `MaterialArtifact`**: design decision AMB-1. Generic Valve is functionally defined (no `hasComponentPartAtAllTimes` parts), so it must NOT be SubClassOf `Assembly`. ControlValve (COPI_0000087) inherits Assembly classification via its `Actuator` part restriction.

**IRI map aliases for process names**: If a process stub needs to satisfy a class definition in a base module (`copi-core` / `copi-vocab`) (e.g. guard-12 requires HeatTransferFunction to realize `COPI_0000004`), add an alias in `copi-iri-map.tsv` mapping the process stub name to the correct protected-range IRI.

## Known issues / workarounds

- **Jinja2 3.1.5+ + Python 3.14**: `env.globals` dict ends up in the LRUCache key tuple, making it unhashable. Fixed by pinning `jinja2==3.1.4` in requirements and using `cache_size=0` on the Jinja2 `Environment` in `app/routers/terms.py`.
- **Starlette 1.0 API**: `TemplateResponse` now takes `(request, name, context)` — `request` is the first positional arg and must NOT be included in the context dict.

## Extending with a new source

1. Add a parser in `parsers/<name>.py` inheriting `BaseParser`, implementing `parse() -> list[ParsedTerm]`.
2. Register it in `parsers/__init__.py` and `scripts/ingest.py` (`PARSERS` dict).
3. Add label and Bootstrap colour in `app/routers/terms.py` (`SOURCE_LABELS`, `SOURCE_COLORS`).
4. Create `data/raw/<name>/`.
