#!/usr/bin/env python3
"""
Fix process_signature type names that are wrong or imprecise, remove stale
auxiliary_class entries, then classify the remaining pending entries.

Run:
    python -m scripts.fix_aux_class_signatures
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB = Path("data/enrichment.db")

# (enrichment_id, old_type, new_type)
SIGNATURE_FIXES: list[tuple[int, str, str]] = [
    (192, "ControlSignalPortion",          "ControlSignal"),
    (192, "MechanicalMotionPortion",       "MechanicalForce"),
    (204, "ElectricalSignalPortion",       "ElectricalSignal"),
    (244, "ElectricalSignalPortion",       "TemperatureSignal"),
    (42,  "ElectricalSignalPortion",       "ElectricalSignal"),
    (638, "SignalOrEnergyQuantity",        "Signal"),
    (100, "SubsurfaceAccess",              "Wellbore"),
    (259, "SpatialRegion",                 "Wellbore"),
    (130, "EnclosedSpace",                 "MaterialComponent"),
    (143, "MaterialEntity",                "FluidPortion"),
    (221, "MechanicalDisplacementStimulus","MechanicalDisplacement"),
    (92,  "AlternatingCurrentPortion",     "ACElectricalPower"),
    (105, "AlternatingElectricalCurrent",  "ACElectricalPower"),
]

# Aux entries whose only source was a now-fixed signature — delete after fixes
STALE_AUX: list[str] = [
    "ControlSignalPortion",
    "MechanicalMotionPortion",
    "ElectricalSignalPortion",
    "SignalOrEnergyQuantity",
    "SubsurfaceAccess",
    "SpatialRegion",
    "EnclosedSpace",
    "MaterialEntity",
    "MechanicalDisplacementStimulus",
    "AlternatingCurrentPortion",
    "AlternatingElectricalCurrent",
]

# Remaining pending entries to classify directly
CLASSIFY: dict[str, list[str]] = {
    "Process": [
        "DisturbanceSource",
        "ElectricalCurrent",
        "ElectromagneticRadiation",
        "PhysicalPhenomenon",
        "SuppressedDisturbance",
    ],
    "FiatObjectPart": [
        "ElectricalEnergyPortion",
        "EnergyPortion",
        "HeatPortion",
        "IgnitionEnergy",
        "MechanicalEnergyPortion",
        "ThermalEnergy",
        "ThermalEnergyPortion",
    ],
}


def _replace_types(sig_json: str, old: str, new: str) -> str:
    sig = json.loads(sig_json)
    for key in ("inputs", "outputs"):
        for item in sig.get(key, []):
            if item.get("type") == old:
                item["type"] = new
    return json.dumps(sig, ensure_ascii=False)


def main() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ------------------------------------------------------------------ #
    # Step 1: Fix process_signature JSONs (with history snapshot)         #
    # ------------------------------------------------------------------ #
    print("\n=== Step 1: process_signature fixes ===")
    affected_ids: set[int] = {eid for eid, _, _ in SIGNATURE_FIXES}
    for eid in sorted(affected_ids):
        row = conn.execute(
            "SELECT id, cluster_label, process_signature, status, updated_at "
            "FROM enrichment WHERE id = ?", (eid,)
        ).fetchone()
        if not row:
            print(f"  [SKIP] enrichment id={eid} not found")
            continue

        # Snapshot before editing
        snapshot = json.dumps({
            "cluster_label":     row["cluster_label"],
            "status":            row["status"],
            "process_signature": row["process_signature"],
            "updated_at":        row["updated_at"],
        }, ensure_ascii=False)
        conn.execute(
            "INSERT INTO enrichment_history (enrichment_id, snapshot_at, trigger, snapshot_json) "
            "VALUES (?, ?, 'process_signature_fix', ?)",
            (eid, now, snapshot),
        )

        new_sig = row["process_signature"]
        fixes = [(old, new) for (i, old, new) in SIGNATURE_FIXES if i == eid]
        for old, new in fixes:
            new_sig = _replace_types(new_sig, old, new)
            print(f"  [{eid}] {row['cluster_label']}: {old} → {new}")

        conn.execute(
            "UPDATE enrichment SET process_signature = ?, updated_at = ? WHERE id = ?",
            (new_sig, now, eid),
        )

    # ------------------------------------------------------------------ #
    # Step 2: Verify stale aux entries are no longer referenced           #
    # ------------------------------------------------------------------ #
    print("\n=== Step 2: stale aux_class entries ===")
    all_sigs = [
        r["process_signature"] for r in
        conn.execute("SELECT process_signature FROM enrichment WHERE process_signature IS NOT NULL").fetchall()
    ]
    sig_blob = " ".join(all_sigs)

    still_referenced = [name for name in STALE_AUX if name in sig_blob]
    if still_referenced:
        print(f"  [WARN] Still referenced — skipping delete: {still_referenced}")
        to_delete = [n for n in STALE_AUX if n not in still_referenced]
    else:
        to_delete = STALE_AUX

    for name in to_delete:
        deleted = conn.execute(
            "DELETE FROM auxiliary_class WHERE name = ?", (name,)
        ).rowcount
        print(f"  {'[DELETE]' if deleted else '[NOT FOUND]'} {name}")

    # ------------------------------------------------------------------ #
    # Step 3: Classify remaining pending                                  #
    # ------------------------------------------------------------------ #
    print("\n=== Step 3: classify remaining pending ===")
    classified = 0
    for category, names in CLASSIFY.items():
        for name in names:
            rows_updated = conn.execute(
                "UPDATE auxiliary_class SET bfo_category = ?, status = 'validated', "
                "updated_at = ? WHERE name = ? AND status = 'pending'",
                (category, now, name),
            ).rowcount
            if rows_updated:
                print(f"  {name} → {category}")
                classified += 1
            else:
                print(f"  [SKIP] {name} (not found or not pending)")

    conn.commit()
    conn.close()

    # ------------------------------------------------------------------ #
    # Summary                                                             #
    # ------------------------------------------------------------------ #
    print(f"\nDone — {len(to_delete)} stale entries removed, {classified} classified.")
    print("Run 'python -m scripts.regen_enriched_owl' to rebuild the OWL.\n")


if __name__ == "__main__":
    main()
