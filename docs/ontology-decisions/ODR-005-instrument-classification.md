# ODR-005 — Instrument Classification: Transmitters, Indicators, and Thermowell

**Status:** Accepted  
**Date:** 2026-05-02  
**Deciders:** Nicolau Santos  

---

## Context

Instrumentation classes span a wide range of physical forms: transmitters are tightly integrated electronic units; indicators are multi-component display assemblies; thermowells are single machined metal pieces. Placing all of them under the same root would lose physically relevant information. This record documents the decisions made for the Tier 2 instrument classes.

---

## Source Definitions

**Transmitter**
- ISO 15926-4: *"A transmitter is a functional object that is capable of transmitting."*
- CFIHOS: *"A physical object that is an element that receives a process variable signal from a sensor and converts it into an output signal."*
- DEXPI: *"A detecting instrument that generates a process variable signal and converts it into an output signal."*
- ISA 5.1: *"A device that senses a process variable through the medium of a sensor or measuring element and has an output whose steady-state value varies only as a predetermined function of the process variable."*
- POSC Caesar: *"A detecting instrument that generates a process variable signal and converts it into an output signal."*

**Indicator**
- ISO 15926-4: *"An indicator is an instrumentation function that has a capability of indicating."* *(Note: ISO 15926 models indicator as a function, not a physical object — this is a known modelling inconsistency in that standard.)*
- POSC Caesar: *"An artefact that is intended to display the value or the status of a condition."*
- OnePetro: *"In the context of a mechanical load, an indicator is a dial or gauge."*

**Thermowell**
- ISO 15926-4: *"A thermowell is an instrument component that is a pressure-tight receptacle adapted to receive a temperature sensing element, provided with external threads or other means for pressure-tight attachment to a vessel or pipe."*
- CFIHOS: *"A physical object that is a pressure-tight receptacle adapted to receive a temperature sensing element, provided with external threads or other means for pressure-tight attachment to a vessel or pipe."*
- POSC Caesar: *"An artefact that is a pressure-tight receptacle adapted to receive a temperature sensing element, provided with external threads or other means for pressure-tight attachment to a vessel or pipe."*

*(Definitions for CFIHOS and POSC Caesar are verbatim identical — strong cross-standard consensus.)*

---

## Decision

### BFO root assignment

| Class | genus | genus_bfo_root | Rationale |
|---|---|---|---|
| transmitter | Instrument | **MaterialArtifact** | Tightly integrated electronic unit; no distinct maintainable sub-assemblies at classification level |
| indicator | Instrument | **Assembly** | Multi-component: sensing element + display element + housing, individually replaceable |
| thermowell | Instrument | **MaterialArtifact** | Single machined piece (turned or forged from bar stock); no sub-assemblies |

### Axiom mode assignment

| Class | Mode | Rationale |
|---|---|---|
| transmitter | equivalent | SignalTransmissionFunction is specific and sufficient |
| indicator | equivalent | IndicationFunction (local display, no remote output) uniquely identifies |
| thermowell | **necessary** | Structurally defined; protection function shared by other device types |

### Genus for flow indicator and pressure gauge

Both `flow indicator` and `pressure gauge` were initially assigned `genus = Instrument`. After `indicator` was confirmed as an enriched class (id 133), both were refined to `genus = indicator` with `bfo_root = Assembly`, consistent with the indicator hierarchy.

---

## Rationale

### Transmitter → `MaterialArtifact`

Modern electronic transmitters (pressure, temperature, flow, level) are manufactured as single integrated units: the sensing element, signal conditioning electronics, housing, and process connection are assembled by the manufacturer and are not intended to be field-disassembled into sub-components for maintenance. From a BFO perspective, the transmitter functions as a single causally unified object. `MaterialArtifact` (not `Assembly`) is therefore appropriate.

### Indicator → `Assembly`

An indicator has at least two distinct functional components: a **sensing/measuring element** and a **display element** (dial, scale, digital readout). In most implementations a third component — the housing — is also distinct. These parts are separately sourced and replaceable. A Bourdon-tube pressure gauge, for instance, has a Bourdon tube (sensing), a pointer/scale (display), and a case (housing) that can be individually serviced. `Assembly` captures this multi-part structure.

### Thermowell → `MaterialArtifact` and `necessary` mode

The ISO 15926-4, CFIHOS, and POSC Caesar definitions are verbatim identical and describe a thermowell as a **single pressure-tight receptacle** — a monolithic piece machined from bar stock or a forging. It has a stem, a bore, and a process connection, but these are geometric features of one piece, not separate assembled components.

A thermowell's classification basis is structural, not functional: a TemperatureSensorProtectionFunction is also borne by heat shields, lagging, and other protective devices. The differentia that identify a thermowell specifically — a pressure-tight bore dimensioned to accept a thermocouple or RTD, with a threaded or flanged process connection — are structural. This makes `necessary` the appropriate axiom mode.

**Assembly was rejected** for thermowell: the initial proposal assigned `genus_bfo_root = Assembly`, which was corrected after review. A single machined piece cannot be an assembly by BFO's definition.

### ISO 15926 modelling inconsistency for indicator

ISO 15926-4 classifies `INDICATOR` as an `INSTRUMENTATION FUNCTION` rather than as a physical object. This is an acknowledged modelling choice in ISO 15926 (which uses a strongly functional ontology). COPI follows POSC Caesar's more physically grounded classification — an indicator is a physical artefact that *bears* an IndicationFunction, not the function itself.

---

## Consequences

- All instrument subtypes (pressure transmitter, temperature transmitter, flow indicator, pressure gauge, etc.) inherit the `bfo_root` from their genus.
- Transmitter subtypes remain `MaterialArtifact`; indicator subtypes are `Assembly`.
- The ISO 15926 functional modelling of `INDICATOR` is noted as a cross-standard divergence in `cross_standard_links`, not adopted as genus.
- Thermowell, being `necessary` mode, will not support automatic reasoner classification of instances — this is intentional and safe under OWA.
