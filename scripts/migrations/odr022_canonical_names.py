#!/usr/bin/env python3
"""
ODR-022 canonical-name migration.

Rewrites participant/part names in enrichment.db to the canonical vocabulary so the
generator stops emitting duplicate readable-name stubs. The IRI remap in
copi-iri-map.tsv then carries each canonical name to its numeric COPI IRI.

Why at source rather than in the remap: remap_graph() is a pure IRI substitution, so
collapsing many stubs onto one target would drag every merged stub's rdfs:label and
skos:definition onto that target. Rewriting the source data means the merged names are
never referenced, so no stub declaration is emitted for them at all (the generator emits
a declaration for every ":Name" it finds referenced but undeclared).

Touches: process_signature, necessary_parts, differentia_expression, fol_axiom,
genus_already_provides, auxiliary_class.
Deliberately does NOT touch llm_raw_response — that is the provenance record of what the
model actually returned and must stay verbatim.

Usage:
    python scripts/migrations/odr022_canonical_names.py --dry-run
    python scripts/migrations/odr022_canonical_names.py --apply
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / "data" / "enrichment.db"

# ── §P1/§P2 portions → canonical ODR-010 vocabulary ──────────────────────────
# Targets are the readable names that copi-iri-map.tsv carries to COPI_0000037-0000044,
# all of which are fully declared in copi-vocab and stripped from copi-enriched by the
# protected-subject rule.
PORTIONS = {
    # → PortionOfFluid (COPI_0000037)
    "FluidPortion": "PortionOfFluid",
    "ProcessFluidPortion": "PortionOfFluid",
    "PressurizedFluidPortion": "PortionOfFluid",
    "HighPressureFluidPortion": "PortionOfFluid",
    "FilteredFluidPortion": "PortionOfFluid",
    "DensePhase": "PortionOfFluid",
    "LightPhase": "PortionOfFluid",
    "ProcessFluidSample": "PortionOfFluid",
    # → PortionOfLiquid (COPI_0000038)
    "LiquidPortion": "PortionOfLiquid",
    # → PortionOfGas (COPI_0000039)
    "GasPortion": "PortionOfGas",
    "GaseousPortion": "PortionOfGas",
    "VaporPortion": "PortionOfGas",
    "WaterVapor": "PortionOfGas",
    "CompressedGasPortion": "PortionOfGas",
    "ExpandedGasPortion": "PortionOfGas",
    "CleanedGasPortion": "PortionOfGas",
    # → PortionOfSolid (COPI_0000040)
    "SolidPortion": "PortionOfSolid",
    # → FluidMixture (COPI_0000044)
    "FluidMixturePortion": "FluidMixture",
    "MixedFluidPortion": "FluidMixture",
    "LiquidMixturePortion": "FluidMixture",
    "GasMixturePortion": "FluidMixture",
    "MultiphaseFluidPortion": "FluidMixture",
    "SeparatedSolidLiquidPortion": "FluidMixture",
    # → bfo:MaterialEntity, via a canonical name the map sends to BFO_0000040
    "MaterialPortion": "MaterialEntity",
    "DriedMaterial": "MaterialEntity",
    "WetMaterial": "MaterialEntity",
}

# ── §P4 domain substances → 15 new classes (COPI_0000386-0000400) ────────────
SUBSTANCES = {
    "AirPortion": "PortionOfAir",
    "CompressedAirPortion": "PortionOfAir",
    "DryAirPortion": "PortionOfAir",
    "HumidAirPortion": "PortionOfAir",
    "WaterPortion": "PortionOfWater",
    "OilPortion": "PortionOfOil",
    "HydrocarbonFluid": "HydrocarbonFluid",
    "FormationFluidPortion": "FormationFluid",
    "WellFluid": "FormationFluid",
    "DrillingFluidPortion": "DrillingFluid",
    "DrillingFluid": "DrillingFluid",
    "HydraulicFluidPortion": "HydraulicFluid",
    "HydraulicFluid": "HydraulicFluid",
    "FuelPortion": "FuelPortion",
    "GaseousFuelPortion": "FuelPortion",
    "ChemicalFuelPortion": "FuelPortion",
    "DieselFuel": "FuelPortion",
    "ExhaustGasPortion": "ExhaustGas",
    "ExhaustGas": "ExhaustGas",
    "CombustionProducts": "CombustionProduct",
    "CombustionProductPortion": "CombustionProduct",
    "CombustionGasPortion": "CombustionProduct",
    "WasteGasPortion": "WasteMaterial",
    "WasteMaterialPortion": "WasteMaterial",
    "CoolantPortion": "HeatTransferMedium",
    "HeatingMedium": "HeatTransferMedium",
    "CooledHeatingMedium": "HeatTransferMedium",
    "CarrierFluid": "CarrierFluid",
    "RockCuttings": "RockCuttings",
    "CuttingsAndFluid": "RockCuttings",
    "RemovedMaterial": "RemovedMaterial",
    "CorrosionProducts": "RemovedMaterial",
    "FilteredContaminants": "RemovedMaterial",
    "FilteredConstituents": "RemovedMaterial",
}

# ── §P3 energy-as-matter → delete from process I/O (ODR-010 §5.1) ────────────
# Not a rename: energy is not a bfo:MaterialEntity, so these participants are removed
# outright. The equipment's energy demand belongs on the equipment as a Quality
# (bearer_of some ElectricalPower / MechanicalPower), not on the process as an input.
ENERGY_DROP = {
    "ElectricalEnergyPortion",
    "MechanicalEnergyPortion",
    "ThermalEnergyPortion",
    "ThermalEnergy",
    "EnergyPortion",
}

# ── §I1/§I2/§I3 information content entities ─────────────────────────────────
ICE = {
    # → iof-core:InformationContentEntity (ODR-010 §3: no Signal taxonomy)
    "ElectricalSignal": "InformationContentEntity",
    "StandardizedSignal": "InformationContentEntity",
    "StandardizedElectricalSignal": "InformationContentEntity",
    "DetectionSignal": "InformationContentEntity",
    "Signal": "InformationContentEntity",
    "InformationSignal": "InformationContentEntity",
    "DiscreteElectricalSignal": "InformationContentEntity",
    "PolyphaseElectricalSignal": "InformationContentEntity",
    "InformationBearingEntity": "InformationContentEntity",
    # → COPI_0000045 control signal
    "ManualControlSignal": "ControlSignal",
    "ReferenceSignal": "ControlSignal",
    # → COPI_0000046 visual indication
    "VisualInformation": "VisualIndication",
    "VisualSignal": "VisualIndication",
    "PhaseSequenceIndication": "VisualIndication",
    # → COPI_0000047-0000051 measurement results
    "TemperatureSignal": "TemperatureMeasurementResult",
    "LocalTemperatureDisplay": "TemperatureMeasurementResult",
    "PressureSignal": "PressureMeasurementResult",
    "PressureReading": "PressureMeasurementResult",
    "LocalPressureDisplay": "PressureMeasurementResult",
    "DifferentialPressureIndication": "PressureMeasurementResult",
    "LowPressureSignal": "PressureMeasurementResult",
    "HighPressureSignal": "PressureMeasurementResult",
    "PressureSignalPair": "PressureMeasurementResult",
    "MassFlowRateSignal": "FlowMeasurementResult",
    "FlowMeasurement": "FlowMeasurementResult",
    "LevelSignal": "LevelMeasurementResult",
    "LevelInformation": "LevelMeasurementResult",
    "ChromatographicSignal": "CompositionMeasurementResult",
    "CompositionAnalysisData": "CompositionMeasurementResult",
    # → generic MeasurementICE
    "MeasurementSignal": "MeasurementInformationContentEntity",
    "ProcessVariable": "MeasurementInformationContentEntity",
    "PhysicalVariable": "MeasurementInformationContentEntity",
    # → §I4 new classes
    "VibrationSignal": "VibrationMeasurementResult",
    "PositionSignal": "PositionMeasurementResult",
}

# ── §1.4 namespace shadows of upstream classes ───────────────────────────────
SHADOWS = {
    "MaterialArtifact": "MaterialArtifact",   # map row sends this to iof-core:
    "MaterialComponent": "MaterialComponent",
    "PhysicalObject": "PhysicalObject",
    "EquipmentItem": "EquipmentItem",
}

# ── §O4/§O5 object and part merges ───────────────────────────────────────────
PARTS = {
    "CleanedSurface": "Surface",
    "ContaminatedSurface": "Surface",
    "SupportedTubingString": "TubingString",
    "SupportedElectricalCable": "ElectricalCable",
    "PipePig": "PipelinePig",
    "CapturedPig": "PipelinePig",
    "PigFromPipeline": "PipelinePig",
    "TemperatureSensingElement": "SensingElement",
    "ProtectedTemperatureSensingElement": "SensingElement",
    "SuctionInlet": "SuctionPort",
    "HydraulicPumpInlet": "SuctionPort",
    "HydraulicPumpOutlet": "DischargePort",
    "TubingBundle": "TubeBundle",
    "VacuumReferenceeChamber": "VacuumReferenceChamber",   # §1.6 typo
}

RENAMES: dict[str, str] = {**PORTIONS, **SUBSTANCES, **ICE, **SHADOWS, **PARTS}

# Columns rewritten. llm_raw_response is intentionally absent.
JSON_COLS = ["process_signature", "necessary_parts"]
TEXT_COLS = ["differentia_expression", "fol_axiom", "genus_already_provides"]


def rewrite_text(val: str, stats: Counter) -> str:
    """Whole-word replace of stub names in a free-text field."""
    if not val:
        return val
    for old, new in RENAMES.items():
        if old == new:
            continue
        pattern = r"\b" + re.escape(old) + r"\b"
        val, n = re.subn(pattern, new, val)
        if n:
            stats[f"text:{old}->{new}"] += n
    return val


def rewrite_signature(raw: str, stats: Counter) -> str:
    """Rename participant types; drop energy-as-matter participants entirely."""
    try:
        sig = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    if not isinstance(sig, dict):
        return raw
    for side in ("inputs", "outputs"):
        items = sig.get(side)
        if not isinstance(items, list):
            continue
        kept = []
        for item in items:
            if not isinstance(item, dict):
                kept.append(item)
                continue
            t = item.get("type")
            if t in ENERGY_DROP:
                stats[f"drop:{t}"] += 1
                continue
            if t in RENAMES and RENAMES[t] != t:
                stats[f"sig:{t}->{RENAMES[t]}"] += 1
                item["type"] = RENAMES[t]
            kept.append(item)
        sig[side] = kept
    return json.dumps(sig, ensure_ascii=False)


def rewrite_parts(raw: str, stats: Counter) -> str:
    """Rename part names and their declared parents."""
    try:
        parts = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    if not isinstance(parts, list):
        return raw
    for p in parts:
        if not isinstance(p, dict):
            continue
        for key in ("name", "parent"):
            v = p.get(key)
            if v in RENAMES and RENAMES[v] != v:
                stats[f"part.{key}:{v}->{RENAMES[v]}"] += 1
                p[key] = RENAMES[v]
    return json.dumps(parts, ensure_ascii=False)


def migrate(apply: bool) -> int:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    stats: Counter = Counter()
    touched = 0

    cols = ["id"] + JSON_COLS + TEXT_COLS
    rows = con.execute(f"SELECT {','.join(cols)} FROM enrichment").fetchall()
    for row in rows:
        updates = {}
        sig = rewrite_signature(row["process_signature"], stats)
        if sig != row["process_signature"]:
            updates["process_signature"] = sig
        parts = rewrite_parts(row["necessary_parts"], stats)
        if parts != row["necessary_parts"]:
            updates["necessary_parts"] = parts
        for c in TEXT_COLS:
            new = rewrite_text(row[c], stats)
            if new != row[c]:
                updates[c] = new
        if not updates:
            continue
        touched += 1
        if apply:
            con.execute(
                "INSERT INTO enrichment_history (enrichment_id, snapshot_at, trigger, snapshot_json) "
                "SELECT id, datetime('now'), 'odr022_canonical_names', "
                "json_object('cluster_label',cluster_label,'status',status,"
                "'process_signature',process_signature,'necessary_parts',necessary_parts,"
                "'differentia_expression',differentia_expression,'updated_at',updated_at) "
                "FROM enrichment WHERE id = ?",
                (row["id"],),
            )
            sets = ", ".join(f"{c} = ?" for c in updates)
            con.execute(
                f"UPDATE enrichment SET {sets}, updated_at = datetime('now') WHERE id = ?",
                (*updates.values(), row["id"]),
            )

    # auxiliary_class: drop names that no longer exist, retype survivors.
    aux_drop = sorted(
        {o for o, n in RENAMES.items() if o != n} | ENERGY_DROP
    )
    have = {r["name"] for r in con.execute("SELECT name FROM auxiliary_class")}
    to_drop = [n for n in aux_drop if n in have]
    stats["aux_rows_dropped"] = len(to_drop)
    if apply and to_drop:
        con.executemany(
            "DELETE FROM auxiliary_class WHERE name = ?", [(n,) for n in to_drop]
        )

    if apply:
        con.commit()
    con.close()

    width = max((len(k) for k in stats), default=10)
    for k in sorted(stats):
        print(f"  {k:<{width}}  {stats[k]}")
    print(f"\nentries touched: {touched}   aux rows dropped: {len(to_drop)}")
    print("APPLIED" if apply else "DRY RUN — nothing written")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    sys.exit(migrate(apply=args.apply))
