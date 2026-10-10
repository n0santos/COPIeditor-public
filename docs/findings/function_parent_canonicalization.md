# Function Parent Canonicalization — COPI Enrichment DB

**Date:** 2026-05-03  
**Tool:** `tools/resolve_function_parent_conflicts.py`  
**Status:** Applied — 0 conflicts remain.

---

## Context

The `function_parent` field in `step1_function` records the most specific
function supertype available for each equipment class's identity-giving function.
The genus-proximum principle (Step 2 of the enrichment method) applies equally
here: the parent should be the most specific available COPI function class, not
`DesignedFunction` if a more specific enriched parent exists.

Conflicts arise when the same `function_name` appears across multiple enrichment
records with different parents, typically because:

1. **Temporal skew** — an equipment class was enriched before its parent function
   was itself enriched. The older record correctly used `DesignedFunction` at the
   time; newer records correctly use the now-available specific parent.
2. **Column/JSON drift** — in three cases the SQL column was manually updated to
   the specific parent but `llm_raw_response` was not synchronised, leaving the
   JSON field still pointing to `DesignedFunction`.

---

## Conflicts Detected and Resolved

All 10 conflicts were resolved automatically by specificity (Rule 1: the most
specific parent in the COPI hierarchy wins; `DesignedFunction` is always the
least specific option). Zero cases required manual review.

| Function name | Old parent(s) | Canonical parent | Rationale |
|---------------|---------------|-----------------|-----------|
| `FlowIndicationFunction` | DesignedFunction / IndicationFunction | `IndicationFunction` | Specificity: IndicationFunction is a COPI class, more specific than DesignedFunction |
| `IndicationFunction` | DesignedFunction / InstrumentationFunction | `InstrumentationFunction` | Specificity: InstrumentationFunction is a COPI class, more specific than DesignedFunction |
| `IsolationFunction` | DesignedFunction (3×) / FlowControlFunction (7×) | `FlowControlFunction` | Specificity: FlowControlFunction is a COPI class, more specific than DesignedFunction |
| `LevelIndicationFunction` | DesignedFunction / IndicationFunction | `IndicationFunction` | Specificity |
| `PressureMeasurementFunction` | DesignedFunction / IndicationFunction | `IndicationFunction` | Specificity |
| `PressureTransmissionFunction` | DesignedFunction / SignalTransmissionFunction | `SignalTransmissionFunction` | Specificity |
| `ProcessControlledFlowFunction` | DesignedFunction (8×) / FlowControlFunction (19×) | `FlowControlFunction` | Specificity |
| `SignalTransmissionFunction` | DesignedFunction / InstrumentationFunction | `InstrumentationFunction` | Specificity |
| `StorageFunction` | DesignedFunction / ContainmentFunction | `ContainmentFunction` | Specificity |
| `TemperatureIndicationFunction` | DesignedFunction / IndicationFunction | `IndicationFunction` | Specificity |

---

## Records Modified

32 enrichment records were updated (coluna `function_parent` and/or
`step1_function.function_parent` + `step1_function.function_parent_enriched`
inside `llm_raw_response`).

Key cluster labels whose `function_parent` was updated:

| cluster_label | function_name | Old parent | New parent |
|---------------|---------------|------------|------------|
| isolation valve (ids 300, 304, 309) | IsolationFunction | DesignedFunction | FlowControlFunction |
| absolute pressure transmitter (id 220) | PressureTransmissionFunction | DesignedFunction | SignalTransmissionFunction |
| level sight glass (id 59) | LevelIndicationFunction | DesignedFunction | IndicationFunction |
| analogue temperature indicator (id 61) | TemperatureIndicationFunction | DesignedFunction | IndicationFunction |
| basin, storage tank (ids 94, 138) | StorageFunction | DesignedFunction | ContainmentFunction |
| butterfly/globe/ball/gate/choke control valve (ids 164–168) | ProcessControlledFlowFunction | DesignedFunction | FlowControlFunction |
| control valve (ids 270, 301, 306) | ProcessControlledFlowFunction | DesignedFunction | FlowControlFunction |
| transmitter (id 9) | SignalTransmissionFunction | DesignedFunction (JSON only) | InstrumentationFunction |
| flow indicator (id 95) | FlowIndicationFunction | DesignedFunction (JSON only) | IndicationFunction |
| pressure gauge (id 124) | PressureMeasurementFunction | DesignedFunction (JSON only) | IndicationFunction |
| indicator (id 133) | IndicationFunction | DesignedFunction (JSON only) | InstrumentationFunction |
| pressure transmitter (id 50) | PressureTransmissionFunction | (enriched flag false) | SignalTransmissionFunction (enriched=True) |

The remaining 20 records with `[json: X → X]` in the dry-run output were updated
only to set `function_parent_enriched = True` (the parent name was already correct
but the boolean flag was stale).

---

## Post-fix Verification

```
python tools/resolve_function_parent_conflicts.py
→ 0 conflict(s) found
```

```
python tools/audit_function_disjointness.py
→ parent_conflicts section: absent (no ⚠ markers in hierarchy table)
→ FlowControlFunction: 2 children (IsolationFunction, ProcessControlledFlowFunction) — correct
```

Spot-check of 3 records (ids 59, 220, 300):
- `function_parent` column ✓
- `step1_function.function_parent` in JSON ✓
- `step1_function.function_parent_enriched = True` in JSON ✓

---

## Implications for the Thesis

If hierarchy statistics are reported (e.g. "the COPI function hierarchy has N
classes across M levels"), this canonicalization is the source of truth for the
hierarchy structure. Before this fix, several function classes were misattributed
to `DesignedFunction` when a more specific parent existed, artificially flattening
the hierarchy.

Post-fix hierarchy depth (validated enrichments):

```
DesignedFunction
├── InstrumentationFunction
│   ├── IndicationFunction
│   │   ├── FlowIndicationFunction
│   │   ├── LevelIndicationFunction
│   │   ├── PressureMeasurementFunction
│   │   └── TemperatureIndicationFunction
│   └── SignalTransmissionFunction
│       ├── FlowSignalTransmissionFunction
│       ├── PressureTransmissionFunction
│       │   └── DifferentialPressureTransmissionFunction
│       ├── PositionTransmissionFunction
│       └── ConductivityTransmissionFunction
├── FlowControlFunction
│   ├── IsolationFunction
│   └── ProcessControlledFlowFunction
│       └── BinaryFlowControlFunction
├── ContainmentFunction
│   ├── PressureContainmentFunction
│   └── StorageFunction
├── SeparationFunction
│   ├── GravitySeparationFunction
│   ├── KnockOutSeparationFunction
│   └── ThreePhaseSeparationFunction
├── DetectionFunction
│   ├── FlameDetectionFunction
│   └── GasDetectionFunction
├── HeatingFunction
│   ├── FiredHeatingFunction
│   └── ReactiveHeatingFunction
├── SafetyReliefFunction
│   └── SubsurfaceSafetyFunction
├── PumpingFunction
│   └── HydraulicPumpingFunction
└── ... (119 direct children of DesignedFunction)
```
