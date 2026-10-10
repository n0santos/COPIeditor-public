---
name: enrich-term
description: Perform the 5-step BFO/IOF-Core enrichment method on a standards term inside a Claude Code session, with no Anthropic API call -- reusing the real production prompt-builder, parser, and write path.
---

# enrich-term

Runs COPIeditor's 5-step enrichment method (see the project's `CLAUDE.md`,
"Enrichment methodology" and "Interactive enrichment pipeline") for one term,
substituting this Claude Code session's own reasoning for the Anthropic API
call `enrich_cluster()` normally makes. Everything else -- prompt rendering,
context fetching, JSON parsing, validators, and the DB write -- is the real
production code, imported and called directly, never reimplemented.

**Never hand-write INSERT statements for `enrichment` rows.** That is a
different generation process (`generation_path='migration_script'` or
`'manual'`) that happens to target the same schema -- see
`scripts/migrations/add_generation_path.py`'s docstring for why this
distinction is tracked at all.

## Workflow

Run from the COPIeditor repo root with `.venv` active.

### Phase 1 — render the prompt

```bash
python .claude/skills/enrich-term/render_prompt.py "<cluster_label>"
```

This calls the exact same fetch functions `enrich_cluster()` calls
(`get_cluster_definitions`, `get_cluster_subtypes`, `get_related_concepts`,
`get_parent_candidates`, `get_existing_ontology_context`,
`get_cluster_properties`, `get_cluster_iso14224_properties`,
`get_component_terms`), then `build_enrichment_prompt()`
(`enrichment/prompts.py`) with them. It prints the rendered system + user
prompt and writes `.enrich_context.json` / `.enrich_prompt.txt` in this
directory for Phase 2 to pick up.

If it errors with "no definitions found," that term isn't in `terms.db` under
that exact `cluster_label` — check spelling/casing against the `terms` table
before retrying.

### Phase 1b — Step 2b/2c secondary/tertiary research (REQUIRED, not optional)

**Do this before Phase 2, every time — `terms.db`'s built-in sources alone are
"primary" only and are frequently thin.** CLAUDE.md's Step 2b is explicit:
"always attempted first," and it's meant to inform the actual axiomatization
(real structural parts, mechanisms, documented subtypes a thin primary
definition doesn't mention), not just decorate provenance metadata after the
fact. Skipping this produces a materially weaker enrichment, not just an
incomplete one — see the session finding that caught this the first time this
skill ran.

Follow CLAUDE.md's Step 2b/2c exactly: search for a correlated normative
standard or curated dictionary (DNV, NIST, NORSOK, ISO/IEC sample previews are
often free) using `WebSearch`, then `WebFetch` with an explicit "quote
verbatim" prompt — never trust `WebSearch`'s own synthesized summary. If
`WebFetch` reports a corrupted/unreadable PDF, **do not mark it failed** — it
still saves the binary locally (path is in the tool result); run `pdftotext
<path> -` via Bash before giving up, then `pdftoppm` + `tesseract` OCR if that
also comes back empty. Extract by the 7 categories (structure, profile,
mechanism, function, application, subtype, parameter), tag each finding
accordingly. Only reach for tertiary sources (Step 2c: manufacturer pages,
patents, web glossaries) if a real gap remains after 2b, and only with 2+
independent tertiary entries (triangulation — enforced by
`validate_tertiary_triangulation()`).

**Why this can't just be folded into Phase 1's `render_prompt.py` call**:
`_store_proposal()` builds `source_definitions_used` itself, from the flat
`terms.db` `definitions` list only — it has no parameter for richer
Step 2b/2c findings. So the sequence that actually works is:
1. Do Phase 1 (render prompt from `terms.db` sources only, as today).
2. Do Step 2b/2c research *before* Phase 2's reasoning, so the extra
   evidence can actually inform Step 2/3/4 of the method (genus, differentia,
   parts) — not just get appended as an afterthought.
3. Do Phase 2 using ALL evidence gathered (terms.db + Step 2b/2c).
4. Do Phase 3 as normal — this stores the flat-shape row via `_store_proposal()`.
5. **Immediately follow up** with a second write enriching
   `source_definitions_used` (full tier/source_type/citation_mode/access/
   categories_covered/quote shape), `secondary_coverage` (call
   `compute_secondary_coverage()` — never eyeball it), and
   `primary_definition_conflict` if warranted. Use `snapshot_enrichment()` +
   `update_enrichment()` for every field it allows (`necessary_parts`,
   `secondary_coverage`, `primary_definition_conflict`, `parts_rationale`,
   `reviewer_notes`) — but note `source_definitions_used` is **not** in
   `update_enrichment()`'s allowed-columns list (nor in the `/update` route's
   form fields); the only real production path for that one field today is a
   direct `UPDATE`, matching `scripts/migrations/backfill_source_tier.py`'s
   own pattern exactly (history snapshot first, then `UPDATE ... SET
   source_definitions_used = ?`).
