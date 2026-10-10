#!/usr/bin/env python3
"""
Load a batch of annotation text into class_annotation (and equipment label_pt).

Batch file shape:
{
  "equipment_label_pt": {"<enrichment id>": "<pt-br label>", ...},
  "registry": {"<ClassName>": {"label_pt": ..., "definition_en": ..., "definition_pt": ...}, ...}
}

Only the fields present in a registry entry are written; each written field's
origin is set to `--origin` (default "generated:<today>") and the row's status is
reset to 'proposed', so generated text is always distinguishable from seeded or
reviewed text. Equipment labels go through snapshot_enrichment + update_enrichment.

Usage:
    python -m scripts.load_class_annotations <batch.json> [--origin generated:2026-09-15] [--apply]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "enrichment"))

import enrichment_service as svc  # noqa: E402

FIELD_ORIGIN = {"label_pt": "origin_label_pt", "definition_en": "origin_en", "definition_pt": "origin_pt"}


def _kind(name: str) -> str:
    if name.endswith("Function"):
        return "function"
    if name.endswith("Process"):
        return "process"
    return "part"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("batch")
    ap.add_argument("--origin", default=f"generated:{date.today().isoformat()}")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    batch = json.loads(Path(args.batch).read_text(encoding="utf-8"))
    svc.init_enrichment_schema()
    conn = svc.get_enrichment_db(actor="load_class_annotations")
    existing = {r["class_name"]: dict(r) for r in conn.execute("SELECT * FROM class_annotation")}

    inserts, updates = [], []
    for name, fields in batch.get("registry", {}).items():
        fields = {k: v.strip() for k, v in fields.items() if k in FIELD_ORIGIN and v and v.strip()}
        if not fields:
            continue
        if name in existing:
            updates.append((name, fields))
        else:
            inserts.append((name, fields))
    labels = batch.get("equipment_label_pt", {})
    print(f"registry: {len(inserts)} insert, {len(updates)} update | equipment label_pt: {len(labels)}")

    if not args.apply:
        print("dry run -- pass --apply to write")
        conn.close()
        return

    for name, fields in inserts:
        cols = ["class_name", "kind", *fields, *(FIELD_ORIGIN[k] for k in fields)]
        vals = [name, _kind(name), *fields.values(), *([args.origin] * len(fields))]
        conn.execute(
            f"INSERT INTO class_annotation ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)
    for name, fields in updates:
        sets = [f"{k} = ?" for k in fields] + [f"{FIELD_ORIGIN[k]} = ?" for k in fields]
        vals = [*fields.values(), *([args.origin] * len(fields)), name]
        conn.execute(
            f"UPDATE class_annotation SET {', '.join(sets)}, status = 'proposed', "
            f"updated_at = datetime('now') WHERE class_name = ?", vals)
    conn.commit()
    conn.close()

    for enr_id, label in labels.items():
        svc.snapshot_enrichment(int(enr_id), trigger="annotation_batch")
        svc.update_enrichment(int(enr_id), {"label_pt": label})
    print("written")


if __name__ == "__main__":
    main()
