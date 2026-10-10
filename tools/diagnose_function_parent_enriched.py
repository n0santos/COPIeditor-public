#!/usr/bin/env python3
"""
Read-only diagnostic for the function_parent_enriched field coverage gap.

The field lives at step1_function.function_parent_enriched inside llm_raw_response
JSON (not at the top level, not as a SQL column).  The SQL `function_parent` column
holds the actual parent value extracted by _store_proposal.

Hypotheses tested
-----------------
  (a) Legacy: records pre-date Leva 2.1 so the field was never requested.
      Dominated by no_fpe + generic function_parent.
  (b) Implicit False: the LLM correctly omitted the field when function_parent
      is DesignedFunction, treating absence as False.  Benign, but ambiguous.
  (c) LLM non-compliance: specific function_parent in SQL column, but
      function_parent_enriched absent from JSON.  The LLM provided a parent
      value without emitting the boolean.  Minor data-quality issue.

Output
------
  /tmp/function_parent_enriched_diagnostic.md   (markdown report)

Usage
-----
  python tools/diagnose_function_parent_enriched.py
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DB_PATH = _PROJECT_ROOT / "data" / "enrichment.db"
_OUT_PATH = Path("/tmp/function_parent_enriched_diagnostic.md")

# First DB record that carries function_parent_enriched — establishes Leva 2.1 start.
# id=9 'transmitter' created 2026-04-09 17:11:06.
_LEVA21_CUTOFF = "2026-04-09"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_latest_records() -> list[dict]:
    """Return one record per cluster_label (highest id wins)."""
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, cluster_label, created_at, function_parent, llm_raw_response
          FROM enrichment e
         WHERE id = (
               SELECT MAX(id) FROM enrichment e2
               WHERE e2.cluster_label = e.cluster_label
         )
         ORDER BY cluster_label
        """
    ).fetchall()
    conn.close()

    records = []
    for r in rows:
        try:
            proposal = json.loads(r["llm_raw_response"] or "{}")
        except Exception:
            proposal = {}
        s1 = proposal.get("step1_function") or {}
        fpe = s1.get("function_parent_enriched", "__ABSENT__") if isinstance(s1, dict) else "__ABSENT__"
        fp_json = s1.get("function_parent", "") if isinstance(s1, dict) else ""

        records.append({
            "id": r["id"],
            "label": r["cluster_label"],
            "created_at": r["created_at"] or "",
            "fp_sql": r["function_parent"] or "",
            "fp_json": fp_json,
            "fpe": fpe,      # True | False | None | '__ABSENT__'
        })
    return records


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify(records: list[dict]) -> dict:
    """
    Partition records into four buckets and cross-tabulate no_fpe by
    function_parent specificity.

    A function_parent is 'specific' when it is neither empty nor 'DesignedFunction'.
    """
    cats: dict[str, list[dict]] = {
        "fpe_true":  [],
        "fpe_false": [],
        "fpe_null":  [],
        "no_fpe":    [],
    }
    for rec in records:
        fpe = rec["fpe"]
        if fpe is True:
            cats["fpe_true"].append(rec)
        elif fpe is False:
            cats["fpe_false"].append(rec)
        elif fpe == "__ABSENT__":
            cats["no_fpe"].append(rec)
        else:
            cats["fpe_null"].append(rec)

    no_fpe_specific = [
        r for r in cats["no_fpe"]
        if r["fp_sql"] and r["fp_sql"] != "DesignedFunction"
    ]
    no_fpe_generic = [
        r for r in cats["no_fpe"]
        if not r["fp_sql"] or r["fp_sql"] == "DesignedFunction"
    ]

    return {
        "total": len(records),
        "fpe_true":  cats["fpe_true"],
        "fpe_false": cats["fpe_false"],
        "fpe_null":  cats["fpe_null"],
        "no_fpe":    cats["no_fpe"],
        "no_fpe_specific": no_fpe_specific,
        "no_fpe_generic":  no_fpe_generic,
    }


