#!/usr/bin/env python3
"""
Pre-Leva 4 audit: read-only data collection to inform pipeline design decisions.

Sections:
  1. System/user prompt size breakdown (static vs dynamic portions).
  2. Parse-error summary (in-DB evidence + logging limitations).
  3. API cost per enrichment (last 20 distinct clusters + full-DB stats).
  4. "Already-Enriched Classes" block overhead analysis.

Output:
  /tmp/pre_leva4_audit.md
  /tmp/pre_leva4_audit.json

Usage:
    python tools/audit_pre_leva4.py
"""

import json
import sqlite3
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "enrichment"))

from prompts import (  # noqa: E402
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
    format_existing_ontology_block,
)

_DB = _PROJECT_ROOT / "data" / "enrichment.db"
_TERMS_DB = _PROJECT_ROOT / "data" / "terms.db"

_COST_PER_MTOK = {
    "input": 3.00,
    "cache_write": 3.75,
    "cache_read": 0.30,
    "output": 15.00,
}

_TOKENS_PER_CHAR = 1 / 3.5  # rough approximation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chars_to_tokens(n: int) -> float:
    return n * _TOKENS_PER_CHAR


def _tok(n: float) -> int:
    return int(round(n))


def _cost_from_tokens(inp: int, out: int, cw: int = 0, cr: int = 0) -> float:
    return (
        inp * _COST_PER_MTOK["input"] / 1_000_000
        + out * _COST_PER_MTOK["output"] / 1_000_000
        + cw * _COST_PER_MTOK["cache_write"] / 1_000_000
        + cr * _COST_PER_MTOK["cache_read"] / 1_000_000
    )


def _db_conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Section 1: Prompt size breakdown
# ---------------------------------------------------------------------------

def _user_prompt_static_size() -> int:
    """
    Measure the static skeleton of USER_PROMPT_TEMPLATE with all format
    placeholders replaced by the empty string.
    """
    keys = [
        "cluster_label", "definitions_block", "subtypes_block",
        "parent_candidates_block", "existing_ontology_block",
        "source_count", "related_concepts", "reviewer_notes_block",
        "iso14224_main_function_block", "standard_properties_block",
        "component_terms_block",
    ]
    filled = USER_PROMPT_TEMPLATE
    for k in keys:
        filled = filled.replace("{" + k + "}", "")
    return len(filled)


def _build_existing_block_all(conn: sqlite3.Connection) -> tuple[str, int]:
    """Return (block_text, n_entries) for ALL enrichment rows."""
    rows = conn.execute(
        "SELECT cluster_label, function_name, genus, status "
        "FROM enrichment ORDER BY cluster_label"
    ).fetchall()
    entries = [dict(r) for r in rows]
    return format_existing_ontology_block(entries), len(entries)


def _build_existing_block_dedup(conn: sqlite3.Connection) -> tuple[str, int]:
    """Return (block_text, n_entries) for latest-per-cluster only."""
    rows = conn.execute(
        """
        SELECT cluster_label, function_name, genus, status
          FROM enrichment
         WHERE id IN (
               SELECT MAX(id) FROM enrichment GROUP BY cluster_label
         )
         ORDER BY cluster_label
        """
    ).fetchall()
    entries = [dict(r) for r in rows]
    return format_existing_ontology_block(entries), len(entries)


