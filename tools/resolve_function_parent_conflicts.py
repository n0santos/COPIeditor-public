#!/usr/bin/env python3
"""
Detect, analyse, and resolve function_parent conflicts in enrichment.db.

A conflict exists when the same function_name appears in multiple enrichment
records with different function_parent values, either in the `function_parent`
column of the enrichment table, in step1_function.function_parent inside
llm_raw_response, or between the two sources.

Canonical parent selection (priority order):
  1. Specificity  — the most specific parent in the COPI function hierarchy wins.
                    DesignedFunction is always the least specific.
  2. Frequency    — most-used parent across records.
  3. Recency      — latest created_at timestamp.
  4. Confidence   — highest confidence.step1 value.

Usage:
    python tools/resolve_function_parent_conflicts.py            # dry-run (default)
    python tools/resolve_function_parent_conflicts.py --dry-run
    python tools/resolve_function_parent_conflicts.py --apply
    python tools/resolve_function_parent_conflicts.py --apply --include-manual

Output (always written, even in dry-run):
    /tmp/function_parent_conflicts.json
    /tmp/function_parent_conflicts.md
"""

import argparse
import json
import shutil
import sqlite3
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "enrichment"))

from enrichment_service import get_enrichment_db  # noqa: E402

DB_PATH  = PROJECT_ROOT / "data" / "enrichment.db"
OUT_JSON = Path("/tmp/function_parent_conflicts.json")
OUT_MD   = Path("/tmp/function_parent_conflicts.md")

CONF_RANK = {"high": 3, "medium": 2, "low": 1, "": 0}


# ---------------------------------------------------------------------------
# Load all enrichment records
# ---------------------------------------------------------------------------

def load_records(conn: sqlite3.Connection) -> list[dict]:
    """
    Return one dict per enrichment record with both the SQL column value
    and the JSON value for function_parent.
    """
    rows = conn.execute(
        "SELECT id, cluster_label, function_name, function_parent, "
        "       created_at, llm_raw_response "
        "FROM enrichment "
        "WHERE function_name IS NOT NULL AND function_name != '' "
        "ORDER BY created_at"
    ).fetchall()

    records = []
    for row in rows:
        try:
            proposal = json.loads(row["llm_raw_response"] or "{}")
        except Exception:
            proposal = {}

        s1 = proposal.get("step1_function") or {}
        json_parent         = (s1.get("function_parent") or "DesignedFunction").strip()
        json_parent_enriched = bool(s1.get("function_parent_enriched", False))
        conf                 = (proposal.get("confidence") or {}).get("step1", "")

        records.append({
            "id":             row["id"],
            "cluster_label":  row["cluster_label"],
            "function_name":  (row["function_name"] or "").strip(),
            "col_parent":     (row["function_parent"] or "DesignedFunction").strip(),
            "json_parent":    json_parent,
            "json_parent_enriched": json_parent_enriched,
            "created_at":     row["created_at"] or "",
            "confidence":     conf,
            "proposal":       proposal,
        })
    return records


# ---------------------------------------------------------------------------
# Build the function hierarchy for specificity detection
# ---------------------------------------------------------------------------

def build_hierarchy(records: list[dict]) -> dict[str, str]:
    """
    Return function_name → most_common_parent (excluding conflicted functions
    in a first pass, then including them with their majority parent).

    Used to determine ancestor relationships for the specificity rule.
    """
    from collections import Counter

    parent_votes: dict[str, Counter] = defaultdict(Counter)
    for r in records:
        fn = r["function_name"]
        # Prefer JSON (more detailed), fall back to column
        parent = r["json_parent"] if r["json_parent"] != "DesignedFunction" else r["col_parent"]
        parent_votes[fn][parent] += 1

    hierarchy: dict[str, str] = {}
    for fn, counter in parent_votes.items():
        hierarchy[fn] = counter.most_common(1)[0][0]
    return hierarchy


def ancestors(fn: str, hierarchy: dict[str, str]) -> set[str]:
    """Return all ancestors of fn in the hierarchy (including DesignedFunction)."""
    seen: set[str] = set()
    current = fn
    while True:
        parent = hierarchy.get(current)
        if not parent or parent in seen:
            break
        seen.add(parent)
        current = parent
    seen.add("DesignedFunction")
    return seen


def is_more_specific(p1: str, p2: str, hierarchy: dict[str, str]) -> bool:
    """True if p1 is strictly more specific (deeper) than p2."""
    if p1 == p2:
        return False
    if p2 == "DesignedFunction":
        # Any COPI function class is more specific than DesignedFunction
        return p1 != "DesignedFunction"
    if p1 == "DesignedFunction":
        return False
    # p1 is more specific than p2 if p2 is an ancestor of p1
    return p2 in ancestors(p1, hierarchy)


