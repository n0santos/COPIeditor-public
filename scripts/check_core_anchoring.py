#!/usr/bin/env python3
"""
COPI-Core anchoring gate.

Every validated/exported equipment process must either reach a COPI-Core operation
(core_operations.TOP_OPERATIONS, through its own process or its process_parent chain) or
record why it cannot (`core_operation_gap`: out_of_scope or core_coverage_gap). And its
controlled transformation_kind must agree with that anchor (core_operations.KIND_TO_OPERATIONS).

Two finding types, keyed `<cluster_label>|<type>`:
  unanchored          no operation reached and no core_operation_gap recorded
  kind_mismatch:<k>   anchored in an operation the transformation_kind <k> does not allow
                      (including a kind COPI-Core has no operation for, e.g. fluid_transport
                      anchored in MomentumTransfer)

Why a gate: an unanchored process is invisible to every other check — HermiT is happy with
`⊑ PlannedProcess`, and the entry still exports. But it silently drops the equipment out of
COPI-Core's category classification, which is the point of the core.

Ratchet over scripts/core-anchoring-baseline.txt, like the other gates: grandfathered at
introduction, prune as entries are re-anchored or given a gap, never add.

Usage:
    python -m scripts.check_core_anchoring              # gate (exit 1 on new)
    python -m scripts.check_core_anchoring --report     # list all, never fail
    python -m scripts.check_core_anchoring --write-baseline
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "enrichment"))
sys.path.insert(0, str(REPO_ROOT))

from core_operations import anchor_for_entry, anchoring_findings  # noqa: E402
from enrichment_service import get_enrichment_db  # noqa: E402

BASELINE_PATH = REPO_ROOT / "scripts" / "core-anchoring-baseline.txt"
TERMINAL_STATUSES = ("validated", "exported")


def scan() -> list[tuple[str, str, int, str]]:
    conn = get_enrichment_db()
    process_parents = {
        r["process_name"]: r["process_parent"]
        for r in conn.execute("SELECT process_name, process_parent FROM enrichment WHERE process_name IS NOT NULL")
    }
    rows = conn.execute(
        """SELECT id, cluster_label, status, process_name, process_parent, process_signature, core_operation_gap
             FROM enrichment WHERE status IN (?, ?) ORDER BY LOWER(cluster_label)""",
        TERMINAL_STATUSES,
    ).fetchall()
    conn.close()
    out = []
    for row in rows:
        anchor = anchor_for_entry(row["process_name"], row["process_parent"], process_parents)
        for f in anchoring_findings(row["process_name"], row["process_parent"], row["process_signature"],
                                    row["core_operation_gap"], process_parents):
            out.append((row["cluster_label"], f, row["id"], anchor or "—"))
    return out


def load_baseline() -> set[str]:
    if not BASELINE_PATH.exists():
        return set()
    return {l.strip() for l in BASELINE_PATH.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.lstrip().startswith("#")}


def write_baseline(findings) -> None:
    header = [
        "# COPI-Core anchoring baseline -- see scripts/check_core_anchoring.py",
        "#",
        "# Validated/exported entries that, when the gate was introduced, either reached no",
        "# COPI-Core operation without a recorded core_operation_gap (`unanchored`), or whose",
        "# transformation_kind disagrees with their anchor (`kind_mismatch:<kind>`).",
        "# Prune a line once the entry is re-anchored or given a gap. Never add lines.",
        "#",
        "# Format: <cluster_label>|<finding>",
        "",
    ]
    lines = sorted({f"{label}|{f}" for label, f, _, _ in findings})
    BASELINE_PATH.write_text("\n".join(header + lines) + "\n", encoding="utf-8")
    print(f"wrote {len(lines)} entries to {BASELINE_PATH.relative_to(REPO_ROOT)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--write-baseline", action="store_true")
    args = ap.parse_args()
    findings = scan()

    if args.write_baseline:
        write_baseline(findings)
        return 0
    if args.report:
        print(f"core anchoring findings: {len(findings)}\n")
        for label, f, eid, anchor in findings:
            print(f"  id={eid:<5} {label:<36} {f:<40} anchor={anchor}")
        return 0

    baseline = load_baseline()
    new = [x for x in findings if f"{x[0]}|{x[1]}" not in baseline]
    stale = baseline - {f"{label}|{f}" for label, f, _, _ in findings}
    if new:
        print(f"FAIL: {len(new)} core anchoring finding(s) not in the baseline:")
        for label, f, eid, anchor in new:
            print(f"  id={eid:<5} {label:<36} {f:<40} anchor={anchor}")
        print("\nAnchor the process in a COPI-Core operation (process_parent), record a "
              "core_operation_gap (out_of_scope | core_coverage_gap), or fix transformation_kind.")
        return 1
    if stale:
        print(f"note: {len(stale)} baseline line(s) no longer occur -- prune them:")
        for key in sorted(stale):
            print(f"  {key}")
    print(f"core anchoring: 0 new findings ({len(findings)} grandfathered in baseline)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
