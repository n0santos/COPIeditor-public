#!/usr/bin/env python3
"""
Extract a stratified sample of T3 (identity-criteria) divergence flags from
enrichment.db for manual review.

Read-only. Outputs /tmp/T3_audit_sample.md.

Stratification: genus_bfo_root values actually present for T3 clusters —
  Assembly (≈109), MaterialArtifact (≈54), and a residual "others" group.
  Up to 25 records are sampled per stratum (or all if < 25).

Usage:
    python tools/audit_T3_classifications.py
    python tools/audit_T3_classifications.py --sample 40 --output /tmp/my_T3.md
"""

import argparse
import json
import random
import sqlite3
from collections import defaultdict
from pathlib import Path

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "enrichment.db"

_TYPE_SHORT = {
    "T1_categorical": "T1",
    "T2_granularity": "T2",
    "T3_identity": "T3",
    "T4_topological": "T4",
    "T5_implicit_function": "T5",
}

# Primary strata (everything else goes into "others")
_PRIMARY_STRATA = ["Assembly", "MaterialArtifact"]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_t3_records() -> list[dict]:
    """
    Return one dict per cluster (latest record) that has at least one T3_identity flag.
    Each dict:
        label         — cluster_label
        genus         — genus_name
        bfo_root      — genus_bfo_root (normalised title-case)
        t3_flags      — list of {evidence, sources_involved} for T3 flags in this record
        co_types      — sorted list of other short types co-occurring (e.g. ["T1", "T2", "T5"])
    """
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, cluster_label, divergence_flags, llm_raw_response
          FROM enrichment
         WHERE divergence_flags IS NOT NULL
         ORDER BY id DESC
        """
    ).fetchall()
    conn.close()

    seen: set = set()
    records: list[dict] = []

    for row in rows:
        lbl = row["cluster_label"]
        if lbl in seen:
            continue
        seen.add(lbl)

        try:
            flags: list = json.loads(row["divergence_flags"] or "[]")
        except Exception:
            flags = []

        t3_flags = [f for f in flags if f.get("type") == "T3_identity"]
        if not t3_flags:
            continue

        try:
            proposal = json.loads(row["llm_raw_response"] or "{}")
            step2 = proposal.get("step2_genus") or {}
            genus = (step2.get("genus_name") or "").strip()
            bfo_raw = (step2.get("genus_bfo_root") or "").strip()
            # Normalise to title-case
            bfo_root = bfo_raw[0].upper() + bfo_raw[1:] if bfo_raw else "(unknown)"
        except Exception:
            genus = ""
            bfo_root = "(unknown)"

        all_short = {_TYPE_SHORT.get(f.get("type", ""), "") for f in flags}
        all_short.discard("")
        co_types = sorted(all_short - {"T3"})

        records.append({
            "label": lbl,
            "genus": genus,
            "bfo_root": bfo_root,
            "t3_flags": [
                {
                    "evidence": (f.get("evidence") or "").strip(),
                    "sources_involved": f.get("sources_involved") or [],
                }
                for f in t3_flags
            ],
            "co_types": co_types,
        })

    return records


# ---------------------------------------------------------------------------
# Stratified sampling
# ---------------------------------------------------------------------------

def stratify(records: list[dict]) -> dict[str, list[dict]]:
    """Group records by genus_bfo_root into primary strata + 'others'."""
    strata: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        key = r["bfo_root"] if r["bfo_root"] in _PRIMARY_STRATA else "others"
        strata[key].append(r)
    return dict(strata)


def sample_strata(
    strata: dict[str, list[dict]],
    n_per_stratum: int,
    seed: int = 42,
) -> list[tuple[str, list[dict]]]:
    """
    For each stratum, return up to n_per_stratum records sampled deterministically.
    Returns list of (stratum_label, sample_list) ordered: primary strata first, others last.
    """
    rng = random.Random(seed)
    ordered_keys = _PRIMARY_STRATA + sorted(
        k for k in strata if k not in _PRIMARY_STRATA
    )

    result = []
    for key in ordered_keys:
        pool = strata.get(key, [])
        if not pool:
            continue
        pool_sorted = sorted(pool, key=lambda r: r["label"])
        sample = rng.sample(pool_sorted, min(n_per_stratum, len(pool_sorted)))
        sample.sort(key=lambda r: r["label"])
        result.append((key, sample))

    return result


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def render_markdown(
    all_records: list[dict],
    sampled: list[tuple[str, list[dict]]],
    strata: dict[str, list[dict]],
) -> str:
    total_t3 = len(all_records)
    total_sampled = sum(len(s) for _, s in sampled)

    # Ordered: primary strata first, then "others" expanded into constituent bfo_roots
    summary_parts = []
    for key in _PRIMARY_STRATA:
        if key in strata:
            summary_parts.append(f"{key}: {len(strata[key])}")
    others = strata.get("others", [])
    if others:
        # Break down by actual bfo_root for transparency
        from collections import Counter
        others_breakdown = Counter(r["bfo_root"] for r in others)
        breakdown_str = ", ".join(
            f"{k}: {v}" for k, v in sorted(others_breakdown.items())
        )
        summary_parts.append(f"others: {len(others)} ({breakdown_str})")
    strata_summary = ", ".join(summary_parts)

    lines: list[str] = [
        "# T3 Identity-Criteria Audit — Stratified Sample",
        "",
        f"**Total T3 clusters in DB:** {total_t3}  ",
        f"**Strata (by genus_bfo_root):** {strata_summary}  ",
        f"**Records in this sample:** {total_sampled}  ",
        "",
        "**Review rubric — for each entry mark ONE:**",
        "",
        "- `[ ] Genuine T3`: sources genuinely disagree on identity criterion "
        "(physical artifact vs functional type vs procurement category vs spatial region, etc.)",
        "- `[ ] Borderline`: evidence mentions identity but is arguable T1 (category) or T2 (granularity)",
        "- `[ ] Misclassification`: evidence actually describes granularity → should be T2, "
        "or categorical disagreement → should be T1",
        "",
        "---",
        "",
    ]

    entry_n = 0
    # Pre-compute stratum pool sizes using the same key logic
    pool_sizes = {k: len(v) for k, v in strata.items()}

    for stratum_label, sample in sampled:
        pool_n = pool_sizes.get(stratum_label, 0)
        lines += [
            f"## Stratum: {stratum_label} ({len(sample)} of {pool_n} clusters)",
            "",
        ]

        for rec in sample:
            entry_n += 1
            co = ", ".join(rec["co_types"]) if rec["co_types"] else "—"
            genus_display = rec["genus"] or "(unknown genus)"
            lines += [
                f"### {entry_n}. `{rec['label']}` · {genus_display} / {rec['bfo_root']}",
                f"_Co-occurring types: {co}_",
                "",
            ]

            for i, flag in enumerate(rec["t3_flags"], start=1):
                prefix = f"**T3 flag {i}:**" if len(rec["t3_flags"]) > 1 else "**Evidence:**"
                evidence = flag["evidence"] or "(no evidence text)"
                sources = (
                    ", ".join(f"`{s}`" for s in flag["sources_involved"])
                    if flag["sources_involved"]
                    else "_(not specified)_"
                )
                lines += [
                    f"{prefix} {evidence}",
                    "",
                    f"**Sources:** {sources}",
                    "",
                ]

            lines += [
                "**Quick check:**",
                "- `[ ]` Genuine T3 — identity-criterion disagreement",
                "- `[ ]` Borderline (arguable T1/T2)",
                "- `[ ]` Misclassification → should be T2 (granularity) / T1 (category)",
                "",
                "---",
                "",
            ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--sample", type=int, default=25, metavar="N",
        help="Max records per stratum (default: 25).",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducible sampling (default: 42).",
    )
    parser.add_argument(
        "--output", default="/tmp/T3_audit_sample.md",
        help="Output path (default: /tmp/T3_audit_sample.md).",
    )
    args = parser.parse_args()

    print("Loading T3 records...", flush=True)
    records = load_t3_records()
    print(f"  {len(records)} clusters with T3 flag found", flush=True)

    strata = stratify(records)
    print(f"  Strata: { {k: len(v) for k, v in strata.items()} }", flush=True)

    sampled = sample_strata(strata, n_per_stratum=args.sample, seed=args.seed)
    total_sampled = sum(len(s) for _, s in sampled)
    print(f"  Sample: {total_sampled} records ({args.sample} per stratum max, seed={args.seed})", flush=True)

    out_path = Path(args.output)
    out_path.write_text(render_markdown(records, sampled, strata), encoding="utf-8")
    print(f"\nWritten: {out_path}")

    print(f"\nStratum breakdown:")
    for key, sample in sampled:
        pool_size = sum(1 for r in records if (r["bfo_root"] if r["bfo_root"] in _PRIMARY_STRATA else "others") == key)
        print(f"  {key:<20}: {len(sample):2d} sampled / {pool_size} total")


if __name__ == "__main__":
    main()
