#!/usr/bin/env python3
"""
Audit all enrichment records that have a non-empty disjoint_with field,
applying the 5-case disjointness decision tree from disjointness_validator.py.

Does NOT modify the database.

Usage:
    python tools/audit_disjointness.py
    python tools/audit_disjointness.py --output /tmp/my_audit.md

Output:
    /tmp/disjointness_audit.md  (default)
    Console summary
"""

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from enrichment.disjointness_validator import (
    validate_disjointness,
    validate_pair_structural,
    build_ontology_state,
    build_normalised_index,
    normalise_label,
    _step5_of,
)

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "enrichment.db"


def _open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def load_records_with_disjointness() -> list[dict]:
    conn = _open_db()
    rows = conn.execute(
        """
        SELECT id, cluster_label, genus,
               function_name, llm_raw_response, status
          FROM enrichment
         ORDER BY cluster_label, id DESC
        """
    ).fetchall()
    conn.close()

    seen: set = set()
    records = []
    for row in rows:
        label = row["cluster_label"]
        if label in seen:
            continue
        seen.add(label)

        raw = row["llm_raw_response"] or "{}"
        if isinstance(raw, str):
            try:
                proposal = json.loads(raw)
            except Exception:
                continue
        else:
            proposal = raw

        disjoint_with = proposal.get("disjoint_with") or []
        if not disjoint_with:
            continue

        # classification_basis is inside the JSON; ensure it's top-level for validator
        proposal.setdefault("cluster_label", label)
        # (classification_basis already present in the parsed JSON)
        step2 = proposal.get("step2_genus") or {}
        if not step2.get("genus_name") and row["genus"]:
            proposal.setdefault("step2_genus", {"genus_name": row["genus"]})

        records.append({
            "id": row["id"],
            "cluster_label": label,
            "status": row["status"],
            "proposal": proposal,
            "disjoint_with": disjoint_with,
        })
    return records