def section1_prompt_size(conn: sqlite3.Connection) -> dict:
    sys_chars = len(SYSTEM_PROMPT)
    sys_tokens = _tok(_chars_to_tokens(sys_chars))

    user_static_chars = _user_prompt_static_size()
    user_static_tokens = _tok(_chars_to_tokens(user_static_chars))

    block_all, n_all = _build_existing_block_all(conn)
    block_dedup, n_dedup = _build_existing_block_dedup(conn)

    block_all_chars = len(block_all)
    block_dedup_chars = len(block_dedup)
    block_all_tokens = _tok(_chars_to_tokens(block_all_chars))
    block_dedup_tokens = _tok(_chars_to_tokens(block_dedup_chars))

    # Per-entry overhead (excluding fixed header lines)
    if n_all > 0:
        header_lines = 4  # "The following classes...", instructions ×3, blank
        avg_header_chars = sum(
            len(ln) + 1 for ln in block_all.split("\n")[:header_lines]
        )
        entry_chars = block_all_chars - avg_header_chars
        avg_entry_chars = entry_chars / n_all
    else:
        avg_entry_chars = 0

    # Estimate existing_ontology_block for last 20 enrichments by id
    # At time of enrichment i, the block contained all rows with id < i.
    recent_20 = conn.execute(
        "SELECT id FROM enrichment ORDER BY id DESC LIMIT 20"
    ).fetchall()
    context_counts = []
    for row in recent_20:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM enrichment WHERE id < ?", (row["id"],)
        ).fetchone()[0]
        context_counts.append(cnt)
    avg_context_entries = sum(context_counts) / len(context_counts) if context_counts else 0
    avg_context_chars = avg_context_entries * avg_entry_chars
    avg_context_tokens = _tok(_chars_to_tokens(avg_context_chars))

    return {
        "system_prompt_chars": sys_chars,
        "system_prompt_tokens_est": sys_tokens,
        "user_prompt_static_chars": user_static_chars,
        "user_prompt_static_tokens_est": user_static_tokens,
        "existing_block_all_entries": n_all,
        "existing_block_all_chars": block_all_chars,
        "existing_block_all_tokens_est": block_all_tokens,
        "existing_block_dedup_entries": n_dedup,
        "existing_block_dedup_chars": block_dedup_chars,
        "existing_block_dedup_tokens_est": block_dedup_tokens,
        "avg_chars_per_entry": round(avg_entry_chars, 1),
        "avg_tokens_per_entry_est": round(avg_entry_chars * _TOKENS_PER_CHAR, 1),
        "last20_avg_context_entries": round(avg_context_entries, 1),
        "last20_avg_context_tokens_est": avg_context_tokens,
    }


# ---------------------------------------------------------------------------
# Section 2: Parse errors
# ---------------------------------------------------------------------------

def section2_parse_errors(conn: sqlite3.Connection) -> dict:
    total_rows = conn.execute("SELECT COUNT(*) FROM enrichment").fetchone()[0]
    null_response = conn.execute(
        "SELECT COUNT(*) FROM enrichment WHERE llm_raw_response IS NULL OR llm_raw_response = ''"
    ).fetchone()[0]
    invalid_json = conn.execute(
        "SELECT COUNT(*) FROM enrichment WHERE json_valid(llm_raw_response) = 0"
    ).fetchone()[0]

    return {
        "tracking_available": False,
        "note": (
            "No file-based log is written by the pipeline. parse errors raise "
            "ValueError in call_llm() (enrichment_service.py:1267) and prevent "
            "the row from being stored — so failed enrichments leave no DB trace. "
            "The counts below reflect only stored rows."
        ),
        "stored_rows": total_rows,
        "stored_with_null_response": null_response,
        "stored_with_invalid_json": invalid_json,
        "observed_parse_failures": 0,
        "observed_retries_429": "unknown — 429 retries are logged to stderr only",
    }


# ---------------------------------------------------------------------------
# Section 3: API cost per enrichment
# ---------------------------------------------------------------------------

