#!/usr/bin/env python3
"""
Participant vocabulary gate.

Every participant type a validated/exported entry names in process_signature must be
hand-authored COPI vocabulary: a class declared in copi-core.ttl / copi-vocab.ttl, a
copi-iri-map.tsv redirect to BFO / IOF-Core, or another validated equipment class.

Why a gate: generate_turtle() emits `someValuesFrom :<Type>` for whatever the
signature says, and allocate_missing_iris() gives any unknown name a fresh COPI IRI.
That is how LLM-invented types -- MovingObject, RestrictedObject (roles, not types),
Surface (a "material artifact" filed under FiatObjectPart), SteelPipe -- were published
as COPI classes with no vocabulary review. HermiT is satisfied, APV sees labels and a
definition, OOPS! finds no pitfall: nothing is inconsistent, the class just should not
exist. auxiliary_class.status does not catch it either -- it was bulk-set by name
pattern (scripts/bulk_classify_aux.py).

Ratchet, like the differentia coverage gate: the unvetted participants already published
when this gate was introduced are grandfathered in
scripts/participant-vocabulary-baseline.txt, and anything NOT listed fails. Prune a line
once the entry uses a real vocab type (or the type has been added to copi-vocab). Do NOT
add lines to get past the gate.

Usage:
    python -m scripts.check_participant_vocabulary              # gate (exit 1 on new)
    python -m scripts.check_participant_vocabulary --report     # list all, never fail
    python -m scripts.check_participant_vocabulary --write-baseline
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "enrichment"))
sys.path.insert(0, str(REPO_ROOT))

from enrichment_service import (  # noqa: E402
    PARTICIPANT_VOCAB_BASELINE_PATH,
    find_unvetted_participants,
    get_enrichment_db,
    load_participant_vocabulary_baseline,
)

TERMINAL_STATUSES = ("validated", "exported")


def scan() -> list[tuple[str, str, int, str]]:
    """[(cluster_label, Type, enrichment_id, status)] for every unvetted participant
    of a validated/exported entry."""
    conn = get_enrichment_db()
    rows = conn.execute(
        """SELECT id, cluster_label, status, process_signature
             FROM enrichment
            WHERE status IN (?, ?)
            ORDER BY LOWER(cluster_label)""",
        TERMINAL_STATUSES,
    ).fetchall()
    conn.close()
    return [
        (row["cluster_label"], t, row["id"], row["status"])
        for row in rows
        for t in find_unvetted_participants(row["process_signature"])
    ]


def write_baseline(findings) -> None:
    header = [
        "# Participant vocabulary baseline -- see scripts/check_participant_vocabulary.py",
        "#",
        "# Each line is a participant type an already-published entry names that is not",
        "# COPI vocabulary (not in copi-core/copi-vocab, not a BFO/IOF-Core redirect, not",
        "# a validated equipment class). Grandfathered when the gate was introduced;",
        "# anything NOT listed here fails. Prune a line once the entry uses a real vocab",
        "# type or the type has been added to copi-vocab.ttl.",
        "#",
        "# Format: <cluster_label>|<ParticipantType>",
        "",
    ]
    lines = sorted({f"{label}|{t}" for label, t, _, _ in findings})
    PARTICIPANT_VOCAB_BASELINE_PATH.write_text("\n".join(header + lines) + "\n", encoding="utf-8")
    print(f"wrote {len(lines)} entries to {PARTICIPANT_VOCAB_BASELINE_PATH.relative_to(REPO_ROOT)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", action="store_true", help="list every unvetted participant and exit 0")
    ap.add_argument("--write-baseline", action="store_true", help="(re)generate the baseline")
    args = ap.parse_args()

    findings = scan()
    if args.write_baseline:
        write_baseline(findings)
        return 0

    if args.report:
        print(f"unvetted participant types: {len(findings)} "
              f"across {len({f[2] for f in findings})} entries\n")
        for label, t, eid, status in findings:
            print(f"  id={eid:<5} {status:<9} {label:<34} {t}")
        return 0

    baseline = load_participant_vocabulary_baseline()
    new = [f for f in findings if f"{f[0]}|{f[1]}" not in baseline]
    stale = baseline - {f"{label}|{t}" for label, t, _, _ in findings}

    if new:
        print(f"FAIL: {len(new)} unvetted participant type(s) not in the baseline:")
        for label, t, eid, status in new:
            print(f"  id={eid:<5} {status:<9} {label:<34} {t}")
        print("\nParticipant types are hand-authored in copi-vocab (ODR-022 §2). Replace each "
              "with an existing copi-vocab type, redirect it to BFO / IOF-Core in "
              "copi-iri-map.tsv, or add it to copi-vocab.ttl first.")
        return 1

    if stale:
        print(f"note: {len(stale)} baseline line(s) no longer occur -- prune them:")
        for key in sorted(stale):
            print(f"  {key}")
    print(f"participant vocabulary: 0 new unvetted types "
          f"({len(findings)} grandfathered in baseline)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
