#!/usr/bin/env python3
"""
Compute T1-T5 divergence typology statistics from the current enrichment.db state.

Read-only. Outputs:
  /tmp/divergence_typology_report.md   — formatted markdown with tables
  /tmp/divergence_typology_report.json — structured JSON for paper citation

Usage:
    python tools/divergence_typology_report.py
    python tools/divergence_typology_report.py --output /tmp/my_report
"""

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "enrichment.db"

ALL_TYPES = ["T1", "T2", "T3", "T4", "T5"]

_TYPE_SHORT = {
    "T1_categorical": "T1",
    "T2_granularity": "T2",
    "T3_identity": "T3",
    "T4_topological": "T4",
    "T5_implicit_function": "T5",
}

_TYPE_DESC = {
    "T1": "Incompatible ontological categories",
    "T2": "Different granularity / subtype coverage",
    "T3": "Identity criteria diverge (artifact vs functional type)",
    "T4": "Mereological / topological relations differ",
    "T5": "Implicit vs explicit function",
}

# Canonical source keys and their aliases (lowercase, stripped)
_SOURCE_CANON: dict[str, str] = {
    "iso 15926-4": "iso15926-4",
    "iso15926-4": "iso15926-4",
    "iso15926_4": "iso15926-4",
    "iso15926": "iso15926-4",
    "iso 15926": "iso15926-4",
    "iso 15926-4 (internal)": "iso15926-4",
    "cfihos": "cfihos",
    "posc caesar": "posc_caesar",
    "posc_caesar": "posc_caesar",
    "posccaesar": "posc_caesar",
    "onepetro": "onepetro",
    "onepetro glossary": "onepetro",
    "onepetro_glossary": "onepetro",
    "slb glossary": "slb_glossary",
    "slb_glossary": "slb_glossary",
    "slb": "slb_glossary",
    "iso 14224": "iso14224",
    "iso14224": "iso14224",
    "iso14224-2016": "iso14224",
    "dexpi": "dexpi",
    "ppdm": "ppdm",
    "isa5_1": "isa5_1",
    "isa 5.1": "isa5_1",
    "isa5.1": "isa5_1",
}

# Human-readable display names for markdown tables
_SOURCE_DISPLAY = {
    "iso15926-4": "ISO 15926-4",
    "cfihos": "CFIHOS",
    "posc_caesar": "POSC Caesar",
    "onepetro": "OnePetro",
    "slb_glossary": "SLB Glossary",
    "iso14224": "ISO 14224",
    "dexpi": "DEXPI",
    "ppdm": "PPDM",
    "isa5_1": "ISA 5.1",
}

_SPLIT_RE = re.compile(r"[;,/]+")

# Sources to suppress from the markdown table (LLM hallucinations / placeholder text)
_SOURCE_SUPPRESS = frozenset({
    "all", "all_other_standards", "not_provided", "various", "multiple",
    "all_sources", "other_standards",
})


def normalise_source(raw: str) -> list[str]:
    """Split a (possibly compound) source string and return canonical keys."""
    pieces = [p.strip() for p in _SPLIT_RE.split(raw) if p.strip()]
    result = []
    for p in pieces:
        canon = _SOURCE_CANON.get(p.lower())
        if canon:
            result.append(canon)
        else:
            result.append(p.lower().replace(" ", "_"))
    return result


