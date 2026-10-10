# Disjointness Decision Procedure — COPI Ontology

**Date:** 2026-05-03  
**Tool:** `tools/audit_disjointness.py`  
**Status:** Procedure implemented; existing records audited; removals pending manual review.

---

## Motivation

The original enrichment prompt contained a single sentence:

> "Two signatures are incompatible if they differ in number of streams, participant types,
> or transformation nature. Incompatible signatures ground disjointness."

This was too permissive — it caused the LLM to declare disjointness between classes that
are merely different rather than provably disjoint under OWL semantics. Disjointness
axioms are logically explosive: a single wrong assertion can trigger unsatisfiability for
any instance that belongs to both classes, making the ontology inconsistent.

---

## The 5-Case Decision Tree

The decision procedure replaces the single sentence with an explicit case-by-case tree.
It is now part of the `## Output Format` section of `enrichment/prompts.py`, immediately
before the `disjoint_with` field.

| Case | Condition | Verdict |
|------|-----------|---------|
| **C1** | Same genus, both `constructive` | Disjoint **iff** structural differentiae are mutually exclusive (cite parts/qualities) |
| **C2** | Same genus, both `functional` | **DORMANT** — requires declared function disjunctions; currently never disjoint |
| **C3** | Same genus, mixed bases | **NEVER** disjoint — functional/constructive are orthogonal axes |
| **C4** | Different genus | Disjoint **iff** signatures incompatible AND both sides have `transformation_kind_status='controlled'` |
| **C5** | Same kind, different operational/regulatory context | **NEVER** disjoint — context does not change ontological identity |

### Case 2 — Dormant Status

The current function hierarchy contains 0 declared OWL disjunctions between function
classes (see `docs/findings/function_parent_canonicalization.md` and
`/tmp/function_disjointness_audit.md`). Until function-level disjunctions are added (post
Leva 3, with domain expert), Case 2 cannot produce valid disjointness assertions. All C2
pairs in existing records should be removed.

### Case 3 — Orthogonality Rationale

A `ball valve` (constructive basis — BallClosure differentia) and a `control valve`
(functional basis — ProcessControlledFlowFunction) share the genus `Valve` but are
classified on orthogonal axes. An instance of `ball control valve` (both) is simultaneously
a ball valve AND a control valve. Declaring them disjoint would make `ball control valve`
unsatisfiable.

---

## Validator Implementation

`enrichment/disjointness_validator.py` implements `validate_disjointness(proposal, ontology_state)`:

- For each C in `proposal['disjoint_with']`, applies the 5-case tree.
- Reads `classification_basis` from `llm_raw_response` JSON (no DB column).
- Returns `{'preserved', 'rejected', 'rationale_invalid', 'asymmetry_warnings'}`.
- Does NOT modify the proposal.

The validator is wired into `enrich_cluster()` as step 3d (after 3c `_validate_transformation_kind`).
Rejected and invalid pairs are logged as warnings. The proposal is stored as-is — pipeline
records LLM output faithfully; corrections are a separate audit process.

---

## Audit Results (2026-05-03)

```
python tools/audit_disjointness.py
→ /tmp/disjointness_audit.md
```

| Metric | Count |
|--------|-------|
| Records with non-empty `disjoint_with` | 187 |
| Total (X, C) pairs | 944 |
| **Preserved** | 31 (3.3%) |
| **Rejected** | 30 (3.2%) |
| **Rationale-invalid / unverifiable** | 883 (93.5%) |
| Asymmetry warnings | 84 |

### Why 93.5% rationale-invalid?

Two causes, both attributable to the old prompt convention:

1. **No case identifier** — the old prompt never required `C1:`/`C2:` labels; existing
   rationale strings use free-text justifications.
2. **CamelCase class names** — old records populate `disjoint_with` with OWL class names
   (`GateValve`, `HeatExchanger`) rather than cluster labels (`gate valve`, `heat
   exchanger`). The validator cannot look these up in the DB.

These 883 pairs are unverifiable by the automated tree — they require manual review or
re-enrichment under the new prompt.

### Rejected pair breakdown

