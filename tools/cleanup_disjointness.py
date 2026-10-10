#!/usr/bin/env python3
"""
Controlled removal of invalid disjointness assertions from enrichment.db.

Batch modes
-----------
  --batch 0   Referential cleanup: remove candidates not found in the DB even
              after normalised (CamelCase-aware) lookup. Pure referential
              cleanup — no ontological decision required.

  --batch 0b  Second-pass referential cleanup: remove pairs currently annotated
              as C?:[unverifiable_class_not_in_db] in disjointness_rationale
              (placed there by backfill_disjointness_case_ids.py) after
              re-confirming the candidate is still absent from the DB.  These
              are fabrications that escaped the original batch-0 run, typically
              because they appear in records enriched after that run.  Also
              strips the corresponding C?: token from disjointness_rationale.

  --batch 3   Remove pairs rejected by Case 3 (same genus, mixed
              functional/constructive bases — orthogonality violation).

  --batch 5   Remove pairs rejected by Case 5 (operational/regulatory context
              — never disjoint by definition).

  --batch 4   Remove pairs rejected by Case 4 (different genus, insufficient
              signature evidence). INTERACTIVE: prompts per pair because
              imprecise signatures may be the root cause, not wrong disjointness.

  --batch 2   DEFERRED. Pairs rejected by Case 2 (both functional, dormant)
              will be revisited after function disjunctions are added to the
              ontology (post-Leva 3 with Régis). Prints explanation and exits.

Flags
-----
  --dry-run   List pairs to remove without touching the DB (default).
  --apply     Execute removals. Auto-backup before the first write.

Multiple --batch flags are allowed in one invocation (applied left to right).

Behaviour
---------
  - Updates both the `disjoint_with` SQL column AND the JSON inside
    `llm_raw_response` (sync lesson from function_parent canonicalization).
  - When removing from a record makes `disjoint_with` empty, also clears
    `disjointness_rationale` in both column and JSON.
  - Batch 0b additionally strips the removed pair's C?: token from a
    non-empty disjointness_rationale (surgical prefix update).
  - All versions of a cluster (multiple enrichment rows for the same label)
    are updated for consistency.
  - Idempotent: safe to run twice.

Usage
-----
  python tools/cleanup_disjointness.py --batch 0 --dry-run
  python tools/cleanup_disjointness.py --batch 0b --dry-run
  python tools/cleanup_disjointness.py --batch 0 --batch 3 --apply
  python tools/cleanup_disjointness.py --batch 0b --apply
  python tools/cleanup_disjointness.py --batch 4 --apply
"""

import argparse
import json
import re
import shutil
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from enrichment.disjointness_validator import (
    build_ontology_state,
    build_normalised_index,
    normalise_label,
    validate_pair_structural,
    _has_operational_marker,
    _step5_of,
)

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "enrichment.db"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _backup_db() -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = _DB_PATH.with_suffix(f".backup_{ts}.db")
    shutil.copy2(_DB_PATH, dst)
    print(f"  backup → {dst}")
    return dst


# ---------------------------------------------------------------------------
# Pair classification
# ---------------------------------------------------------------------------

BATCH_NOT_IN_DB  = 0
BATCH_C1         = 1
BATCH_C2         = 2
BATCH_C3         = 3
BATCH_C4         = 4
BATCH_C5         = 5
BATCH_PRESERVED  = -1   # passes tree — do not remove
BATCH_UNVERIFIABLE = -2

_BATCH_LABELS = {
    BATCH_NOT_IN_DB:   "referential (C not in DB)",
    BATCH_C1:          "C1 (same genus, both constructive — needs structural review)",
    BATCH_C2:          "C2 (same genus, both functional — dormant)",
    BATCH_C3:          "C3 (same genus, mixed bases — orthogonal)",
    BATCH_C4:          "C4 (different genus — signature evidence insufficient)",
    BATCH_C5:          "C5 (operational/regulatory context)",
    BATCH_PRESERVED:   "preserved (passes tree)",
    BATCH_UNVERIFIABLE:"unverifiable (missing structural fields)",
}

