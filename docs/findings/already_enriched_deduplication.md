# Already-Enriched Classes — Context Deduplication

**Date:** 2026-05-04  
**Status:** Fixed (non-publishable, internal pipeline note)

## Finding

`get_existing_ontology_context()` in `enrichment/enrichment_service.py` was querying
all rows from the `enrichment` table without deduplication:

```sql
-- before (bug)
SELECT cluster_label, function_name, genus, status
  FROM enrichment
 ORDER BY cluster_label
```

The table stores one row per enrichment *attempt*, including re-runs and regression
test runs. With 218 distinct clusters and 354 total rows at the end of Leva 3, the
`## Already-Enriched Classes` block injected into every user prompt contained **354
entries** instead of **218 concepts**.

## Impact

| Metric | Before | After |
|:-------|-------:|------:|
| Entries in context block | 354 | 218 |
| Block size (chars) | 32,381 | 21,012 |
| Block size (tokens est.) | ~9,252 | ~6,003 |
| Token saving per enrichment | — | ~3,249 (~35%) |

The overhead was pure noise: duplicate entries for the same cluster conveyed no new
information to the LLM and only diluted the signal from unique concepts.

## Fix

Replaced the flat `SELECT` with a dedup subquery keyed on `MAX(id)` per cluster:

```sql
-- after (fixed)
SELECT cluster_label, function_name, genus, status
  FROM enrichment
 WHERE id IN (SELECT MAX(id) FROM enrichment GROUP BY cluster_label)
 ORDER BY cluster_label
```

Added an optional `include_proposed: bool = True` parameter:

- `True` (default): all statuses included — the LLM sees proposed entries and avoids
  inventing duplicate `function_name`s before expert review completes.
- `False`: validated-only (74 entries at Leva 3 end) — useful if future Levas want the
  context to reflect only peer-reviewed ontology decisions.

Added an `INFO` log line at context-build time:
```
Built existing-ontology block: 218 unique clusters (proposed=144, validated=74)
```

## Decision

`include_proposed=False` deferred: 144 proposed entries are real ontological
commitments (reviewed by domain expert during enrichment); excluding them risks
`function_name` collisions in Leva 4. Re-evaluate if the block exceeds ~20K tokens
(expected after ~800 distinct clusters).
