#!/usr/bin/env python3
"""
Mirrors what enrichment_routes.py's /{enrichment_id}/update route does when a
human reviewer sets status='validated' in the /enrich/ UI, for use when that
UI is unavailable (Docker stuck) and a Claude Code session is doing the review
instead, per explicit user instruction.

Per-id, in order:
  1. snapshot_enrichment(id, trigger='save')      -- matches the route exactly
  2. update_enrichment(id, {status, last_edited_by, last_edited_at,
     expert_reviewer, updated_at})
  3. generate_turtle(id) + verify_service.run_consistency_check() -- the same
     per-class HermiT check the route runs on a validated/exported transition

Usage:
    python .claude/skills/enrich-term/validate_batch.py <id> [<id> ...]
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "enrichment"))

from enrichment_service import snapshot_enrichment, update_enrichment, generate_turtle
from verify_service import run_consistency_check

REVIEWER = "claude-code-session"


def main():
    ids = [int(a) for a in sys.argv[1:]]
    if not ids:
        print("usage: validate_batch.py <id> [<id> ...]", file=sys.stderr)
        sys.exit(1)

    saved_at = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    results = []

    for enr_id in ids:
        try:
            ttl = generate_turtle(enr_id)
            r = run_consistency_check(ttl)
            ok = bool(getattr(r, "ok", False)) and bool(getattr(r, "consistent", False))
        except Exception as e:
            ok = False
            r = None
            print(f"[{enr_id}] consistency check EXCEPTION: {e}")

        if r is not None:
            print(f"[{enr_id}] ok={getattr(r,'ok',None)} consistent={getattr(r,'consistent',None)} error={getattr(r,'error',None)}")

        if not ok:
            print(f"[{enr_id}] SKIPPED validation -- consistency check did not pass.")
            results.append((enr_id, False))
            continue

        snapshot_enrichment(enr_id, trigger="save")
        update_enrichment(enr_id, {
            "status": "validated",
            "last_edited_by": REVIEWER,
            "last_edited_at": saved_at,
            "expert_reviewer": REVIEWER,
        })
        print(f"[{enr_id}] validated.")
        results.append((enr_id, True))

    print("\nSummary:")
    for enr_id, ok in results:
        print(f"  {enr_id}: {'validated' if ok else 'SKIPPED'}")


if __name__ == "__main__":
    main()