def run_audit(output_path: str = "/tmp/disjointness_audit.md") -> None:
    print("Loading ontology state...", flush=True)
    ontology_state = build_ontology_state()

    print("Loading records with disjointness...", flush=True)
    records = load_records_with_disjointness()

    if not records:
        print("No records with non-empty disjoint_with found.")
        return

    print(f"Auditing {len(records)} records...", flush=True)

    # Aggregate stats
    case_counters: Counter = Counter()
    total_preserved = 0
    total_rejected = 0
    total_invalid = 0
    total_asymmetry = 0

    preserved_rows: list = []
    rejected_rows: list = []
    invalid_rows: list = []
    asymmetry_rows: list = []

    for rec in records:
        result = validate_disjointness(rec["proposal"], ontology_state)
        label = rec["cluster_label"]
        status = rec["status"]

        for candidate, case_id, note in result["preserved"]:
            total_preserved += 1
            case_counters[f"preserved_{case_id}"] += 1
            preserved_rows.append((label, status, candidate, case_id, note))

        for candidate, case_id, reason in result["rejected"]:
            total_rejected += 1
            case_counters[f"rejected_{case_id}"] += 1
            rejected_rows.append((label, status, candidate, case_id, reason))

        for candidate, reason in result["rationale_invalid"]:
            total_invalid += 1
            invalid_rows.append((label, status, candidate, reason))

        for warning in result["asymmetry_warnings"]:
            total_asymmetry += 1
            asymmetry_rows.append((label, warning))

    # ---- Build markdown report ----
    total_pairs = total_preserved + total_rejected + total_invalid
    lines = [
        "# Disjointness Audit — COPI Enrichment DB",
        "",
        f"**Records audited:** {len(records)}  ",
        f"**Total (X, C) pairs:** {total_pairs}  ",
        f"**Preserved:** {total_preserved}  ",
        f"**Rejected:** {total_rejected}  ",
        f"**Rationale-invalid / unverifiable:** {total_invalid}  ",
        f"**Asymmetry warnings:** {total_asymmetry}  ",
        "",
        "---",
        "",
        "## By Case",
        "",
        "| Case | Preserved | Rejected |",
        "|------|-----------|----------|",
    ]
    for case_id in ("C1", "C2", "C3", "C4", "C5"):
        p = case_counters.get(f"preserved_{case_id}", 0)
        r = case_counters.get(f"rejected_{case_id}", 0)
        lines.append(f"| {case_id} | {p} | {r} |")
    lines += ["", "---", ""]

    # ---- Preserved ----
    lines += [f"## Preserved ({total_preserved} pairs)", ""]
    if preserved_rows:
        lines += [
            "| X | Status | C | Case | Note |",
            "|---|--------|---|------|------|",
        ]
        for label, status, candidate, case_id, note in preserved_rows:
            note_short = note[:80] + "…" if len(note) > 80 else note
            lines.append(f"| `{label}` | {status} | `{candidate}` | {case_id} | {note_short} |")
    else:
        lines.append("_None._")
    lines += ["", "---", ""]

    # ---- Rejected ----
    lines += [f"## Rejected ({total_rejected} pairs)", ""]

    for case_id, case_title in (
        ("C1", "Case 1 — Same genus, both constructive (structural evidence missing)"),
        ("C2", "Case 2 — Same genus, both functional (dormant — no function disjunctions)"),
        ("C3", "Case 3 — Same genus, mixed bases (orthogonal — never disjoint)"),
        ("C4", "Case 4 — Different genus (signature incompatibility not confirmed)"),
        ("C5", "Case 5 — Operational/regulatory context (never disjoint)"),
    ):
        subset = [(l, s, c, r) for l, s, c, ci, r in rejected_rows if ci == case_id]
        if not subset:
            continue
        lines += [f"### {case_title} ({len(subset)})", ""]
        lines += [
            "| X | Status | C | Reason |",
            "|---|--------|---|--------|",
        ]
        for label, status, candidate, reason in subset:
            r_short = reason[:100] + "…" if len(reason) > 100 else reason
            lines.append(f"| `{label}` | {status} | `{candidate}` | {r_short} |")
        lines += [""]

    lines += ["---", ""]

    # ---- Rationale invalid ----
    lines += [f"## Rationale-invalid / Unverifiable ({total_invalid} pairs)", ""]
    if invalid_rows:
        lines += [
            "| X | Status | C | Reason |",
            "|---|--------|---|--------|",
        ]
        for label, status, candidate, reason in invalid_rows:
            r_short = reason[:120] + "…" if len(reason) > 120 else reason
            lines.append(f"| `{label}` | {status} | `{candidate}` | {r_short} |")
    else:
        lines.append("_None._")
    lines += ["", "---", ""]

    # ---- Asymmetry ----
    lines += [f"## Asymmetry Warnings ({total_asymmetry})", ""]
    if asymmetry_rows:
        lines += [
            "| X | Warning |",
            "|---|---------|",
        ]
        for label, warning in asymmetry_rows:
            lines.append(f"| `{label}` | {warning} |")
    else:
        lines.append("_None._")
    lines += ["", "---", ""]

    # ---- Removal policy ----
    lines += [
        "## Removal Policy",
        "",
        "- **Batch 1 (safest):** Remove all rejected C3 pairs (orthogonal bases). Low controversy.",
        "- **Batch 2:** Remove rejected C5 pairs (operational context). Low controversy.",
        "- **Batch 3 (review):** Inspect rejected C4 pairs — signature may be imprecise, not disjointness wrong.",
        "- **Batch 4 (future):** Revisit rejected C2 pairs when function disjunctions are added to the ontology.",
        "",
        "_No automatic removals performed by this script. Each batch requires human confirmation and DB backup._",
    ]

    report = "\n".join(lines)
    Path(output_path).write_text(report, encoding="utf-8")

    # Console summary
    print(f"\n{'='*60}")
    print(f"Records audited:          {len(records)}")
    print(f"Total (X, C) pairs:       {total_pairs}")
    print(f"  Preserved:              {total_preserved}")
    print(f"  Rejected:               {total_rejected}")
    print(f"  Rationale-invalid:      {total_invalid}")
    print(f"  Asymmetry warnings:     {total_asymmetry}")
    print(f"{'='*60}")
    print(f"Report written to: {output_path}")