| Case | Count | Action |
|------|-------|--------|
| C1 — structural evidence missing | 3 | Review: may be salvageable with rationale edit |
| C2 — both functional, dormant | 22 | Remove (safe — no function disjunctions exist) |
| C3 — mixed bases, orthogonal | 4 | Remove (safe — definitionally never disjoint) |
| C4 — kind evidence insufficient | 1 | Review: `rupture disc` vs `control valve` (C_status='') |
| C5 — operational context | 0 | — |

---

## Removal Batches

**Batch 1 (safest):** Remove all 4 C3-rejected pairs.  
These violate orthogonality by definition. No domain ambiguity.

| X | C |
|---|---|
| `differential pressure transmitter` | `absolute pressure transmitter` |
| `hydraulic motor` | `pneumatic motor` |
| `pneumatic motor` | `hydraulic motor` |
| `tubing hanger` | `manifold` |

**Batch 2:** Remove all 22 C2-rejected pairs.  
Safe because Case 2 is currently dormant. Document as pending re-evaluation when function
disjunctions are added.

Key affected records: `axial displacement transmitter`, `conductivity transmitter`,
`densitometer`, `electric generator`, `furnace`, `level indicator`, `pressure indicating
transmitter`, `safety valve`, `tubing hanger`, `vibration transmitter`.

**Batch 3 (review):** Inspect 3 C1-rejected pairs.
`gas engine` / `diesel engine`, `pipe elbow` / `pipe tee`, `pipe elbow` / `pipe reducer`
— differentiae may be structurally exclusive but rationale doesn't cite the evidence.

**Batch 4 (future):** When function disjunctions are added to the ontology (post-Leva 3),
revisit all C2-removed pairs. Case 2 activates automatically.

---

## Implications for the Thesis

The audit quantifies how much of the existing disjointness data was generated under a
looser criterion:

- 93.5% of declared (X, C) pairs cannot be validated by the automated tree because they
  predate the structured procedure.
- Of the 61 pairs that CAN be validated (with DB lookup), 31 pass (50.8%) and 30 fail
  (49.2%).
- Case 2 dormancy is a documented limitation: the function hierarchy currently lacks
  declared disjunctions, making functional-basis disjointness unassertable. This is
  appropriate under OWA.

The procedure establishes a principled foundation for future disjointness work,
distinguishing it clearly from the exploratory assertions in earlier enrichment rounds.


## Case Identifier Backfill

**Date:** 2026-05-04
**Tool:** `tools/backfill_disjointness_case_ids.py --apply`
**Records updated:** 242
**Pairs labelled:** 585

### Distribution of derived case identifiers

| Tag | Count | % of pairs | Meaning |
|:----|------:|:----------:|:--------|
| C1 | 78 | 13.3% | Same genus, both constructive |
| C2 | 113 | 19.3% | Same genus, both functional (dormant — pending removal) |
| C4 | 130 | 22.2% | Different genus, transformation_kind incompatible |
| C? | 264 | 45.1% | Unverifiable (kind ambiguous or class not in DB) |

C? breakdown:
- `unverifiable_class_not_in_db`: 200 pairs — CamelCase class names not found as cluster labels
- `kind_ambiguous`: 64 pairs — different genus but same `transformation_kind` (cannot confirm incompatibility)
- `unverifiable`: 0 pairs — genus or kind data missing
- `legacy_orphan` (C3/C5): 0 pairs — should have been removed by Leva 3.4c; require manual review

### Interpretation

**C4 (130 pairs, 22.2%)** is the dominant case.  Most legacy
disjointness assertions involve classes with different BFO genera and incompatible
`transformation_kind` values — a structurally sound basis for disjointness.

**C2 (113 pairs)** pairs are dormant (Case 2 dormancy documented above).
They remain in `disjoint_with` but are tagged for future removal when function-level
disjunctions are added to the ontology.

**C? (264 pairs)** are the legacy "CamelCase" pairs (200
not in DB) plus kind-ambiguous pairs (64).  The CamelCase
entries were generated by old enrichment runs that used OWL class names rather than
cluster labels; they cannot be validated until a CamelCase→cluster mapping is built.