def specificity_depth(fn: str, hierarchy: dict[str, str]) -> int:
    """Number of hops from fn to DesignedFunction (0 = is DesignedFunction)."""
    if fn == "DesignedFunction":
        return 0
    depth = 0
    current = fn
    seen: set[str] = set()
    while current and current not in seen and current != "DesignedFunction":
        seen.add(current)
        current = hierarchy.get(current, "DesignedFunction")
        depth += 1
    return depth


# ---------------------------------------------------------------------------
# Detect conflicts
# ---------------------------------------------------------------------------

def detect_conflicts(records: list[dict]) -> dict[str, dict]:
    """
    For each function_name, collect all distinct parents across both the
    SQL column and the llm_raw_response JSON.

    Returns {function_name: {
        "parents": {parent_name: {"count_col": N, "count_json": N,
                                  "samples": [...], "earliest": ..., "latest": ...,
                                  "confidences": [...]}},
        "conflicted": bool,
    }}
    """
    by_fn: dict[str, dict] = defaultdict(lambda: {"parents": defaultdict(lambda: {
        "count_col": 0, "count_json": 0,
        "samples": [], "timestamps": [], "confidences": [],
    })})

    for r in records:
        fn = r["function_name"]
        entry = by_fn[fn]
        for parent, source in [(r["col_parent"], "col"), (r["json_parent"], "json")]:
            p = entry["parents"][parent]
            p[f"count_{source}"] += 1
            if len(p["samples"]) < 5 and r["cluster_label"] not in p["samples"]:
                p["samples"].append(r["cluster_label"])
            if r["created_at"]:
                p["timestamps"].append(r["created_at"])
            if r["confidence"]:
                p["confidences"].append(r["confidence"])

    result = {}
    for fn, entry in by_fn.items():
        parents = entry["parents"]
        conflicted = len(parents) > 1
        result[fn] = {
            "parents": {
                name: {
                    "count_col":   pdata["count_col"],
                    "count_json":  pdata["count_json"],
                    "count_total": pdata["count_col"] + pdata["count_json"],
                    "samples":     pdata["samples"],
                    "earliest":    min(pdata["timestamps"]) if pdata["timestamps"] else "",
                    "latest":      max(pdata["timestamps"]) if pdata["timestamps"] else "",
                    "top_confidence": max(
                        pdata["confidences"], key=lambda c: CONF_RANK.get(c, 0), default=""
                    ),
                }
                for name, pdata in parents.items()
            },
            "conflicted": conflicted,
        }
    return result


# ---------------------------------------------------------------------------
# Canonical parent selection
# ---------------------------------------------------------------------------