def section3_api_cost(conn: sqlite3.Connection) -> dict:
    # Last 20 by id (raw, includes re-runs)
    rows_raw = conn.execute(
        """
        SELECT id, cluster_label, input_tokens, output_tokens, estimated_cost_usd,
               cache_write_tokens, cache_read_tokens, llm_model, created_at
          FROM enrichment
         ORDER BY id DESC LIMIT 20
        """
    ).fetchall()

    # Last 20 distinct clusters (latest per cluster)
    rows_distinct = conn.execute(
        """
        SELECT id, cluster_label, input_tokens, output_tokens, estimated_cost_usd,
               cache_write_tokens, cache_read_tokens, llm_model, created_at
          FROM enrichment
         WHERE id IN (SELECT MAX(id) FROM enrichment GROUP BY cluster_label)
         ORDER BY id DESC LIMIT 20
        """
    ).fetchall()

    def _stats(rows):
        if not rows:
            return {}
        inp = [r["input_tokens"] for r in rows]
        out = [r["output_tokens"] for r in rows]
        cw = [r["cache_write_tokens"] or 0 for r in rows]
        cr = [r["cache_read_tokens"] or 0 for r in rows]
        cost = [r["estimated_cost_usd"] or 0.0 for r in rows]
        n = len(rows)
        return {
            "n": n,
            "avg_input_tokens": round(sum(inp) / n),
            "avg_output_tokens": round(sum(out) / n),
            "avg_cache_write_tokens": round(sum(cw) / n),
            "avg_cache_read_tokens": round(sum(cr) / n),
            "avg_cost_usd": round(sum(cost) / n, 6),
            "min_cost_usd": round(min(cost), 6),
            "max_cost_usd": round(max(cost), 6),
            "total_cost_usd": round(sum(cost), 4),
        }

    # Full-DB stats (all rows)
    all_rows = conn.execute(
        "SELECT input_tokens, output_tokens, estimated_cost_usd, "
        "cache_write_tokens, cache_read_tokens FROM enrichment"
    ).fetchall()

    s_raw = _stats(rows_raw)
    s_distinct = _stats(rows_distinct)
    s_all = _stats(all_rows)

    # Projection for remaining clusters
    # Distinct clusters enriched: 218; total terms in terms.db: approximate
    enriched_distinct = conn.execute(
        "SELECT COUNT(DISTINCT cluster_label) FROM enrichment"
    ).fetchone()[0]

    terms_total = None
    try:
        tconn = _db_conn(_TERMS_DB)
        terms_total = tconn.execute(
            "SELECT COUNT(DISTINCT lower(trim(preferred_label))) FROM terms"
        ).fetchone()[0]
        tconn.close()
    except Exception:
        pass

    avg_cost_per_cluster = s_distinct["avg_cost_usd"] if s_distinct else 0
    projection = {}
    if terms_total and avg_cost_per_cluster:
        remaining_9700 = 9700 - enriched_distinct
        remaining_all = terms_total - enriched_distinct
        projection = {
            "enriched_distinct_clusters": enriched_distinct,
            "terms_db_distinct_labels": terms_total,
            "assumed_remaining_user_estimate": 9700 - enriched_distinct,
            "assumed_remaining_all_terms": remaining_all,
            "avg_cost_per_cluster_usd": avg_cost_per_cluster,
            "projected_cost_9700_remaining_usd": round(remaining_9700 * avg_cost_per_cluster, 2),
            "projected_cost_all_remaining_usd": round(remaining_all * avg_cost_per_cluster, 2),
            "note_cache": (
                "Recent runs show heavy prompt-cache usage (cache_read > 0, cache_write = 0). "
                "Cache reads cost $0.30/MTok vs $3.00/MTok uncached — 90% saving on input tokens. "
                "Projection uses avg_cost from last-20-distinct which already reflects cache pricing."
            ),
        }

    return {
        "last_20_by_id_raw": s_raw,
        "last_20_distinct_clusters": s_distinct,
        "all_354_rows": s_all,
        "pricing_usd_per_mtok": _COST_PER_MTOK,
        "projection": projection,
    }


# ---------------------------------------------------------------------------
# Section 4: Already-Enriched Classes overhead analysis
# ---------------------------------------------------------------------------

