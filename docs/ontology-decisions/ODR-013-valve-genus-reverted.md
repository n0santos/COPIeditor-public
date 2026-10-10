# ODR-013 — Valve: Genus Reverted to MaterialArtifact; Assembly Reserved for Compositionally-Defined Subclasses

**Status:** Accepted (supersedes ODR-007)
**Date:** 2026-06-10
**Deciders:** Nicolau Santos

---

## Context

ODR-007 changed the genus of `Valve` from `MaterialArtifact` to `Assembly`, treating the
two as mutually exclusive alternatives. In IOF-Core, `Assembly ⊑ MaterialArtifact` (axiom
LA1), so the choice was never disjunctive: asserting `Assembly` strengthens, rather than
corrects, the commitment. That strengthening is false as a necessary condition of the kind.

**Counterexample:** a duckbill check valve is a monolithic elastomeric flap — no distinct
components, no disassembly capacity. IOF-Core's own natural-language definition of Assembly
requires the bearer to be "capable of disassembly" and to have ≥ 2 distinct
`MaterialComponent` parts. A duckbill check valve fails both conditions, yet it is
unambiguously a valve. Therefore `Valve ⊑ Assembly` is not a valid necessary axiom for
the kind.

---

## Decision

- **`Valve`**: `genus` and `genus_bfo_root` reverted to `MaterialArtifact`.
- **`axiom_mode`** remains `necessary`; `FlowControlFunction` remains necessary and
  non-sufficient (the orifice-plate counterexample from ODR-007 is unaffected).
- **`ControlValve`**: retains `genus_bfo_root = Assembly`. Body + actuator + positioner
  is a definicional composition for the kind — the Assembly commitment is justified and
  explicit. `ControlValve ⊑ Valve ⊓ Assembly` is consistent because
  `Assembly ⊑ MaterialArtifact ⊑ …` and subsumption permits a child to carry stronger
  structural commitments than its parent.
- **All other valve subclasses** (gate, globe, ball, needle, plug, check, relief, safety,
  isolation, etc.): `genus_bfo_root` reverted to `MaterialArtifact`. No explicit
  compositional justification was on record for any of them; the Assembly value was
  inherited wholesale from ODR-007.
- **Children of `ControlValve`** (ball control valve, butterfly control valve, gate control
  valve, globe control valve, choke control valve, on-off control valve): `genus_bfo_root`
  remains `Assembly` — they inherit from a genus (`ControlValve`) for which Assembly is
  justified.
- **Children of reverted classes** (piston check valve, swing check valve, wafer check
  valve, down hole safety valve): `genus_bfo_root` reverted to `MaterialArtifact`,
  consistent with their parent genus.

---

## Rationale

- **LA1 and disassembly.** IOF-Core requires ≥ 2 distinct MaterialComponents and
  "capable of disassembly" for Assembly. Monolithic valves (duckbill, flapper, elastomeric
  check valves) fail both. `Valve ⊑ Assembly` as a necessary axiom would exclude these
  legitimate instances.
- **The maintenance argument is defeasible.** ODR-007 argued that trim replacement (seat +
  closure member + packing) proves valves are assemblies. This is a statistical
  generalization about typical process valves, not a necessary condition of the kind.
  Furthermore, `hasComponentPartAtAllTimes` is a permanent mereological relation; a
  replacement seat that did not exist before installation cannot be a permanent part of the
  valve — the argument also tensions the temporal semantics of the part-whole relation.
- **Hierarchical consistency is not incoherence.** ODR-007 flagged `ControlValve ⊑ Assembly`
  while `Valve ⊑ MaterialArtifact` as a hierarchy incoherence. This is not incoherent:
  subsumption permits subclasses to carry stronger commitments than their superclass.
  `ControlValve ⊑ Valve` and `ControlValve ⊑ Assembly` are both valid without requiring
  `Valve ⊑ Assembly`.
- **Default to the weaker genus.** The safe default for a kind is the weakest genus that
  does not exclude known instances; the stronger commitment (Assembly) is what requires
  explicit justification. ODR-007 inverted this rule; this ODR restores it.

---

## Consequences

- `ControlValve ⊑ Valve ⊓ Assembly` (consistent: Assembly ⊑ MaterialArtifact).
- Future valve subclasses use `MaterialArtifact` as `genus_bfo_root` by default. Asserting
  `Assembly` requires explicit compositional justification recorded in an ODR.
- OWL export to be regenerated.
- ODR-007 status updated to "Superseded by ODR-013".
