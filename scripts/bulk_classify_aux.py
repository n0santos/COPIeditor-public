#!/usr/bin/env python3
"""
Bulk-classify pending auxiliary_class entries by name pattern.

Preview (default — no DB writes):
    python -m scripts.bulk_classify_aux

Apply:
    python -m scripts.bulk_classify_aux --commit

Edit EXACT and SUFFIX_PATTERNS below to adjust rules before committing.
"""

import argparse
import re
import sqlite3
from pathlib import Path

DB_PATH = Path("data/enrichment.db")

# ---------------------------------------------------------------------------
# Rules — edit here to adjust before running with --commit
# ---------------------------------------------------------------------------

# Exact name → category.  First match wins over suffix patterns.
EXACT: dict[str, str] = {

    # Process — occurrents
    "Flame":                              "Process",
    "ElectricalCurrentFlow":              "Process",
    "KineticMotion":                      "Process",
    "MechanicalMotion":                   "Process",
    "MechanicalMovement":                 "Process",
    "MechanicalRotation":                 "Process",
    "MechanicalWork":                     "Process",
    "RotationalMotion":                   "Process",

    # Quality — specifically dependent continuants
    "Temperature":                        "Quality",
    "WeightOnBit":                        "Quality",
    "MechanicalForce":                    "Quality",
    "StructuralForce":                    "Quality",
    "MechanicalLoad":                     "Quality",
    "MechanicalDisplacement":             "Quality",
    "StructuralDisplacement":             "Quality",
    "ACElectricalPower":                  "Quality",
    "ElectricalPower":                    "Quality",
    "MechanicalPower":                    "Quality",
    "WellborePressure":                   "Quality",
    "PressureField":                      "Quality",

    # InformationContentEntity — generically dependent continuants
    "Signal":                             "InformationContentEntity",
    "ControlSignal":                      "InformationContentEntity",
    "ManualControlSignal":                "InformationContentEntity",
    "ReferenceSignal":                    "InformationContentEntity",
    "DetectionSignal":                    "InformationContentEntity",
    "InformationSignal":                  "InformationContentEntity",
    "StandardizedSignal":                 "InformationContentEntity",
    "VisualSignal":                       "InformationContentEntity",
    "VisualInformation":                  "InformationContentEntity",
    "LevelInformation":                   "InformationContentEntity",
    "LoggingData":                        "InformationContentEntity",
    "CompositionAnalysisData":            "InformationContentEntity",
    "ProcessVariable":                    "InformationContentEntity",
    "PhysicalVariable":                   "InformationContentEntity",
    "PhysicalQuantityValue":              "InformationContentEntity",
    "ProcessFluidSample":                 "InformationContentEntity",
    "InformationContentEntity":           "InformationContentEntity",
    "InformationBearingEntity":           "InformationContentEntity",
    "PressureSignalPair":                 "InformationContentEntity",

    # MeasurementICE — measurement-specific information content entities
    "ChromatographicSignal":              "MeasurementICE",
    "MeasurementSignal":                  "MeasurementICE",
    "TemperatureSignal":                  "MeasurementICE",
    "PressureSignal":                     "MeasurementICE",
    "MassFlowRateSignal":                 "MeasurementICE",
    "VibrationSignal":                    "MeasurementICE",
    "LevelSignal":                        "MeasurementICE",
    "PositionSignal":                     "MeasurementICE",
    "PressureReading":                    "MeasurementICE",
    "FlowMeasurement":                    "MeasurementICE",
    "DifferentialPressureIndication":     "MeasurementICE",
    "PhaseSequenceIndication":            "MeasurementICE",
    "LocalIndication":                    "MeasurementICE",
    "VisualIndication":                   "MeasurementICE",
    "LocalPressureDisplay":               "MeasurementICE",
    "LocalTemperatureDisplay":            "MeasurementICE",

    # FiatObjectPart — named fluids, substances, and material outputs
    "AbsorbentPhase":                     "FiatObjectPart",
    "DensePhase":                         "FiatObjectPart",
    "LightPhase":                         "FiatObjectPart",
    "CarrierFluid":                       "FiatObjectPart",
    "HeatingMedium":                      "FiatObjectPart",
    "CooledHeatingMedium":                "FiatObjectPart",
    "HydraulicFluid":                     "FiatObjectPart",
    "HydrocarbonFluid":                   "FiatObjectPart",
    "DrillingFluid":                      "FiatObjectPart",
    "DieselFuel":                         "FiatObjectPart",
    "WellFluid":                          "FiatObjectPart",
    "RichAbsorbent":                      "FiatObjectPart",
    "CombustibleMixture":                 "FiatObjectPart",
    "FluidMixture":                       "FiatObjectPart",
    "DepletedFluid":                      "FiatObjectPart",
    "ExhaustGas":                         "FiatObjectPart",
    "WaterVapor":                         "FiatObjectPart",
    "CombustionProducts":                 "FiatObjectPart",
    "CorrosionProducts":                  "FiatObjectPart",
    "FilteredConstituents":               "FiatObjectPart",
    "FilteredContaminants":               "FiatObjectPart",
    "RockCuttings":                       "FiatObjectPart",
    "CuttingsAndFluid":                   "FiatObjectPart",
    "DriedMaterial":                      "FiatObjectPart",
    "WetMaterial":                        "FiatObjectPart",
    "RemovedMaterial":                    "FiatObjectPart",
    # Portions that don't match a suffix pattern below
    "CombustionProductPortion":           "FiatObjectPart",
    "CoolantPortion":                     "FiatObjectPart",
    "FluidMixturePortion":                "FiatObjectPart",
    "GasMixturePortion":                  "FiatObjectPart",
    "LiquidMixturePortion":               "FiatObjectPart",
    "LiquidOrSemiSolidPortion":           "FiatObjectPart",
    "LiquidOrSlurryPortion":              "FiatObjectPart",
    "OilPortion":                         "FiatObjectPart",
    "SeparatedSolidLiquidPortion":        "FiatObjectPart",
    "VapourPortion":                      "FiatObjectPart",

    # Object — independent continuants with determinate boundaries
    "ElectricalCable":                    "Object",
    "SupportedElectricalCable":           "Object",
    "CapturedPig":                        "Object",
    "PigFromPipeline":                    "Object",
    "PipePig":                            "Object",
    "PipelinePig":                        "Object",
    "DrillString":                        "Object",
    "DownholeToolString":                 "Object",
    "TubingString":                       "Object",
    "SupportedTubingString":              "Object",
    "DrillingTool":                       "Object",
    "TemperatureSensingElement":          "Object",
    "ProtectedTemperatureSensingElement": "Object",
    "TubingHanger":                       "Object",
    "SteelPipe":                          "Object",
    "Wellbore":                           "Object",
    "DownholeToolAssembly":               "Object",
    "CompressorInternals":                "Object",
    "MetallicStructure":                  "Object",
    "MechanicalSupport":                  "Object",
    "SealedJoint":                        "Object",
    "MatingSurface":                      "Object",
    "CleanedSurface":                     "Object",
    "ContaminatedSurface":                "Object",
    "CentrifugalCompressor":              "Object",
    "ChristmasTreeConnectionPoint":       "Object",
    "LoadObject":                         "Object",
    "MovingObject":                       "Object",
    "RestrictedObject":                   "Object",
    "PhysicalObject":                     "Object",
    "EquipmentItem":                      "Object",
    "MaterialArtifact":                   "Object",
    "MaterialComponent":                  "Object",
    "InformationBearingArtifact":         "Object",
}