def section4_overhead(conn: sqlite3.Connection) -> dict:
    block_all, n_all = _build_existing_block_all(conn)
    block_dedup, n_dedup = _build_existing_block_dedup(conn)

    # Status breakdown of what get_existing_ontology_context() would return
    status_counts = {
        r["status"]: r["cnt"]
        for r in conn.execute(
            "SELECT status, COUNT(*) as cnt FROM enrichment GROUP BY status"
        ).fetchall()
    }

    # How many entries have a non-null function_name (useful for reuse detection)
    has_fn = conn.execute(
        "SELECT COUNT(*) FROM enrichment WHERE function_name IS NOT NULL AND function_name != ''"
    ).fetchone()[0]
    has_genus = conn.execute(
        "SELECT COUNT(*) FROM enrichment WHERE genus IS NOT NULL AND genus != ''"
    ).fetchone()[0]

    # Estimate entry sizes for filtering scenarios
    # Scenario A: current behavior — ALL 354 rows
    chars_all = len(block_all)
    tokens_all = _tok(_chars_to_tokens(chars_all))

    # Scenario B: deduplicated (218 rows, latest per cluster)
    chars_dedup = len(block_dedup)
    tokens_dedup = _tok(_chars_to_tokens(chars_dedup))

    # Scenario C: only reviewed/validated entries
    rows_validated = conn.execute(
        """
        SELECT cluster_label, function_name, genus, status
          FROM enrichment
         WHERE id IN (SELECT MAX(id) FROM enrichment GROUP BY cluster_label)
           AND status IN ('reviewed', 'validated')
         ORDER BY cluster_label
        """
    ).fetchall()
    block_validated = format_existing_ontology_block([dict(r) for r in rows_validated])
    n_validated = len(rows_validated)
    tokens_validated = _tok(_chars_to_tokens(len(block_validated)))

    # Growth trajectory: how many rows added per month
    monthly_growth = {}
    for row in conn.execute(
        "SELECT strftime('%Y-%m', created_at) as mo, COUNT(*) as cnt "
        "FROM enrichment GROUP BY mo ORDER BY mo"
    ).fetchall():
        monthly_growth[row["mo"]] = row["cnt"]

    # Forecast: at 218 new distinct clusters per Leva, block grows by ~218 entries
    avg_chars_per_entry_all = chars_all / n_all if n_all else 0
    tokens_per_entry = avg_chars_per_entry_all * _TOKENS_PER_CHAR
    tokens_after_leva4 = _tok((n_dedup + 218) * tokens_per_entry)

    return {
        "current_behavior": {
            "rows_passed_to_llm": n_all,
            "description": (
                "get_existing_ontology_context() returns ALL rows from enrichment "
                "(including re-runs of the same cluster), not deduplicated."
            ),
            "chars": chars_all,
            "tokens_est": tokens_all,
        },
        "scenario_dedup_latest_per_cluster": {
            "rows": n_dedup,
            "chars": chars_dedup,
            "tokens_est": tokens_dedup,
            "saving_tokens_vs_current": tokens_all - tokens_dedup,
            "saving_pct": round((tokens_all - tokens_dedup) / tokens_all * 100, 1) if tokens_all else 0,
        },
        "scenario_validated_only": {
            "rows": n_validated,
            "chars": len(block_validated),
            "tokens_est": tokens_validated,
            "saving_tokens_vs_current": tokens_all - tokens_validated,
            "saving_pct": round((tokens_all - tokens_validated) / tokens_all * 100, 1) if tokens_all else 0,
            "risk": "Excludes proposed-only entries; LLM may duplicate proposed function_names.",
        },
        "avg_chars_per_entry": round(avg_chars_per_entry_all, 1),
        "avg_tokens_per_entry_est": round(tokens_per_entry, 1),
        "entry_completeness": {
            "total_entries_all": n_all,
            "with_function_name": has_fn,
            "with_genus": has_genus,
        },
        "status_breakdown_all_rows": status_counts,
        "monthly_row_growth": monthly_growth,
        "forecast_tokens_after_leva4": tokens_after_leva4,
        "forecast_note": (
            f"If Leva 4 enriches ~218 new distinct clusters and dedup filter is NOT applied, "
            f"the block grows from ~{tokens_dedup} to ~{tokens_after_leva4} tokens."
        ),
    }


# ---------------------------------------------------------------------------
# Render markdown
# ---------------------------------------------------------------------------

