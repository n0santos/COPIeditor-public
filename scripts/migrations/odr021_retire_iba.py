#!/usr/bin/env python3
"""
ODR-021 — retire InformationBearingArtifact from COPI.

COPI has no InformationBearingArtifact. Every one of the 8 uses names information
content, not a material artifact — the constraint text says so in each case ("visual
information", "measurement signal", "control signal", "data streams", "communication
signal"). IBA was typed bfo:Object, which is what made those restrictions unsatisfiable:
a bfo:Object output on a process whose outputs are constrained to MeasurementICE
(a GenericallyDependentContinuant) is an IndependentContinuant ⊓ GDC clash.

The original ODR-021 sketch was to re-type IBA → ICE. Deleting it instead is cleaner:
re-typing would keep a COPI-specific class that duplicates iof-core:InformationContentEntity
and the ODR-010 signal vocabulary, which is exactly the duplication ODR-022 removed
everywhere else.

Each use is mapped to the most specific existing class its own constraint text supports:

  entry  side  constraint says                        -> target
  388    OUT   "visual information about fluid state" -> VisualIndication      (COPI_0000046)
  403    OUT   "measurement signal ... flow rate"     -> FlowMeasurementResult (COPI_0000049)
  405    IN    "control signal"                       -> ControlSignal         (COPI_0000045)
  410    IN    "digital or analog signals, data"      -> InformationContentEntity (iof-core)
  410    OUT   "visual presentation ... human"        -> VisualIndication      (COPI_0000046)
  411    IN    "control signal"                       -> ControlSignal         (COPI_0000045)
  413    OUT   "protected signal transmission"        -> InformationContentEntity (iof-core)
  428    IN    "communication signal, data"           -> InformationContentEntity (iof-core)
  428    OUT   "interface response, connection"       -> InformationContentEntity (iof-core)

Retiring IBA also retires the last participant-restriction quarantine in
regen_enriched_owl.py (ODR-020 §6 / ODR-022 §O3).

Usage:
    python scripts/migrations/odr021_retire_iba.py --dry-run
    python scripts/migrations/odr021_retire_iba.py --apply
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / "data" / "enrichment.db"

IBA = "InformationBearingArtifact"

# (entry_id, side) -> replacement type
MAPPING = {
    (388, "outputs"): "VisualIndication",
    (403, "outputs"): "FlowMeasurementResult",
    (405, "inputs"):  "ControlSignal",
    (410, "inputs"):  "InformationContentEntity",
    (410, "outputs"): "VisualIndication",
    (411, "inputs"):  "ControlSignal",
    (413, "outputs"): "InformationContentEntity",
    (428, "inputs"):  "InformationContentEntity",
    (428, "outputs"): "InformationContentEntity",
}


def migrate(apply: bool) -> int:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    changed = 0
    unmapped = []

    rows = con.execute(
        "SELECT id, cluster_label, process_signature FROM enrichment "
        "WHERE process_signature LIKE ?", (f"%{IBA}%",)
    ).fetchall()

    for row in rows:
        sig = json.loads(row["process_signature"])
        touched = False
        for side in ("inputs", "outputs"):
            for item in sig.get(side) or []:
                if not isinstance(item, dict) or item.get("type") != IBA:
                    continue
                target = MAPPING.get((row["id"], side))
                if target is None:
                    unmapped.append((row["id"], row["cluster_label"], side))
                    continue
                print(f"  [{row['id']:>3}] {row['cluster_label']:<24} "
                      f"{side[:-1]:<6} {IBA} -> {target}")
                item["type"] = target
                touched = True
        if not touched:
            continue
        changed += 1
        if apply:
            con.execute(
                "INSERT INTO enrichment_history (enrichment_id, snapshot_at, trigger, snapshot_json) "
                "SELECT id, datetime('now'), 'odr021_retire_iba', "
                "json_object('cluster_label',cluster_label,'status',status,"
                "'process_signature',process_signature,'updated_at',updated_at) "
                "FROM enrichment WHERE id = ?", (row["id"],),
            )
            con.execute(
                "UPDATE enrichment SET process_signature = ?, updated_at = datetime('now') "
                "WHERE id = ?",
                (json.dumps(sig, ensure_ascii=False), row["id"]),
            )

    if unmapped:
        print("\nERROR — unmapped IBA occurrences (refusing to guess):")
        for eid, lbl, side in unmapped:
            print(f"  [{eid}] {lbl} ({side})")
        con.close()
        return 1

    aux = con.execute(
        "SELECT id FROM auxiliary_class WHERE name = ?", (IBA,)
    ).fetchone()
    if aux and apply:
        con.execute("DELETE FROM auxiliary_class WHERE name = ?", (IBA,))

    if apply:
        con.commit()
    con.close()

    print(f"\nentries changed: {changed}   auxiliary_class row removed: {bool(aux)}")
    print("APPLIED" if apply else "DRY RUN — nothing written")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    sys.exit(migrate(apply=args.apply))