# Matches a single C?:[unverifiable_class_not_in_db] token in disjointness_rationale,
# including its trailing ". " separator produced by _build_prefix().
_CQ_NOT_IN_DB_TOKEN_RE = re.compile(
    r"C\?: ([^\[.]+) \[unverifiable_class_not_in_db\]\. "
)


def classify_pair(
    x_label: str,
    x_basis: str,
    x_genus: str,
    x_kind: str,
    x_kind_status: str,
    candidate: str,
    ontology_state: dict,
    norm_index: dict,
) -> tuple[int, str, str]:
    """Classify an (X, candidate) pair into a batch number.

    Returns (batch_id, resolved_c_label_or_empty, reason).
    """
    # --- Lookup ---
    c_row = ontology_state.get(candidate)
    resolved = candidate
    if c_row is None:
        norm_key = normalise_label(candidate)
        resolved = norm_index.get(norm_key, "")
        if resolved:
            c_row = ontology_state[resolved]

    if c_row is None:
        return BATCH_NOT_IN_DB, "", "C not found in DB (even after normalised lookup)"

    # --- Extract C structural fields ---
    raw_c = c_row.get("llm_raw_response") or "{}"
    if isinstance(raw_c, str):
        try:
            parsed_c = json.loads(raw_c)
        except Exception:
            parsed_c = {}
    else:
        parsed_c = raw_c

    c_basis = c_row.get("classification_basis") or parsed_c.get("classification_basis") or ""
    c_genus = c_row.get("genus") or (parsed_c.get("step2_genus") or {}).get("genus_name") or ""
    step5_c = _step5_of(c_row)
    c_kind = step5_c.get("transformation_kind") or ""
    c_kind_status = step5_c.get("transformation_kind_status") or ""

    classification, case_id, reason = validate_pair_structural(
        x_label, x_basis, x_genus, x_kind, x_kind_status,
        resolved or candidate, c_basis, c_genus, c_kind, c_kind_status,
    )

    case_num = int(case_id[1]) if case_id and case_id[1:2].isdigit() else 0

    if classification == "rejected_by_structure":
        return case_num, resolved, reason
    elif classification == "preserved_by_structure":
        return BATCH_PRESERVED, resolved, reason
    else:
        return BATCH_UNVERIFIABLE, resolved, reason


def collect_pairs(
    requested_batches: set[int],
    ontology_state: dict,
    norm_index: dict,
) -> dict[int, list[tuple]]:
    """Return {batch_id: [(record_id, x_label, candidate_exact, reason), ...]}."""
    conn = _open_db()
    rows = conn.execute(
        """
        SELECT id, cluster_label, llm_raw_response
          FROM enrichment
         WHERE disjoint_with IS NOT NULL AND disjoint_with NOT IN ('[]', '')
         ORDER BY cluster_label, id
        """
    ).fetchall()
    conn.close()

    result: dict = defaultdict(list)

    for row in rows:
        x_label = row["cluster_label"]
        raw = row["llm_raw_response"] or "{}"
        if isinstance(raw, str):
            try:
                proposal = json.loads(raw)
            except Exception:
                continue
        else:
            proposal = raw

        candidates = proposal.get("disjoint_with") or []
        if not candidates:
            continue

        x_basis = proposal.get("classification_basis") or ""
        x_genus = (proposal.get("step2_genus") or {}).get("genus_name") or ""
        step5_x = proposal.get("step5_signature") or {}
        x_kind = step5_x.get("transformation_kind") or ""
        x_kind_status = step5_x.get("transformation_kind_status") or ""

        for candidate in candidates:
            batch_id, resolved, reason = classify_pair(
                x_label, x_basis, x_genus, x_kind, x_kind_status,
                candidate, ontology_state, norm_index,
            )
            if batch_id in requested_batches:
                result[batch_id].append((row["id"], x_label, candidate, resolved, reason))

    return result


# ---------------------------------------------------------------------------
# DB update
# ---------------------------------------------------------------------------

