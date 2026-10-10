#!/usr/bin/env python3
"""
Backfill divergence_flags for enrichment records that have none, by calling the LLM
with an isolated prompt that asks ONLY for cross-standard divergence detection (T1-T5).
Also compares LLM-detected flags with existing divergence_log entries.

Modes:
  --dry-run   (default): show pending count + existing divergence_log T1-T5 distribution.
              No LLM calls.
  --sample N: process exactly N records via LLM (no DB writes), print T1-T5 distribution
              and comparison with existing divergence_log. Useful for prompt calibration.
  --apply [--limit N]: full backfill (or first N records). Writes divergence_flags to
              enrichment table and inserts into divergence_log with detected_by='llm'.
              Creates a DB backup before first write.

Usage:
    python tools/extract_divergence_flags.py --dry-run
    python tools/extract_divergence_flags.py --sample 10
    python tools/extract_divergence_flags.py --apply --limit 50
    python tools/extract_divergence_flags.py --apply
"""

import argparse
import asyncio
import json
import os
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import httpx

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DB_PATH = _PROJECT_ROOT / "data" / "enrichment.db"
_TERMS_DB_PATH = _PROJECT_ROOT / "data" / "terms.db"

_ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
_DEFAULT_MODEL = "claude-sonnet-4-20250514"

_TYPE_SHORT = {
    "T1_categorical": "T1",
    "T2_granularity": "T2",
    "T3_identity": "T3",
    "T4_topological": "T4",
    "T5_implicit_function": "T5",
}

_TYPE_LONG = {v: k for k, v in _TYPE_SHORT.items()}

_SYSTEM_PROMPT = """\
You are an ontology engineer specializing in cross-standard divergence analysis for industrial equipment ontologies.

Given definitions of an equipment concept from multiple industrial standards, identify divergences according to the T1-T5 typology:

- T1_categorical: the term is classified under incompatible ontological categories in different sources
- T2_granularity: markedly different number of subtypes or specified properties across sources
- T3_identity: identity criteria diverge (physical artifact in one source vs functional type in another)
- T4_topological: mereological/topological relations (part-of, connected-to) diverge
- T5_implicit_function: one source defines the function explicitly, another defines only structure

Report ONLY divergences with concrete evidence in the provided definitions.
Return ONLY a JSON object with no markdown, no preamble:
{"divergence_flags": [{"type": "<T1_categorical|T2_granularity|T3_identity|T4_topological|T5_implicit_function>", "evidence": "<concrete observation referencing sources>", "sources_involved": ["<source1>", "<source2>"]}]}
If no divergences, return {"divergence_flags": []}.
"""


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _open_enrichment_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _open_terms_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_TERMS_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _load_pending_records(conn: sqlite3.Connection) -> list[dict]:
    """
    Return one dict per cluster (latest enrichment row) where divergence_flags
    is NULL. An explicit '[]' means "processed, no divergences" and is excluded.
    Uses ORDER BY id DESC + Python dedup to get the most recent row per cluster.
    """
    rows = conn.execute(
        """
        SELECT id, cluster_label, source_definitions_used, divergence_flags
          FROM enrichment
         ORDER BY id DESC
        """
    ).fetchall()

    seen: set = set()
    pending: list[dict] = []
    for row in rows:
        label = row["cluster_label"]
        if label in seen:
            continue
        seen.add(label)

        # NULL means not yet processed; explicit '[]' means processed with no divergences
        if row["divergence_flags"] is not None:
            continue

        src_defs_raw = row["source_definitions_used"] or "[]"
        try:
            src_defs = json.loads(src_defs_raw)
        except Exception:
            src_defs = []

        pending.append({
            "id": row["id"],
            "cluster_label": label,
            "source_definitions_used": src_defs,
        })

    return pending


