# ODR-006 — Function Hierarchy and Tank/StorageTank Merge

**Status:** Accepted  
**Date:** 2026-05-02  
**Deciders:** Nicolau Santos  

---

## Context

Two related issues were identified in the Validate diagram:

1. **Missing function hierarchy arrows** — `PressureContainmentFunction` and `StorageFunction` appeared as direct subclasses of `DesignedFunction`, with no arrow connecting them to `ContainmentFunction`. The `function_parent` field existed in the schema but was ignored by `build_consequence_graph()`.

2. **Tank/StorageTank redundancy** — `tank` was modelled as an intermediate class between `vessel` and `storage tank`, but review showed they are semantically equivalent in the O&G domain and in the normative sources.

---

## Decision 1 — Function Hierarchy

`build_consequence_graph()` was updated to read the `function_parent` field and render intermediate function nodes. The settled function hierarchy is:

```
DesignedFunction
├── ContainmentFunction          ← Vessel
│   ├── PressureContainmentFunction  ← PressureVessel
│   └── StorageFunction              ← StorageTank
├── AbsorptionFunction           ← Absorber
├── HeatTransferFunction         ← HeatExchanger
├── CompressionFunction          ← Compressor
├── PumpingFunction              ← Pump
└── FlowControlFunction          ← Valve
```

**Rationale:** When `PressureVessel ⊆ Vessel` is expressed via `equivalentClass`, the reasoner must be able to infer that any bearer of `PressureContainmentFunction` also bears `ContainmentFunction`. This requires `PressureContainmentFunction ⊆ ContainmentFunction` in the function hierarchy. Without this axiom, the class hierarchy and the function hierarchy are disconnected and the OWL reasoner cannot propagate subclass membership correctly.

The same applies to `StorageFunction ⊆ ContainmentFunction`: a storage tank contains fluids (ContainmentFunction) and the storage purpose is a specialisation of containment, not a distinct functional category.

`AbsorptionFunction` and `HeatTransferFunction` are **not** placed under `PressureContainmentFunction` despite Absorber and HeatExchanger being subtypes of PressureVessel. Their identity-giving functions are distinct functional categories (mass transfer and heat transfer, respectively) that co-occur with pressure containment in the same object but do not specialise it.

---

## Decision 2 — Tank and StorageTank Are the Same Class

The intermediate class `tank` (id 8) was deleted. `storage tank` now has `genus = Vessel` directly, with `alt_label = ["tank"]`.

### Source Definition

- ISO 15926-4: *"A STORAGE TANK is an ARTEFACT and a TANK that is intended for storage."*

### Why They Are the Same

The ISO 15926-4 definition is near-circular: a TANK is already a vessel for storage, and a STORAGE TANK is a tank *intended for storage*. No normative source provides a definition of "tank" that is meaningfully broader than "storage tank". The distinction "temporary holding vs. long-term storage" that would justify two separate classes does not appear in ISO 15926-4, CFIHOS, POSC Caesar, or ISO 14224.

In O&G plant practice, the terms "tank" and "storage tank" are used interchangeably for the same physical equipment category (crude oil tanks, product tanks, slop tanks, water tanks, etc.).

### Consequence of Keeping Both

Both classes had `function_name = StorageFunction` and `axiom_mode = equivalent`. Under OWL semantics this makes them logically equivalent classes (`Tank ≡ StorageTank`), which is correct but makes the intermediate class redundant.

### Alias

`"tank"` is recorded as an `alt_label` on `StorageTank` to capture alternative labelling in source standards and plant documentation.

---

## Consequences

- The settled static equipment hierarchy is:
  ```
  Vessel
  ├── PressureVessel
  │   ├── Absorber
  │   └── HeatExchanger
  └── StorageTank  (alt: tank)
  ```
- Any future tank subtype (buffer tank, slop tank, surge drum) should use `StorageTank` or `Vessel` as genus, not `Tank`.
- The `function_parent` field must be set for every new enrichment where the designed function specialises a parent function — it is not filled automatically by the LLM.