def select_canonical(
    fn: str,
    parents: dict[str, dict],
    hierarchy: dict[str, str],
) -> tuple[str, str, str]:
    """
    Return (canonical_parent, rationale, decision_type).
    decision_type: 'automatica' | 'manual_review'
    """
    parent_names = list(parents.keys())
    if len(parent_names) == 1:
        return parent_names[0], "sole parent — no conflict", "automatica"

    # --- Rule 1: Specificity ---
    # Find the most specific parent(s)
    most_specific: list[str] = []
    for p in parent_names:
        if all(
            is_more_specific(p, other, hierarchy) or p == other
            for other in parent_names
        ):
            most_specific.append(p)

    # Remove dominated parents (those that are less specific than some other)
    dominated: set[str] = set()
    for p in parent_names:
        for other in parent_names:
            if p != other and is_more_specific(other, p, hierarchy):
                dominated.add(p)
    candidates = [p for p in parent_names if p not in dominated]

    if len(candidates) == 1:
        dominated_list = ", ".join(sorted(dominated))
        rationale = (
            f"Specificity: '{candidates[0]}' is more specific than {dominated_list}. "
            f"Genus-proximum principle (Step 2) applied to function hierarchy."
        )
        return candidates[0], rationale, "automatica"

    # Parents are incomparable — check for DesignedFunction override
    # If exactly one parent is a non-DesignedFunction COPI class and another is DesignedFunction:
    non_df = [p for p in candidates if p != "DesignedFunction"]
    if len(non_df) == 1 and "DesignedFunction" in candidates:
        rationale = (
            f"Specificity (DesignedFunction override): '{non_df[0]}' is a COPI function "
            f"class and therefore more specific than DesignedFunction."
        )
        return non_df[0], rationale, "automatica"

    if not candidates:
        candidates = parent_names  # fallback: no clear winner from specificity

    # --- Rule 2: Frequency ---
    by_freq = sorted(candidates, key=lambda p: -parents[p]["count_total"])
    if parents[by_freq[0]]["count_total"] > parents[by_freq[1]]["count_total"]:
        rationale = (
            f"Frequency: '{by_freq[0]}' used {parents[by_freq[0]]['count_total']} "
            f"times vs {parents[by_freq[1]]['count_total']}. "
            f"Parents are incomparable in the hierarchy."
        )
        return by_freq[0], rationale, "automatica"

    # --- Rule 3: Recency ---
    by_recency = sorted(
        candidates,
        key=lambda p: parents[p]["latest"],
        reverse=True,
    )
    if parents[by_recency[0]]["latest"] != parents[by_recency[1]]["latest"]:
        rationale = (
            f"Recency: '{by_recency[0]}' appears in records as late as "
            f"{parents[by_recency[0]]['latest']} "
            f"(vs {parents[by_recency[1]]['latest']} for '{by_recency[1]}'). "
            f"Later enrichments reflect more mature prompt."
        )
        return by_recency[0], rationale, "automatica"

    # --- Rule 4: Confidence ---
    by_conf = sorted(
        candidates,
        key=lambda p: CONF_RANK.get(parents[p]["top_confidence"], 0),
        reverse=True,
    )
    if (CONF_RANK.get(parents[by_conf[0]]["top_confidence"], 0)
            > CONF_RANK.get(parents[by_conf[1]]["top_confidence"], 0)):
        rationale = (
            f"Confidence tiebreaker: '{by_conf[0]}' associated with "
            f"confidence.step1='{parents[by_conf[0]]['top_confidence']}'."
        )
        return by_conf[0], rationale, "automatica"

    # Unresolved
    rationale = (
        "All four tiebreaker rules failed to disambiguate. "
        f"Candidates: {candidates}. Manual review required."
    )
    return candidates[0], rationale, "manual_review"


# ---------------------------------------------------------------------------
# Build the final conflict report
# ---------------------------------------------------------------------------

def build_report(records: list[dict]) -> dict:
    hierarchy = build_hierarchy(records)
    all_fn = detect_conflicts(records)

    conflicts = []
    for fn, info in sorted(all_fn.items()):
        if not info["conflicted"]:
            continue
        canonical, rationale, decision_type = select_canonical(
            fn, info["parents"], hierarchy
        )
        conflicts.append({
            "function_name":            fn,
            "parents_observed":         [
                {
                    "parent":          name,
                    "count_col":       pdata["count_col"],
                    "count_json":      pdata["count_json"],
                    "count_total":     pdata["count_total"],
                    "samples":         pdata["samples"],
                    "earliest":        pdata["earliest"],
                    "latest":          pdata["latest"],
                    "top_confidence":  pdata["top_confidence"],
                }
                for name, pdata in info["parents"].items()
            ],
            "proposed_canonical_parent": canonical,
            "rationale":                 rationale,
            "decision_type":             decision_type,
        })

    return {
        "total_conflicts":  len(conflicts),
        "automatica":       sum(1 for c in conflicts if c["decision_type"] == "automatica"),
        "manual_review":    sum(1 for c in conflicts if c["decision_type"] == "manual_review"),
        "conflicts":        conflicts,
    }


# ---------------------------------------------------------------------------
# Apply fixes
# ---------------------------------------------------------------------------