def _apply_removal(
    conn: sqlite3.Connection,
    record_id: int,
    candidate: str,
) -> tuple[bool, bool]:
    """Remove `candidate` from `disjoint_with` in both column and JSON.

    Returns (modified, list_now_empty).
    """
    row = conn.execute(
        "SELECT disjoint_with, disjointness_rationale, llm_raw_response FROM enrichment WHERE id = ?",
        (record_id,),
    ).fetchone()
    if row is None:
        return False, False

    # --- Column ---
    col_list: list = json.loads(row["disjoint_with"]) if row["disjoint_with"] else []
    if candidate not in col_list:
        return False, False  # already removed (idempotent)
    col_list.remove(candidate)

    # --- JSON ---
    raw = row["llm_raw_response"] or "{}"
    if isinstance(raw, str):
        try:
            proposal = json.loads(raw)
        except Exception:
            proposal = {}
    else:
        proposal = dict(raw)

    json_list: list = proposal.get("disjoint_with") or []
    if candidate in json_list:
        json_list.remove(candidate)
    proposal["disjoint_with"] = json_list

    list_empty = len(col_list) == 0

    # Clear rationale if list is now empty
    new_rationale = None if list_empty else row["disjointness_rationale"]
    if list_empty:
        proposal["disjointness_rationale"] = None

    conn.execute(
        """
        UPDATE enrichment
           SET disjoint_with          = ?,
               disjointness_rationale = ?,
               llm_raw_response       = ?,
               updated_at             = CURRENT_TIMESTAMP
         WHERE id = ?
        """,
        (
            json.dumps(col_list),
            new_rationale,
            json.dumps(proposal),
            record_id,
        ),
    )
    return True, list_empty


# ---------------------------------------------------------------------------
# Batch 0b helpers
# ---------------------------------------------------------------------------

def collect_batch_0b_pairs(
    ontology_state: dict,
    norm_index: dict,
) -> list[dict]:
    """
    Identify pairs currently annotated as C?:[unverifiable_class_not_in_db]
    in disjointness_rationale and confirm they are still absent from the DB.

    Returns list of dicts:
      record_id, x_label, candidate, original_drat
    """
    conn = _open_db()
    rows = conn.execute(
        """
        SELECT id, cluster_label, disjointness_rationale, llm_raw_response
          FROM enrichment
         WHERE disjointness_rationale LIKE '%[unverifiable_class_not_in_db]%'
         ORDER BY cluster_label, id
        """
    ).fetchall()
    conn.close()

    pairs = []
    for row in rows:
        drat = row["disjointness_rationale"] or ""
        # Extract every C? label annotated as not-in-db from the rationale prefix
        labels_in_rationale = [m.strip() for m in _CQ_NOT_IN_DB_TOKEN_RE.findall(drat)]
        if not labels_in_rationale:
            continue

        try:
            proposal = json.loads(row["llm_raw_response"] or "{}")
        except Exception:
            continue

        current_dw: list = proposal.get("disjoint_with") or []

        for c_label in labels_in_rationale:
            if c_label not in current_dw:
                continue  # already removed — idempotent skip

            # Re-confirm still absent (DB may have grown since the backfill)
            if ontology_state.get(c_label) is not None:
                continue
            norm_key = normalise_label(c_label)
            if norm_index.get(norm_key, ""):
                continue

            pairs.append({
                "record_id": row["id"],
                "x_label": row["cluster_label"],
                "candidate": c_label,
                "original_drat": drat,
            })

    return pairs


