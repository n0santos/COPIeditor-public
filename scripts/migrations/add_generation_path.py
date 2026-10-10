#!/usr/bin/env python3
"""
Add a `generation_path` column to `enrichment` and backfill the 287 existing rows
with their known origin, so API-produced and non-API-produced records stop being
indistinguishable. See CLAUDE.md "Interactive enrichment pipeline" and the
enrich-term skill (.claude/skills/enrich-term/).

Values: api_call_llm, skill_session, migration_script, manual.

Backfill partition, established by cross-referencing llm_model + created_at
clustering against scripts/migrations/*.py ENTRIES cluster_label lists (all 287
rows partition cleanly, no row's origin is guessed):

  - 260 rows, llm_model='claude-sonnet-4-20250514' (Apr-May 2026, real API calls,
    input_tokens>0)                                            -> api_call_llm
  - 17 rows, llm_model='claude-opus-5' (2026-08-08, input_tokens=0, cluster_labels
    match scripts/migrations/odr022_enrich_15_components.py and
    odr022_enrich_4_gaps.py's hardcoded ENTRIES dicts exactly) -> migration_script
  - 10 rows, llm_model='claude-sonnet-4-6' (2026-06-25, identical single-second
    timestamp, input_tokens=0, hand-written INSERTs from a Claude Code chat
    session -- no script file exists for these, unlike the 17 above) -> manual

New inserts going forward: _store_proposal()'s two production call sites
(enrich_cluster(), the batch-import path) default to generation_path='api_call_llm'
unchanged; the enrich-term skill passes generation_path='skill_session' explicitly.

Usage:
    python scripts/migrations/add_generation_path.py --dry-run
    python scripts/migrations/add_generation_path.py --apply
"""
import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "enrichment.db"

MIGRATION_SCRIPT_IDS = frozenset({
    # scripts/migrations/odr022_enrich_15_components.py + odr022_enrich_4_gaps.py
    "master valve", "wing valve", "drill bit", "finned tube", "tube bundle",
    "chamber", "electrical switch", "stator winding",
    "gas detecting measuring element", "panel", "piston", "filter medium",
    "tubing bowl", "measuring element", "fluid port", "drill string",
    "electrical cable",
})


def main(apply: bool) -> int:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    cols = [r[1] for r in con.execute("PRAGMA table_info(enrichment)").fetchall()]
    column_exists = "generation_path" in cols
    if not column_exists:
        print("Adding generation_path column..." + ("" if apply else " (dry run: not actually adding)"))
        if apply:
            con.execute(
                "ALTER TABLE enrichment ADD COLUMN generation_path TEXT "
                "CHECK(generation_path IN ('api_call_llm','skill_session',"
                "'migration_script','manual'))"
            )
            column_exists = True
    else:
        print("generation_path column already exists.")

    select_cols = "id, cluster_label, llm_model" + (", generation_path" if column_exists else "")
    rows = con.execute(f"SELECT {select_cols} FROM enrichment").fetchall()

    assignments = {}
    unmatched = []
    for row in rows:
        if column_exists and row["generation_path"] is not None:
            continue
        model = row["llm_model"]
        label = (row["cluster_label"] or "").strip().lower()
        if model == "claude-sonnet-4-20250514":
            path = "api_call_llm"
        elif model == "claude-opus-5" and label in MIGRATION_SCRIPT_IDS:
            path = "migration_script"
        elif model == "claude-sonnet-4-6":
            path = "manual"
        elif model == "claude-opus-5":
            # opus-5 row whose cluster_label isn't in the known migration-script
            # set -- don't guess, surface it for a human to classify.
            unmatched.append((row["id"], row["cluster_label"], model))
            continue
        else:
            unmatched.append((row["id"], row["cluster_label"], model))
            continue
        assignments[row["id"]] = path

    for path, count in sorted(
        {p: list(assignments.values()).count(p) for p in set(assignments.values())}.items()
    ):
        print(f"  {path}: {count} rows")
    if unmatched:
        print("  UNMATCHED (not backfilled, needs manual classification):")
        for rid, label, model in unmatched:
            print(f"    id={rid} cluster_label={label!r} llm_model={model!r}")

    if apply:
        for rid, path in assignments.items():
            con.execute(
                "INSERT INTO enrichment_history (enrichment_id, snapshot_at, trigger, snapshot_json) "
                "SELECT id, datetime('now'), 'add_generation_path_backfill', "
                "json_object('cluster_label',cluster_label,'generation_path',generation_path) "
                "FROM enrichment WHERE id = ?", (rid,)
            )
            con.execute(
                "UPDATE enrichment SET generation_path = ? WHERE id = ?", (path, rid)
            )
        con.commit()

    print(f"\n{len(assignments)} rows backfilled, {len(unmatched)} unmatched.")
    print("APPLIED" if apply else "DRY RUN — nothing written")
    con.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    sys.exit(main(apply=ap.parse_args().apply))