def _fetch_definitions(cluster_label: str, terms_conn: sqlite3.Connection) -> list[dict]:
    """
    Return a list of {"source": ..., "label": ..., "definition": ...} dicts
    for the given cluster_label. Matches on preferred_label (case-insensitive).
    Deduplicates by (source, label) keeping first.
    """
    rows = terms_conn.execute(
        """
        SELECT source, preferred_label AS label, definition
          FROM terms
         WHERE lower(preferred_label) LIKE lower(?)
           AND definition IS NOT NULL
         ORDER BY source
        """,
        (f"%{cluster_label}%",),
    ).fetchall()

    seen: set = set()
    results: list[dict] = []
    for row in rows:
        key = (row["source"], row["label"])
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "source": row["source"],
            "label": row["label"],
            "definition": row["definition"],
        })
    return results


def _build_definitions_block(defs: list[dict]) -> str:
    """Format definitions as '[SOURCE] label: definition' lines."""
    lines = []
    for d in defs:
        src = d["source"].upper()
        lbl = d["label"]
        defn = (d["definition"] or "").strip().replace("\n", " ")
        lines.append(f"[{src}] {lbl}: {defn}")
    return "\n".join(lines)


def get_divergence_stats(conn: sqlite3.Connection) -> dict:
    """Return T1-T5 counts and percentages from divergence_log."""
    rows = conn.execute(
        """
        SELECT divergence_type, COUNT(*) AS cnt
          FROM divergence_log
         GROUP BY divergence_type
         ORDER BY divergence_type
        """
    ).fetchall()
    total = sum(r["cnt"] for r in rows)
    stats = {}
    for row in rows:
        t = row["divergence_type"]
        cnt = row["cnt"]
        stats[t] = {"count": cnt, "pct": round(100.0 * cnt / total, 1) if total else 0.0}
    return stats


def _print_divergence_stats(conn: sqlite3.Connection) -> None:
    stats = get_divergence_stats(conn)
    total = sum(v["count"] for v in stats.values())
    print(f"\nDivergence log summary ({total} total entries):")
    print(f"  {'Type':<6}  {'Count':>6}  {'%':>6}")
    print(f"  {'------':<6}  {'------':>6}  {'------':>6}")
    for t in ("T1", "T2", "T3", "T4", "T5"):
        v = stats.get(t, {"count": 0, "pct": 0.0})
        print(f"  {t:<6}  {v['count']:>6}  {v['pct']:>5.1f}%")


# ---------------------------------------------------------------------------
# LLM call (standalone, using httpx directly)
# ---------------------------------------------------------------------------

async def _call_llm_divergence(
    cluster_label: str,
    definitions_block: str,
    api_key: str,
    model: str,
) -> list[dict]:
    """
    Call Anthropic API for divergence detection.
    Returns a list of divergence flag dicts (may be empty).
    Retries up to 3 times on 429 with exponential backoff.
    """
    user_prompt = (
        f"## Equipment Concept: {cluster_label}\n\n"
        f"## Definitions from Industrial Standards:\n\n"
        f"{definitions_block}"
    )

    payload = {
        "model": model,
        "max_tokens": 1024,
        "temperature": 0,
        "system": [
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [{"role": "user", "content": user_prompt}],
    }
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "prompt-caching-2024-07-31",
    }

    backoffs = [10, 30, 60]
    for attempt, backoff in enumerate([0] + backoffs):
        if backoff:
            print(f"  [429 rate limit] retrying in {backoff}s (attempt {attempt}/{len(backoffs)})...")
            await asyncio.sleep(backoff)
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(_ANTHROPIC_API_URL, headers=headers, json=payload)
        if response.status_code == 429 and attempt < len(backoffs):
            continue
        response.raise_for_status()
        break

    data = response.json()
    text = ""
    for block in data.get("content", []):
        if block.get("type") == "text":
            text += block.get("text", "")

    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM returned invalid JSON for '{cluster_label}': {exc}\nRaw: {text[:300]}")

    return result.get("divergence_flags", [])


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------

def _get_existing_flags_for_clusters(
    conn: sqlite3.Connection,
    cluster_labels: list[str],
) -> dict[str, set[str]]:
    """
    Return {cluster_label: set_of_short_types} from divergence_log.
    Maps T1_categorical → T1, etc.
    """
    if not cluster_labels:
        return {}

    placeholders = ",".join("?" * len(cluster_labels))
    rows = conn.execute(
        f"SELECT cluster_label, divergence_type FROM divergence_log WHERE cluster_label IN ({placeholders})",
        cluster_labels,
    ).fetchall()

    result: dict[str, set[str]] = {}
    for row in rows:
        lbl = row["cluster_label"]
        dt = row["divergence_type"]  # already "T1", "T2", etc.
        result.setdefault(lbl, set()).add(dt)
    return result


