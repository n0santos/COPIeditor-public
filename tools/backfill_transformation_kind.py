#!/usr/bin/env python3
"""
Backfill transformation_kind / transformation_kind_status / proposed_kind_rationale
into existing enrichment records that have a transformation text but no transformation_kind.

Each record gets ONE isolated LLM call with a minimal prompt — no full enrichment.
Input: ~150 tokens. Output: ~50 tokens. Estimated total: ~63,000 tokens for 313 records
≈ $0.20 at Claude Sonnet 4 rates (well within one batch budget).

Usage:
    python tools/backfill_transformation_kind.py --dry-run   # process first 10, print only
    python tools/backfill_transformation_kind.py             # apply to all pending records

Idempotent: records already having transformation_kind are skipped.
A DB backup is created before the full run.
"""

import argparse
import asyncio
import json
import os
import shutil
import sqlite3
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "enrichment"))

from enrichment_service import (  # noqa: E402
    ANTHROPIC_API_URL,
    DEFAULT_MODEL,
    TRANSFORMATION_KINDS_CONTROLLED,
    _validate_transformation_kind,
    call_llm,
)

DB_PATH = PROJECT_ROOT / "data" / "enrichment.db"

_VOCAB_BLOCK = "\n".join(
    f"  - {t}" for t in sorted(TRANSFORMATION_KINDS_CONTROLLED)
)

_SYSTEM_PROMPT = """\
You are an ontology engineer. You will be given a free-text description of an ontological
transformation performed by an industrial process, and you must classify it using a
controlled vocabulary or propose a new term if truly necessary.

Canonical vocabulary (17 terms):
""" + _VOCAB_BLOCK + """

Classification policy:
1. Prefer a canonical term even if the match is approximate.
2. If multiple canonical terms apply, pick the one capturing the primary ontological
   identity (e.g. a centrifugal pump = pressure_increase, not fluid_transport).
3. Propose a new term only when NO canonical term fits, even approximately.
   New terms: snake_case, <= 50 chars, verb+object or nominal_descriptive format.
   When proposing, explain why the 2-3 closest canonical terms were rejected.

Return ONLY valid JSON — no markdown, no preamble:
{
  "transformation_kind": "<canonical or new term>",
  "transformation_kind_status": "controlled | proposed",
  "proposed_kind_rationale": "<null when controlled; rationale when proposed>"
}"""


def _user_prompt(transformation: str) -> str:
    return f'Classify the following transformation:\n\n"{transformation}"'


def load_pending(conn: sqlite3.Connection) -> list[dict]:
    """Return records that have a transformation but no transformation_kind yet."""
    rows = conn.execute(
        "SELECT id, cluster_label, llm_raw_response FROM enrichment"
    ).fetchall()
    pending = []
    for row in rows:
        try:
            p = json.loads(row["llm_raw_response"] or "{}")
        except Exception:
            continue
        sig = p.get("step5_signature") or {}
        transformation = (sig.get("transformation") or "").strip()
        if not transformation:
            continue
        if sig.get("transformation_kind"):
            continue  # already filled
        pending.append({
            "id":             row["id"],
            "cluster_label":  row["cluster_label"],
            "transformation": transformation,
            "proposal":       p,
        })
    return pending


async def classify_one(
    transformation: str,
    api_key: str,
    model: str,
) -> dict:
    """Call LLM to classify a single transformation string. Returns the parsed dict."""
    result, _, _, _, _, _ = await call_llm(
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=_user_prompt(transformation),
        api_key=api_key,
        model=model,
        temperature=0,
    )
    return result


def apply_classification(record: dict, classification: dict) -> dict:
    """
    Merge classification result into the record's proposal dict.
    Returns the updated proposal.
    """
    proposal = record["proposal"]
    sig = proposal.setdefault("step5_signature", {})
    sig["transformation_kind"]        = classification.get("transformation_kind", "")
    sig["transformation_kind_status"] = classification.get("transformation_kind_status", "proposed")
    sig["proposed_kind_rationale"]    = classification.get("proposed_kind_rationale")
    # Run the same validator used in the live pipeline
    _validate_transformation_kind(proposal)
    return proposal


def save_classification(conn: sqlite3.Connection, record_id: int, updated_proposal: dict) -> None:
    conn.execute(
        "UPDATE enrichment SET llm_raw_response = ? WHERE id = ?",
        (json.dumps(updated_proposal, ensure_ascii=False), record_id),
    )


async def run(dry_run: bool, api_key: str, model: str, limit: int | None) -> None:
    if not DB_PATH.exists():
        sys.exit(f"Database not found: {DB_PATH}")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    pending = load_pending(conn)
    print(f"Records with transformation but no transformation_kind: {len(pending)}")

    if not pending:
        print("Nothing to backfill.")
        conn.close()
        return

    targets = pending[:limit] if limit else pending

    # Cost estimate
    est_input  = len(targets) * 180
    est_output = len(targets) * 50
    est_cost   = (est_input * 3.00 + est_output * 15.00) / 1_000_000
    print(f"Targets for this run  : {len(targets)}")
    print(f"Estimated tokens      : ~{est_input + est_output:,}  (${est_cost:.3f})")

    if dry_run:
        print("\n[dry-run] Processing first 10 records (no writes):\n")
        targets = targets[:10]
    else:
        bak = DB_PATH.with_suffix(f".db.bak.{date.today().strftime('%Y%m%d')}")
        shutil.copy2(DB_PATH, bak)
        print(f"\nBackup: {bak}")
        print()

    updated = 0
    proposed = 0
    errors = 0

    for rec in targets:
        label = rec["cluster_label"]
        try:
            classification = await classify_one(rec["transformation"], api_key, model)
            updated_proposal = apply_classification(rec, classification)

            kind   = (updated_proposal.get("step5_signature") or {}).get("transformation_kind", "?")
            status = (updated_proposal.get("step5_signature") or {}).get("transformation_kind_status", "?")
            marker = " [PROPOSED]" if status == "proposed" else ""
            print(f"  {'(dry) ' if dry_run else ''}{label!r:40s}  →  {kind}{marker}")

            if not dry_run:
                save_classification(conn, rec["id"], updated_proposal)

            updated += 1
            if status == "proposed":
                proposed += 1

        except Exception as exc:
            errors += 1
            print(f"  ERROR  {label!r}: {exc}")

    if not dry_run:
        conn.commit()

    conn.close()

    print()
    print(f"Processed : {updated}")
    print(f"Proposed  : {proposed}  ({round(100*proposed/updated, 1) if updated else 0} %)")
    print(f"Errors    : {errors}")
    if not dry_run:
        print("Changes committed to database.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Classify first 10 pending records without writing to DB")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"LLM model (default: {DEFAULT_MODEL})")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        sys.exit("Error: ANTHROPIC_API_KEY environment variable is not set.")

    limit = 10 if args.dry_run else None
    asyncio.run(run(dry_run=args.dry_run, api_key=api_key, model=args.model, limit=limit))


if __name__ == "__main__":
    main()