6. Re-run the three `/update`-path validators against the *new* data before
   writing step 5 — same as the route does when `necessary_parts` changes
   alongside `source_definitions_used`.

### Phase 2 — do the actual enrichment

**This is not automated — it's the point.** Read the full rendered prompt
(system + user) exactly as printed. It is the real production prompt, with
the same instructions, schema, and constraints a real API call would receive.
Do the 5-step reasoning it asks for, using the cross-source definitions it
already embedded. Produce the same JSON structure the API would return:
`step1_function`, `step2_genus`, `step3_differentia`, `step4_parts`,
`step5_signature`, `axiom_mode`, `disjoint_with`, `definitions`, etc. — follow
the prompt's own schema instructions, not this file's description of them.

Write that JSON response to a file (plain text, markdown fences around it are
fine — the parser strips them, same as the real one does).

### Phase 3 — parse, validate, store

```bash
python .claude/skills/enrich-term/store_response.py <response_file> <model_id>
```

`<model_id>` is the exact model running this session (e.g. `claude-opus-5`) —
it is written to `llm_model`, so never guess or copy it from an earlier run.

Runs, in order, exactly what the production pipeline runs:
1. JSON parsing — identical fence-stripping + `json.loads()` logic to
   `call_llm()` in `enrichment_service.py`.
2. Creation-time checks `enrich_cluster()` itself runs (non-blocking):
   `_validate_part_source_labels()`, `_validate_transformation_kind()`,
   `validate_disjointness()`.
3. The three validators the `/update` route runs (**blocking** — a failure
   here means nothing gets written, same as the route returning HTTP 422):
   `validate_tertiary_triangulation()`, `validate_necessary_parts_quotes()`,
   `validate_part_universality()`.
4. `_store_proposal()` — the real write path, `status='proposed'` (hardcoded
   in production, not a skill choice), `generation_path='skill_session'`.

## Known, deliberate gap in `_store_proposal()` — and how Phase 1b's follow-up write fixes it for this skill's output

