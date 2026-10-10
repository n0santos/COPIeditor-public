#!/usr/bin/env python3
"""
Regression harness for the COPI enrichment pipeline.

Usage:
    python tests/regression.py snapshot                    # create/overwrite all baselines
    python tests/regression.py compare                     # diff current output vs baselines
    python tests/regression.py update-baseline [slug ...]  # update specific baselines

Both snapshot and compare call the LLM at temperature=0 so results are
deterministic.  Baseline JSON (tests/baselines/{slug}.json) stores the full
proposal minus volatile fields (id, token counts, cost).  The *compare*
command extracts structural fields from both saved baseline and current run,
then diffs them path-by-path.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "enrichment"))

import enrichment_service as _svc  # noqa: E402
from enrichment_service import enrich_cluster  # noqa: E402

# ---------------------------------------------------------------------------
# Deterministic patch: force temperature=0 for all LLM calls in this process.
# ---------------------------------------------------------------------------
_orig_call_llm = _svc.call_llm


async def _call_llm_t0(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    model: str = _svc.DEFAULT_MODEL,
    temperature: float | None = None,
):
    return await _orig_call_llm(system_prompt, user_prompt, api_key, model, temperature=0)


_svc.call_llm = _call_llm_t0

# ---------------------------------------------------------------------------

BASELINES_DIR = Path(__file__).parent / "baselines"

TERMS = [
    {"label": "control valve",    "slug": "control_valve"},
    {"label": "ball valve",       "slug": "ball_valve"},
    {"label": "centrifugal pump", "slug": "centrifugal_pump"},
    {"label": "isolation valve",  "slug": "isolation_valve"},  # role contextual; esperado: is_role=true, bearer_class=Valve
    # wellbore: axiom_mode alternates equivalent/necessary even at temp=0 (genuinely borderline)
    {"label": "wellbore",         "slug": "wellbore",          "skip_fields": {"axiom_mode"}},
]

# Fields added by enrich_cluster that carry no semantic signal.
VOLATILE_FIELDS = frozenset({"id", "input_tokens", "output_tokens", "estimated_cost_usd"})

# Paths highlighted in compare output when they change (most semantically critical).
KEY_FIELDS = frozenset({
    "axiom_mode",
    "step2.genus_bfo_root",
    "step5.transformation_kind",
    "step5.transformation_kind_status",
})


# ---------------------------------------------------------------------------
# Structural extraction
# ---------------------------------------------------------------------------

def _extract_structural(proposal: dict) -> dict:
    """
    Extract the fields that are stable across consecutive LLM calls at temperature=0.

    Empirically, even at temperature=0 the Anthropic API is not fully deterministic
    (Anthropic documents this limitation).  After measuring consecutive runs we
    found that only these fields are reliably stable:
      - axiom_mode      (3-value enum; captures the same downstream decision as
                         classification_basis but is more stable — centrifugal_pump
                         alternates 'constructive'/'both' while axiom_mode stays
                         'necessary' in both cases)
      - step1 names     (function_name / process_name — proper nouns, stable)
      - step2 genus     (genus_name / bfo_root / enriched — proper noun + 7-value enum)

    Fields excluded because they vary between consecutive runs without any code change:
      classification_basis (centrifugal_pump: 'constructive' ↔ 'both'),
      step3 differentia / distinguishes_from / genus_already_provides,
      step4 parts list, step5 free-text transformation, disjoint_with, confidence scores.
      is_role / role_detection: removed from the pipeline (see docs/findings/role_detection_audit.md).
      divergence_flags: empirically unstable — control_valve and ball_valve alternate T-types
        between consecutive calls; full divergence_flags are preserved in the saved baseline
        JSON for manual comparison.

    transformation_kind is included: it is a controlled-vocabulary enum and is expected to
    be stable at temperature=0 for the baseline terms (control_valve→flow_regulation,
    ball_valve→flow_regulation, centrifugal_pump→pressure_increase,
    isolation_valve→flow_isolation).

    Per-term skip_fields (set in TERMS): additional fields excluded for specific
    terms known to be borderline at the top level —
      wellbore.axiom_mode: alternates 'equivalent' ↔ 'necessary' at temperature=0.

    The full proposal JSON is still saved in the baseline for manual inspection.
    """
    step1 = proposal.get("step1_function") or {}
    step2 = proposal.get("step2_genus") or {}
    step5 = proposal.get("step5_signature") or {}

    return {
        "axiom_mode": proposal.get("axiom_mode"),
        "step1": {
            "function_name": step1.get("function_name"),
            "process_name":  step1.get("process_name"),
        },
        "step2": {
            "genus_name":     step2.get("genus_name"),
            "genus_bfo_root": step2.get("genus_bfo_root"),
            "genus_enriched": step2.get("genus_enriched"),
        },
        "step5": {
            "transformation_kind":        step5.get("transformation_kind"),
            "transformation_kind_status": step5.get("transformation_kind_status"),
        },
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def strip_volatile(obj):
    if isinstance(obj, dict):
        return {k: strip_volatile(v) for k, v in obj.items() if k not in VOLATILE_FIELDS}
    if isinstance(obj, list):
        return [strip_volatile(v) for v in obj]
    return obj


def get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        sys.exit("Error: ANTHROPIC_API_KEY environment variable is not set.")
    return key


async def run_term(label: str, api_key: str) -> dict:
    print(f"  enriching '{label}' ...", flush=True)
    proposal = await enrich_cluster(label, api_key)
    return strip_volatile(proposal)


# ---------------------------------------------------------------------------
# Structural diff
# ---------------------------------------------------------------------------

def diff_objects(old, new, path: str = "") -> list[dict]:
    """
    Recursive path-by-path diff.  Returns [{path, old, new}, ...] for every
    leaf that differs, including added/removed keys and list items.
    """
    changes: list[dict] = []

    if isinstance(old, dict) and isinstance(new, dict):
        for k in sorted(set(old) | set(new)):
            child = f"{path}.{k}" if path else k
            if k not in old:
                changes.append({"path": child, "old": None, "new": new[k]})
            elif k not in new:
                changes.append({"path": child, "old": old[k], "new": None})
            else:
                changes.extend(diff_objects(old[k], new[k], child))

    elif isinstance(old, list) and isinstance(new, list):
        for i, (ov, nv) in enumerate(zip(old, new)):
            changes.extend(diff_objects(ov, nv, f"{path}[{i}]"))
        for i in range(len(new), len(old)):
            changes.append({"path": f"{path}[{i}]", "old": old[i], "new": None})
        for i in range(len(old), len(new)):
            changes.append({"path": f"{path}[{i}]", "old": None, "new": new[i]})

    else:
        if old != new:
            changes.append({"path": path, "old": old, "new": new})

    return changes


def _fmt_val(v) -> str:
    if v is None:
        return "<missing>"
    if isinstance(v, (dict, list)):
        s = json.dumps(v, ensure_ascii=False)
        return (s[:200] + " ...") if len(s) > 200 else s
    return repr(v)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

async def cmd_snapshot(slugs: list[str] | None = None) -> None:
    api_key = get_api_key()
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)
    targets = [t for t in TERMS if not slugs or t["slug"] in slugs]

    print(f"Snapshotting {len(targets)} term(s) at temperature=0...\n")
    for term in targets:
        proposal = await run_term(term["label"], api_key)
        out_path = BASELINES_DIR / f"{term['slug']}.json"
        out_path.write_text(json.dumps(proposal, indent=2, ensure_ascii=False))
        print(f"  saved  {out_path.relative_to(PROJECT_ROOT)}")

    print("\nSnapshot complete.")


async def cmd_compare() -> int:
    api_key = get_api_key()
    total_diffs = 0

    print(f"Comparing {len(TERMS)} term(s) against baselines (temperature=0)...\n")

    for term in TERMS:
        baseline_path = BASELINES_DIR / f"{term['slug']}.json"
        label = term["slug"]

        if not baseline_path.exists():
            print(f"[{label}] MISSING baseline — run 'snapshot' first.")
            total_diffs += 1
            continue

        baseline_full = json.loads(baseline_path.read_text())
        current_full  = await run_term(term["label"], api_key)

        skip = set(term.get("skip_fields") or set())
        baseline_struct = {k: v for k, v in _extract_structural(baseline_full).items() if k not in skip}
        current_struct  = {k: v for k, v in _extract_structural(current_full).items()  if k not in skip}
        changes = diff_objects(baseline_struct, current_struct)

        if not changes:
            print(f"[{label}] OK")
            continue

        key_changes = [c for c in changes if c["path"] in KEY_FIELDS]
        key_note = f"  *** {len(key_changes)} KEY FIELD(S) ***" if key_changes else ""
        print(f"[{label}] {len(changes)} difference(s){key_note}")
        for c in changes:
            marker = " ***" if c["path"] in KEY_FIELDS else ""
            print(f"  {c['path']}{marker}")
            print(f"    old: {_fmt_val(c['old'])}")
            print(f"    new: {_fmt_val(c['new'])}")

        total_diffs += len(changes)

    print()
    if total_diffs == 0:
        print("All baselines match.")
        return 0
    else:
        print(f"{total_diffs} total structural difference(s) found.")
        return 1


async def cmd_update_baseline(slugs: list[str]) -> None:
    await cmd_snapshot(slugs if slugs else None)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="COPI enrichment regression harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("snapshot",
                   help="Create/overwrite baselines for all 5 terms (temperature=0)")
    sub.add_parser("compare",
                   help="Re-run enrichment and diff structural fields against baselines")
    upd = sub.add_parser("update-baseline",
                          help="Regenerate baseline(s) for specific term(s)")
    upd.add_argument("slugs", nargs="*",
                     metavar="slug",
                     help="Term slug(s) to update (all 5 if omitted).  "
                          "Valid: control_valve, ball_valve, centrifugal_pump, riser, wellbore")

    args = parser.parse_args()

    if args.cmd == "snapshot":
        asyncio.run(cmd_snapshot())
    elif args.cmd == "compare":
        sys.exit(asyncio.run(cmd_compare()))
    elif args.cmd == "update-baseline":
        asyncio.run(cmd_update_baseline(args.slugs))


if __name__ == "__main__":
    main()
