#!/usr/bin/env python3
"""
Replace an enrichment entry's process_signature with a corrected one.

Usage:
    python .claude/skills/model-participant/apply_signature.py <id> <signature.json>            # dry run
    python .claude/skills/model-participant/apply_signature.py <id> <signature.json> --commit   # write

<signature.json> is the complete new signature object (inputs, outputs, transformation,
transformation_kind, ...), not a patch.

Dry run and --commit both:
  1. Refuse if any participant type fails the participant vocabulary gate.
  2. For each participant type being removed from this entry, list every other place it is
     still referenced (other signatures, necessary_parts, candidate_parts, differentia).
  3. For a removed type that was published and is referenced nowhere else, print what
     ODR-022 §15 prescribes: the class drops out on the next regen; if it has a
     replacement, a copi-iri-map.tsv row repointing the old readable name to the
     replacement's IRI (paste it yourself — this script never edits the map).
  4. Print the baseline lines that become stale.

--commit additionally writes an enrichment_history snapshot, then updates the row through
enrichment_service.update_enrichment().
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "enrichment"))

import enrichment_service as svc  # noqa: E402

NS = "https://www.inf.ufrgs.br/ontologies/copi/"


def resolve_iri(name: str, iri_map: dict, rows) -> str | None:
    if NS + name in iri_map:
        return iri_map[NS + name]
    for r in rows:
        if svc._to_pascal_case(r["cluster_label"]) == name and r["copi_id"]:
            return f"{NS}COPI_{r['copi_id']:07d}"
    return None


def references(name: str, rows, skip_id: int) -> list[str]:
    found = []
    for r in rows:
        if r["id"] == skip_id:
            continue
        if name in svc.participant_types(r["process_signature"]):
            found.append(f"{r['cluster_label']} (id {r['id']}): process_signature")
        for field in ("necessary_parts", "candidate_parts"):
            try:
                items = json.loads(r[field] or "[]")
            except (json.JSONDecodeError, TypeError):
                items = []
            if any(isinstance(p, dict) and svc._to_pascal_case(str(p.get("name", ""))) == name for p in items):
                found.append(f"{r['cluster_label']} (id {r['id']}): {field}")
        if r["differentia_expression"] and re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", r["differentia_expression"]):
            found.append(f"{r['cluster_label']} (id {r['id']}): differentia_expression")
    return found


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    commit = "--commit" in sys.argv
    if len(args) != 2 or not args[0].isdigit():
        print(__doc__)
        return 2
    entry_id, sig_path = int(args[0]), Path(args[1])
    new_sig = json.loads(sig_path.read_text(encoding="utf-8"))
    if not isinstance(new_sig, dict) or not isinstance(new_sig.get("inputs"), list) or not isinstance(new_sig.get("outputs"), list):
        print("signature must be an object with 'inputs' and 'outputs' lists")
        return 2

    conn = svc.get_enrichment_db()
    rows = conn.execute("SELECT * FROM enrichment").fetchall()
    conn.close()
    row = next((r for r in rows if r["id"] == entry_id), None)
    if row is None:
        print(f"no enrichment entry with id {entry_id}")
        return 1
    label = row["cluster_label"]

    baseline = svc.load_participant_vocabulary_baseline()
    # A type already grandfathered for this entry may stay (e.g. one waiting on the pipeline);
    # anything else must be vocabulary.
    unvetted = [t for t in svc.find_unvetted_participants(new_sig) if f"{label}|{t}" not in baseline]
    if unvetted:
        print(f"REFUSED: not COPI participant vocabulary: {', '.join(unvetted)}")
        print("Use lookup.py to find an existing type, or get the class added to copi-vocab.ttl / enriched first.")
        return 1

    old_types = svc.participant_types(row["process_signature"])
    new_types = svc.participant_types(new_sig)
    removed = [t for t in old_types if t not in new_types]
    iri_map = svc._load_copi_iri_map()

    print(f"{label} (id {entry_id}, {row['status']})")
    print(f"  participants before: {', '.join(old_types) or '—'}")
    print(f"  participants after:  {', '.join(new_types) or '—'}")

    for name in removed:
        old_iri = iri_map.get(NS + name)
        still = references(name, rows, entry_id)
        print(f"\n  removed {name}" + (f" (published as {old_iri.rsplit('/', 1)[-1]})" if old_iri and old_iri.startswith(NS) else ""))
        if still:
            print("    still referenced — the class stays until these are fixed too:")
            for ref in still:
                print(f"      {ref}")
            continue
        if not (old_iri and old_iri.startswith(NS)):
            print("    never published — nothing else to do")
            continue
        print("    no other references — the class drops out of copi-enriched.owl on the next regen (ODR-022 §15: removed, not deprecated)")
        replacements = [t for t in new_types if t not in old_types]
        if len(replacements) == 1:
            target = resolve_iri(replacements[0], iri_map, rows)
            if target:
                print("    repoint the old name in copi-iri-map.tsv (replace its existing row):")
                print(f"      {NS}{name}\t{target}")
        elif replacements:
            print(f"    several replacements ({', '.join(replacements)}): choose the canonical one for the copi-iri-map.tsv row")
        else:
            print("    no replacement: leave its copi-iri-map.tsv row as is so the number is not reallocated")

    stale = sorted(k for k in baseline if k.startswith(f"{label}|") and k.split("|", 1)[1] not in new_types)
    if stale:
        print("\n  prune from scripts/participant-vocabulary-baseline.txt after committing:")
        for key in stale:
            print(f"    {key}")

    if not commit:
        print("\nDry run — nothing written. Re-run with --commit to apply.")
        return 0

    conn = svc.get_enrichment_db(actor="model_participant_skill")
    conn.execute(
        """INSERT INTO enrichment_history (enrichment_id, snapshot_at, trigger, snapshot_json)
           SELECT id, datetime('now'), 'model_participant_skill',
                  json_object('cluster_label', cluster_label, 'status', status,
                              'process_signature', process_signature, 'updated_at', updated_at)
             FROM enrichment WHERE id = ?""",
        (entry_id,),
    )
    conn.commit()
    conn.close()
    svc.update_enrichment(entry_id, {"process_signature": new_sig})
    print("\nWritten: enrichment_history snapshot + process_signature updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