def normalise_genus(genus: str) -> str:
    if not genus:
        return "(unknown)"
    g = genus.strip()
    return g[0].upper() + g[1:] if g else "(unknown)"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_cluster_data() -> list[dict]:
    """
    Return one dict per cluster (latest record) where divergence_flags IS NOT NULL.
    Each dict: {label, genus, types: set[str], sources: Counter}.
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
    clusters: list[dict] = []

    for row in rows:
        lbl = row["cluster_label"]
        if lbl in seen:
            continue
        seen.add(lbl)

        try:
            flags: list = json.loads(row["divergence_flags"] or "[]")
        except Exception:
            flags = []

        try:
            proposal = json.loads(row["llm_raw_response"] or "{}")
            genus = normalise_genus(
                (proposal.get("step2_genus") or {}).get("genus_name") or ""
            )
        except Exception:
            genus = "(unknown)"

        types: set[str] = set()
        sources: Counter = Counter()
        for f in flags:
            short = _TYPE_SHORT.get(f.get("type", ""), "")
            if short:
                types.add(short)
            for src_raw in (f.get("sources_involved") or []):
                for canon in normalise_source(src_raw):
                    sources[canon] += 1

        clusters.append({
            "label": lbl,
            "genus": genus,
            "types": types,
            "sources": sources,
        })

    return clusters


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def compute_stats(clusters: list[dict]) -> dict:
    total = len(clusters)
    total_with_flags = sum(1 for c in clusters if c["types"])

    # 1. Incidence by type
    incidence: dict[str, dict] = {}
    for t in ALL_TYPES:
        count = sum(1 for c in clusters if t in c["types"])
        incidence[t] = {
            "count": count,
            "percentage": round(100.0 * count / total, 1) if total else 0.0,
        }

    # 2. Co-occurrence matrix
    co_occur: dict[str, int] = {}
    for t1, t2 in combinations(ALL_TYPES, 2):
        count = sum(1 for c in clusters if t1 in c["types"] and t2 in c["types"])
        co_occur[f"{t1}_{t2}"] = count

    # 3. Source divergence counts (aggregate over all clusters)
    all_sources: Counter = Counter()
    for c in clusters:
        all_sources.update(c["sources"])
    sources_sorted = dict(
        sorted(all_sources.items(), key=lambda x: -x[1])
    )

    # 4. By genus (only genera with ≥ 1 cluster; JSON includes all, markdown filters ≥ 3)
    genus_map: dict[str, list[set]] = defaultdict(list)
    for c in clusters:
        genus_map[c["genus"]].append(c["types"])

    by_genus = []
    for genus, type_sets in sorted(genus_map.items(), key=lambda x: -len(x[1])):
        n = len(type_sets)
        gin: dict[str, dict] = {}
        for t in ALL_TYPES:
            cnt = sum(1 for ts in type_sets if t in ts)
            gin[t] = {
                "count": cnt,
                "percentage": round(100.0 * cnt / n, 1) if n else 0.0,
            }
        by_genus.append({
            "genus": genus,
            "n_clusters": n,
            "incidence_by_type": gin,
        })

    return {
        "total_clusters_audited": total,
        "total_clusters_with_flags": total_with_flags,
        "incidence_by_type": incidence,
        "co_occurrence_matrix": co_occur,
        "sources_divergence_count": sources_sorted,
        "by_genus": by_genus,
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def render_markdown(stats: dict) -> str:
    lines: list[str] = []
    total = stats["total_clusters_audited"]
    total_with = stats["total_clusters_with_flags"]

    lines += [
        "# Divergence Typology Report — COPI Enrichment DB",
        "",
        f"**Total clusters audited:** {total}  ",
        f"**Clusters with at least one divergence flag:** "
        f"{total_with} ({round(100.0 * total_with / total, 1) if total else 0}%)",
        "",
        "---",
        "",
    ]

    # --- Section 1: Incidence ---
    lines += [
        "## 1. Incidence by Divergence Type",
        "",
        "| Type | Description | Clusters | % of audited |",
        "|:-----|:------------|--------:|:------------:|",
    ]
    for t in ALL_TYPES:
        v = stats["incidence_by_type"][t]
        lines.append(
            f"| **{t}** | {_TYPE_DESC[t]} | {v['count']} | {v['percentage']}% |"
        )
    lines.append("")

    # --- Section 2: Co-occurrence ---
    lines += [
        "## 2. Co-occurrence Matrix",
        "",
        "_Cell (Ti, Tj): number of clusters exhibiting both types simultaneously._  ",
        "_Diagonal: incidence count for that type._",
        "",
    ]
    header = "| · |" + "".join(f" **{t}** |" for t in ALL_TYPES)
    sep = "|---|" + "|".join("---:" for _ in ALL_TYPES) + "|"
    lines += [header, sep]
    for t1 in ALL_TYPES:
        row_cells = []
        for t2 in ALL_TYPES:
            if t1 == t2:
                row_cells.append(f" **{stats['incidence_by_type'][t1]['count']}** ")
            else:
                key = f"{min(t1, t2)}_{max(t1, t2)}"
                row_cells.append(f" {stats['co_occurrence_matrix'].get(key, 0)} ")
        lines.append(f"| **{t1}** |" + "|".join(row_cells) + "|")
    lines.append("")

    # --- Section 3: Sources ---
    lines += [
        "## 3. Sources Most Frequently Involved in Divergences",
        "",
        "| Source | Times cited in `sources_involved` |",
        "|:-------|----------------------------------:|",
    ]
    for src, cnt in stats["sources_divergence_count"].items():
        if src in _SOURCE_SUPPRESS:
            continue
        display = _SOURCE_DISPLAY.get(src, src)
        lines.append(f"| {display} | {cnt} |")
    lines.append("")

    # --- Section 4: By genus ---
    lines += [
        "## 4. Distribution by Genus",
        "",
        "_(Genera with ≥ 3 clusters)_",
        "",
        "| Genus | N | T1 | T2 | T3 | T4 | T5 |",
        "|:------|--:|---:|---:|---:|---:|---:|",
    ]
    for g in stats["by_genus"]:
        if g["n_clusters"] < 3:
            continue
        inc = g["incidence_by_type"]

        def cell(t: str) -> str:
            v = inc[t]
            return f"{v['count']} ({v['percentage']}%)"

        lines.append(
            f"| {g['genus']} | {g['n_clusters']} |"
            f" {cell('T1')} | {cell('T2')} | {cell('T3')} | {cell('T4')} | {cell('T5')} |"
        )
    lines.append("")

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
        "--output", default="/tmp/divergence_typology_report",
        help="Output path prefix (no extension). Outputs <prefix>.md and <prefix>.json.",
    )
    args = parser.parse_args()

    print("Loading enrichment data...", flush=True)
    clusters = load_cluster_data()
    print(f"  {len(clusters)} clusters loaded", flush=True)

    print("Computing statistics...", flush=True)
    stats = compute_stats(clusters)

    out_prefix = Path(args.output)
    out_md = out_prefix.with_suffix(".md")
    out_json = out_prefix.with_suffix(".json")

    out_md.write_text(render_markdown(stats), encoding="utf-8")
    out_json.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"  Written: {out_md}")
    print(f"  Written: {out_json}")

    # Console summary
    total = stats["total_clusters_audited"]
    print(f"\n{'='*55}")
    print(f"Total clusters audited : {total}")
    print(f"With at least one flag : {stats['total_clusters_with_flags']}")
    print(f"\nIncidence (% of all {total} clusters):")
    for t in ALL_TYPES:
        v = stats["incidence_by_type"][t]
        bar = "█" * int(v["percentage"] / 5)
        print(f"  {t}  {v['count']:3d} / {total}  {v['percentage']:5.1f}%  {bar}")

    print(f"\nCo-occurrence highlights (top 5 pairs):")
    pairs = sorted(stats["co_occurrence_matrix"].items(), key=lambda x: -x[1])
    for key, cnt in pairs[:5]:
        print(f"  {key.replace('_', ' & ')}: {cnt} clusters")

    print(f"\nTop sources by divergence citations:")
    for src, cnt in list(stats["sources_divergence_count"].items())[:6]:
        display = _SOURCE_DISPLAY.get(src, src)
        print(f"  {display:<20}: {cnt}")


if __name__ == "__main__":
    main()