def _compare_flags(
    llm_flags: list[dict],
    existing_types: set[str],
) -> dict:
    """
    Compare LLM flags vs existing divergence_log entries.
    Returns dict with 'only_llm', 'only_existing', 'both' sets.
    """
    llm_types: set[str] = set()
    for f in llm_flags:
        short = _TYPE_SHORT.get(f.get("type", ""), "")
        if short:
            llm_types.add(short)

    return {
        "only_llm": llm_types - existing_types,
        "only_existing": existing_types - llm_types,
        "both": llm_types & existing_types,
    }


def _print_comparison_table(
    processed: list[dict],
    existing_map: dict[str, set[str]],
) -> None:
    """
    Print per-cluster comparison table and aggregate discrepancy rate.
    processed: list of {"cluster_label": ..., "flags": [...]}
    """
    print("\nPer-cluster comparison (LLM vs existing divergence_log):")
    print(f"  {'Cluster':<35}  {'Only LLM':<20}  {'Only existing':<25}  {'Both':<20}")
    print(f"  {'-'*35}  {'-'*20}  {'-'*25}  {'-'*20}")

    total_clusters = len(processed)
    discrepant = 0

    for item in processed:
        lbl = item["cluster_label"]
        existing = existing_map.get(lbl, set())
        comp = _compare_flags(item["flags"], existing)
        only_llm_s = ", ".join(sorted(comp["only_llm"])) or "-"
        only_ex_s = ", ".join(sorted(comp["only_existing"])) or "-"
        both_s = ", ".join(sorted(comp["both"])) or "-"
        if comp["only_llm"] or comp["only_existing"]:
            discrepant += 1
        lbl_display = lbl[:33] + ".." if len(lbl) > 35 else lbl
        print(f"  {lbl_display:<35}  {only_llm_s:<20}  {only_ex_s:<25}  {both_s:<20}")

    rate = round(100.0 * discrepant / total_clusters, 1) if total_clusters else 0.0
    print(f"\nDiscrepancy rate: {discrepant}/{total_clusters} clusters ({rate}%) have at least one mismatch.")


def _print_llm_distribution(processed: list[dict]) -> None:
    """Print T1-T5 distribution of LLM-returned flags."""
    type_counts: Counter = Counter()
    for item in processed:
        for f in item["flags"]:
            short = _TYPE_SHORT.get(f.get("type", ""), "")
            if short:
                type_counts[short] += 1

    total_flags = sum(type_counts.values())
    print(f"\nLLM flag distribution ({len(processed)} clusters, {total_flags} total flags):")
    print(f"  {'Type':<6}  {'Count':>6}  {'%':>6}")
    print(f"  {'------':<6}  {'------':>6}  {'------':>6}")
    for t in ("T1", "T2", "T3", "T4", "T5"):
        cnt = type_counts.get(t, 0)
        pct = round(100.0 * cnt / total_flags, 1) if total_flags else 0.0
        print(f"  {t:<6}  {cnt:>6}  {pct:>5.1f}%")


# ---------------------------------------------------------------------------
# Core async runner
# ---------------------------------------------------------------------------

