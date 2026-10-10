# ODR-004 — Rotating Equipment: Pump and Compressor

**Status:** Accepted  
**Date:** 2026-05-02  
**Deciders:** Nicolau Santos  

---

## Context

Pump and compressor are the two rotating equipment classes in Tier 1. Both operate on a fluid (liquid and gas, respectively) by adding mechanical energy. Their genus, axiom mode, and necessary parts required explicit decisions because: (1) several industrial sources treat them as subtypes of generic "process equipment" classes that are not ontologically precise; (2) their necessary parts vary significantly across subtypes (centrifugal vs. reciprocating vs. screw), creating a risk of over-specifying universal conditions.

---

## Source Definitions

**Pump**
- ISO 15926-4: *"A pump is a functional object that is capable of pumping but may require parts and subsystems for that capability."*
- CFIHOS: *"A physical object that adds or removes mechanical energy to a fluid, either constantly or periodically."*
- DEXPI: *"A machine that is capable of pumping but may require parts and subsystems for that capability."*
- ISO 14224: equipment category only, no definition.
- POSC Caesar: no definition available.

**Compressor**
- ISO 15926-4: *"A compressor is a functional object that has the capability of compressing a gas."*
- CFIHOS: *"A physical object that is driven by a prime mover by which energy is either constantly or periodically added to an amount of gas in order to increase its pressure."*
- DEXPI: *"A machine that has the capability of compressing a gas."*
- SLB Glossary: *"A device that raises the pressure of air or natural gas."*
- POSC Caesar: *"A gas pressure increase device and an artefact that is driven by a prime mover by which energy is either constantly or periodically added to an amount of gas in order to increase its pressure."*
- OnePetro: *"A type of pump that increases the pressure of gas."*
- ISO 14224: equipment category only, no definition.

---

## Decision

Both pump and compressor are placed directly under `Assembly` as the genus, with `equivalent` axiom mode.

**Pump necessary parts (universal — `hasComponentPartAtAllTimes`):**
- `PumpCasing` — contains the fluid and houses internal components
- `FluidDisplacementElement` — the element that imparts energy to the fluid (impeller, piston, gears, diaphragm — type varies by subtype)
- `FluidInlet` — connection to receive the fluid to be pumped
- `FluidOutlet` — connection to discharge pressurised fluid

**Pump necessary parts (subtype-specific — `is_subtype_specific: true`):**
- `DriveShaft` — present in most pumps but absent in pneumatic diaphragm and peristaltic pumps

**Compressor necessary parts (universal):**
- `CompressorCasing` — pressure-rated enclosure for the gas being compressed
- `CompressionElement` — the mechanism performing compression (impeller, piston, screw — type varies)
- `GasInlet` — connection for suction gas
- `GasOutlet` — connection for discharge gas

---

## Rationale

### Genus: `Assembly` (not `ProcessEquipment` or `MechanicalEquipment`)

Parent candidates from industrial standards include terms like "Mechanical equipment class" (CFIHOS), "ProcessEquipment" (DEXPI hierarchy), and "rotating equipment" (ISO 14224 category). None of these is an ontologically precise class in BFO/IOF-Core terms — they are administrative groupings used for maintenance planning, not formal genus terms.

`Assembly` is the most specific applicable IOF-Core class: both pumps and compressors are composed of multiple distinct, individually replaceable mechanical parts (casing, rotating element, bearings, seals, inlet/outlet connections) that form a single causally unified machine.

`MaterialArtifact` was rejected as too generic — it does not capture the multi-part, maintainable nature of these machines.

### Axiom mode: `equivalent`

PumpingFunction uniquely identifies pumps: if an assembly bears the function of adding mechanical energy to liquid for pressurisation and transport, it is a pump. No other assembly class in this ontology shares this functional description. The same argument applies to CompressionFunction for compressors (gas-specific energy addition for pressure increase).

Note: OnePetro describes a compressor as "a type of pump that increases the pressure of gas" — this is colloquial usage. Formally, pumps and compressors are disjoint: pumps operate on liquids (near-incompressible), compressors on gases (compressible). This disjointness will be captured in the OWL axioms.

### DriveShaft as subtype-specific

The drive shaft was initially proposed as a universal necessary part of all pumps. This was corrected after review: **pneumatic diaphragm pumps** are driven by compressed air acting directly on a diaphragm — no rotating shaft is present. **Peristaltic pumps** use a rotor that compresses a tube, but the motion-transmitting element differs fundamentally from a traditional shaft. `DriveShaft` was therefore demoted to `is_subtype_specific: true`, applying to rotodynamic and reciprocating pumps but not to all pumps universally.

### FluidInlet and FluidOutlet as universal parts

Every pump, regardless of operating principle, must have a port through which fluid enters and a port through which it exits. These are topological necessities of the pumping function and are universal across all pump subtypes. They were added to correct an omission in the initial enrichment.

---

## Consequences

- Centrifugal pump, reciprocating pump, screw pump, and other subtypes will inherit the four universal parts and may add subtype-specific parts (DriveShaft, Impeller, Piston, etc.).
- Disjointness between Pump and Compressor will be axiomatised (a machine cannot simultaneously add energy to liquid and gas in the same functional role).
- The `ProcessEquipment` and `MechanicalEquipment` terms from source standards are recorded as `cross_standard_links` but not used as genus in COPI.
