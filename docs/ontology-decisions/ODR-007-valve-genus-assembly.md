# ODR-007 — Valve: Genus Corrected from MaterialArtifact to Assembly

**Status:** Superseded by ODR-013  
**Date:** 2026-05-02  
**Supersedes:** initial exported enrichment of `valve` (id 4)  
**Deciders:** Nicolau Santos  

---

## Context

The root class `valve` was initially enriched and exported with `genus = MaterialArtifact` and `genus_bfo_root = MaterialArtifact`. During Tier 3 review, this classification was identified as incorrect. All child classes of `valve` (ball valve, gate valve, control valve, check valve, etc.) inherit this root, making the genus choice consequential for the entire valve hierarchy.

---

## Source Definitions

- ISO 15926-4: *"A valve is a functional object that has the capability of controlling the flow of a fluid."*
- CFIHOS: *"A physical object that controls the rate, volume or direction of flow of a fluid by opening, closing or obstructing passageways."*
- POSC Caesar: *"A functional object that controls the rate, volume or direction of flow."*
- ISA 5.1: valve as a final control element in a control loop.

---

## Decision

`genus` and `genus_bfo_root` corrected from `MaterialArtifact` to **`Assembly`**.  
`axiom_mode` remains `necessary` (unchanged).  
Status reset from `exported` to `validated` pending re-export.

---

## Rationale

**Why Assembly:**

A valve — even the simplest manual shutoff valve — is composed of multiple distinct, individually replaceable parts:

- **ValveBody** — the pressure-containing shell; replaced when corroded or cracked
- **FlowControlElement** — the closure member (ball, disc, gate, plug, needle) that modulates flow; replaced for wear
- **Seat** — the sealing surface against which the closure member operates; replaced for wear or leakage
- **Stem/Spindle** — transmits motion from handwheel or actuator to closure member
- **Packing/Stem Seal** — prevents process fluid from escaping along the stem; routinely replaced

In plant maintenance practice, valves are overhauled by replacing trim (seat + closure member + packing) while retaining the body — a clear sign that they are assemblies of distinct parts, not monolithic material artifacts.

**Why MaterialArtifact was wrong:**

`MaterialArtifact` is appropriate for single-piece or tightly integrated units (thermowells, orifice plates) where there are no user-replaceable sub-components. A valve body without its trim cannot perform its function — the parts are essential and distinct. A thermowell without internal bore features cannot be separated into sub-parts at all.

**Consistency with children:**

`ControlValve` was already modelled with `genus_bfo_root = Assembly` (body + actuator + positioner). Having the parent class `Valve` as `MaterialArtifact` while a child class was `Assembly` created an incoherent hierarchy — a child class cannot be more complex than the root from which it inherits.

**Why axiom_mode stays `necessary`:**

`FlowControlFunction` is not sufficient to identify a valve because fixed flow restrictors (orifice plates, flow nozzles) also restrict flow without being valves. The defining differentia of a valve is **variable, on-demand flow control** — but expressing this precisely in OWL without creating false positives is safer with `necessary` mode, leaving classification to structural constraints in subclasses.

---

## Consequences

- All valve subclasses inherit `genus_bfo_root = Assembly`.
- Simple valves (needle, plug) that could arguably be `MaterialArtifact` remain `Assembly` at the genus level for consistency; their individual enrichments may refine `bfo_root` if justified.
- The OWL export must be regenerated to reflect this correction.
- Future valve classes must not use `MaterialArtifact` as `genus_bfo_root` without explicit justification.
