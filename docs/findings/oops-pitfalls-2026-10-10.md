# OOPS! pitfalls on the full COPI ontology — what is ours, what is upstream, what is a false positive

Run 2026-10-10 with the OOPS! CLI built from `oeg-upm/OOPS` (Maven, no network service), over
`copi-core` + `copi-vocab` + `copi-enriched`, once without and once with the BFO and IOF-Core
mirrors merged in (`owl:imports` stripped). Not identical to the hosted service: the CLI's
checker set and version may differ, and two of its 33 checkers (C06/P06 and C24) crashed with
`ConcurrentModificationException` and produced no result.

## Fixed

- **P13-N** on `COPI_0000002` (functionally participates in): no inverse declared. Added
  `COPI_0000805` (has functional participant) with `owl:inverseOf COPI_0000002` in `copi-core`
  (authorised exception to the frozen-core rule), and reserved the number in `copi-iri-map.tsv`
  through the readable name `hasFunctionalParticipant`, because the allocator only reads that map
  and would otherwise have issued `COPI_0000805` to the next new class.
- APV `ClassMinAnnotationCoverage` on `COPI_0000536` (fluid port) and `COPI_0000654` (subsurface
  access process): the genus/component stub emitter ignored `class_annotation` (commit `8f7e993`).

## Not ours (BFO / IOF-Core)

P05 (six "wrong inverse" pairs, e.g. `located in`/`location of`, `bearer of`/`inheres in`), P29
(`hasComponentPartAtAllTimes` and `componentPartOfAtAllTimes` marked transitive), P11, P13-S, P35,
P34, P04, most of P13-N and P08-A (188 elements). Every affected element is a BFO or IOF-Core IRI.
Nothing to change here; an upstream IOF-Core issue is the only possible action.

## False positives that stay

### P30 — "equivalent classes not explicitly declared"

The checker compares the English labels of every pair of classes and asks WordNet whether they are
synonymous nouns; if so, and no equivalence is declared, it reports the pair. It is a lexical
heuristic, not a modelling check.

| Pair | Why the equivalence would be wrong |
|---|---|
| `separator` / `centrifuge` (`COPI_0000084`, `COPI_0000225`) | `centrifuge` is a subclass of `separator`. Declaring them equivalent would make every separator a centrifuge. |
| `operation` / `bfo:process` (`COPI_0000001`) | `operation` is a subclass of `process`. |
| `tube` / `pipe` (`COPI_0000719`, `COPI_0000321`) | Distinct equipment classes in the sources (different sizing standards, e.g. ASME tube vs pipe). This is the only pair where a modelling question could be raised; it is a domain decision, not something the pitfall settles. |

Also reported, both BFO/IOF: `role`/`function`, `System`/`Organization`.

### P22 — "different naming conventions"

The checker reads the local names of IRIs and flags a mix of styles. COPI IRIs are
`COPI_0000663`-style (ODR-022), IOF-Core's are CamelCase (`MeasurementProcess`), so any COPI class
triggers it; the report shows one example pair (`COPI_0000663` / `MeasurementProcess`). The only
way to remove it is to abandon numeric IRIs, which ODR-022 rules out.

## Status

Kept as accepted residuals. APV over the three components: 0 violations. `scripts/verify_owl.sh`
passes. Re-run the OOPS! CLI after any change to the property set or to IRI allocation.
