# ODR-014 — Module Export Strategy: copi-base.ttl and per-equipment modules

**Status:** Accepted
**Date:** 2026-06
**Deciders:** Nicolau Santos
**Context:** Fase A of ODR-009/copi-base.ttl session; A3 design decision

---

## Context

The introduction of `copi-base.ttl` (ODR-009/010/011 foundation classes) splits the COPI
OWL graph into at least two files. The export endpoint (`/ontology/export`) and
`generate_combined_turtle()` must decide what to deliver:

- **(a) Module only** — the combined per-equipment TTL imports `copi-base.ttl` via
  `owl:imports`; both files are needed for a complete ontology.
- **(b) Merged file** — `generate_combined_turtle()` prepends the content of
  `copi-base.ttl` and emits one self-contained file.
- **(c) Both** — the endpoint delivers two artefacts (the module and the merged file).

## Decision

**Option (a) — module-only, with owl:imports.**

Each per-equipment TTL module emits `owl:imports <https://www.inf.ufrgs.br/ontologies/copi/base>`
in its ontology header. Tools that load the module must resolve the import (via a catalog
or by fetching the IRI). The `verify_owl.sh` harness resolves the import via
`catalog-v001.xml`, pointing to the local `src/ontology/components/copi-base.ttl`.

## Rationale

- **Modularity**: axioms in `copi-base.ttl` are maintained once; consumers import them by
  reference. Merging would duplicate them per-module and diverge over time.
- **Versioning**: `copi-base.ttl` and the combined equipment module can be versioned
  independently. A base-only change does not require re-generating the equipment module.
- **OWL convention**: OWL imports are the standard mechanism for multi-file ontologies;
  every major reasoner and editor (Protégé, HermiT, ELK) handles them correctly.
- **Tool compatibility**: `verify_owl.sh` already resolves two external imports (IOF-Core,
  BFO) via catalog; adding a third is a one-line change.

## Consequences

- Consumers of the combined TTL (e.g., Protégé users, downstream scripts) must either
  follow the import chain or merge the files manually. A merge script can be added as a
  convenience artefact if needed (deferred).
- The `/ontology/export` endpoint should document that the delivered TTL requires
  `copi-base.ttl` to be imported separately. The endpoint may optionally offer a
  `?merge=true` query parameter in a future session.
- `copi-base.ttl` is kept at `src/ontology/components/copi-base.ttl` in the repository and
  served (in future) from `https://www.inf.ufrgs.br/ontologies/copi/base`.