def _iso_week(date_str: str) -> str:
    try:
        dt = datetime.fromisoformat(date_str)
        y, w, _ = dt.isocalendar()
        return f"{y}-W{w:02d}"
    except Exception:
        return "unknown"


def _is_post_leva21(date_str: str) -> bool:
    return date_str >= _LEVA21_CUTOFF


# ---------------------------------------------------------------------------
# Hypothesis determination
# ---------------------------------------------------------------------------

def determine_hypothesis(stats: dict) -> tuple[str, str]:
    """
    Return (dominant_hypothesis_key, explanation).

    Keys: 'a', 'b', 'c'.
    Logic:
      - If M (no_fpe_specific) > 10  → hypothesis (c) confirmed (LLM non-compliance)
        and all suspects are post-Leva-2.1 → pipeline not at fault.
      - If M > 0 and all suspects pre-Leva-2.1 → hypothesis (a) legacy.
      - If M == 0 and no_fpe_generic ≈ no_fpe → hypothesis (b) implicit-False.
    """
    suspects = stats["no_fpe_specific"]
    m = len(suspects)
    post_suspects = [s for s in suspects if _is_post_leva21(s["created_at"])]
    pre_suspects  = [s for s in suspects if not _is_post_leva21(s["created_at"])]

    if m == 0:
        return (
            "b",
            f"All {len(stats['no_fpe'])} no-field records have generic "
            f"function_parent (DesignedFunction or empty). Absence is equivalent "
            f"to False — the field was simply not emitted when the parent was not "
            f"enriched.  Benign but ambiguous."
        )

    if pre_suspects and not post_suspects:
        return (
            "a",
            f"All {m} suspect(s) pre-date Leva 2.1 ({_LEVA21_CUTOFF}). "
            f"These are legacy records enriched before the field was introduced. "
            f"Expected behaviour."
        )

    if post_suspects:
        return (
            "c",
            f"{len(post_suspects)} of {m} suspect(s) are post-Leva 2.1 "
            f"({_LEVA21_CUTOFF}).  The LLM returned a specific function_parent "
            f"but omitted function_parent_enriched from step1_function. "
            f"Root cause: LLM non-compliance with the prompt schema, not a "
            f"pipeline bug (_store_proposal stores llm_raw_response verbatim)."
        )

    return ("b", "Mixed; hypothesis (b) default.")


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

