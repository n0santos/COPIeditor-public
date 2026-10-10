# ODR-001 — BFO/IOF-Core as Foundational Upper Ontology

**Status:** Accepted  
**Date:** 2026-05-02  
**Deciders:** Nicolau Santos  

---

## Context

The COPI ontology aims to provide a formal, reusable representation of equipment classes in oil & gas production plants, grounded in definitions from authoritative industrial standards (ISO 15926-4, POSC Caesar RDL, CFIHOS, DEXPI, SLB Glossary, ISO 14224). For the ontology to be interoperable with other industrial ontologies and to support automated reasoning, it must be aligned to a well-established upper ontology.

Three upper ontologies were considered: BFO (Basic Formal Ontology), DOLCE, and EMMO (Elementary Multiperspective Material Ontology). Additionally, the Industrial Ontology Foundry Core Ontology (IOF-Core) was evaluated as a mid-level ontology already aligned to BFO and designed for manufacturing and industrial systems.

---

## Decision

COPI is aligned to **BFO 2020** via **IOF-Core** as the primary mid-level ontology. All equipment classes are placed under IOF-Core roots, with three root categories used in practice:

- **`Assembly`** — a material artifact composed of multiple distinct, maintainable component parts (vessels, pumps, compressors, indicators)
- **`MaterialArtifact`** — a material artifact that is a single integrated unit (thermowells, transmitters as tightly integrated electronic units)
- **`EngineeredSystem`** — reserved for multi-equipment systems (currently unused in Tier 1–2)

The `genus_bfo_root` field in the enrichment database encodes this classification for every enriched class.

---

## Rationale

**BFO** provides a domain-neutral, formally rigorous foundation endorsed by ISO/IEC 21838-2. Its distinction between *continuants* (enduring objects) and *occurrents* (processes) maps naturally onto the separation between equipment (physical objects) and the processes they participate in — a distinction central to the COPI 4-step axiomatization methodology.

**IOF-Core** adds the industrial mid-level classes needed to avoid reinventing common concepts (material artifact, assembly, designed function, planned process), and is already used by ISO 15926-4 in its ontological formalization effort.

**DOLCE** was rejected because its *physical object* hierarchy does not distinguish between natural objects and artifacts at a level of granularity useful for this domain.

**EMMO** was rejected because its orientation toward materials science and physics introduces unnecessary complexity for equipment classification; its alignment to BFO is also less direct.

---

## Consequences

- Every COPI class must have an explicit `genus_bfo_root` value drawn from {`Assembly`, `MaterialArtifact`, `EngineeredSystem`}.
- The identity criterion for each class is its **designed function** (`DesignedFunction` in IOF-Core), which grounds the axiom mode selection (see ODR-002).
- Cross-standard definitions must be interpreted through BFO/IOF-Core lenses: functional descriptions from ISO 15926 map to `DesignedFunction`; structural descriptions map to `hasComponentPartAtAllTimes` restrictions.
- Future expansion (piping, electrical, civil) must maintain this alignment.
