#!/usr/bin/env python3
"""
Differentia coverage gate.

Step 3 writes `differentia_expression` as free text. Only the structured fields
(genus, function, necessary_parts, qualities, process_signature) drive
generate_turtle(). Any conjunct naming a class that never reaches the generated
OWL is stated in the documentation -- and shown on the published class page --
but absent from the artifact: the class ships weaker than it reads, and in the
worst case reduces to a bare `genus + function` axiom indistinguishable from its
siblings.

None of the four checkers already in the publish path detects this. HermiT sees
a consistent ontology, APV sees complete annotations, OOPS!/FOOPS! see no
pitfall -- because nothing is *wrong*, something is *missing*.

Enforced as a ratchet, mirroring the ODR-022 numeric-IRI gate: the conjuncts
unrendered when this gate was introduced are grandfathered in
scripts/differentia-coverage-baseline.txt, and any conjunct NOT in that baseline
fails the build. The count can only go down. When the baseline is empty the gate
enforces zero unconditionally.

Deliberately NOT a repair. Emitting a restriction per conjunct would publish
~250 classes with no source grounding (many differentia targets are prose
paraphrases -- NormalSeat, SwingArm, RotatingDrum -- with no term behind them)
and would require inventing object properties BFO/IOF-Core does not define
(utilizesPhysicalPrinciple, surrounds, connects_to). The correct per-conjunct
fix is to ground it into the field that carries it, or to trim the differentia
text; both need source evidence and human judgement.

Usage:
    python -m scripts.check_differentia_coverage              # gate (exit 1 on new)
    python -m scripts.check_differentia_coverage --report     # list, never fail
    python -m scripts.check_differentia_coverage --write-baseline
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "enrichment"))
sys.path.insert(0, str(REPO_ROOT))

from enrichment.enrichment_service import (  # noqa: E402
    extract_differentia_conjuncts,
    generate_turtle,
    get_enrichment_db,
)

BASELINE_PATH = REPO_ROOT / "scripts" / "differentia-coverage-baseline.txt"

# Terminal statuses only: a proposed record is still in the review queue, and its
# differentia is expected to be ahead of its structured fields.
TERMINAL_STATUSES = ("validated", "exported")


def _key(cluster_label: str, pred: str, target: str) -> str:
    """Baseline key. Keyed on cluster_label, not id, so the entry survives a
    re-run that replaces the row."""
    return f"{cluster_label}|{pred}.{target}"


def scan() -> list[tuple[str, str, str, int]]:
    """Return [(cluster_label, predicate, target, enrichment_id)] for every
    differentia conjunct absent from the record's generated OWL."""
    conn = get_enrichment_db()
    placeholders = ",".join("?" * len(TERMINAL_STATUSES))
    rows = conn.execute(
        f"""SELECT id, cluster_label, differentia_expression
              FROM enrichment
             WHERE status IN ({placeholders})
             ORDER BY LOWER(cluster_label)""",
        TERMINAL_STATUSES,
    ).fetchall()
    conn.close()

    findings: list[tuple[str, str, str, int]] = []
    for row in rows:
        conjuncts = extract_differentia_conjuncts(row["differentia_expression"])
        if not conjuncts:
            continue
        try:
            turtle_src = generate_turtle(row["id"])
        except Exception as exc:  # a record that cannot render is a separate defect
            print(
                f"  warn: generate_turtle({row['id']}, {row['cluster_label']!r}) "
                f"failed: {exc}",
                file=sys.stderr,
            )
            continue
        import re as _re

        for pred, target in conjuncts:
            if not _re.search(rf":{_re.escape(target)}\b", turtle_src):
                findings.append((row["cluster_label"], pred, target, row["id"]))
    return findings


def load_baseline() -> set[str]:
    if not BASELINE_PATH.exists():
        return set()
    return {
        line.strip()
        for line in BASELINE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def write_baseline(findings: list[tuple[str, str, str, int]]) -> None:
    header = [
        "# Differentia coverage baseline -- see scripts/check_differentia_coverage.py",
        "#",
        "# Each line is a differentia conjunct that is stated in",
        "# differentia_expression but never reaches the generated OWL. These were",
        "# grandfathered when the gate was introduced; anything NOT listed here",
        "# fails the build. Prune a line once the conjunct is either grounded into",
        "# necessary_parts/qualities or removed from the differentia text.",
        "#",
        "# Format: <cluster_label>|<predicate>.<TargetClass>",
        "",
    ]
    lines = sorted({_key(label, pred, target) for label, pred, target, _ in findings})
    BASELINE_PATH.write_text("\n".join(header + lines) + "\n", encoding="utf-8")
    print(f"wrote {len(lines)} entries to {BASELINE_PATH.relative_to(REPO_ROOT)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", action="store_true",
                    help="list every unrendered conjunct and exit 0")
    ap.add_argument("--write-baseline", action="store_true",
                    help="(re)generate the baseline from the current state")
    args = ap.parse_args()

    findings = scan()

    if args.write_baseline:
        write_baseline(findings)
        return 0

    by_pred: dict[str, int] = {}
    for _, pred, _, _ in findings:
        by_pred[pred] = by_pred.get(pred, 0) + 1
    records = len({fid for *_, fid in findings})

    if args.report:
        print(f"unrendered differentia conjuncts: {len(findings)} "
              f"across {records} records\n")
        for pred, n in sorted(by_pred.items(), key=lambda kv: -kv[1]):
            print(f"  {pred:<32} {n:>4}")
        print()
        for label, pred, target, eid in findings:
            print(f"  id={eid:<5} {label:<34} {pred}.{target}")
        return 0

    baseline = load_baseline()
    current = {_key(label, pred, target) for label, pred, target, _ in findings}
    new = sorted(current - baseline)
    retired = sorted(baseline - current)

    if new:
        print("FAIL: differentia conjuncts not covered by the baseline:",
              file=sys.stderr)
        for k in new:
            print(f"    {k}", file=sys.stderr)
        print(
            "\nEach is stated in differentia_expression but absent from the "
            "generated OWL.\nGround it into necessary_parts/qualities (with a "
            "verbatim source_quote), or\ntrim the differentia text to match what "
            "the artifact asserts.\nDo not add it to the baseline to get past "
            "this gate.",
            file=sys.stderr,
        )
        return 1

    print(f"differentia coverage: no new unrendered conjuncts "
          f"({len(current)} grandfathered across {records} records).")
    if retired:
        print(f"  {len(retired)} baseline entries retired -- prune "
              f"{BASELINE_PATH.relative_to(REPO_ROOT)}:")
        for k in retired[:20]:
            print(f"    {k}")
        if len(retired) > 20:
            print(f"    ... and {len(retired) - 20} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