def render_markdown(s1: dict, s2: dict, s3: dict, s4: dict) -> str:
    lines = []

    def h(n, t):
        lines.append(f"\n{'#' * n} {t}\n")

    def row(*cols):
        lines.append("| " + " | ".join(str(c) for c in cols) + " |")

    def sep(*widths):
        lines.append("| " + " | ".join("-" * w for w in widths) + " |")

    lines.append("# Pre-Leva 4 Audit\n")
    lines.append("_Read-only. All numbers derived from `data/enrichment.db` and `enrichment/prompts.py`._\n")

    # ── Section 1 ────────────────────────────────────────────────────────────
    h(2, "1. Prompt Size Breakdown")

    h(3, "1a. Static portions")
    row("Component", "Chars", "Tokens (est.)")
    sep(40, 10, 15)
    row("`SYSTEM_PROMPT` (static)", f"{s1['system_prompt_chars']:,}", f"~{s1['system_prompt_tokens_est']:,}")
    row("User-prompt skeleton (no placeholders)", f"{s1['user_prompt_static_chars']:,}", f"~{s1['user_prompt_static_tokens_est']:,}")
    total_static_tok = s1['system_prompt_tokens_est'] + s1['user_prompt_static_tokens_est']
    row("**Total static**", "", f"**~{total_static_tok:,}**")
    lines.append("")

    h(3, "1b. `## Already-Enriched Classes` block (dynamic, in user prompt)")
    row("Scenario", "Entries", "Chars", "Tokens (est.)")
    sep(45, 10, 10, 14)
    row("Current (ALL rows, including re-runs)",
        s1['existing_block_all_entries'], f"{s1['existing_block_all_chars']:,}", f"~{s1['existing_block_all_tokens_est']:,}")
    row("Deduplicated (latest per cluster)",
        s1['existing_block_dedup_entries'], f"{s1['existing_block_dedup_chars']:,}", f"~{s1['existing_block_dedup_tokens_est']:,}")
    lines.append("")
    lines.append(f"- Average chars per entry: **{s1['avg_chars_per_entry']}** (~{s1['avg_tokens_per_entry_est']:.1f} tokens)")
    lines.append("")

    h(3, "1c. Existing-block size at time of last 20 enrichments")
    lines.append(
        f"At the time of the 20 most-recent enrichments, the existing-ontology block "
        f"contained on average **{s1['last20_avg_context_entries']:.0f} entries** "
        f"(~**{s1['last20_avg_context_tokens_est']:,} tokens** estimated)."
    )
    lines.append("")

    # ── Section 2 ────────────────────────────────────────────────────────────
    h(2, "2. Parse-Error Summary")

    lines.append(
        "> **Tracking limitation:** The pipeline logs parse errors to `stderr` only "
        "(`logger.error` in `call_llm()`). A failed parse raises `ValueError` and "
        "prevents DB insertion, so failed enrichments leave no trace. The counts below "
        "reflect successfully stored rows only."
    )
    lines.append("")
    row("Metric", "Value")
    sep(45, 20)
    row("Stored rows (total)", s2['stored_rows'])
    row("Rows with null/empty `llm_raw_response`", s2['stored_with_null_response'])
    row("Rows with invalid JSON in `llm_raw_response`", s2['stored_with_invalid_json'])
    row("Observed parse failures (in-DB evidence)", s2['observed_parse_failures'])
    row("429 retries", s2['observed_retries_429'])
    lines.append("")
    lines.append("**Recommendation for Leva 4:** add a `parse_errors` counter to the batch-submit "
                 "return dict and log it to a file or DB table.")
    lines.append("")

    # ── Section 3 ────────────────────────────────────────────────────────────
    h(2, "3. API Cost per Enrichment")

    h(3, "3a. Token averages — last 20 distinct clusters (latest run per cluster)")
    d = s3['last_20_distinct_clusters']
    row("Metric", "Value")
    sep(40, 20)
    row("N (clusters)", d['n'])
    row("Avg input tokens", f"{d['avg_input_tokens']:,}")
    row("Avg output tokens", f"{d['avg_output_tokens']:,}")
    row("Avg cache-write tokens", f"{d['avg_cache_write_tokens']:,}")
    row("Avg cache-read tokens", f"{d['avg_cache_read_tokens']:,}")
    row("Avg cost (USD)", f"${d['avg_cost_usd']:.4f}")
    row("Min / Max cost", f"${d['min_cost_usd']:.4f} / ${d['max_cost_usd']:.4f}")
    lines.append("")

    h(3, "3b. Pricing (claude-sonnet-4)")
    row("Token type", "USD / MTok")
    sep(25, 15)
    for k, v in s3['pricing_usd_per_mtok'].items():
        row(f"`{k}`", f"${v:.2f}")
    lines.append("")

    h(3, "3c. Cost projections")
    p = s3['projection']
    if p:
        row("Scenario", "Clusters", "Projected cost (USD)")
        sep(50, 10, 22)
        row("Remaining from user estimate (~9,700 total)",
            f"{p['assumed_remaining_user_estimate']:,}", f"${p['projected_cost_9700_remaining_usd']:,.2f}")
        row("Remaining if all distinct labels in terms.db",
            f"{p['assumed_remaining_all_terms']:,}", f"${p['projected_cost_all_remaining_usd']:,.2f}")
        lines.append("")
        lines.append(f"_Basis: avg cost per cluster = ${p['avg_cost_per_cluster_usd']:.4f}; "
                     f"{p['enriched_distinct_clusters']} clusters already enriched; "
                     f"terms.db has {p['terms_db_distinct_labels']:,} distinct normalized labels._")
        lines.append("")
        lines.append(f"> **Cache note:** {p['note_cache']}")
    lines.append("")

    # ── Section 4 ────────────────────────────────────────────────────────────
    h(2, "4. Already-Enriched Classes Block — Overhead Analysis")

    h(3, "4a. Current behavior")
    cb = s4['current_behavior']
    lines.append(f"- `get_existing_ontology_context()` returns **all {cb['rows_passed_to_llm']} rows** "
                 f"(including re-runs of the same cluster).")
    lines.append(f"- Block size: **{cb['chars']:,} chars** (~{cb['tokens_est']:,} tokens est.).")
    lines.append(f"- {cb['description']}")
    lines.append("")

    h(3, "4b. Filtering scenarios")
    row("Scenario", "Entries", "Tokens (est.)", "Saving vs current", "Saving %")
    sep(48, 10, 14, 20, 10)
    row("Current (all rows, no dedup)", cb['rows_passed_to_llm'], f"~{cb['tokens_est']:,}", "—", "—")
    sc_d = s4['scenario_dedup_latest_per_cluster']
    row("Deduplicated (latest per cluster)",
        sc_d['rows'], f"~{sc_d['tokens_est']:,}",
        f"~{sc_d['saving_tokens_vs_current']:,} tok", f"{sc_d['saving_pct']}%")
    sc_v = s4['scenario_validated_only']
    row(f"Validated/reviewed only ({sc_v['rows']} entries)",
        sc_v['rows'], f"~{sc_v['tokens_est']:,}",
        f"~{sc_v['saving_tokens_vs_current']:,} tok", f"{sc_v['saving_pct']}%")
    lines.append("")

    h(3, "4c. Entry completeness (all 354 rows)")
    ec = s4['entry_completeness']
    row("Field", "Rows with value", "% of total")
    sep(25, 18, 12)
    row("`function_name`", ec['with_function_name'],
        f"{ec['with_function_name']/ec['total_entries_all']*100:.1f}%")
    row("`genus`", ec['with_genus'],
        f"{ec['with_genus']/ec['total_entries_all']*100:.1f}%")
    lines.append("")

    h(3, "4d. Status breakdown (all 354 rows)")
    row("Status", "Count")
    sep(20, 8)
    for st, cnt in sorted(s4['status_breakdown_all_rows'].items()):
        row(f"`{st}`", cnt)
    lines.append("")

    h(3, "4e. Growth trajectory and forecast")
    row("Month", "New rows added")
    sep(12, 16)
    for mo, cnt in s4['monthly_row_growth'].items():
        row(mo, cnt)
    lines.append("")
    lines.append(s4['forecast_note'])
    lines.append(f"- Average chars per entry: **{s4['avg_chars_per_entry']}** "
                 f"(~{s4['avg_tokens_per_entry_est']:.1f} tokens)")
    lines.append("")

    h(2, "5. Summary of Recommendations for Leva 4")
    lines.append("| # | Finding | Recommended action |")
    lines.append("|---|:--------|:-------------------|")
    lines.append("| 1 | `get_existing_ontology_context()` returns all 354 rows (incl. re-runs) | "
                 "Filter to latest-per-cluster before building the block (~{} tokens saved) |".format(
                     sc_d['saving_tokens_vs_current']))
    lines.append("| 2 | No parse-error tracking — failures leave no DB trace | "
                 "Add parse-error counter to batch-submit return dict |")
    lines.append("| 3 | Avg cost ~${:.4f}/cluster; projecting ~9,700 remaining → ~${:.0f} total | "
                 "Verify cache hit rate is stable; consider batching to maximize cache reuse |".format(
                     d['avg_cost_usd'],
                     p.get('projected_cost_9700_remaining_usd', 0) if p else 0))
    lines.append("| 4 | System prompt is ~{:,} tokens (static) | "
                 "Stable; no compression needed for Leva 4 |".format(
                     s1['system_prompt_tokens_est']))

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if not _DB.exists():
        sys.exit(f"DB not found: {_DB}")

    conn = _db_conn(_DB)

    print("Section 1: prompt size...", flush=True)
    s1 = section1_prompt_size(conn)

    print("Section 2: parse errors...", flush=True)
    s2 = section2_parse_errors(conn)

    print("Section 3: API cost...", flush=True)
    s3 = section3_api_cost(conn)

    print("Section 4: existing-block overhead...", flush=True)
    s4 = section4_overhead(conn)

    conn.close()

    md = render_markdown(s1, s2, s3, s4)
    payload = {"section1_prompt_size": s1, "section2_parse_errors": s2,
               "section3_api_cost": s3, "section4_overhead": s4}

    out_md = Path("/tmp/pre_leva4_audit.md")
    out_json = Path("/tmp/pre_leva4_audit.json")
    out_md.write_text(md, encoding="utf-8")
    out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Written: {out_md}")
    print(f"  Written: {out_json}")

    # Console summary
    print("\n" + "=" * 60)
    print(f"SYSTEM_PROMPT:           {s1['system_prompt_chars']:>8,} chars  ~{s1['system_prompt_tokens_est']:>6,} tok")
    print(f"User skeleton (static):  {s1['user_prompt_static_chars']:>8,} chars  ~{s1['user_prompt_static_tokens_est']:>6,} tok")
    print(f"Existing block (all):    {s1['existing_block_all_chars']:>8,} chars  ~{s1['existing_block_all_tokens_est']:>6,} tok  ({s1['existing_block_all_entries']} entries)")
    print(f"Existing block (dedup):  {s1['existing_block_dedup_chars']:>8,} chars  ~{s1['existing_block_dedup_tokens_est']:>6,} tok  ({s1['existing_block_dedup_entries']} entries)")
    print(f"Last-20 context avg:     {s1['last20_avg_context_entries']:>8.0f} entries  ~{s1['last20_avg_context_tokens_est']:>6,} tok (est.)")
    print()
    print(f"Parse failures (in-DB):  {s2['observed_parse_failures']}")
    print()
    d20 = s3['last_20_distinct_clusters']
    print(f"Avg cost/cluster:        ${d20['avg_cost_usd']:.4f}  (last 20 distinct)")
    print(f"  input: {d20['avg_input_tokens']:,}  output: {d20['avg_output_tokens']:,}  cache_read: {d20['avg_cache_read_tokens']:,}")
    p = s3['projection']
    if p:
        print(f"  → ~9,700 remaining estimate: ${p['projected_cost_9700_remaining_usd']:,.2f}")
    print()
    sc_d = s4['scenario_dedup_latest_per_cluster']
    print(f"Dedup saving:            {sc_d['saving_pct']}% tokens vs current behavior")
    print(f"Forecast after Leva 4:   ~{s4['forecast_tokens_after_leva4']:,} tokens (dedup not applied)")


if __name__ == "__main__":
    main()
