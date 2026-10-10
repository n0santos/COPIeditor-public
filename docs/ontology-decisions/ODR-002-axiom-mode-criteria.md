# ODR-002 — Axiom Mode Selection Criteria

**Status:** Accepted  
**Date:** 2026-05-02  
**Deciders:** Nicolau Santos  

---

## Context

OWL allows two fundamentally different ways to define a class:

- **Necessary conditions only** (`rdfs:subClassOf` restrictions) — an open-world axiomatization where membership is not decidable from structure alone.
- **Necessary and sufficient conditions** (`owl:equivalentClass` restrictions) — a closed definition that enables the reasoner to *automatically classify* individuals.

For equipment ontologies, choosing the wrong mode creates either false positives (reasoner classifies unrelated things as the target class) or false negatives (correctly built instances are not classified by the reasoner). The COPI ontology defines a principled criterion for this choice.

---

## Decision

Axiom mode is assigned based on the **classification basis** of the equipment class:

| Mode | Criterion | Effect |
|---|---|---|
| `equivalent` | Class is individuated primarily by its **designed function** — the function is necessary *and* sufficient to identify an instance as belonging to the class | Reasoner can automatically classify; enables inference |
| `necessary` | Class is individuated primarily by **structural or constructive features** — the function may be shared by other classes, or the structural differentia are necessary conditions only | Safe under OWA; avoids false positives |
| `mixed` | Class has both a functional side (equivalent) and a constructive subtype side (necessary) | Hybrid; used when both bases coexist in the same class |

---

## Application to Tier 1 Classes

| Class | Mode | Basis |
|---|---|---|
| vessel | equivalent | ContainmentFunction is necessary and sufficient |
| pressure vessel | equivalent | PressureContainmentFunction distinguishes from unpressurised vessels |
| absorber | equivalent | AbsorptionFunction (mass transfer) is specific enough to identify |
| heat exchanger | equivalent | HeatTransferFunction uniquely identifies |
| storage tank | equivalent | StorageFunction (long-term) distinguishes from process vessels |
| compressor | equivalent | CompressionFunction (gases only) uniquely identifies |
| pump | equivalent | PumpingFunction (liquids) uniquely identifies |

### Application to Tier 2 Classes

| Class | Mode | Basis |
|---|---|---|
| transmitter | equivalent | SignalTransmissionFunction uniquely identifies |
| indicator | equivalent | IndicationFunction (local display) uniquely identifies |
| thermowell | **necessary** | Structurally defined (pressure-tight receptacle); TemperatureSensorProtectionFunction is shared by other protective devices |

---

## Rationale

The key insight is that **functional basis implies equivalence** in this domain: if the only thing that makes an object a compressor is that it bears a CompressionFunction, then bearing a CompressionFunction is both necessary and sufficient to be a compressor. The open-world assumption is not a concern here because the function itself is tightly scoped.

**Thermowell** is the exception: its protective function (shielding temperature sensors from process conditions) is also borne by other devices (protective tubes, heat shields). Its identity-giving differentia — the pressure-tight receptacle with threaded/flanged process attachment — are structural features, not functional ones. Using `equivalent` on a structural description under OWA would create false positives whenever an unrelated pressure-tight receptacle is described.

---

## Alternatives Rejected

**Always use `necessary` (conservative approach):** Rejected because it sacrifices the reasoner's ability to classify instances automatically, which is one of the main advantages of a formal ontology over a taxonomy.

**Always use `equivalent` (aggressive approach):** Rejected because structurally-defined classes (ball valve, gate valve, thermowell) would generate false positives — any object with the listed structural parts would be classified as an instance, regardless of intended function.

---

## Consequences

- Every new class must have its classification basis explicitly assessed before axiom mode is assigned.
- The `axiom_mode` field in the enrichment database must be set to `equivalent`, `necessary`, or `mixed` with a documented rationale.
- Structurally-defined subclasses of a functionally-defined class (e.g., centrifugal pump as subclass of pump) may require `mixed` mode.
- The mode choice has direct implications for the OWL axiom generated at export time.
