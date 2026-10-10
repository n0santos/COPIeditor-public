#!/usr/bin/env python3
"""
Reusable Phase 1b step 5-6 follow-up for the enrich-term skill: write the
rich-shape source_definitions_used (tier/source_type/citation_mode/access/
categories_covered/quote), compute secondary_coverage deterministically,
optionally set primary_definition_conflict and reviewer_notes, then
re-run the three /update-path validators against the new data -- same
pattern SKILL.md's Phase 1b describes and scripts/migrations/
backfill_source_tier.py uses for the direct UPDATE.

Usage:
    python .claude/skills/enrich-term/finalize_step2b.py <enrichment_id> <payload.json>

payload.json shape:
{
  "source_definitions_used": [ {...}, ... ],   // required, full rich shape
  "primary_definition_conflict": "..." | null,  // optional, default null
  "reviewer_notes": "...",                      // optional, appended
  "necessary_parts": [ {...}, ... ]             // optional, only if re-validating parts
}
"""
import sys, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "enrichment"))

from enrichment_service import (
    snapshot_enrichment, update_enrichment, compute_secondary_coverage,
    validate_tertiary_triangulation, validate_necessary_parts_quotes,
    validate_part_universality, get_enrichment_db,
)


def main():
    if len(sys.argv) != 3:
        print("usage: finalize_step2b.py <enrichment_id> <payload.json>", file=sys.stderr)
        sys.exit(1)

    enr_id = int(sys.argv[1])
    payload = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))

    src_defs = payload["source_definitions_used"]
    src_json = json.dumps(src_defs, ensure_ascii=False)
    parts = payload.get("necessary_parts", [])

    coverage = compute_secondary_coverage(src_json)
    print(f"[{enr_id}] secondary_coverage computed: {coverage}")

    tri_err = validate_tertiary_triangulation(src_json)
    print(f"[{enr_id}] validate_tertiary_triangulation:", tri_err or "OK")

    candidate_parts = []
    if parts:
        part_err = validate_necessary_parts_quotes(parts, src_json)
        print(f"[{enr_id}] validate_necessary_parts_quotes:", part_err or "OK")
        if part_err:
            print(f"[{enr_id}] BLOCKED -- not writing.")
            sys.exit(1)
        univ_err = validate_part_universality(parts)
        if univ_err:
            # CLAUDE.md Step 2c safeguard 3: a hedged part is not blocking --
            # it moves to candidate_parts (unconfirmed genus-wide) instead of
            # necessary_parts, same remedy the check itself prescribes.
            print(f"[{enr_id}] validate_part_universality: {univ_err}")
            print(f"[{enr_id}] -> moving hedged part(s) to candidate_parts instead of blocking.")
            candidate_parts = parts
            parts = []
        else:
            print(f"[{enr_id}] validate_part_universality: OK")
    else:
        part_err = None
        print(f"[{enr_id}] validate_necessary_parts_quotes/universality: OK (no parts)")

    if tri_err:
        print(f"[{enr_id}] BLOCKED -- not writing.")
        sys.exit(1)

    snapshot_enrichment(enr_id, trigger="skill_session_step2b")

    conn = get_enrichment_db(actor="skill_session_step2b")
    if candidate_parts:
        conn.execute(
            "UPDATE enrichment SET source_definitions_used = ?, candidate_parts = ?, "
            "updated_at = datetime('now') WHERE id = ?",
            (src_json, json.dumps(candidate_parts, ensure_ascii=False), enr_id),
        )
    else:
        conn.execute(
            "UPDATE enrichment SET source_definitions_used = ?, updated_at = datetime('now') WHERE id = ?",
            (src_json, enr_id),
        )
    conn.commit()
    conn.close()

    updates = {
        "secondary_coverage": coverage,
        "primary_definition_conflict": payload.get("primary_definition_conflict"),
    }
    if payload.get("reviewer_notes"):
        updates["reviewer_notes"] = payload["reviewer_notes"]
    if parts:
        updates["necessary_parts"] = parts
        if payload.get("parts_rationale"):
            updates["parts_rationale"] = payload["parts_rationale"]

    update_enrichment(enr_id, updates)
    print(f"[{enr_id}] Follow-up write done.")


if __name__ == "__main__":
    main()