# Suffix/prefix regex patterns applied when EXACT has no match.
# (pattern, category) — first match wins.
SUFFIX_PATTERNS: list[tuple[str, str]] = [
    # Process
    (r"Motion$",          "Process"),
    (r"Rotation$",        "Process"),
    (r"Movement$",        "Process"),
    (r"Flow$",            "Process"),
    (r"Work$",            "Process"),
    # Quality
    (r"Force$",           "Quality"),
    (r"Load$",            "Quality"),
    # MeasurementICE
    (r"Indication$",      "MeasurementICE"),
    (r"Display$",         "MeasurementICE"),
    (r"Reading$",         "MeasurementICE"),
    # InformationContentEntity
    (r"Signal$",          "InformationContentEntity"),
    (r"Information$",     "InformationContentEntity"),
    (r"Data$",            "InformationContentEntity"),
    (r"Variable$",        "InformationContentEntity"),
    # FiatObjectPart — material portions (energy/signal portions are excluded via EXACT or left pending)
    (r"FluidPortion$",    "FiatObjectPart"),
    (r"GasPortion$",      "FiatObjectPart"),
    (r"LiquidPortion$",   "FiatObjectPart"),
    (r"AirPortion$",      "FiatObjectPart"),
    (r"WaterPortion$",    "FiatObjectPart"),
    (r"VaporPortion$",    "FiatObjectPart"),
    (r"SolidPortion$",    "FiatObjectPart"),
    (r"FuelPortion$",     "FiatObjectPart"),
    (r"MaterialPortion$", "FiatObjectPart"),
    (r"GaseousPortion$",  "FiatObjectPart"),
    (r"Phase$",           "FiatObjectPart"),
]