`_store_proposal()` writes `source_definitions_used` in the **old flat
`{source, term}` shape** only — it has no parameter for the tier/source_type/
citation_mode/**quote** shape the rest of the population was backfilled to
(`scripts/migrations/backfill_source_tier.py`, 2026-09-08). This is a real,
live gap in production (`enrich_cluster()` has the identical limitation) —
not something to patch inside `_store_proposal()` itself, which stays called
exactly as production calls it.

But if you skip Phase 1b (Step 2b/2c research) and its step-6 follow-up
write, `necessary_parts` quote-grounding checks will run against that flat
shape's dict-repr text — real prose is very unlikely to match, so
`validate_necessary_parts_quotes()` will very likely reject any part with a
genuine quote. **This is exactly why Phase 1b's step 5 (the direct `UPDATE`
of `source_definitions_used` with real quotes) isn't optional polish** — it's
what makes quote-grounding actually meaningful for this record, matching
what the tier-backfill did for the rest of the population. Do Phase 1b in
full; don't stop at Phase 3 and call the run complete.

## Retired participant type — `InformationBearingArtifact` (fixed 2026-09-10)

`enrichment/prompts.py`'s Step 5 participant-type guidance used to list
`InformationBearingArtifact` as an established type for "any signal,
measurement output, or control signal", and listed the portion types as
`FluidPortion`/`GasPortion`/`LiquidPortion`/`SolidPortion`. Both were wrong
against the live ontology: `InformationBearingArtifact` was retired from COPI
by ODR-021 (resolved 2026-08-08) — `regen_enriched_owl.py` has a dedicated
assertion (`assert_all_classes_anchored`, then the explicit ODR-021
absence check) that **fails the build** if it reappears in the graph — and
the real, IRI-allocated portion types are `PortionOfFluid`/`PortionOfGas`/
`PortionOfLiquid`/`PortionOfSolid` (`Portion Of X`, not `X Portion`).

This was caught the hard way: a batch of 5 entries (`gas chromatograph`,
`temperature measuring instrument - bimetal`, `probe`, `moisture meter`,
`process variable transmitter`) used `InformationBearingArtifact` for their
output participants — following the prompt's own guidance faithfully — and
`regen_enriched_owl.py` refused to build once they reached `status='validated'`
(`StubPolicyError: ... COPI_0000553` — the numeric IRI for
`InformationBearingArtifact`). Fixed by editing each record's
`process_signature` directly (`update_enrichment`, `process_signature` field)
to use the real ICE-family type already used by that entry's own genus or
closest sibling (e.g. `chromatograph`'s own `CompositionMeasurementResult` for
`gas chromatograph`; `humidity analyser`'s `MeasurementInformationContentEntity`
+ `VisualIndication` pair for the structurally-identical `moisture meter`).

`enrichment/prompts.py` itself is fixed now (not just this file) — the
participant-type guidance lists the real established ICE types
(`InformationContentEntity`, `MeasurementInformationContentEntity`,
`VisualIndication`, `ControlSignal`, the `{Quantity}MeasurementResult`
family) and the correct `PortionOfX` naming, with an explicit instruction to
check the concept's own genus/sibling for its existing output type(s) before
picking a generic one from scratch. Since this skill renders from the same
`build_enrichment_prompt()` as the real API path, this fix applies to both —
but it does **not** retroactively fix any record enriched before 2026-09-10;
re-run `grep -l InformationBearingArtifact` (or the equivalent
`process_signature LIKE` query) against `data/enrichment.db` if auditing
older output is ever in scope.

**General lesson for Phase 2 reasoning**: before inventing or trusting a
participant type name from the prompt's own guidance list, it costs nothing
extra to check what the concept's own genus (or closest already-enriched
sibling) actually uses in its stored `process_signature` — the prompt's
static guidance can drift out of sync with the live ontology (as it did
here) in a way the LLM reasoning itself has no way to detect without
looking.

## Batch validation without the `/enrich/` UI

When the Docker-hosted dashboard is unavailable, `finalize_step2b.py` (Phase
1b's follow-up write, described above) and `validate_batch.py` in this same
directory cover the rest of the workflow the UI would otherwise handle:
`validate_batch.py <id> [<id> ...]` mirrors exactly what the `/update` route
does on a `status='validated'` transition (snapshot, `update_enrichment`,
then a per-class `generate_turtle()` + `verify_service.run_consistency_check()`
HermiT check) and refuses to validate any id that fails it. This is a
per-class check only (imports stripped) — it does not substitute for running
the real `python -m scripts.regen_enriched_owl && bash scripts/verify_owl.sh`
over the full combined ontology before treating a batch as safe, which is
what actually caught the `InformationBearingArtifact` issue above (the
per-class check alone did not).

**Environment gotcha**: in this repo, `source .venv/bin/activate` does **not**
reliably select this project's own virtualenv — its `bin/activate` script
carries a stale hardcoded `VIRTUAL_ENV` path left over from `agregador-termos`
(the project COPIeditor was forked from), which silently redirects `python`/
`pip` to the *other* project's venv and its different (sometimes missing)
package set. Invoke `.venv/bin/python3` by path instead of sourcing activate,
in this skill's scripts and anywhere else in this repo, until that activate
script is regenerated properly.

## Verification discipline

Enrich **one term end-to-end** and show: the rendered prompt, the raw
response, the parsed record, every validator's result, and the final DB row
(`id`, `status`, `generation_path`, `llm_model`). Stop there for inspection
before enriching a second term or batch.
