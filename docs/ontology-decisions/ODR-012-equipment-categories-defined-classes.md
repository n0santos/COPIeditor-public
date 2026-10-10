# ODR-012 (proposed): Equipment categories — defined classes, naming, and relation to `iof:PieceOfEquipment`

- **Status:** Accepted (implemented in ODR-015 Phase 1, 2026-06-15; see Implementation Notes)
- **Date:** 2026-06
- **Related:** ODR-009 (revised); I1 (FL ODP); dual 9×9 taxonomy

## Context

COPI groups equipment by the operation its designed function realizes, yielding nine
categories currently named `...Equipment` (`MomentumTransferEquipment`, …) with two
exceptions (`ChemicalReactor`, `MeasurementInstrument`). Group review (Jun 2026) raised:

1. Why are these **defined classes** rather than asserted universals?
2. The defined-class form is what `iof:PieceOfEquipment` needs because it is **role-based**
   and anti-rigid; for a **rigid** function basis it is not necessary.
3. A per-operation defined class looks **redundant** with just querying the processes.
4. `...Equipment` is **confusing**: "equipment" is uncountable in English, and the name
   collides with `iof:PieceOfEquipment`, suggesting these are something *other than* pieces
   of equipment.
5. (separate) Should a **generic function taxonomy** parallel to the operations be included?

## Decision

1. **Keep the nine categories as defined classes** (`owl:equivalentClass`), not asserted
   universals.
2. **Rename the `...Equipment` head to `...Device`** — a count noun that does not collide
   with `iof:PieceOfEquipment` (alternatives `...Artifact`, `...Unit` considered; see Naming).
3. **Make the relation to `iof:PieceOfEquipment` explicit:** a COPI category instance that
   bears an `EquipmentRole` is (inferred) an `iof:PieceOfEquipment`. The COPI category is a
   *function-based* `MaterialArtifact` subclass; `iof:PieceOfEquipment` is the orthogonal
   *role-based* view. Document this so users see how the two notions connect.
4. **Defer** the generic function taxonomy (point 5) to the journal scope; recorded as
   considered.

## Rationale

- **(1) Why defined, not universal.** The categories are *dispersive functional groupings*,
  not natural kinds: "momentum-transfer equipment" spans pumps, compressors, and fans, which
  share a function-feature, not an essence. The identity-bearing universals are the *leaves*.
  Modeling the categories as defined classes is the more honest realist choice; asserting
  them as universals would over-commit to natural kinds that are not there.
- **(2) Rigidity ≠ necessity of a defined class.** Correct: `iof:PieceOfEquipment` *must* be
  defined because its basis (an equipment role) is anti-rigid. COPI's basis (designed
  function) is rigid, so a defined class is not *forced* for that reason. COPI uses the
  defined-class form for a different, deliberate reason — automatic classification plus a
  consistency check between a leaf's declared function and its category — and because the
  grouping is dispersive (point 1). COPI will **not** justify its defined classes by analogy
  to `iof:PieceOfEquipment`.
- **(3) Not redundant when the class carries axioms.** Naming the class is redundant *only*
  for retrieval; a DL/SPARQL query over the function-realization pattern would return the
  same members. The named class earns its place by being the **subject/object of further
  axioms** that a query cannot carry: selective disjointness (e.g.,
  `MomentumTransferDevice ⊓ MeasurementInstrument ⊑ ⊥`), ISO 14224 failure-mode mappings (the
  multifunctional reboiler populating two categories → two failure-mode families), and
  cross-standard equivalences. **Rule:** if a category carries no such axioms, drop it in
  favour of a direct query.
- **(4) Count noun + no collision.** "Equipment" is uncountable — an instance is "a pump",
  not "an equipment" — so a count-noun head is preferable for a class whose instances are
  individuals. A non-"Equipment" head also removes the apparent conflict with
  `iof:PieceOfEquipment`; the explicit relation (decision 3) then states how the two connect.

## Naming options

- **`...Device`** (chosen): count; standard in the literature ("mass-transfer device",
  "heat-transfer device"); mild stretch for very large vessels/columns. Uniform IRIs, with
  friendly `rdfs:label`s (reactor, instrument) where natural.
- **`...Artifact`**: precise (mirrors the genus `iof:MaterialArtifact`), count, zero
  collision; reads academic.
- **`...Unit`**: echoes "unit operation", but risks confusion with a process unit/skid (a
  *section* of plant) rather than a single item; `MeasurementUnit` collides with units of
  measure.
- Domain-natural labels retained regardless: *reactor* (ChemicalReaction), *instrument*
  (Measurement).

## Consequences

- Rename propagates to TTL class IRIs, the dual-taxonomy figure, and the paper text
  (head-noun change only; anonymous/camera-ready IRI handling unaffected).
- Add the `iof:PieceOfEquipment` relation axiom/annotation and a short paper note
  contrasting COPI category (function, rigid) vs `iof:PieceOfEquipment` (role, contextual).
- Re-run HermiT after rename + disjointness review.

## Open

- Whether to introduce the generic function taxonomy (point 5) now or in the journal.

---

## Implementation Notes (ODR-015 Phase 1, 2026-06-15)

### Decision 2 — `...Device` rename: implemented ✓

`MomentumTransferDevice`, `HeatTransferDevice`, `MassTransferDevice`,
`MechanicalSeparationDevice`, `PhaseChangeDevice`, `ContainmentDevice`,
`FlowControlDevice` are in `copi-core.ttl` with `owl:equivalentClass` definitions.
`ChemicalReactor` and `MeasurementInstrument` retain domain-natural labels as specified.

### Decision 3 — `iof:PieceOfEquipment` relation: RESOLVED (PR #10, 2026-06-18)

The `iof-av:explanatoryNote` documenting the complementary relation between COPI device
categories and `iof:PieceOfEquipment` was added to the `copi-core.ttl` ontology header in
COPI PR #10 (bilingual, en/pt-br). The note clarifies that a COPI `...Device` instance
that bears an `EquipmentRole` is inferred `iof:PieceOfEquipment` via IOF-Core's own
axioms — no new COPI axiom was introduced. The note is an `iof-av:explanatoryNote` on the
ontology IRI itself rather than per-class, reflecting the cross-cutting nature of the
relation.