async def _process_records(
    records: list[dict],
    api_key: str,
    model: str,
    terms_conn: sqlite3.Connection,
) -> list[dict]:
    """
    Process each record via LLM. Returns list of
    {"cluster_label": ..., "id": ..., "flags": [...]} dicts.
    Short sleep between calls to avoid rate limiting.
    """
    total = len(records)
    results: list[dict] = []

    for i, rec in enumerate(records, start=1):
        label = rec["cluster_label"]
        print(f"[{i}/{total}] {label}...", end=" ", flush=True)

        defs = _fetch_definitions(label, terms_conn)
        if not defs:
            print("(no definitions found — skipped)")
            results.append({"cluster_label": label, "id": rec["id"], "flags": []})
            continue

        defs_block = _build_definitions_block(defs)
        try:
            flags = await _call_llm_divergence(label, defs_block, api_key, model)
            short_types = [_TYPE_SHORT.get(f.get("type", ""), "?") for f in flags]
            print(f"{len(flags)} flag(s): {', '.join(short_types) if short_types else 'none'}")
            results.append({"cluster_label": label, "id": rec["id"], "flags": flags})
        except Exception as exc:
            print(f"ERROR: {exc}")
            results.append({"cluster_label": label, "id": rec["id"], "flags": [], "error": str(exc)})

        if i < total:
            await asyncio.sleep(1)

    return results


# ---------------------------------------------------------------------------
# DB write helpers
# ---------------------------------------------------------------------------

def _write_results_to_db(
    enrich_conn: sqlite3.Connection,
    results: list[dict],
) -> tuple[int, int]:
    """
    For each result:
    1. UPDATE enrichment SET divergence_flags = ? for the latest record of that cluster.
    2. INSERT into divergence_log with detected_by='llm' (skip if cluster+type already
       has detected_by='llm' entry).

    Returns (flags_written, log_rows_inserted).
    """
    flags_written = 0
    log_rows_inserted = 0

    for item in results:
        label = item["cluster_label"]
        flags = item["flags"]
        enrichment_id = item["id"]

        if not flags:
            # Still update the column to mark it as processed (empty array)
            enrich_conn.execute(
                "UPDATE enrichment SET divergence_flags = '[]' WHERE id = ?",
                (enrichment_id,),
            )
            flags_written += 1
            continue

        flags_json = json.dumps(flags, ensure_ascii=False)
        enrich_conn.execute(
            "UPDATE enrichment SET divergence_flags = ? WHERE id = ?",
            (flags_json, enrichment_id),
        )
        flags_written += 1

        for flag in flags:
            flag_type_full = flag.get("type", "")
            short = _TYPE_SHORT.get(flag_type_full, "")
            if not short:
                continue
            evidence = flag.get("evidence", "")
            sources_involved = flag.get("sources_involved", [])

            # Check if already has a 'llm' entry for this cluster+type
            existing = enrich_conn.execute(
                """
                SELECT id FROM divergence_log
                 WHERE cluster_label = ?
                   AND divergence_type = ?
                   AND detected_by = 'llm'
                 LIMIT 1
                """,
                (label, short),
            ).fetchone()
            if existing:
                continue

            # source_a = first source, source_b = remaining sources joined
            src_a = sources_involved[0] if sources_involved else ""
            src_b = ", ".join(sources_involved[1:]) if len(sources_involved) > 1 else ""

            description = f"[llm_backfill] {evidence}"

            enrich_conn.execute(
                """
                INSERT INTO divergence_log
                  (enrichment_id, cluster_label, divergence_type, divergence_label,
                   source_a, source_b, description, detected_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'llm')
                """,
                (enrichment_id, label, short, short, src_a, src_b, description),
            )
            log_rows_inserted += 1

    return flags_written, log_rows_inserted


# ---------------------------------------------------------------------------
# Mode implementations
# ---------------------------------------------------------------------------

def run_dry_run() -> None:
    """Show pending count and existing divergence_log distribution. No LLM calls."""
    if not _DB_PATH.exists():
        sys.exit(f"Enrichment DB not found: {_DB_PATH}")

    conn = _open_enrichment_db()
    pending = _load_pending_records(conn)

    print(f"Pending records (no divergence_flags): {len(pending)}")

    # Show T1-T5 distribution for clusters that are pending
    pending_labels = [r["cluster_label"] for r in pending]
    if pending_labels:
        placeholders = ",".join("?" * len(pending_labels))
        rows = conn.execute(
            f"""
            SELECT divergence_type, COUNT(*) AS cnt
              FROM divergence_log
             WHERE cluster_label IN ({placeholders})
             GROUP BY divergence_type
             ORDER BY divergence_type
            """,
            pending_labels,
        ).fetchall()
        total_for_pending = sum(r["cnt"] for r in rows)
        if total_for_pending:
            print(f"\nExisting divergence_log entries for pending clusters ({total_for_pending} entries):")
            print(f"  {'Type':<6}  {'Count':>6}  {'%':>6}")
            print(f"  {'------':<6}  {'------':>6}  {'------':>6}")
            type_counts = {r["divergence_type"]: r["cnt"] for r in rows}
            for t in ("T1", "T2", "T3", "T4", "T5"):
                cnt = type_counts.get(t, 0)
                pct = round(100.0 * cnt / total_for_pending, 1) if total_for_pending else 0.0
                print(f"  {t:<6}  {cnt:>6}  {pct:>5.1f}%")
        else:
            print("\nNo existing divergence_log entries for pending clusters.")

    _print_divergence_stats(conn)
    conn.close()