def _apply_removal_0b(
    conn: sqlite3.Connection,
    record_id: int,
    candidate: str,
) -> tuple[bool, bool]:
    """
    Remove `candidate` from disjoint_with and strip its C?: token from
    disjointness_rationale (or clear rationale entirely when list becomes empty).

    Returns (modified, list_now_empty).
    """
    row = conn.execute(
        "SELECT disjoint_with, disjointness_rationale, llm_raw_response "
        "FROM enrichment WHERE id = ?",
        (record_id,),
    ).fetchone()
    if row is None:
        return False, False

    col_list: list = json.loads(row["disjoint_with"]) if row["disjoint_with"] else []
    if candidate not in col_list:
        return False, False  # idempotent

    col_list.remove(candidate)

    try:
        proposal = json.loads(row["llm_raw_response"] or "{}")
    except Exception:
        proposal = {}

    json_list = list(proposal.get("disjoint_with") or [])
    if candidate in json_list:
        json_list.remove(candidate)
    proposal["disjoint_with"] = json_list

    list_empty = len(col_list) == 0
    current_drat = row["disjointness_rationale"] or ""

    if list_empty:
        new_drat = None
        proposal["disjointness_rationale"] = None
        s5 = proposal.get("step5_signature") or {}
        if "disjointness_rationale" in s5:
            s5["disjointness_rationale"] = None
            proposal["step5_signature"] = s5
    else:
        # Strip only the specific C?: token for this candidate
        token_re = re.compile(
            r"C\?: " + re.escape(candidate) + r" \[unverifiable_class_not_in_db\]\. "
        )
        new_drat = token_re.sub("", current_drat, count=1).strip()
        if "disjointness_rationale" in proposal:
            proposal["disjointness_rationale"] = new_drat
        s5 = proposal.get("step5_signature") or {}
        if "disjointness_rationale" in s5:
            s5["disjointness_rationale"] = new_drat
            proposal["step5_signature"] = s5

    conn.execute(
        """
        UPDATE enrichment
           SET disjoint_with          = ?,
               disjointness_rationale = ?,
               llm_raw_response       = ?,
               updated_at             = CURRENT_TIMESTAMP
         WHERE id = ?
        """,
        (
            json.dumps(col_list),
            new_drat,
            json.dumps(proposal, ensure_ascii=False),
            record_id,
        ),
    )
    return True, list_empty


def run_batch_0b(pairs: list[dict], dry_run: bool) -> int:
    """Execute or preview batch-0b removals. Returns count of pairs removed."""
    affected_records = len({p["record_id"] for p in pairs})

    print(f"\n{'='*60}")
    print("Batch 0b: second-pass referential cleanup")
    print("  Criterion: C?:[unverifiable_class_not_in_db] + still absent from DB")
    print(f"  Pairs identified: {len(pairs)}  (escaped original batch-0 run)")
    print(f"  Records affected: {affected_records}")
    if dry_run:
        print("  Mode: DRY-RUN (no changes)")
    print()

    if not pairs:
        print("  Nothing to do — no confirmed fabrications found.")
        return 0

    conn = _open_db() if not dry_run else None
    backed_up = False
    removed = 0

    for p in pairs:
        display = (
            f"  [{p['x_label']}] ✕ '{p['candidate']}'  "
            f"| confirmed absent from DB"
        )

        if dry_run:
            print(display)
            removed += 1
            continue

        if not backed_up:
            print("  Creating backup...")
            _backup_db()
            backed_up = True

        modified, emptied = _apply_removal_0b(conn, p["record_id"], p["candidate"])
        if modified:
            suffix = " [list empty → rationale cleared]" if emptied else ""
            print(f"  REMOVED  {display}{suffix}")
            removed += 1
        else:
            print(f"  SKIP (already absent)  [{p['x_label']}] '{p['candidate']}'")

    if conn:
        conn.commit()
        conn.close()

    action = "Would remove" if dry_run else "Removed"
    print(f"\n  → {action} {removed} pair(s).")
    print(f"    (These are confirmed fabrications that escaped the original "
          f"batch-0 run.)")
    return removed


# ---------------------------------------------------------------------------
# Batch execution
# ---------------------------------------------------------------------------

def run_batch(
    batch_id: int,
    pairs: list[tuple],
    dry_run: bool,
    interactive: bool = False,
) -> int:
    """Execute or preview removal for a single batch. Returns removal count."""
    label = _BATCH_LABELS[batch_id]
    print(f"\n{'='*60}")
    print(f"Batch {batch_id}: {label}")
    print(f"  Pairs identified: {len(pairs)}")
    if dry_run:
        print("  Mode: DRY-RUN (no changes)")
    print()

    if not pairs:
        print("  Nothing to do.")
        return 0

    conn = _open_db() if not dry_run else None
    backed_up = False
    removed = 0

    for record_id, x_label, candidate, resolved, reason in pairs:
        resolved_note = f" (resolved→ '{resolved}')" if resolved and resolved != candidate else ""
        display = f"  [{x_label}] ✕ '{candidate}'{resolved_note}  | {reason}"

        if interactive and not dry_run:
            print(display)
            answer = input("    Remove this pair? [y/N] ").strip().lower()
            if answer != "y":
                print("    Skipped.")
                continue

        if dry_run:
            print(display)
            removed += 1
            continue

        # Apply
        if not backed_up:
            print("  Creating backup...")
            _backup_db()
            backed_up = True

        modified, emptied = _apply_removal(conn, record_id, candidate)
        if modified:
            suffix = " [list now empty → rationale cleared]" if emptied else ""
            print(f"  REMOVED  {display}{suffix}")
            removed += 1
        else:
            print(f"  SKIP (already absent)  [{x_label}] '{candidate}'")

    if conn:
        conn.commit()
        conn.close()

    action = "Would remove" if dry_run else "Removed"
    print(f"\n  → {action} {removed} pair(s) in batch {batch_id}.")
    return removed


