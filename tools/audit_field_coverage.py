#!/usr/bin/env python3
"""
Compute field-coverage statistics for Leva 2 and Leva 3 fields across the
entire enrichment.db.

Scope: ALL enriched records in the database (not deduplicated per cluster).
Re-enrichments of the same concept are counted individually, which gives the
most accurate picture of pipeline-level field adoption over time.

Field paths (all read from llm_raw_response JSON):
  source_label              → step4_parts.parts[*].source_label
  transformation_kind       → step5_signature.transformation_kind
  divergence_flags          → top-level divergence_flags[]
  function_parent_enriched  → step1_function.function_parent_enriched
                              (NOT a top-level key; NOT a SQL column)
  disjointness case IDs     → disjointness_rationale column (C1:–C5: prefix)

Path note (2026-05-04): function_parent_enriched lives at
step1_function.function_parent_enriched.  The _step1() helper reads this
correctly.  'Field absent' includes both pre-Leva-2.1 records and the 15
suspects where the LLM emitted a specific function_parent without the boolean
(LLM non-compliance, not a pipeline bug).  After running
tools/backfill_function_parent_enriched.py --apply the absent count falls.

Temporal grouping: monthly (YYYY-MM).  Dataset spans Apr–May 2026 (2 bins);
quarterly would collapse to a single bin and is omitted.  JSON key: by_month.

Outputs:
  /tmp/field_coverage_audit.md    — markdown with tables
  /tmp/field_coverage_audit.json  — structured JSON for paper citation

Read-only. Does not modify the database.

Usage:
    python tools/audit_field_coverage.py
    python tools/audit_field_coverage.py --output /tmp/my_audit
"""

import argparse
import datetime
import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "enrichment.db"

_CASE_RE = re.compile(r"\bC[1-5]:", re.IGNORECASE)

_TYPE_SHORT = {
    "T1_categorical": "T1",
    "T2_granularity": "T2",
    "T3_identity": "T3",
    "T4_topological": "T4",
    "T5_implicit_function": "T5",
}

ALL_TYPES = ["T1", "T2", "T3", "T4", "T5"]

_BFO_ORDER = ["Assembly", "MaterialArtifact", "EngineeredSystem", "Site", "(unknown)"]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _month_label(dt_str: str) -> str:
    """Return 'YYYY-MM' bucket for temporal grouping."""
    dt = datetime.datetime.fromisoformat(dt_str)
    return f"{dt.year}-{dt.month:02d}"