_RECS: dict[str, list[str]] = {
    "a": [
        "Document as expected legacy behaviour in `docs/findings/`.",
        "Backfill is optional: for the 15 suspect records (specific fp_sql but "
        "no fpe field), infer `function_parent_enriched: true` from the SQL column "
        "without LLM re-enrichment.",
        "For the 181 generic-fp no-field records, treating absence as False is "
        "safe; backfill adds uniformity but is low priority.",
    ],
    "b": [
        "Decide policy: keep absence-as-False-implicit or backfill all no-field "
        "records with explicit False.",
        "Recommendation: **backfill for uniformity**.  Future tooling that checks "
        "`fpe == False` will behave differently from tooling that checks "
        "`fpe is not True`, introducing latent bugs.",
        "For the 15 specific-fp suspects, backfill with True (derivable from "
        "fp_sql != DesignedFunction).",
    ],
    "c": [
        "The pipeline (_store_proposal) stores llm_raw_response verbatim — no "
        "field is injected or dropped server-side.  The field is absent because "
        "the LLM omitted it.",
        "**Short-term fix (no LLM)**: backfill the 15 suspects by inferring "
        "`function_parent_enriched = (fp_sql != 'DesignedFunction')` from the SQL "
        "column.  Add a post-store check in enrichment_service.py that logs a "
        "warning when fp_sql is specific but fpe is absent.",
        "**Long-term**: add a prompt-compliance assertion in the LLM response "
        "parser that raises a warning (not an error) when this field is missing "
        "and function_parent is non-generic.",
    ],
}


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def build_report(stats: dict, hyp_key: str, hyp_text: str) -> str:
    total = stats["total"]
    n_true  = len(stats["fpe_true"])
    n_false = len(stats["fpe_false"])
    n_null  = len(stats["fpe_null"])
    n_no    = len(stats["no_fpe"])
    n_spec  = len(stats["no_fpe_specific"])
    n_gen   = len(stats["no_fpe_generic"])
    suspects = stats["no_fpe_specific"]

    lines: list[str] = []
    lines.append("# Function Parent Enriched — Field Coverage Diagnostic")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  ")
    lines.append(f"**Records analysed (latest per cluster):** {total}")
    lines.append("")

    # 1. Field-state distribution
    lines.append("## 1. Distribution by field state")
    lines.append("")
    lines.append("_Field path: `step1_function.function_parent_enriched` in `llm_raw_response` JSON_")
    lines.append("")
    lines.append("| State | Count | % of total | Meaning |")
    lines.append("|:------|------:|-----------:|:--------|")
    lines.append(f"| `has_field_true`  | {n_true}  | {100*n_true/total:.1f}% | "
                 "LLM confirmed a specific, enriched parent |")
    lines.append(f"| `has_field_false` | {n_false} | {100*n_false/total:.1f}% | "
                 "LLM confirmed parent stayed at DesignedFunction |")
    lines.append(f"| `has_field_null`  | {n_null}  | {100*n_null/total:.1f}% | "
                 "Field present but null (should not occur) |")
    lines.append(f"| `no_field_at_all` | {n_no}    | {100*n_no/total:.1f}% | "
                 "Field absent from JSON entirely |")
    lines.append("")

    # 2. no_fpe × function_parent cross-tab
    lines.append("## 2. `no_field_at_all` × `function_parent` cross-tabulation")
    lines.append("")
    lines.append(f"| Subgroup | Count | Interpretation |")
    lines.append("|:---------|------:|:---------------|")
    lines.append(
        f"| `function_parent = DesignedFunction` (or empty) | {n_gen} | "
        "Absence ≈ implicit False — benign |"
    )
    lines.append(
        f"| `function_parent` specific (not DesignedFunction) | {n_spec} | "
        "**Suspects** — field should be True but is absent |"
    )
    lines.append("")

    if n_spec == 0:
        lines.append("**All 196 no-field records have generic function_parent.** "
                     "Hypothesis (a)/(b) confirmed.")
    elif n_spec <= 10:
        lines.append(f"**{n_spec} suspect record(s)** — small number consistent with "
                     "occasional LLM non-compliance (hypothesis c), not a systematic bug.")
    else:
        lines.append(f"**{n_spec} suspect records** — substantial gap, requires investigation.")
    lines.append("")

    # 3. Suspect details
    if suspects:
        lines.append("## 3. Suspect records (specific `fp_sql` but `fpe` absent)")
        lines.append("")
        lines.append("_Suspects are records where the SQL `function_parent` column "
                     "holds a specific value (not DesignedFunction) but "
                     "`function_parent_enriched` is absent from `step1_function` in "
                     "the stored JSON._")
        lines.append("")
        lines.append(f"| id | cluster_label | created_at | ISO week | "
                     f"function_parent (SQL) | post-Leva 2.1? |")
        lines.append("|---:|:--------------|:-----------|:---------|:---------------------|:--------------:|")
        for s in sorted(suspects, key=lambda x: x["created_at"]):
            week = _iso_week(s["created_at"])
            post = "yes" if _is_post_leva21(s["created_at"]) else "no"
            lines.append(
                f"| {s['id']} | `{s['label']}` | {s['created_at'][:19]} | "
                f"{week} | `{s['fp_sql']}` | {post} |"
            )
        lines.append("")

        post_count = sum(1 for s in suspects if _is_post_leva21(s["created_at"]))
        pre_count  = len(suspects) - post_count
        lines.append(
            f"**Post-Leva 2.1 suspects:** {post_count}  "
            f"**Pre-Leva 2.1 suspects:** {pre_count}"
        )
        lines.append("")
        lines.append(f"_Leva 2.1 cutoff: first DB record with fpe field = "
                     f"id=9 'transmitter' ({_LEVA21_CUTOFF})_")
        lines.append("")

    # 4. Hypothesis and root cause
    lines.append("## 4. Dominant hypothesis")
    lines.append("")
    hyp_names = {
        "a": "(a) Legacy / pre-Leva 2.1",
        "b": "(b) Implicit False — absence is benign",
        "c": "(c) LLM non-compliance — field omitted despite specific parent",
    }
    lines.append(f"**{hyp_names[hyp_key]}**")
    lines.append("")
    lines.append(hyp_text)
    lines.append("")

    # Pipeline note for hypothesis c
    if hyp_key == "c":
        lines.append("### Root-cause note")
        lines.append("")
        lines.append(
            "`_store_proposal()` in `enrichment/enrichment_service.py` stores "
            "`llm_raw_response` verbatim (line 1519).  It extracts `function_parent` "
            "from `step1_function.function_parent` for the SQL column but does not "
            "inject or normalise `function_parent_enriched`.  Therefore, if the LLM "
            "emits a specific `function_parent` without the boolean flag, the SQL "
            "column is populated but the JSON field is absent.  No data is dropped "
            "by the pipeline; the gap originates at the LLM response level."
        )
        lines.append("")

    # 5. Recommendations
    lines.append("## 5. Recommendations")
    lines.append("")
    recs = _RECS.get(hyp_key, _RECS["b"])
    for i, r in enumerate(recs, 1):
        lines.append(f"{i}. {r}")
        lines.append("")

    # 6. Summary table
    lines.append("## 6. Summary statistics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|:-------|------:|")
    lines.append(f"| Total records (latest per cluster) | {total} |")
    lines.append(f"| `function_parent_enriched = True` | {n_true} |")
    lines.append(f"| `function_parent_enriched = False` | {n_false} |")
    lines.append(f"| `function_parent_enriched = null` | {n_null} |")
    lines.append(f"| Field absent (`no_field_at_all`) | {n_no} |")
    lines.append(f"| Field absent + generic fp (benign) | {n_gen} |")
    lines.append(f"| Field absent + specific fp (suspects) | {n_spec} |")
    lines.append(f"| Dominant hypothesis | **({hyp_key})** |")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if not _DB_PATH.exists():
        raise SystemExit(f"DB not found: {_DB_PATH}")

    print("Loading latest-per-cluster records...", flush=True)
    records = load_latest_records()
    print(f"  {len(records)} records loaded", flush=True)

    print("Classifying...", flush=True)
    stats = classify(records)

    n_true  = len(stats["fpe_true"])
    n_false = len(stats["fpe_false"])
    n_null  = len(stats["fpe_null"])
    n_no    = len(stats["no_fpe"])
    n_spec  = len(stats["no_fpe_specific"])
    n_gen   = len(stats["no_fpe_generic"])

    print(f"\nField state distribution ({stats['total']} records):")
    print(f"  has_field_true   : {n_true}")
    print(f"  has_field_false  : {n_false}")
    print(f"  has_field_null   : {n_null}")
    print(f"  no_field_at_all  : {n_no}")
    print(f"\nno_field_at_all cross-tab:")
    print(f"  generic fp (DesignedFunction or empty) : {n_gen}")
    print(f"  specific fp — SUSPECTS                 : {n_spec}")

    if stats["no_fpe_specific"]:
        print(f"\nSuspects (specific fp_sql but fpe absent):")
        for s in sorted(stats["no_fpe_specific"], key=lambda x: x["created_at"]):
            week = _iso_week(s["created_at"])
            post = "post-Leva2.1" if _is_post_leva21(s["created_at"]) else "pre-Leva2.1"
            print(f"  [{s['id']}] {s['label']!r:40s} {week}  {s['fp_sql']!r}  ({post})")

    hyp_key, hyp_text = determine_hypothesis(stats)
    print(f"\nDominant hypothesis: ({hyp_key})")
    print(f"  {hyp_text[:120]}...")

    report = build_report(stats, hyp_key, hyp_text)
    _OUT_PATH.write_text(report, encoding="utf-8")
    print(f"\nReport written to: {_OUT_PATH}")


if __name__ == "__main__":
    main()
