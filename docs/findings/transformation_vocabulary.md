# Transformation-Kind Controlled Vocabulary — COPI Enrichment Pipeline

**Date:** 2026-05-03  
**Status:** Active — first canonical version (17 terms).

---

## Origin

The vocabulary was derived empirically from an audit of 313 enrichment records in
`enrichment.db`. The free-text `transformation` field of `step5_signature` was analysed
with `tools/audit_transformations.py`, which clustered the texts using regex-based
first-match-wins grouping (17 groups, 100% coverage of the 313 records).

The cluster labels from that audit were then refined into a controlled vocabulary that
follows the naming conventions of BFO/IOF-Core process types: snake_case, nominal or
verb+object format, precise scope description. The vocabulary is deliberately narrower
than the audit groups — `gas_compression` and `mechanical_energy_to_fluid` are merged
into `pressure_increase`; `kinetic_pressure_conversion` and
`mechanical_power_transmission` are distinguished by whether the output is fluid
pressure or mechanical torque.

---

## Canonical Vocabulary (17 terms)

| Term | Scope | Typical equipment |
|------|-------|-------------------|
| `flow_regulation` | Flow rate modulation — partial obstruction to control flow | Control valves, globe valves, butterfly valves |
| `flow_isolation` | Complete flow shutoff for system isolation | Isolation valves, ESDVs, block valves, gate valves |
| `flow_direction_control` | Backflow prevention; unidirectional passage only | Check valves, non-return valves |
| `pressure_increase` | Work input raises fluid pressure or velocity | Pumps (all types), compressors, fans, blowers |
| `pressure_reduction` | Pressure let-down without mechanical energy recovery | Relief valves, PRVs, restriction orifices, chokes |
| `mechanical_power_transmission` | Torque/speed conversion between mechanical shafts | Gearboxes, couplings, actuators (pneumatic/hydraulic/electric) |
| `electrical_power_conversion` | Electrical energy production, transformation, or switching | Electric motors, generators, transformers, circuit breakers, fuses |
| `thermal_energy_transfer` | Heat exchange between process streams or with utilities | Heat exchangers, heaters, coolers, condensers, reboilers |
| `phase_separation` | Density- or gravity-driven separation of co-mingled phases | Separators, scrubbers, cyclones, centrifuges, flash drums |
| `mass_transfer` | Selective inter-phase transfer of chemical species | Absorbers, amine contactors, dehydrators, strippers |
| `mechanical_filtration` | Size-based removal of solid particles from a fluid | Filters, strainers, screens, coalescers |
| `chemical_transformation` | Chemical reaction as primary transformation mechanism | Flares, incinerators, combustion engines, reactors |
| `measurement_transduction` | Physical quantity converted to a measurable signal | Transmitters, sensors, gauges, analysers, meters |
| `fluid_transport` | Fluid conveyance without mechanical work addition | Pipes, risers, elbows, manifolds, headers, tees |
| `subsurface_access` | Creation or maintenance of a pathway to/from the subsurface | Wellbores, wells, drilling strings |
| `containment` | Passive enclosure or structural retention with minimal transformation | Vessels, tanks, flanges, seals, gaskets |
| `mixing` | Stream combination or homogenisation | Static mixers, agitators, blenders |

---

## Classification Policy

Priority order when selecting a term:

1. **Prefer canonical terms** — a reasonable approximation is better than a new extension.
2. **Choose by ontological identity** — pick the term that captures the primary designed
   function, not secondary mechanisms. A centrifugal pump = `pressure_increase` even
   though it also exhibits internal `fluid_transport` and `mechanical_power_transmission`.
3. **Propose only when genuinely outside the spectrum** — the transformation must be
   irreducible to any of the 17 terms, even approximately. Criteria for a valid extension:
   - Articulate why each of the 2–3 closest canonical terms fails.
   - Use snake_case, ≤ 50 characters, verb+object or nominal_descriptive format
     (e.g. `cathodic_protection`, `signal_amplification`).

---

## Extension Mechanism

When an LLM proposes a new term, the pipeline sets:

```json
{
  "transformation_kind": "cathodic_protection",
  "transformation_kind_status": "proposed",
  "proposed_kind_rationale": "..."
}
```

The validator in `enrichment_service._validate_transformation_kind()` checks:
- If status=`controlled` but term not in `TRANSFORMATION_KINDS_CONTROLLED` → demote to
  `proposed` with an auto-generated rationale note.
- If status=`proposed` and `proposed_kind_rationale` is empty → warning logged.
- If status=`proposed` and term violates snake_case or exceeds 50 chars → warning logged.

---

## Review Cadence

Run `python tools/audit_proposed_kinds.py` every ~500 new enrichments.

For each proposed extension decide:

| Action | Criterion | Steps |
|--------|-----------|-------|
| **Promote** | Term used ≥ 3 times with consistent rationale across independent enrichments | Add to `TRANSFORMATION_KINDS_CONTROLLED` in `enrichment_service.py`; update system prompt in `prompts.py`; run backfill to update `proposed` → `controlled` for existing records; update this document |
| **Reject** | Term is a special case of an existing canonical term | Update affected records to use the canonical term (manual SQL or migration script) |
| **Keep** | Ambiguous; insufficient evidence | Defer to next review cycle |

---

## Extensions Promoted to Controlled

*(None yet — vocabulary at version 1.0, 2026-05-03.)*

---

## Implications for Disjointness (Leva 3.4)

`transformation_kind` is used as one input to the disjointness grounding logic.
**Only `controlled` terms generate disjointness grounds.** Records with
`transformation_kind_status='proposed'` are treated as "kind unknown" under OWA:
they neither ground disjointness assertions nor confirm compatibility with siblings.
This prevents an unreviewed extension from silently corrupting the disjointness graph.

---

## Backfill

The 313 existing enrichments (as of 2026-05-03) that predate this vocabulary were
retrofitted using `tools/backfill_transformation_kind.py`, which submits each record's
free-text `transformation` to an isolated, minimal LLM call at `temperature=0`.