# ---------------------------------------------------------------------------
# Batch 2 deferred message
# ---------------------------------------------------------------------------

_BATCH2_MESSAGE = """\
Batch 2 — DEFERRED

  Batch 2 covers pairs rejected by Case 2: same genus, both functional bases,
  no declared function disjunctions in the current ontology.

  These 81+ pairs represent disjointness assertions that CANNOT be validated
  under the current ontology because Case 2 is dormant — the COPI function
  hierarchy has 0 declared OWL disjunctions between function classes.

  Removal will be safe once function-level disjunctions are added (planned
  post-Leva 3 with Régis). At that point:
    - Re-run audit_disjointness.py
    - Case 2 will activate for pairs whose functions ARE declared disjoint
    - Remaining Case-2 pairs can be removed with this batch

  No changes made.
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

_VALID_BATCH_IDS = {"0", "0b", "2", "3", "4", "5"}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove invalid disjointness pairs from enrichment.db.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--batch", type=str, action="append", dest="batches",
        metavar="{0,0b,2,3,4,5}",
        help="Batch(es) to process (repeatable). See module docstring for details.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="List pairs to remove without modifying the DB (default).",
    )
    parser.add_argument(
        "--apply", dest="dry_run", action="store_false",
        help="Apply removals (auto-backup before first write).",
    )
    args = parser.parse_args()

    if not args.batches:
        parser.error("Specify at least one --batch. Use --help for details.")

    for b in args.batches:
        if b not in _VALID_BATCH_IDS:
            parser.error(
                f"invalid --batch '{b}': choose from "
                + ", ".join(sorted(_VALID_BATCH_IDS))
            )

    run_0b = "0b" in args.batches
    numeric_batches = sorted(int(b) for b in args.batches if b != "0b")

    # Batch 2 is deferred — handle immediately and remove from list
    if 2 in numeric_batches:
        print(_BATCH2_MESSAGE)
        numeric_batches = [b for b in numeric_batches if b != 2]
        if not numeric_batches and not run_0b:
            sys.exit(0)

    print("Loading ontology state...", flush=True)
    ontology_state = build_ontology_state()
    norm_index = build_normalised_index(ontology_state)

    total_removed = 0

    # ── Batch 0b ──────────────────────────────────────────────────────────
    if run_0b:
        print("Collecting batch-0b pairs (C?:[unverifiable_class_not_in_db])...",
              flush=True)
        pairs_0b = collect_batch_0b_pairs(ontology_state, norm_index)
        total_removed += run_batch_0b(pairs_0b, args.dry_run)

    # ── Numeric batches (0, 2, 3, 4, 5) ──────────────────────────────────
    if numeric_batches:
        print(f"Collecting pairs for batch(es) {numeric_batches}...", flush=True)
        requested = set(numeric_batches)
        batch_pairs = collect_pairs(requested, ontology_state, norm_index)

        total_identified = sum(len(v) for v in batch_pairs.values())
        print(f"Total pairs identified: {total_identified}")

        for batch_id in numeric_batches:
            pairs = batch_pairs.get(batch_id, [])
            interactive = (batch_id == 4)
            total_removed += run_batch(
                batch_id, pairs, args.dry_run, interactive=interactive
            )

    n_batches = len(args.batches)
    print(f"\n{'='*60}")
    action = "Would remove" if args.dry_run else "Removed"
    print(f"{action} {total_removed} pair(s) across {n_batches} batch(es).")
    if args.dry_run and total_removed:
        print("Re-run with --apply to execute.")


if __name__ == "__main__":
    main()