async def _run_sample(n: int, api_key: str, model: str) -> None:
    if not _DB_PATH.exists():
        sys.exit(f"Enrichment DB not found: {_DB_PATH}")
    if not _TERMS_DB_PATH.exists():
        sys.exit(f"Terms DB not found: {_TERMS_DB_PATH}")

    enrich_conn = _open_enrichment_db()
    terms_conn = _open_terms_db()

    pending = _load_pending_records(enrich_conn)
    sample = pending[:n]

    print(f"Total pending: {len(pending)}")
    print(f"Processing sample of {len(sample)} record(s) via LLM (model: {model})...\n")

    results = await _process_records(sample, api_key, model, terms_conn)

    _print_llm_distribution(results)

    cluster_labels = [r["cluster_label"] for r in results]
    existing_map = _get_existing_flags_for_clusters(enrich_conn, cluster_labels)
    _print_comparison_table(results, existing_map)

    terms_conn.close()
    enrich_conn.close()


async def _run_apply(limit: int | None, api_key: str, model: str) -> None:
    if not _DB_PATH.exists():
        sys.exit(f"Enrichment DB not found: {_DB_PATH}")
    if not _TERMS_DB_PATH.exists():
        sys.exit(f"Terms DB not found: {_TERMS_DB_PATH}")

    enrich_conn = _open_enrichment_db()
    terms_conn = _open_terms_db()

    pending = _load_pending_records(enrich_conn)
    targets = pending[:limit] if limit else pending

    print(f"Total pending: {len(pending)}")
    print(f"Targets for this run: {len(targets)}")

    # Backup before first write
    bak = _DB_PATH.with_suffix(f".db.bak.{date.today().strftime('%Y%m%d')}")
    shutil.copy2(_DB_PATH, bak)
    print(f"Backup created: {bak}\n")

    results = await _process_records(targets, api_key, model, terms_conn)

    _print_llm_distribution(results)

    flags_written, log_inserted = _write_results_to_db(enrich_conn, results)
    enrich_conn.commit()

    errors = sum(1 for r in results if r.get("error"))
    print(f"\nResults:")
    print(f"  Processed    : {len(results)}")
    print(f"  Flags written: {flags_written}")
    print(f"  Log inserted : {log_inserted}")
    print(f"  Errors       : {errors}")
    print("Changes committed to database.")

    terms_conn.close()
    enrich_conn.close()


# ---------------------------------------------------------------------------
# From-log backfill (no LLM)
# ---------------------------------------------------------------------------

