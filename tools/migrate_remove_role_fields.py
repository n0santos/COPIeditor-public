#!/usr/bin/env python3
"""
Migration: remove is_role / role_detection fields from enrichment.db.

Rationale: role-detection was removed from the COPI enrichment pipeline
after an empirical audit of 273 enrichments found zero stable positives.
All enrichments are now treated as kinds. See docs/findings/role_detection_audit.md.

Usage:
    python tools/migrate_remove_role_fields.py --dry-run   # preview only
    python tools/migrate_remove_role_fields.py             # apply

Idempotent: running twice is safe — rows already cleaned are skipped.
"""

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH      = PROJECT_ROOT / "data" / "enrichment.db"
ROLE_KEYS    = {"is_role", "role_detection"}


def _strip_role_keys(raw: str) -> tuple[str, bool]:
    """Remove ROLE_KEYS from a JSON string. Returns (new_json, changed)."""
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw, False
    before = set(obj.keys()) & ROLE_KEYS
    if not before:
        return raw, False
    for k in before:
        del obj[k]
    return json.dumps(obj, ensure_ascii=False), True


def run(dry_run: bool) -> None:
    if not DB_PATH.exists():
        sys.exit(f"Database not found: {DB_PATH}")

    if not dry_run:
        bak = DB_PATH.with_suffix(f".db.bak.{date.today().strftime('%Y%m%d')}")
        shutil.copy2(DB_PATH, bak)
        print(f"Backup created: {bak}")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, llm_raw_response, is_role FROM enrichment").fetchall()

    to_update   = []
    already_clean = 0
    total_chars_removed = 0

    for row in rows:
        raw = row["llm_raw_response"] or "{}"
        new_raw, changed = _strip_role_keys(raw)
        if changed:
            chars_removed = len(raw) - len(new_raw)
            total_chars_removed += chars_removed
            to_update.append((new_raw, row["id"]))
        else:
            already_clean += 1

    print(f"\nTotal records      : {len(rows)}")
    print(f"To be modified     : {len(to_update)}")
    print(f"Already clean      : {already_clean}")
    if to_update:
        avg_removed = total_chars_removed / len(to_update)
        print(f"Avg chars removed  : {avg_removed:.0f}")

    if dry_run:
        print("\n[dry-run] No changes written.")
        return

    if not to_update:
        print("\nNothing to do — all records already clean.")
        conn.close()
        return

    conn.executemany(
        "UPDATE enrichment SET llm_raw_response = ?, is_role = 0, "
        "role_bearer = NULL, role_bearer_rationale = NULL WHERE id = ?",
        to_update,
    )
    conn.commit()
    conn.close()
    print(f"\nUpdated {len(to_update)} record(s). Migration complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without writing to the database")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
