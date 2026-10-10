# ODR-003 — Static Equipment Hierarchy: Vessel, PressureVessel, and Subtypes

**Status:** Accepted  
**Date:** 2026-05-02  
**Deciders:** Nicolau Santos  

---

## Context

The COPI ontology must place five static equipment classes — vessel, pressure vessel, absorber, heat exchanger, and storage tank — in a coherent hierarchy. Several genus choices were available for each class, and several alternatives were explicitly considered and rejected. This record documents the hierarchy as settled for Tier 1 and the reasoning behind each placement.

---

## Source Definitions

**Vessel**
- ISO 15926-4: *"A vessel is a fluid container, intended for storage and/or processing of fluids."*
- CFIHOS: *"A container intended for storage and/or processing of fluids."*
- DEXPI: *"A container intended for storage and/or processing of fluids or solids."*

**Pressure Vessel**
- POSC Caesar: *"A vessel intended to withstand external and/or internal pressure."*
- ISO 14224: no definition provided (equipment category only).

**Absorber**
- ISO 15926-4: *"An absorber is a functional object that has a capability of absorbing."*
- POSC Caesar: *"A functional object that absorbs."*
- OnePetro: *"A vertical, cylindrical vessel that recovers heavier hydrocarbons from a mixture of lighter hydrocarbons."*

**Heat Exchanger**
- ISO 15926-4: *"A heat exchanger is an exchanger that has the capability of heat exchanging."*
- CFIHOS: *"A physical object that is intended to transfer heat from one object to another."*
- POSC Caesar: no definition provided.
- ISO 14224: no definition provided.

**Storage Tank**
- ISO 15926-4: *"A storage tank is an artefact and a tank that is intended for storage."*

---

## Decision

The settled hierarchy is:

```
Assembly
└── Vessel                  (ContainmentFunction)
    ├── PressureVessel      (PressureContainmentFunction)
    │   ├── Absorber        (AbsorptionFunction)
    │   └── HeatExchanger   (HeatTransferFunction)
    └── Tank                (StorageFunction)
        └── StorageTank     (long-term StorageFunction)
```

---

## Key Decisions and Rationale

### Vessel → genus: `Assembly`

Vessels are composed of multiple distinct, individually manufactured and replaceable parts (shell plates, heads, nozzles, flanges, gaskets, internals). They are not single-piece material artifacts. `Assembly` is the most specific applicable IOF-Core root.

### PressureVessel → genus: `Vessel`

The POSC Caesar definition is decisive: pressure vessels are vessels with a structural constraint (pressure boundary). `PressureVessel` inherits the ContainmentFunction of Vessel and adds a PressureContainmentFunction differentia.

### Absorber → genus: `PressureVessel` (not `Vessel`, not `Separator`)

**Separator rejected:** Absorption is mass transfer between phases (gas-liquid contact); separation is physical segregation of already-separated phases. The absorptive mechanism is chemically or physically distinct from mechanical separation. Assigning `Separator` as genus would conflate mass-transfer columns with gravitational or centrifugal separators.

**Vessel accepted as interim genus** while PressureVessel was not yet enriched.

**Refined to PressureVessel** after PressureVessel was confirmed as an enriched class: all absorbers in oil & gas operate under process pressure (the gas stream enters under pressure; the solvent circulates under pressure). The pressure boundary is definitionally required, not incidental.

*Genus progression recorded:* Separator → Vessel → **PressureVessel**

### HeatExchanger → genus: `PressureVessel` (not `Assembly`)

All heat exchangers in oil & gas production plants are pressure-containing equipment. Shell-and-tube exchangers, plate exchangers, air coolers, and fired heaters all operate with at least one fluid stream under pressure, requiring a certified pressure boundary per applicable pressure vessel codes (ASME VIII, EN 13445, etc.).

**Assembly rejected as final genus:** while HeatExchanger is physically an assembly, `PressureVessel` is more specific — it carries the pressure-boundary differentia that Assembly does not. Using `Assembly` as genus would lose information expressible in the ontology.

*Genus progression recorded:* Assembly (placeholder) → **PressureVessel**

### StorageTank → genus: `Tank`

`Tank` is an enriched intermediate class (a vessel with a StorageFunction). `StorageTank` refines it by specifying long-term, dedicated storage (as opposed to surge drums or boot drums that temporarily hold fluid during a process). ISO 15926-4 explicitly uses "intended for storage" as the differentia.

---

## Consequences

- Any new static equipment class (reactor, column, drum, separator) must be evaluated for placement under `Vessel`, `PressureVessel`, or `Tank` before a more general root is used.
- The pressure-boundary criterion is operative: if a vessel is designed and certified to operate under internal or external pressure differential, it is a `PressureVessel`.
- Absorber and HeatExchanger are now siblings under PressureVessel — a future `Separator` class would also be a sibling if it operates under pressure (which most do in O&G).