def run_from_log(dry_run: bool = True) -> None:
    """
    Populate divergence_flags from existing divergence_log entries (no LLM calls).

    For each pending record:
      - Look up divergence_log rows for that cluster_label
      - Build divergence_flags array using the long-form type names and log descriptions
      - UPDATE enrichment SET divergence_flags = ?

    Records with no log entries get divergence_flags = '[]' (marked as processed).
    No new divergence_log rows are inserted.
    """
    if not _DB_PATH.exists():
        sys.exit(f"Enrichment DB not found: {_DB_PATH}")

    conn = _open_enrichment_db()
    pending = _load_pending_records(conn)

    if not pending:
        print("No pending records.")
        conn.close()
        return

    print(f"Pending records (no divergence_flags): {len(pending)}")

    # Load all divergence_log entries for pending clusters
    pending_labels = [r["cluster_label"] for r in pending]
    placeholders = ",".join("?" * len(pending_labels))
    log_rows = conn.execute(
        f"""
        SELECT cluster_label, divergence_type, description, source_a, source_b
          FROM divergence_log
         WHERE cluster_label IN ({placeholders})
         ORDER BY cluster_label, divergence_type
        """,
        pending_labels,
    ).fetchall()

    # Group by cluster_label
    log_by_cluster: dict[str, list] = {}
    for row in log_rows:
        log_by_cluster.setdefault(row["cluster_label"], []).append(row)

    has_log = sum(1 for lbl in pending_labels if lbl in log_by_cluster)
    no_log = len(pending) - has_log
    print(f"  With log entries : {has_log}")
    print(f"  No log entries   : {no_log} (will get empty flags)")

    if dry_run:
        print("\n[DRY-RUN] No changes applied. Pass --from-log --apply to execute.")
        sample = pending_labels[:10]
        print(f"\nSample (first {len(sample)}):")
        for lbl in sample:
            rows = log_by_cluster.get(lbl, [])
            types = sorted({_TYPE_LONG.get(r["divergence_type"], r["divergence_type"]) for r in rows})
            print(f"  {lbl}: {types if types else '[]'}")
        conn.close()
        return

    # Apply
    bak = _DB_PATH.with_suffix(f".db.bak.{date.today().strftime('%Y%m%d')}")
    if not bak.exists():
        shutil.copy2(_DB_PATH, bak)
        print(f"Backup created: {bak}")

    written = 0
    for rec in pending:
        lbl = rec["cluster_label"]
        rows = log_by_cluster.get(lbl, [])

        # Deduplicate by (type, source_a, source_b) — log may have multiple entries per type
        seen_keys: set = set()
        flags: list[dict] = []
        for row in rows:
            short = row["divergence_type"]
            long_type = _TYPE_LONG.get(short, short)
            src_a = row["source_a"] or ""
            src_b = row["source_b"] or ""
            key = (long_type, src_a)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            sources = [s for s in [src_a, src_b] if s]
            evidence = (row["description"] or "").removeprefix("[llm_backfill] ").strip()
            flags.append({
                "type": long_type,
                "evidence": evidence,
                "sources_involved": sources,
            })

        flags_json = json.dumps(flags, ensure_ascii=False)
        conn.execute(
            "UPDATE enrichment SET divergence_flags = ? WHERE id = ?",
            (flags_json, rec["id"]),
        )
        written += 1

    conn.commit()
    conn.close()
    print(f"\nUpdated {written} enrichment record(s) with divergence_flags from log.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--dry-run", action="store_true", default=False,
        help="Show pending count and divergence_log distribution. No LLM calls (default mode).",
    )
    mode_group.add_argument(
        "--sample", type=int, metavar="N",
        help="Process N records via LLM (no DB writes). Print T1-T5 distribution and comparison.",
    )
    mode_group.add_argument(
        "--apply", action="store_true", default=False,
        help="Full backfill: call LLM and write results to DB.",
    )
    parser.add_argument(
        "--from-log", action="store_true", default=False, dest="from_log",
        help="Populate divergence_flags from existing divergence_log (no LLM calls). "
             "Preview only unless combined with --apply.",
    )
    parser.add_argument(
        "--limit", type=int, metavar="N",
        help="With --apply: process at most N records.",
    )
    parser.add_argument(
        "--model", default=_DEFAULT_MODEL,
        help=f"LLM model to use (default: {_DEFAULT_MODEL})",
    )
    args = parser.parse_args()

    # Default to dry-run if no mode specified
    if not args.sample and not args.apply and not args.from_log:
        args.dry_run = True

    if args.from_log:
        run_from_log(dry_run=not args.apply)
        return

    if args.dry_run:
        run_dry_run()
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        sys.exit("Error: ANTHROPIC_API_KEY environment variable is not set.")

    if args.sample:
        asyncio.run(_run_sample(args.sample, api_key, args.model))
    elif args.apply:
        asyncio.run(_run_apply(args.limit, api_key, args.model))


if __name__ == "__main__":
    main()