_COMPILED = [(re.compile(p), cat) for p, cat in SUFFIX_PATTERNS]

# ---------------------------------------------------------------------------


def classify(name: str) -> tuple[str, str] | None:
    """Return (category, rule_source) or None if no rule matches."""
    if name in EXACT:
        return EXACT[name], "exact"
    for pattern, cat in _COMPILED:
        if pattern.search(name):
            return cat, f"suffix:{pattern.pattern}"
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="store_true",
                        help="Write classifications to DB (default: preview only)")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT name FROM auxiliary_class WHERE status = 'pending' ORDER BY name"
    ).fetchall()

    by_cat: dict[str, list[tuple[str, str]]] = {}
    pending: list[str] = []

    for row in rows:
        name = row["name"]
        result = classify(name)
        if result:
            cat, rule = result
            by_cat.setdefault(cat, []).append((name, rule))
        else:
            pending.append(name)

    cat_order = ["Process", "Quality", "MeasurementICE", "InformationContentEntity",
                 "FiatObjectPart", "Object", "ObjectAggregate", "Disposition", "Role"]
    all_cats = cat_order + [c for c in by_cat if c not in cat_order]

    total_classified = sum(len(v) for v in by_cat.values())
    print(f"\nClassification preview  ({total_classified}/{len(rows)} entries matched, "
          f"{len(pending)} remain pending)\n")

    for cat in all_cats:
        if cat not in by_cat:
            continue
        entries = by_cat[cat]
        print(f"  {cat}  ({len(entries)})")
        for name, rule in sorted(entries):
            print(f"    {name:<50}  [{rule}]")
        print()

    if pending:
        print(f"  PENDING — no rule matched  ({len(pending)})")
        for name in pending:
            print(f"    {name}")
        print()

    if not args.commit:
        print("Dry run — pass --commit to apply.\n")
        conn.close()
        return

    updated = 0
    for cat, entries in by_cat.items():
        for name, _ in entries:
            conn.execute(
                "UPDATE auxiliary_class SET bfo_category = ?, status = 'validated', "
                "updated_at = datetime('now') WHERE name = ? AND status = 'pending'",
                (cat, name),
            )
            updated += conn.execute("SELECT changes()").fetchone()[0]
    conn.commit()
    conn.close()
    print(f"Done — {updated} rows updated to 'validated'.\n")


if __name__ == "__main__":
    main()
