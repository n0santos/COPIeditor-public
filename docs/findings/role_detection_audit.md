# Role-Detection Audit — COPI Enrichment Pipeline

**Date:** 2026-05-03  
**Status:** Closed — role-detection removed from pipeline.

---

## Context

During a review of the enrichment prompt for the COPI ontology editor, the pipeline included a
"Role vs. Kind (Pre-check)" step that instructed the LLM to classify each cluster as either a
*kind* (a class with intrinsic identity) or a *role* (a contextual designation borne by instances
of a more fundamental kind). The intent was to prevent operational roles from being modelled as
T-Box classes.

The audit was triggered by two observations: (1) after 273 enrichments, only one record had
`is_role=true`; and (2) the LLM was spending substantial tokens articulating negative
role-detection rationales for every term it correctly classified as a kind.

---

## Method

Three steps were carried out:

**a) Diagnostic with a canonical role term (Prompt 0.3 — "spare pump")**  
"Spare pump" is a paradigmatic operational role: the same physical pump is a spare when a
running unit exists and becomes primary when it fails. The pipeline was invoked on this term.
Result: `ValueError: No definitions found for cluster 'spare pump'`. The term does not appear
in any of the six consulted industrial sources (CFIHOS, ISO 15926-4, DEXPI, ISO 14224, SLB
Glossary, POSC Caesar RDL).

**b) Audit of the database (Prompt 0.5)**  
SQL query on all 273 records in `enrichment.db`:

```sql
SELECT is_role, COUNT(*) FROM enrichment GROUP BY is_role;
SELECT cluster_label, role_bearer, role_bearer_rationale
FROM enrichment WHERE is_role = 1;
SELECT COUNT(*), AVG(LENGTH(role_detection_rationale))
FROM enrichment WHERE is_role = 0;
```

(The last query was approximated via Python by parsing `llm_raw_response`.)

**c) Stability test via regression harness**  
"riser" — the sole `is_role=true` record — was included in the regression harness as a
role-detection candidate. Over four consecutive runs at `temperature=0`, `is_role` flipped
between `True` and `False`, confirming the positive was noise rather than a reliable signal.

---

## Quantitative Results

| Metric | Value |
|--------|-------|
| Total enrichments audited | 273 |
| `is_role = true` | **1** (riser, bearer "pipe") |
| Stable positives (consistent across runs) | **0** |
| Negative records with rationale filled | 191 / 272 (70 %) |
| Negative records with empty rationale | 81 / 272 (30 %) |
| Mean negative rationale length | **271 characters (~55 tokens)** |
| Max negative rationale length | 432 characters |
| Estimated cumulative token cost of negative rationales | ~15 000 tokens across 273 enrichments |
| Canonical role term ("spare pump") present in sources | **No** |

The 81 records with empty rationale correspond to older enrichments produced before the
`role_detection` field was added to the schema.

---

## Qualitative Results

- The sole positive (`riser`) had two records in the database with contradictory rationales:
  one argued riser is a role (bearer = pipe); the other argued it is a kind with a functional
  differentia (upward fluid conduction). Neither was stable at `temperature=0`.
- "isolation valve" — chosen as a role candidate in the regression harness — was also
  consistently classified as `is_role=false` across all runs.
- "spare pump" is absent from all six industrial sources. Its absence confirms that
  operational roles (standby designation, lead/lag assignment) are not vocabulary items in
  procurement or maintenance standards; they are operational annotations on individuals.

---

## Conclusion

The industrial sources consulted by COPI (CFIHOS, ISO 15926-4, DEXPI, ISO 14224, SLB Glossary,
POSC Caesar RDL) **do not model role-as-class**. Equipment classes in these sources are
uniformly defined by designed function or physical structure — i.e., they are *kinds* in the
BFO sense. Operational roles emerge at runtime over individual equipment instances.

**Architectural decision:** role modelling is delegated to:
- **Pillar 1** — Functional Location ODP, where roles are borne by individuals at `bfo:Site`
  anchors (e.g., a pump instance occupying a "spare pump" functional location).
- **Pillar 3** — OMIS information anchoring layer, for operational annotations such as standby
  designation, isolation duty, and lead/lag assignment on equipment instances.

The `is_role` / `role_detection` machinery has been removed from:
- `enrichment/prompts.py` — "Role vs. Kind (Pre-check)" section deleted.
- `enrichment/enrichment_service.py` — `_store_proposal`, `generate_turtle`,
  `list_enrichments` updated; `_generate_role_turtle` retained but marked unused.
- `enrichment/enrichment_routes.py` — role fields removed from update field map.
- `enrichment.db` — data cleaned via `tools/migrate_remove_role_fields.py`.

---

## Implications for the Thesis

This audit provides convergent empirical evidence for the architectural decision not to have
role-classes in the COPI T-Box:

1. **Zero stable positives** in 273 enrichments — the model never consistently identified a
   role class despite explicit instructions and examples.
2. **Absence of canonical role terms** in the source corpus — "spare pump" is not a class in
   any of the six standards, confirming that the standards themselves treat these as
   operational annotations, not types.
3. **Disproportionate token cost** — ~15 000 tokens spent articulating negative role
   rationales, contributing no ontological content.

This finding is suitable for citation in:
- The thesis validation section as evidence that COPI's kind-only T-Box is consistent with
  source vocabulary.
- The COPIeditor (I3) discussion as an example of LLM-assisted tooling revealing domain
  structure that supports design decisions.
