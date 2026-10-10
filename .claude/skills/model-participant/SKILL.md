---
name: model-participant
description: Use when a COPI process_signature names a participant type that is not COPI vocabulary — flagged by check_participant_vocabulary.py, verify_owl.sh exit 9, a 422 on validation, the "not in COPI vocabulary" warning in /enrich/, or participant_vocabulary_gaps — or when deciding how an auxiliary Step 5 term should be modelled in BFO / IOF-Core / COPI.
---

# model-participant

Participant types are hand-authored `copi-vocab` vocabulary (CLAUDE.md, ODR-022 §2). This skill
fixes a signature that names something else, using the project's real vocabulary and write path.

## Tools (run from repo root, `.venv` active; all read-only unless `--commit`)

| Command | Use |
|---|---|
| `python .claude/skills/model-participant/inspect_entry.py <id\|label>` | Signature, gate verdict per participant, published IRI + definition, other users of the type. `--all-unvetted` lists every case. |
| `python .claude/skills/model-participant/lookup.py <words>` | Candidates in lookup order: copi-vocab → enriched classes → ISO 15926-4 FunctionalObject terms → IOF/BFO hints. |
| `python .claude/skills/model-participant/apply_signature.py <id> <sig.json> [--commit]` | Gate check, remaining references, §15 retirement output, stale baseline lines. Writes only with `--commit`. |

Run `inspect_entry.py` and `lookup.py` before reasoning — they replace exploring the DB, map and TTL files by hand.

## Deciding the type

Answer in order; stop at the first that settles it.

1. **Not a continuant?** A process or event (flame, flow), or energy as such → move it into `transformation`, or type the carrier (`HeatTransferMedium`) or a quality (`Pressure`, `MechanicalPower`).
2. **A role or state** (moving, restricted, load, sealed, protected)? → type the bearer itself; input and output use the **same** type when the entity persists.
3. **Only some implementations have it** (MWD in a BHA, an electrical igniter)? → drop it; the signature must hold genus-wide.
4. **Listed in lookup section 1** → use it; most specific the source text supports.
5. **Equipment with an enriched class** (section 2) → use that class; if its entry is `proposed`, the case waits for that validation.
6. **ISO 15926-4 FunctionalObject term** (section 3) → it must be enriched through the 5-step pipeline first (use the `enrich-term` skill); meanwhile keep the case open.
7. **Nothing fits** → nearest broader section-1 type in the signature, plus a `participant_vocabulary_gaps` entry. Adding a class to `copi-vocab.ttl` is the user's decision — propose it, never create it.

## Already-published types

`apply_signature.py` prints what to do; follow it, not general OWL practice:

- **ODR-022 §15: removed, not deprecated.** No `owl:deprecated`, no `IAO:0100001` — COPI has no external consumers. The class drops out on regen once nothing references it.
- With a single replacement, **repoint the old readable name** in `copi-iri-map.tsv` to the replacement's IRI (the script prints the row). With none, leave the row so the number is never reallocated.
- A type still referenced elsewhere (other signatures, `necessary_parts`, `differentia_expression`) stays until every reference is fixed.
- Prune `scripts/participant-vocabulary-baseline.txt` only **after** the signature change is committed — never add lines.

## Output

Per entry, give the user: participant → decision (rule number above) → proposed type, one-line justification, the corrected signature JSON, and the published-class consequence. **Stop for approval before `--commit`**; modelling decisions are the user's. After committing: `python scripts/check_participant_vocabulary.py`, then `bash scripts/verify_owl.sh` before any publish.

## Common mistakes

| Mistake | Fix |
|---|---|
| Inventing a narrower name (`SteelPipe`, `LiquidOrSlurryPortion`) | Rules 4–7; a disjunction is never a type |
| Proposing `owl:deprecated` for a retired COPI class | §15 removal + map repoint |
| Fixing the signature but not `necessary_parts` / differentia that name the same type | Read the "still referenced" list |
| Editing `enrichment` with raw SQL | `apply_signature.py --commit` (history snapshot + `update_enrichment`) |
| Leaving a wrong `transformation_kind` while rewriting the signature | Re-check it against `TRANSFORMATION_KINDS_CONTROLLED` |
