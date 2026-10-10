# Ontology Design Records — COPI

Records of significant design decisions made during the development of the COPI core ontology for oil & gas production plants.

## Index

| ODR | Title | Status | Date |
|---|---|---|---|
| [ODR-001](ODR-001-bfo-iof-alignment.md) | BFO/IOF-Core as Foundational Upper Ontology | Accepted | 2026-05-02 |
| [ODR-002](ODR-002-axiom-mode-criteria.md) | Axiom Mode Selection Criteria (equivalent / necessary / mixed) | Accepted | 2026-05-02 |
| [ODR-003](ODR-003-static-equipment-hierarchy.md) | Static Equipment Hierarchy: Vessel, PressureVessel, and Subtypes | Accepted | 2026-05-02 |
| [ODR-004](ODR-004-rotating-equipment.md) | Rotating Equipment: Pump and Compressor | Accepted | 2026-05-02 |
| [ODR-005](ODR-005-instrument-classification.md) | Instrument Classification: Transmitters, Indicators, and Thermowell | Accepted | 2026-05-02 |
| [ODR-006](ODR-006-function-hierarchy-and-tank-merge.md) | Function Hierarchy and Tank/StorageTank Merge | Accepted | 2026-05-02 |
| [ODR-007](ODR-007-valve-genus-assembly.md) | Valve: Genus Corrected from MaterialArtifact to Assembly | Superseded | 2026-05-02 |
| [ODR-008](ODR-008-valve-functional-constructive-axes.md) | Valve Hierarchy: Functional and Constructive Classification Axes | Accepted | 2026-05-02 |
| [ODR-009](ODR-009-processkind-taxonomy.md) | Ontological Rooting of the Operation Classes (revised) | Accepted | 2026-06-15 |
| [ODR-010](ODR-010-participant-type-anchoring.md) | Participant Type Anchoring for Step 5 | Accepted | 2026-06-15 |
| [ODR-011](ODR-011-step5-axiomatization-template.md) | Step 5 Axiomatization: Dual Taxonomy and OWL Template | Accepted | 2026-06-15 |
| [ODR-012](ODR-012-equipment-categories-defined-classes.md) | Equipment Categories: Defined Classes, Naming, and Relation to iof:PieceOfEquipment | Accepted | 2026-06-15 |
| [ODR-013](ODR-013-valve-genus-reverted.md) | Valve: Genus Reverted to MaterialArtifact; Assembly Reserved for Compositionally-Defined Subclasses | Accepted | 2026-06-10 |
| [ODR-014](ODR-014-module-export-strategy.md) | Module Export Strategy: copi-base.ttl and per-equipment modules | Accepted | 2026-06 |
| [ODR-015](ODR-015-release-architecture-split-copi-base.md) | Release Architecture: ODK Split, Module Components, copi-base.ttl Dissolution | Accepted (Phase 1) | 2026-06-15 |
| [ODR-016](ODR-016-sthe-nivel1-encoding.md) | STHE Nível 1 Encoding: Primitive Class with HeatTransferFunction | Accepted | 2026-06-15 |
| [ODR-017](ODR-017-nivel2-operation-anchors.md) | Nível 2 Incremento 1a: Operation Anchors and OntoCAPE Cross-References | Accepted | 2026-06-22 |
| [ODR-018](ODR-018-nivel2-structural-genera.md) | Nível 2 Incremento 2a: Structural Genera (PressureVessel, Instrument, HeatExchanger) | Accepted | 2026-06-22 |
| [ODR-019](ODR-019-nivel2-structural-differentia.md) | Nível 2 Incremento 2b: Structural Differentia (FOL, →) for HeatExchanger and STHE | Accepted | 2026-06-22 |

## Status vocabulary

- **Accepted** — decision is in force and reflected in the enrichment database
- **Revised** — superseded by a later ODR; original reasoning preserved for traceability
- **Proposed** — under discussion, not yet applied

## Template

```markdown
# ODR-NNN — Title

**Status:** Accepted / Revised / Proposed
**Date:** YYYY-MM-DD
**Deciders:** name(s)

## Context
## Source Definitions
## Decision
## Rationale
## Alternatives Rejected
## Consequences
```
