#!/usr/bin/env python3
"""
ODR-022 §O5 — repoint the `Shell` part reference to the existing `VesselShell` class.

`Shell` reached the ontology as a readable-name stub from the `shell and tube heat
exchanger` entry's necessary_parts. CFIHOS defines shell as "a layer or surface with a
shape in two dimensions and length in the third dimension surrounding a space. Typically
the cylindrical part of a vessel."

COPI already has that class: `vessel shell` (COPI_0000374, exported) — "the outer
pressure-containing structural boundary of a vessel". Same concept, and the subsumption
chain holds: shell and tube heat exchanger ⊑ HeatExchanger ⊑ PressureVessel ⊑ Vessel, so
its shell IS a vessel shell.

Enriching `Shell` as a new entry would have created a second class for one universal —
the duplication ODR-022 exists to remove. Repointing the reference retires the stub with
no new IRI at all.

The source_quote is preserved: the grounding evidence is unchanged, only the name it
resolves to.

Usage:
    python scripts/migrations/odr022_repoint_shell.py --dry-run
    python scripts/migrations/odr022_repoint_shell.py --apply
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / "data" / "enrichment.db"
OLD, NEW = "Shell", "VesselShell"


def main(apply: bool) -> int:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    target = con.execute(
        "SELECT id, status FROM enrichment WHERE cluster_label = 'vessel shell'"
    ).fetchone()
    if not target:
        print("ERROR — 'vessel shell' entry not found; refusing to repoint to a class "
              "that does not exist.")
        con.close()
        return 1
    print(f"target: vessel shell (id={target['id']}, status={target['status']})\n")

    changed = 0
    for row in con.execute(
        "SELECT id, cluster_label, necessary_parts FROM enrichment "
        "WHERE necessary_parts IS NOT NULL AND necessary_parts NOT IN ('', '[]', 'null')"
    ).fetchall():
        parts = json.loads(row["necessary_parts"])
        touched = False
        for part in parts:
            if not isinstance(part, dict):
                continue
            for key in ("name", "parent"):
                if part.get(key) == OLD:
                    print(f"  [{row['id']}] {row['cluster_label']}: {key} {OLD} -> {NEW}")
                    if key == "name":
                        print(f"      quote kept: {(part.get('source_quote') or '')[:90]}")
                    part[key] = NEW
                    touched = True
        if not touched:
            continue
        changed += 1
        if apply:
            con.execute(
                "INSERT INTO enrichment_history (enrichment_id, snapshot_at, trigger, snapshot_json) "
                "SELECT id, datetime('now'), 'odr022_repoint_shell', "
                "json_object('cluster_label',cluster_label,'status',status,"
                "'necessary_parts',necessary_parts,'updated_at',updated_at) "
                "FROM enrichment WHERE id = ?", (row["id"],))
            con.execute(
                "UPDATE enrichment SET necessary_parts = ?, updated_at = datetime('now') "
                "WHERE id = ?",
                (json.dumps(parts, ensure_ascii=False), row["id"]))

    aux = con.execute("SELECT id FROM auxiliary_class WHERE name = ?", (OLD,)).fetchone()
    if aux:
        print(f"\n  auxiliary_class row for {OLD} will be removed")
        if apply:
            con.execute("DELETE FROM auxiliary_class WHERE name = ?", (OLD,))

    if apply:
        con.commit()
    con.close()
    print(f"\nentries changed: {changed}")
    print("APPLIED" if apply else "DRY RUN — nothing written")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    sys.exit(main(apply=a.apply))