def load_records() -> list[dict]:
    """
    Return ALL enriched records from the database.
    Re-enrichments of the same concept are included — coverage is measured
    at the pipeline level, not deduplicated per concept.
    """
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, cluster_label, created_at, genus_bfo_root,
               llm_raw_response, divergence_flags, disjointness_rationale
          FROM enrichment
         ORDER BY id
        """
    ).fetchall()
    conn.close()

    records: list[dict] = []
    for row in rows:
        try:
            proposal: dict = json.loads(row["llm_raw_response"] or "{}")
        except Exception:
            proposal = {}

        try:
            flags: list = json.loads(row["divergence_flags"] or "[]")
        except Exception:
            flags = []

        records.append({
            "id": row["id"],
            "label": row["cluster_label"],
            "created_at": row["created_at"] or "",
            "bfo_root": row["genus_bfo_root"] or "(unknown)",
            "proposal": proposal,
            "flags": flags,
            "drat": row["disjointness_rationale"] or "",
        })

    return records


# ---------------------------------------------------------------------------
# Field-level extractors
# ---------------------------------------------------------------------------

def _parts(proposal: dict) -> list[dict]:
    return (proposal.get("step4_parts") or {}).get("parts") or []


def _dw(proposal: dict) -> list:
    return proposal.get("disjoint_with") or []


def _step5(proposal: dict) -> dict:
    return proposal.get("step5_signature") or {}


def _step1(proposal: dict) -> dict:
    return proposal.get("step1_function") or {}


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def compute_stats(records: list[dict]) -> dict:
    total = len(records)

    # ── 1. source_label (Leva 2.2) ─────────────────────────────────────────
    src_total_parts = 0
    src_with_label = 0
    src_verified = 0       # part_name_unverified == False
    src_unverified = 0     # part_name_unverified == True
    src_legacy_null = 0    # part_name_unverified is absent (legacy)
    src_name_null = 0      # name is None

    for rec in records:
        for pt in _parts(rec["proposal"]):
            src_total_parts += 1
            if pt.get("source_label") is not None:
                src_with_label += 1
            name = pt.get("name")
            pnu = pt.get("part_name_unverified")
            if name is None:
                # "No matching term" case — part_name_unverified is irrelevant
                src_name_null += 1
            elif pnu is False:
                src_verified += 1
            elif pnu is True:
                src_unverified += 1
            else:
                # name present but part_name_unverified absent → legacy record
                src_legacy_null += 1

    # Rate = verified / (verified + unverified): only among parts where
    # the feature was applied (name present and part_name_unverified recorded)
    eligible_for_rate = src_verified + src_unverified
    verified_rate = round(src_verified / eligible_for_rate, 4) if eligible_for_rate else None

    # ── 2. disjointness case identifier (Leva 3.4) ──────────────────────────
    dw_total_pairs = 0
    dw_with_case_id = 0
    dw_without_case_id = 0
    dw_without_rationale = 0

    for rec in records:
        dw = _dw(rec["proposal"])
        n = len(dw)
        if n == 0:
            continue
        dw_total_pairs += n
        drat = rec["drat"]
        if _CASE_RE.search(drat):
            dw_with_case_id += n
        elif drat:
            dw_without_case_id += n
        else:
            dw_without_rationale += n

    case_id_rate = round(dw_with_case_id / dw_total_pairs, 4) if dw_total_pairs else None

    # ── 3. transformation_kind (Leva 3.2) ───────────────────────────────────
    tk_filled = 0
    tk_controlled = 0
    tk_proposed = 0
    tk_empty = 0

    for rec in records:
        s5 = _step5(rec["proposal"])
        kind = s5.get("transformation_kind") or ""
        status = s5.get("transformation_kind_status") or ""
        if kind:
            tk_filled += 1
            if status == "controlled":
                tk_controlled += 1
            elif status == "proposed":
                tk_proposed += 1
        else:
            tk_empty += 1

    # ── 4. divergence_flags (Leva 3.3) ──────────────────────────────────────
    flags_nonempty = 0
    type_counts: dict[str, int] = {t: 0 for t in ALL_TYPES}

    for rec in records:
        flags = rec["flags"]
        if flags:
            flags_nonempty += 1
        # Count records, not flag instances (a record may have multiple flags of same type)
        types_present = {_TYPE_SHORT.get(f.get("type", ""), "") for f in flags} - {""}
        for t in types_present:
            type_counts[t] += 1

    # ── 5. function_parent_enriched (Leva 2.1) ──────────────────────────────
    fpe_true = 0
    fpe_false = 0
    fpe_legacy = 0

    for rec in records:
        val = _step1(rec["proposal"]).get("function_parent_enriched")
        if val is True:
            fpe_true += 1
        elif val is False:
            fpe_false += 1
        else:
            fpe_legacy += 1

    fpe_base = fpe_true + fpe_false
    fpe_rate = round(fpe_true / fpe_base, 4) if fpe_base else None

    # ── 6. by_month (temporal coverage) ─────────────────────────────────────
    month_buckets: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        if rec["created_at"]:
            month_buckets[_month_label(rec["created_at"])].append(rec)

    by_month = []
    for mo in sorted(month_buckets.keys()):
        cohort = month_buckets[mo]
        by_month.append(_cohort_coverage(mo, cohort, len(cohort)))

    # ── 7. by_genus (BFO root) ───────────────────────────────────────────────
    genus_buckets: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        genus_buckets[rec["bfo_root"]].append(rec)

    by_genus = []
    for bfo in _BFO_ORDER:
        cohort = genus_buckets.get(bfo)
        if cohort:
            by_genus.append(_cohort_coverage(bfo, cohort, len(cohort)))
    # Append any unexpected roots
    for bfo, cohort in sorted(genus_buckets.items()):
        if bfo not in _BFO_ORDER:
            by_genus.append(_cohort_coverage(bfo, cohort, len(cohort)))

    return {
        "total_records": total,
        "source_label_coverage": {
            "total_parts": src_total_parts,
            "with_source_label": src_with_label,
            "verified_count": src_verified,
            "unverified_count": src_unverified,
            "legacy_null_count": src_legacy_null,
            "name_null_count": src_name_null,
            "verified_rate": verified_rate,
        },
        "disjointness_case_id_coverage": {
            "total_pairs": dw_total_pairs,
            "with_case_id": dw_with_case_id,
            "without_case_id": dw_without_case_id,
            "without_rationale": dw_without_rationale,
            "case_id_rate": case_id_rate,
        },
        "transformation_kind_coverage": {
            "total_records": total,
            "filled": tk_filled,
            "controlled": tk_controlled,
            "proposed": tk_proposed,
            "empty": tk_empty,
            "filled_rate": round(tk_filled / total, 4) if total else None,
            "controlled_rate": round(tk_controlled / total, 4) if total else None,
        },
        "divergence_flags_coverage": {
            "total_records": total,
            "with_flags": flags_nonempty,
            "without_flags": total - flags_nonempty,
            "flags_rate": round(flags_nonempty / total, 4) if total else None,
            "by_type": {
                t: {
                    "count": type_counts[t],
                    "rate": round(type_counts[t] / total, 4) if total else None,
                }
                for t in ALL_TYPES
            },
        },
        "function_parent_enriched_coverage": {
            "total_records": total,
            "enriched_true": fpe_true,
            "enriched_false": fpe_false,
            "legacy_null": fpe_legacy,
            "enriched_rate": fpe_rate,
            "coverage_note": (
                f"{fpe_base}/{total} records have the field; "
                f"{fpe_legacy} are legacy (field absent)"
            ),
        },
        "by_month": by_month,
        "by_genus": by_genus,
    }


def _cohort_coverage(label: str, cohort: list[dict], n: int) -> dict:
    """Compute coverage summary for a group of records."""
    parts_total = sum(len(_parts(r["proposal"])) for r in cohort)
    parts_with_src = sum(
        1 for r in cohort for pt in _parts(r["proposal"])
        if pt.get("source_label") is not None
    )
    parts_verified = sum(
        1 for r in cohort for pt in _parts(r["proposal"])
        if pt.get("part_name_unverified") is False
    )
    # Records with ≥1 part having source_label
    recs_with_src = sum(
        1 for r in cohort
        if any(pt.get("source_label") is not None for pt in _parts(r["proposal"]))
    )

    dw_total = sum(len(_dw(r["proposal"])) for r in cohort)
    dw_case = sum(
        len(_dw(r["proposal"])) for r in cohort
        if _CASE_RE.search(r["drat"])
    )

    tk_filled = sum(
        1 for r in cohort if (_step5(r["proposal"]).get("transformation_kind") or "")
    )
    flags_nonempty = sum(1 for r in cohort if r["flags"])

    fpe_base = sum(
        1 for r in cohort
        if _step1(r["proposal"]).get("function_parent_enriched") is not None
    )
    fpe_true = sum(
        1 for r in cohort
        if _step1(r["proposal"]).get("function_parent_enriched") is True
    )

    def _rate(num: int, den: int) -> float | None:
        return round(num / den, 4) if den else None

    return {
        "label": label,
        "n_records": n,
        "source_label": {
            "total_parts": parts_total,
            "parts_with_source_label": parts_with_src,
            "parts_verified": parts_verified,
            "records_with_any_source_label": recs_with_src,
            "source_label_rate_parts": _rate(parts_with_src, parts_total),
        },
        "disjointness": {
            "total_pairs": dw_total,
            "with_case_id": dw_case,
            "case_id_rate": _rate(dw_case, dw_total),
        },
        "transformation_kind_filled_rate": _rate(tk_filled, n),
        "flags_rate": _rate(flags_nonempty, n),
        "function_parent_enriched": {
            "true": fpe_true,
            "field_present": fpe_base,
            "true_rate": _rate(fpe_true, fpe_base),
            # Coverage = fraction of records in cohort that have the field at all
            # (useful for temporal rollout view)
            "field_coverage_rate": _rate(fpe_base, n),
        },
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def _pct(value: float | None, denominator: int = 0) -> str:
    """Format a rate (0–1) as a percentage string."""
    if value is None:
        return "N/A"
    return f"{value * 100:.1f}%"


def render_markdown(stats: dict) -> str:
    lines: list[str] = []
    total = stats["total_records"]

    lines += [
        "# Field Coverage Audit — Leva 2 & 3 Features",
        "",
        f"**Records analysed (all enriched records):** {total}  ",
        f"**Generated:** " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "",
        "---",
        "",
    ]

    # ── Section 1: source_label ─────────────────────────────────────────────
    sl = stats["source_label_coverage"]
    eligible = sl["total_parts"] - sl["name_null_count"] - sl["legacy_null_count"]
    lines += [
        "## 1. `source_label` Coverage (Leva 2.2 — Step 4 Parts)",
        "",
        "| Metric | Count |",
        "|:-------|------:|",
        f"| Total parts across all records | {sl['total_parts']} |",
        f"| Parts with `name = null` (no matching term) | {sl['name_null_count']} |",
        f"| Parts with `source_label` populated | {sl['with_source_label']} |",
        f"| Parts where `part_name_unverified = False` (verified) | {sl['verified_count']} |",
        f"| Parts where `part_name_unverified = True` (suspect) | {sl['unverified_count']} |",
        f"| Parts where `part_name_unverified` absent (legacy) | {sl['legacy_null_count']} |",
        f"| Eligible for rate (excl. name=null and legacy) | {eligible} |",
        f"| **Verified rate** (verified / eligible) | **{_pct(sl['verified_rate'])}** |",
        "",
    ]

    # ── Section 2: disjointness case IDs ────────────────────────────────────
    dc = stats["disjointness_case_id_coverage"]
    lines += [
        "## 2. Disjointness Case-Identifier Coverage (Leva 3.4)",
        "",
        "_A pair inherits the case-ID status of its record's `disjointness_rationale`._",
        "",
        "| Metric | Pairs | % of total |",
        "|:-------|------:|-----------:|",
        f"| Total `disjoint_with` pairs | {dc['total_pairs']} | 100% |",
        f"| With C1:–C5: case identifier | {dc['with_case_id']} | {_pct(dc['case_id_rate'])} |",
        f"| Rationale present, no case ID (legacy) | {dc['without_case_id']} | "
        f"{_pct(dc['without_case_id'] / dc['total_pairs'] if dc['total_pairs'] else None)} |",
        f"| No rationale | {dc['without_rationale']} | "
        f"{_pct(dc['without_rationale'] / dc['total_pairs'] if dc['total_pairs'] else None)} |",
        "",
    ]

    # ── Section 3: transformation_kind ──────────────────────────────────────
    tk = stats["transformation_kind_coverage"]
    lines += [
        "## 3. `transformation_kind` Coverage (Leva 3.2)",
        "",
        "| Metric | Count | % of records |",
        "|:-------|------:|-------------:|",
        f"| Filled | {tk['filled']} | {_pct(tk['filled_rate'])} |",
        f"| Status `controlled` | {tk['controlled']} | {_pct(tk['controlled_rate'])} |",
        f"| Status `proposed` | {tk['proposed']} | "
        f"{_pct(tk['proposed'] / total if total else None)} |",
        f"| Empty (not backfilled) | {tk['empty']} | "
        f"{_pct(tk['empty'] / total if total else None)} |",
        "",
    ]

    # ── Section 4: divergence_flags ─────────────────────────────────────────
    df = stats["divergence_flags_coverage"]
    lines += [
        "## 4. `divergence_flags` Coverage (Leva 3.3)",
        "",
        f"**Records with ≥1 flag:** {df['with_flags']} / {total} "
        f"({_pct(df['flags_rate'])})  ",
        f"**Records with no flags:** {df['without_flags']}",
        "",
        "| Type | Description | Records | % |",
        "|:-----|:------------|--------:|--:|",
    ]
    _type_desc = {
        "T1": "Incompatible ontological categories",
        "T2": "Different granularity / subtype coverage",
        "T3": "Identity criteria diverge",
        "T4": "Mereological / topological relations differ",
        "T5": "Implicit vs explicit function",
    }
    for t in ALL_TYPES:
        v = df["by_type"][t]
        lines.append(
            f"| **{t}** | {_type_desc[t]} | {v['count']} | {_pct(v['rate'])} |"
        )
    lines.append("")

    # ── Section 5: function_parent_enriched ─────────────────────────────────
    fpe = stats["function_parent_enriched_coverage"]
    fpe_base = fpe["enriched_true"] + fpe["enriched_false"]
    lines += [
        "## 5. `function_parent_enriched` Coverage (Leva 2.1)",
        "",
        "| Metric | Count | % of records with field |",
        "|:-------|------:|:-----------------------:|",
        f"| `True` (enriched beyond IOF-Core root) | {fpe['enriched_true']} | "
        f"{_pct(fpe['enriched_rate'])} |",
        f"| `False` (stayed at genus_bfo_root) | {fpe['enriched_false']} | "
        f"{_pct(fpe['enriched_false'] / fpe_base if fpe_base else None)} |",
        f"| Field absent (legacy or LLM non-compliance) | {fpe['legacy_null']} | — |",
        "",
        f"_{fpe['coverage_note']}_",
        "",
    ]

    # ── Section 6: temporal (by_month) ───────────────────────────────────────
    lines += [
        "## 6. Temporal Coverage (by month)",
        "",
        "_(Records grouped by `created_at` month.  Dataset spans Apr–May 2026.)_",
        "",
        "| Month | N | src_label % | case_id % | tk_filled % | flags % | fpe field % |",
        "|:------|--:|------------:|----------:|------------:|--------:|------------:|",
    ]
    for mo in stats["by_month"]:
        n = mo["n_records"]
        sl_rate = mo["source_label"]["source_label_rate_parts"]
        dj_rate = mo["disjointness"]["case_id_rate"]
        tk_rate = mo["transformation_kind_filled_rate"]
        fl_rate = mo["flags_rate"]
        fp_rate = mo["function_parent_enriched"]["field_coverage_rate"]
        lines.append(
            f"| {mo['label']} | {n} "
            f"| {_pct(sl_rate)} "
            f"| {_pct(dj_rate)} "
            f"| {_pct(tk_rate)} "
            f"| {_pct(fl_rate)} "
            f"| {_pct(fp_rate)} |"
        )
    lines += [
        "",
        "_Columns: src_label % = parts with source_label / total parts in cohort;_  ",
        "_case_id % = dw pairs with C1:–C5: rationale / total dw pairs in cohort;_  ",
        "_fpe field % = records with `function_parent_enriched` field present / N._",
        "",
    ]

    # ── Section 7: by_genus ──────────────────────────────────────────────────
    lines += [
        "## 7. Coverage by `genus_bfo_root`",
        "",
        "| genus_bfo_root | N | parts | src_label | verified | case_id % | flags % |",
        "|:---------------|--:|------:|----------:|---------:|----------:|--------:|",
    ]
    for g in stats["by_genus"]:
        n = g["n_records"]
        sl = g["source_label"]
        dj = g["disjointness"]
        fl_rate = g["flags_rate"]
        src_note = (
            f"{sl['parts_with_source_label']}/{sl['total_parts']}"
            if sl["total_parts"] > 0
            else "N/A"
        )
        ver_note = (
            f"{sl['parts_verified']}/{sl['total_parts']}"
            if sl["total_parts"] > 0
            else "N/A"
        )
        lines.append(
            f"| {g['label']} | {n} "
            f"| {sl['total_parts']} "
            f"| {src_note} "
            f"| {ver_note} "
            f"| {_pct(dj['case_id_rate'])} "
            f"| {_pct(fl_rate)} |"
        )
    lines += [
        "",
        "_src_label = parts_with_source_label / total_parts; "
        "verified = part_name_unverified=False / total_parts._",
        "",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Console summary
# ---------------------------------------------------------------------------

def print_summary(stats: dict) -> None:
    total = stats["total_records"]
    print(f"\n{'='*55}")
    print(f"Total enriched records (all)       : {total}")

    sl = stats["source_label_coverage"]
    eligible = sl["total_parts"] - sl["name_null_count"] - sl["legacy_null_count"]
    print(f"\nsource_label (Leva 2.2):")
    print(f"  Total parts               : {sl['total_parts']}")
    print(f"  With source_label         : {sl['with_source_label']}")
    print(f"  Verified (unverified=F)   : {sl['verified_count']}")
    print(f"  Unverified (unverified=T) : {sl['unverified_count']}")
    print(f"  Legacy null               : {sl['legacy_null_count']}")
    print(f"  name=null                 : {sl['name_null_count']}")
    print(f"  Verified rate (eligible)  : {_pct(sl['verified_rate'])}"
          f"  [{sl['verified_count']}/{eligible}]")

    dc = stats["disjointness_case_id_coverage"]
    print(f"\nDisjointness case IDs (Leva 3.4):")
    print(f"  Total pairs               : {dc['total_pairs']}")
    print(f"  With C1:–C5: ID           : {dc['with_case_id']}  ({_pct(dc['case_id_rate'])})")
    print(f"  Legacy (no case ID)       : {dc['without_case_id']}")
    print(f"  No rationale              : {dc['without_rationale']}")

    tk = stats["transformation_kind_coverage"]
    print(f"\ntransformation_kind (Leva 3.2):")
    print(f"  Filled                    : {tk['filled']}  ({_pct(tk['filled_rate'])})")
    print(f"  Controlled                : {tk['controlled']}")
    print(f"  Proposed                  : {tk['proposed']}")
    print(f"  Empty                     : {tk['empty']}")

    df = stats["divergence_flags_coverage"]
    print(f"\ndivergence_flags (Leva 3.3):")
    print(f"  Records with ≥1 flag      : {df['with_flags']}  ({_pct(df['flags_rate'])})")
    for t in ALL_TYPES:
        v = df["by_type"][t]
        bar = "█" * int((v["rate"] or 0) * 40)
        print(f"  {t}  {v['count']:3d}  {_pct(v['rate']):6}  {bar}")

    fpe = stats["function_parent_enriched_coverage"]
    print(f"\nfunction_parent_enriched (Leva 2.1):")
    print(f"  True                      : {fpe['enriched_true']}")
    print(f"  False                     : {fpe['enriched_false']}")
    print(f"  Legacy (absent)           : {fpe['legacy_null']}")
    print(f"  Enriched rate (w/ field)  : {_pct(fpe['enriched_rate'])}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--output", default="/tmp/field_coverage_audit",
        help="Output path prefix (no extension). Default: /tmp/field_coverage_audit",
    )
    args = parser.parse_args()

    print("Loading enrichment records...", flush=True)
    records = load_records()
    print(f"  {len(records)} distinct clusters loaded", flush=True)

    print("Computing coverage statistics...", flush=True)
    stats = compute_stats(records)

    out_prefix = Path(args.output)
    out_md = out_prefix.with_suffix(".md")
    out_json = out_prefix.with_suffix(".json")

    out_md.write_text(render_markdown(stats), encoding="utf-8")
    out_json.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"  Written: {out_md}")
    print(f"  Written: {out_json}")

    print_summary(stats)


if __name__ == "__main__":
    main()