def run_extended_audit(
    output_path: str = "/tmp/disjointness_audit_extended.md",
) -> None:
    """Re-analyse rationale_invalid pairs using structural fields only.

    For each pair where the candidate can be found via normalised name lookup,
    applies the 5-case tree without reading the rationale text. Reclassifies as:
      - preserved_by_structure: tree is consistent with disjointness
      - rejected_by_structure:  tree definitively excludes disjointness (C2/C3/C5)
      - unverifiable:           required structural field absent
    Pairs where the candidate is not found in DB remain rationale_invalid.
    """
    print("Loading ontology state and building normalised index...", flush=True)
    ontology_state = build_ontology_state()
    norm_index = build_normalised_index(ontology_state)

    print("Loading records with disjointness...", flush=True)
    records = load_records_with_disjointness()

    if not records:
        print("No records with non-empty disjoint_with found.")
        return

    print(f"Running base audit on {len(records)} records...", flush=True)

    # ---- Phase 1: collect preserved/rejected/invalid from base validator ----
    all_invalid_pairs: list = []  # (x_label, x_status, candidate, reasons)
    preserved_base: list = []
    rejected_base: list = []

    for rec in records:
        result = validate_disjointness(rec["proposal"], ontology_state)
        label = rec["cluster_label"]
        status = rec["status"]

        for item in result["preserved"]:
            preserved_base.append((label, status) + item)
        for item in result["rejected"]:
            rejected_base.append((label, status) + item)

        # Deduplicate invalid entries per (label, candidate) — the validator may
        # add two entries for the same pair (missing case ID + not in DB).
        seen_pairs: dict = {}  # candidate → list[reason]
        for candidate, reason in result["rationale_invalid"]:
            seen_pairs.setdefault(candidate, []).append(reason)
        for candidate, reasons in seen_pairs.items():
            all_invalid_pairs.append((label, status, candidate, reasons))

    print(
        f"  preserved={len(preserved_base)}, rejected={len(rejected_base)}, "
        f"invalid_pairs={len(all_invalid_pairs)}"
    )

    # ---- Phase 2: structural re-analysis of invalid pairs ----
    preserved_struct: list = []   # (x_label, x_status, candidate, case_id, note)
    rejected_struct: list  = []   # (x_label, x_status, candidate, case_id, reason)
    unverifiable: list     = []   # (x_label, x_status, candidate, reason)
    still_invalid: list    = []   # candidate not found even after normalisation

    print("Re-analysing rationale-invalid pairs structurally...", flush=True)
    for x_label, x_status, candidate, _reasons in all_invalid_pairs:
        # Try direct lookup first, then normalised
        c_row = ontology_state.get(candidate)
        if c_row is None:
            norm_key = normalise_label(candidate)
            resolved = norm_index.get(norm_key)
            if resolved:
                c_row = ontology_state[resolved]
            else:
                still_invalid.append((x_label, x_status, candidate))
                continue

        # Gather X's structural fields from the record's proposal
        x_rec = next((r for r in records if r["cluster_label"] == x_label), None)
        if x_rec is None:
            still_invalid.append((x_label, x_status, candidate))
            continue

        x_proposal = x_rec["proposal"]
        x_basis = x_proposal.get("classification_basis") or ""
        x_genus = (x_proposal.get("step2_genus") or {}).get("genus_name") or ""
        step5_x = x_proposal.get("step5_signature") or {}
        x_kind = step5_x.get("transformation_kind") or ""
        x_kind_status = step5_x.get("transformation_kind_status") or ""

        # Gather C's structural fields
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
            candidate, c_basis, c_genus, c_kind, c_kind_status,
        )

        if classification == "preserved_by_structure":
            preserved_struct.append((x_label, x_status, candidate, case_id, reason))
        elif classification == "rejected_by_structure":
            rejected_struct.append((x_label, x_status, candidate, case_id, reason))
        else:
            unverifiable.append((x_label, x_status, candidate, reason))

    # ---- Build report ----
    total_pairs = (
        len(preserved_base) + len(rejected_base) + len(all_invalid_pairs)
    )
    total_struct_resolved = len(preserved_struct) + len(rejected_struct) + len(unverifiable)
    struct_case_dist: Counter = Counter()
    for _, _, _, case_id, _ in rejected_struct:
        struct_case_dist[f"rejected_{case_id}"] += 1
    for _, _, _, case_id, _ in preserved_struct:
        struct_case_dist[f"preserved_{case_id}"] += 1

    # base raw pair count (with duplicates from double-entry per invalid pair)
    base_raw_pairs = len(preserved_base) + len(rejected_base) + sum(
        len(reasons) for _, _, _, reasons in all_invalid_pairs
    )

    lines = [
        "# Disjointness Audit (Extended) — COPI Enrichment DB",
        "",
        "_Extends the base audit by re-analysing rationale-invalid pairs using structural "
        "fields only (genus, classification_basis, transformation_kind). Ignores rationale "
        "text for this phase._",
        "",
        "---",
        "",
        "## Summary",
        "",
        f"**Records audited:** {len(records)}  ",
        f"**Total unique (X, C) pairs:** {total_pairs}  ",
        f"_(Base audit reports {base_raw_pairs} because each rationale-invalid pair "
        f"generates two entries; extended audit deduplicates.)_",
        "",
        "### Base audit (rationale-aware)",
        "",
        f"| Category | Count |",
        f"|----------|-------|",
        f"| Preserved | {len(preserved_base)} |",
        f"| Rejected | {len(rejected_base)} |",
        f"| Rationale-invalid (unique pairs) | {len(all_invalid_pairs)} |",
        "",
        "### Structural re-analysis of rationale-invalid pairs",
        "",
        f"| Category | Count |",
        f"|----------|-------|",
        f"| preserved_by_structure | {len(preserved_struct)} |",
        f"| rejected_by_structure | {len(rejected_struct)} |",
        f"| unverifiable (missing fields) | {len(unverifiable)} |",
        f"| still rationale-invalid (C not found) | {len(still_invalid)} |",
        "",
        "---",
        "",
    ]

    # ---- preserved_by_structure ----
    lines += [f"## preserved_by_structure ({len(preserved_struct)} pairs)", ""]
    lines += ["_Sample of up to 10 pairs:_", ""]
    if preserved_struct:
        lines += [
            "| X | Status | C (resolved) | Case | Note |",
            "|---|--------|--------------|------|------|",
        ]
        for label, status, candidate, case_id, note in preserved_struct[:10]:
            note_s = note[:90] + "…" if len(note) > 90 else note
            lines.append(f"| `{label}` | {status} | `{candidate}` | {case_id} | {note_s} |")
        if len(preserved_struct) > 10:
            lines.append(f"_… and {len(preserved_struct) - 10} more_")
    else:
        lines.append("_None._")
    lines += ["", "---", ""]

    # ---- rejected_by_structure ----
    lines += [f"## rejected_by_structure ({len(rejected_struct)} pairs)", ""]
    lines += ["### Distribution by case", ""]
    lines += ["| Case | Count |", "|------|-------|"]
    for case_id in ("C1", "C2", "C3", "C4", "C5"):
        n = struct_case_dist.get(f"rejected_{case_id}", 0)
        if n:
            lines.append(f"| {case_id} | {n} |")
    lines += [""]

    for case_id, case_title in (
        ("C1", "Case 1 — Same genus, both constructive (structural evidence missing)"),
        ("C2", "Case 2 — Same genus, both functional (dormant)"),
        ("C3", "Case 3 — Same genus, mixed bases (orthogonal)"),
        ("C4", "Case 4 — Different genus (signatures compatible or indeterminate)"),
        ("C5", "Case 5 — Operational context"),
    ):
        subset = [(l, s, c, r) for l, s, c, ci, r in rejected_struct if ci == case_id]
        if not subset:
            continue
        lines += [f"### {case_title} ({len(subset)})", ""]
        lines += ["| X | Status | C | Reason |", "|---|--------|---|--------|"]
        for label, status, candidate, reason in subset[:30]:
            r_s = reason[:100] + "…" if len(reason) > 100 else reason
            lines.append(f"| `{label}` | {status} | `{candidate}` | {r_s} |")
        if len(subset) > 30:
            lines.append(f"_… and {len(subset) - 30} more_")
        lines += [""]
    lines += ["---", ""]

    # ---- unverifiable ----
    lines += [f"## unverifiable ({len(unverifiable)} pairs)", ""]
    if unverifiable:
        missing_fields: Counter = Counter()
        for _, _, _, reason in unverifiable:
            if "classification_basis missing" in reason:
                missing_fields["classification_basis"] += 1
            elif "genus missing" in reason:
                missing_fields["genus"] += 1
            elif "kind evidence insufficient" in reason:
                missing_fields["kind_status_not_controlled"] += 1
            elif "same transformation_kind" in reason:
                missing_fields["same_kind_different_genus"] += 1
            else:
                missing_fields["other"] += 1
        lines += ["### Missing-field breakdown", ""]
        lines += ["| Field | Count |", "|-------|-------|"]
        for field, count in missing_fields.most_common():
            lines.append(f"| {field} | {count} |")
        lines += [""]
        if len(unverifiable) > 50:
            lines.append(
                f"⚠ {len(unverifiable)} unverifiable pairs — worth investigating which "
                "records are missing structural fields."
            )
            lines += [""]
        lines += ["_Sample (up to 15):_", ""]
        lines += ["| X | Status | C | Reason |", "|---|--------|---|--------|"]
        for label, status, candidate, reason in unverifiable[:15]:
            r_s = reason[:110] + "…" if len(reason) > 110 else reason
            lines.append(f"| `{label}` | {status} | `{candidate}` | {r_s} |")
        if len(unverifiable) > 15:
            lines.append(f"_… and {len(unverifiable) - 15} more_")
    else:
        lines.append("_None._")
    lines += ["", "---", ""]

    # ---- still invalid (C not found) ----
    lines += [
        f"## still rationale-invalid — C not found ({len(still_invalid)} pairs)", "",
        "_Candidate class could not be resolved even after normalised lookup. "
        "These require manual review or re-enrichment under the new prompt._", "",
    ]
    if still_invalid:
        unique_c = {c for _, _, c in still_invalid}
        lines += [f"**Unique unresolved candidate names:** {len(unique_c)}  ", ""]
        lines += ["_Sample (up to 20):_", ""]
        lines += ["| X | Status | C (unresolved) |", "|---|--------|----------------|"]
        for label, status, candidate in still_invalid[:20]:
            lines.append(f"| `{label}` | {status} | `{candidate}` |")
        if len(still_invalid) > 20:
            lines.append(f"_… and {len(still_invalid) - 20} more_")
    else:
        lines.append("_None._")
    lines += ["", "---", ""]

    # ---- Combined summary ----
    total_confirmed_preserved = len(preserved_base) + len(preserved_struct)
    total_confirmed_rejected = len(rejected_base) + len(rejected_struct)
    lines += [
        "## Combined Verdict (base + structural)",
        "",
        "| Category | Count | % of total pairs |",
        "|----------|-------|-----------------|",
        f"| Confirmed preserved | {total_confirmed_preserved} | "
        f"{total_confirmed_preserved / total_pairs * 100:.1f}% |",
        f"| Confirmed rejected | {total_confirmed_rejected} | "
        f"{total_confirmed_rejected / total_pairs * 100:.1f}% |",
        f"| Unverifiable (missing fields) | {len(unverifiable)} | "
        f"{len(unverifiable) / total_pairs * 100:.1f}% |",
        f"| Not found in DB | {len(still_invalid)} | "
        f"{len(still_invalid) / total_pairs * 100:.1f}% |",
    ]

    report = "\n".join(lines)
    Path(output_path).write_text(report, encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"Records audited:              {len(records)}")
    print(f"Total (X, C) pairs:           {total_pairs}")
    print(f"  preserved (base):           {len(preserved_base)}")
    print(f"  rejected (base):            {len(rejected_base)}")
    print(f"  invalid pairs (base):       {len(all_invalid_pairs)}")
    print(f"    → preserved_by_structure: {len(preserved_struct)}")
    print(f"    → rejected_by_structure:  {len(rejected_struct)}")
    print(f"    → unverifiable:           {len(unverifiable)}")
    print(f"    → C not found:            {len(still_invalid)}")
    print(f"{'='*60}")
    print(f"Combined confirmed preserved: {total_confirmed_preserved}")
    print(f"Combined confirmed rejected:  {total_confirmed_rejected}")
    print(f"Report written to: {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit disjointness declarations in the enrichment DB."
    )
    parser.add_argument(
        "--output", default="/tmp/disjointness_audit.md",
        help="Base audit output path (default: /tmp/disjointness_audit.md)",
    )
    parser.add_argument(
        "--extended-output", default="/tmp/disjointness_audit_extended.md",
        help="Extended audit output (default: /tmp/disjointness_audit_extended.md)",
    )
    parser.add_argument(
        "--extended", action="store_true", default=True,
        help="Also run the structural re-analysis of rationale-invalid pairs (default: on)",
    )
    parser.add_argument(
        "--no-extended", dest="extended", action="store_false",
        help="Skip the structural re-analysis",
    )
    args = parser.parse_args()
    run_audit(args.output)
    if args.extended:
        print()
        run_extended_audit(args.extended_output)


if __name__ == "__main__":
    main()