def apply_fixes(
    report: dict,
    records: list[dict],
    conn: sqlite3.Connection,
    include_manual: bool,
    dry_run: bool,
) -> None:
    """Update function_parent column and llm_raw_response JSON for conflicted records."""

    canonical_map: dict[str, str] = {}
    skipped_manual: list[str] = []

    for conflict in report["conflicts"]:
        if conflict["decision_type"] == "manual_review" and not include_manual:
            skipped_manual.append(conflict["function_name"])
            continue
        canonical_map[conflict["function_name"]] = conflict["proposed_canonical_parent"]

    if not canonical_map:
        print("  Nothing to apply (all conflicts are manual_review and --include-manual not set).")
        return

    updated = 0
    skipped_consistent = 0

    for rec in records:
        fn = rec["function_name"]
        if fn not in canonical_map:
            continue
        canonical = canonical_map[fn]
        canonical_enriched = canonical != "DesignedFunction"

        col_needs_update  = rec["col_parent"]  != canonical
        json_needs_update = rec["json_parent"] != canonical or \
                            rec["json_parent_enriched"] != canonical_enriched

        if not col_needs_update and not json_needs_update:
            skipped_consistent += 1
            continue

        # Build updated proposal JSON
        updated_proposal = rec["proposal"]
        s1 = updated_proposal.setdefault("step1_function", {})
        s1["function_parent"]          = canonical
        s1["function_parent_enriched"] = canonical_enriched

        if not dry_run:
            conn.execute(
                "UPDATE enrichment "
                "SET function_parent = ?, llm_raw_response = ? "
                "WHERE id = ?",
                (canonical, json.dumps(updated_proposal, ensure_ascii=False), rec["id"]),
            )
        else:
            col_note  = f" [col: {rec['col_parent']} → {canonical}]"  if col_needs_update  else ""
            json_note = f" [json: {rec['json_parent']} → {canonical}]" if json_needs_update else ""
            print(f"    id={rec['id']:5d}  {fn}  {rec['cluster_label']}{col_note}{json_note}")

        updated += 1

    if not dry_run:
        conn.commit()

    if skipped_manual:
        print(f"  Skipped (manual_review, not applied): {skipped_manual}")
    print(f"  Updated : {updated} record(s)")
    print(f"  Already consistent: {skipped_consistent} record(s)")


# ---------------------------------------------------------------------------
# Report output
# ---------------------------------------------------------------------------

def write_json(report: dict) -> None:
    OUT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False))


def write_markdown(report: dict) -> None:
    lines = [
        "# Function Parent Conflicts — COPI Enrichment DB",
        "",
        f"**Total conflicts:** {report['total_conflicts']}  ",
        f"**Automatic resolution:** {report['automatica']}  ",
        f"**Manual review required:** {report['manual_review']}  ",
        "",
        "---",
        "",
    ]

    for conflict in report["conflicts"]:
        fn       = conflict["function_name"]
        canon    = conflict["proposed_canonical_parent"]
        dtype    = conflict["decision_type"]
        rationale = conflict["rationale"]
        badge = "🟢 automática" if dtype == "automatica" else "🔴 manual_review"

        lines += [
            f"## `{fn}` — {badge}",
            "",
            f"**Proposed canonical parent:** `{canon}`  ",
            f"**Rationale:** {rationale}  ",
            "",
            "| Parent | Count (col) | Count (json) | Earliest | Latest | Confidence |",
            "|--------|-------------|--------------|----------|--------|------------|",
        ]
        for p in sorted(conflict["parents_observed"],
                        key=lambda x: -x["count_total"]):
            samples = ", ".join(p["samples"][:3])
            lines.append(
                f"| `{p['parent']}` | {p['count_col']} | {p['count_json']} "
                f"| {p['earliest'][:10]} | {p['latest'][:10]} | {p['top_confidence']} |"
            )
            lines.append(f"| — samples | | | {samples} | | |")
        lines.append("")

    OUT_MD.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Generate reports only; do not modify the database (default)")
    parser.add_argument("--apply", action="store_true",
                        help="Apply canonical parent fixes to the database")
    parser.add_argument("--include-manual", action="store_true",
                        help="Include manual_review conflicts when using --apply "
                             "(prompts for confirmation)")
    args = parser.parse_args()

    dry_run = not args.apply

    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")

    conn = get_enrichment_db()

    print("Loading records...")
    records = load_records(conn)
    print(f"  {len(records)} records loaded")

    print("Detecting conflicts...")
    report = build_report(records)
    print(f"  {report['total_conflicts']} conflict(s) found "
          f"({report['automatica']} automatic, {report['manual_review']} manual_review)")

    write_json(report)
    write_markdown(report)
    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")

    if report["total_conflicts"] == 0:
        print("\nNo conflicts — database is consistent.")
        conn.close()
        return

    print()
    for c in report["conflicts"]:
        print(f"  {c['function_name']:50s}  →  {c['proposed_canonical_parent']}  [{c['decision_type']}]")

    if dry_run:
        print("\n[dry-run] No changes written. Re-run with --apply to apply fixes.")
        print("Changes that would be applied:")
        apply_fixes(report, records, conn, args.include_manual, dry_run=True)
    else:
        bak = DB_PATH.with_suffix(f".db.bak.{date.today().strftime('%Y%m%d')}")
        if not bak.exists():
            shutil.copy2(DB_PATH, bak)
            print(f"\nBackup: {bak}")
        else:
            print(f"\nBackup already exists: {bak}")

        print("\nApplying fixes...")
        apply_fixes(report, records, conn, args.include_manual, dry_run=False)
        print("Done.")

    conn.close()


if __name__ == "__main__":
    main()
