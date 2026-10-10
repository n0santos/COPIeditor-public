"""
Evaluation metrics API for COPI Editor.

Read-only endpoints that expose the data collected silently by evaluation_metrics.py.
Mount inside the enrichment router with prefix="/metrics".

Endpoints:
    GET /enrich/metrics/summary      — all validated/exported classes + computed metrics
    GET /enrich/metrics/export       — CSV or JSON download for pandas
    GET /enrich/metrics/class/{id}   — per-class event timeline + axiom diff
    GET /enrich/metrics/aggregate    — aggregated statistics across all classes
    GET /enrich/metrics/pareto/{dim} — Pareto table for a specific dimension
"""
from __future__ import annotations

import csv
import io
import json
import sqlite3
import statistics
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse

from enrichment_service import ENRICHMENT_DB_PATH
from evaluation_metrics import (
    compute_active_time_minutes,
    compute_axiom_diff,
    compute_field_level_diff,
    compute_time_per_step,
    _STEP_ATOMIC_FIELDS,
)

router = APIRouter()

_PARETO_DIMENSIONS = frozenset({"field_changes", "genus_proposed", "genus_accepted", "modification_types"})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(ENRICHMENT_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _build_class_metrics(enrichment_id: int, conn: sqlite3.Connection) -> dict:
    """Compute all metrics for one enrichment and return as a plain dict."""
    row = conn.execute(
        "SELECT id, cluster_label, status, axiom_mode, llm_model, "
        "input_tokens, output_tokens, estimated_cost_usd, created_at, updated_at "
        "FROM enrichment WHERE id = ?",
        (enrichment_id,),
    ).fetchone()
    if not row:
        return {}

    d = dict(row)

    # Event counts
    ev = conn.execute(
        """
        SELECT
            SUM(CASE WHEN event_type = 'open'           THEN 1 ELSE 0 END) AS open_count,
            SUM(CASE WHEN event_type = 'save'           THEN 1 ELSE 0 END) AS save_count,
            SUM(CASE WHEN event_type = 'step_review'    THEN 1 ELSE 0 END) AS step_review_count,
            SUM(CASE WHEN event_type = 'rerun_request'  THEN 1 ELSE 0 END) AS rerun_count,
            COUNT(*) AS total_events
        FROM eval_interaction_event
        WHERE enrichment_id = ?
        """,
        (enrichment_id,),
    ).fetchone()
    d.update({
        "open_count":        ev["open_count"]        or 0,
        "save_count":        ev["save_count"]        or 0,
        "step_review_count": ev["step_review_count"] or 0,
        "rerun_count":       ev["rerun_count"]       or 0,
        "total_events":      ev["total_events"]      or 0,
    })

    d["active_time_minutes"] = compute_active_time_minutes(conn, enrichment_id)

    diff = compute_axiom_diff(conn, enrichment_id)
    d.update(diff)

    # Verification snapshot
    vs = conn.execute(
        "SELECT * FROM eval_verification_snapshot WHERE enrichment_id = ?",
        (enrichment_id,),
    ).fetchone()
    if vs:
        d.update({
            "hermit_consistent":       vs["hermit_consistent"],
            "hermit_error":            vs["hermit_error"],
            "oops_critical_count":     vs["oops_critical_count"],
            "oops_important_count":    vs["oops_important_count"],
            "oops_minor_count":        vs["oops_minor_count"],
            "has_nl_definition":       bool(vs["has_nl_definition"]),
            "has_semiformal_def":      bool(vs["has_semiformal_def"]),
            "has_fol_axiom":           bool(vs["has_fol_axiom"]),
            "has_primitive_rationale": bool(vs["has_primitive_rationale"]),
            "has_label_en":            bool(vs["has_label_en"]),
            "has_label_pt":            bool(vs["has_label_pt"]),
        })
    else:
        d.update({
            "hermit_consistent": None,
            "hermit_error": None,
            "oops_critical_count": 0,
            "oops_important_count": 0,
            "oops_minor_count": 0,
            "has_nl_definition": False,
            "has_semiformal_def": False,
            "has_fol_axiom": False,
            "has_primitive_rationale": False,
            "has_label_en": False,
            "has_label_pt": False,
        })

    # ── New granular metrics ──────────────────────────────────────────────────

    # Step modification types (one per step)
    step_mods = conn.execute(
        "SELECT step_number, modification_type, changed_field_count, content_changed_count "
        "FROM eval_step_modification_summary WHERE enrichment_id = ?",
        (enrichment_id,),
    ).fetchall()
    for sm in step_mods:
        n = sm["step_number"]
        d[f"step_{n}_modification_type"]    = sm["modification_type"]
        d[f"step_{n}_changed_fields"]       = sm["changed_field_count"]
        d[f"step_{n}_content_changed_fields"] = sm["content_changed_count"]

    # Fill missing steps with None
    for n in range(1, 6):
        d.setdefault(f"step_{n}_modification_type",       None)
        d.setdefault(f"step_{n}_changed_fields",          None)
        d.setdefault(f"step_{n}_content_changed_fields",  None)

    # Field-level diff summary (changed field count per step)
    fld_diff = compute_field_level_diff(conn, enrichment_id)
    field_changes_per_step: dict[str, int] = {}
    for step_key, fields in fld_diff.items():
        field_changes_per_step[step_key] = sum(
            1 for s in fields.values() if s != "unchanged"
        )
    d["field_changes_per_step"] = field_changes_per_step

    # Genus usage
    gu = conn.execute(
        "SELECT proposed_genus, accepted_genus, proposed_source, "
        "accepted_source, changed_during_review "
        "FROM eval_genus_usage WHERE enrichment_id = ?",
        (enrichment_id,),
    ).fetchone()
    if gu:
        d.update({
            "proposed_genus":         gu["proposed_genus"],
            "accepted_genus":         gu["accepted_genus"],
            "proposed_genus_source":  gu["proposed_source"],
            "accepted_genus_source":  gu["accepted_source"],
            "proposed_genus_changed": bool(gu["changed_during_review"]),
        })
    else:
        d.update({
            "proposed_genus":         None,
            "accepted_genus":         None,
            "proposed_genus_source":  None,
            "accepted_genus_source":  None,
            "proposed_genus_changed": None,
        })

    # Time per step (only populated if step_focus events exist)
    d["time_per_step"] = compute_time_per_step(conn, enrichment_id)

    return d


# ---------------------------------------------------------------------------
# Pareto computation helpers
# ---------------------------------------------------------------------------

def _pareto_table(items: list[tuple[str, int, int]], total_enrichments: int) -> list[dict]:
    """
    Convert raw (name, tc, mc) tuples to a Pareto table sorted by TC descending.

    TC = total occurrences, MC = distinct enrichments where this item appears.
    RTC = TC / sum(TC), RMC = MC / N  (Barcelos et al. 2025 convention).
    cumulative_rtc and cumulative_rmc are running sums top-to-bottom.
    """
    if not items:
        return []

    items_sorted = sorted(items, key=lambda x: (-x[1], x[0]))
    total_tc = sum(t for _, t, _ in items_sorted)

    result = []
    cum_rtc = 0.0
    cum_rmc = 0.0
    for name, tc, mc in items_sorted:
        rtc = round(tc / total_tc, 4) if total_tc else 0.0
        rmc = round(mc / total_enrichments, 4) if total_enrichments else 0.0
        cum_rtc = round(cum_rtc + rtc, 4)
        cum_rmc = round(cum_rmc + rmc, 4)
        result.append({
            "name": name,
            "tc": tc,
            "mc": mc,
            "rtc": rtc,
            "rmc": rmc,
            "cumulative_rtc": cum_rtc,
            "cumulative_rmc": cum_rmc,
        })
    return result


def _field_change_pareto_raw(conn: sqlite3.Connection) -> list[tuple[str, int, int]]:
    """Raw (name, tc, mc) tuples for field-change Pareto across validated/exported enrichments."""
    rows = conn.execute(
        """
        SELECT
            'step_' || sfs_i.step_number || '.' || sfs_i.field_name AS name,
            COUNT(*) AS tc,
            COUNT(DISTINCT sfs_i.enrichment_id) AS mc
        FROM eval_step_field_snapshot sfs_i
        JOIN eval_step_field_snapshot sfs_f
             ON  sfs_i.enrichment_id = sfs_f.enrichment_id
             AND sfs_i.step_number   = sfs_f.step_number
             AND sfs_i.field_name    = sfs_f.field_name
        JOIN enrichment e ON sfs_i.enrichment_id = e.id
        WHERE sfs_i.snapshot_type = 'llm_initial'
          AND sfs_f.snapshot_type = 'final_export'
          AND sfs_i.field_value_hash != sfs_f.field_value_hash
          AND e.status IN ('validated', 'exported')
        GROUP BY sfs_i.step_number, sfs_i.field_name
        """,
    ).fetchall()
    return [(r["name"], r["tc"], r["mc"]) for r in rows]


def _genus_pareto_raw(conn: sqlite3.Connection, column: str) -> list[tuple[str, int, int]]:
    rows = conn.execute(
        f"""
        SELECT COALESCE({column}, '(none)') AS name,
               COUNT(*) AS tc,
               COUNT(DISTINCT gu.enrichment_id) AS mc
        FROM eval_genus_usage gu
        JOIN enrichment e ON gu.enrichment_id = e.id
        WHERE e.status IN ('validated', 'exported')
        GROUP BY {column}
        """,
    ).fetchall()
    return [(r["name"], r["tc"], r["mc"]) for r in rows]


def _modification_type_distribution(conn: sqlite3.Connection) -> dict[str, dict[str, int]]:
    rows = conn.execute(
        """
        SELECT sms.step_number, sms.modification_type, COUNT(*) AS cnt
        FROM eval_step_modification_summary sms
        JOIN enrichment e ON sms.enrichment_id = e.id
        WHERE e.status IN ('validated', 'exported')
        GROUP BY sms.step_number, sms.modification_type
        """,
    ).fetchall()

    dist: dict[str, dict[str, int]] = {}
    for r in rows:
        key = f"step_{r['step_number']}"
        dist.setdefault(key, {})
        dist[key][r["modification_type"]] = r["cnt"]

    # Ensure all 5 steps present with zero-filled categories
    _cats = ("accepted_as_is", "minor_edit", "content_changed", "rejected_empty", "rerun_resolved")
    for n in range(1, 6):
        k = f"step_{n}"
        dist.setdefault(k, {})
        for cat in _cats:
            dist[k].setdefault(cat, 0)

    return dist


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/summary", response_class=JSONResponse)
async def metrics_summary():
    """
    Return metrics for all validated/exported enrichments.
    Each item includes event counts, active time, axiom diff stats,
    step modification types, genus usage, and verification snapshot fields.
    """
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT id FROM enrichment WHERE status IN ('validated', 'exported') "
            "ORDER BY cluster_label"
        ).fetchall()
        result = [_build_class_metrics(r["id"], conn) for r in rows]
    finally:
        conn.close()
    return JSONResponse(result)


@router.get("/export")
async def metrics_export(format: str = Query(default="json", pattern="^(json|csv)$")):
    """
    Download metrics as JSON or CSV for offline analysis with pandas.
    GET /enrich/metrics/export?format=csv
    GET /enrich/metrics/export?format=json
    """
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT id FROM enrichment WHERE status IN ('validated', 'exported') "
            "ORDER BY cluster_label"
        ).fetchall()
        data = [_build_class_metrics(r["id"], conn) for r in rows]
    finally:
        conn.close()

    if format == "json":
        buf = io.BytesIO(json.dumps(data, ensure_ascii=False, default=str).encode())
        return StreamingResponse(
            buf,
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=copi_metrics.json"},
        )

    # CSV
    if not data:
        raise HTTPException(404, "No validated enrichments to export")

    # Flatten nested dicts for CSV
    flat_data = []
    for item in data:
        row = {}
        for k, v in item.items():
            if isinstance(v, dict):
                for dk, dv in v.items():
                    row[f"{k}.{dk}"] = dv
            elif isinstance(v, list):
                row[k] = json.dumps(v, ensure_ascii=False)
            else:
                row[k] = v
        flat_data.append(row)

    fieldnames = list(flat_data[0].keys()) if flat_data else []
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in flat_data:
        writer.writerow({k: str(v) if isinstance(v, (list, dict)) else v for k, v in row.items()})
    buf.seek(0)

    return StreamingResponse(
        io.BytesIO(buf.read().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=copi_metrics.csv"},
    )


@router.get("/class/{enrichment_id}", response_class=JSONResponse)
async def metrics_class(enrichment_id: int):
    """
    Detailed metrics for one enrichment: computed summary + full event timeline
    (with timestamps) + axiom diff detail + field-level diff.
    """
    conn = _get_db()
    try:
        summary = _build_class_metrics(enrichment_id, conn)
        if not summary:
            raise HTTPException(404, f"Enrichment {enrichment_id} not found")

        events = conn.execute(
            "SELECT id, event_type, event_detail, created_at "
            "FROM eval_interaction_event WHERE enrichment_id = ? "
            "ORDER BY created_at ASC",
            (enrichment_id,),
        ).fetchall()

        snapshots = conn.execute(
            "SELECT snapshot_type, axiom_mode, created_at "
            "FROM eval_axiom_snapshot WHERE enrichment_id = ? "
            "ORDER BY created_at ASC",
            (enrichment_id,),
        ).fetchall()

        field_diff = compute_field_level_diff(conn, enrichment_id)
    finally:
        conn.close()

    return JSONResponse({
        "summary": summary,
        "field_level_diff": field_diff,
        "events": [
            {
                "id":           e["id"],
                "event_type":   e["event_type"],
                "event_detail": json.loads(e["event_detail"]) if e["event_detail"] else None,
                "created_at":   e["created_at"],
            }
            for e in events
        ],
        "snapshots": [dict(s) for s in snapshots],
    })


@router.get("/aggregate", response_class=JSONResponse)
async def metrics_aggregate():
    """
    Aggregated statistics across all validated/exported enrichments.
    Includes: time stats, iteration counts, HermiT/IOF rates, OOPS! totals,
    LLM cost, axiom mode distribution, field-change Pareto, modification type
    distribution per step, and genus usage analysis.
    """
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT id FROM enrichment WHERE status IN ('validated', 'exported') "
            "ORDER BY cluster_label"
        ).fetchall()
        data = [_build_class_metrics(r["id"], conn) for r in rows]
        n = len(data)

        if n == 0:
            return JSONResponse({"n": 0})

        def _stats(values: list) -> dict:
            clean = [v for v in values if v is not None]
            if not clean:
                return {"mean": None, "median": None, "min": None, "max": None}
            return {
                "mean":   round(statistics.mean(clean), 3),
                "median": round(statistics.median(clean), 3),
                "min":    round(min(clean), 3),
                "max":    round(max(clean), 3),
            }

        active_times  = [d.get("active_time_minutes") for d in data]
        reruns        = [d.get("rerun_count") for d in data]
        accept_ratios = [d.get("acceptance_ratio") for d in data]

        hermit_runs   = [d for d in data if d.get("hermit_consistent") is not None]
        hermit_ok_pct = (
            round(sum(1 for d in hermit_runs if d["hermit_consistent"] == 1)
                  / len(hermit_runs) * 100, 1)
            if hermit_runs else None
        )

        iof_complete = [d for d in data if all([
            d.get("has_nl_definition"), d.get("has_semiformal_def"),
            d.get("has_fol_axiom"), d.get("has_label_en"), d.get("has_label_pt"),
        ])]
        iof_complete_pct = round(len(iof_complete) / n * 100, 1)

        total_cost          = round(sum(d.get("estimated_cost_usd") or 0 for d in data), 4)
        total_oops_critical = sum(d.get("oops_critical_count") or 0 for d in data)
        turtle_added        = [d.get("turtle_lines_added") for d in data]
        turtle_removed      = [d.get("turtle_lines_removed") for d in data]

        # ── Pareto: field changes ─────────────────────────────────────────────
        raw_fc = _field_change_pareto_raw(conn)
        field_change_pareto = {
            item["name"]: {k: item[k] for k in ("tc", "mc", "rtc", "rmc")}
            for item in _pareto_table(raw_fc, n)
        }

        # ── Modification type distribution per step ───────────────────────────
        mod_dist = _modification_type_distribution(conn)

        # ── Genus usage ───────────────────────────────────────────────────────
        raw_proposed = _genus_pareto_raw(conn, "proposed_genus")
        raw_accepted = _genus_pareto_raw(conn, "accepted_genus")

        genus_unchanged = conn.execute(
            """SELECT COUNT(*) AS cnt FROM eval_genus_usage gu
               JOIN enrichment e ON gu.enrichment_id = e.id
               WHERE e.status IN ('validated','exported') AND gu.changed_during_review = 0"""
        ).fetchone()["cnt"]
        genus_total = conn.execute(
            """SELECT COUNT(*) AS cnt FROM eval_genus_usage gu
               JOIN enrichment e ON gu.enrichment_id = e.id
               WHERE e.status IN ('validated','exported')"""
        ).fetchone()["cnt"]
        acceptance_rate = round(genus_unchanged / genus_total, 3) if genus_total else None

        genus_usage = {
            "top_proposed": [
                [item["name"], item["tc"]]
                for item in _pareto_table(raw_proposed, n)[:10]
            ],
            "top_accepted": [
                [item["name"], item["tc"]]
                for item in _pareto_table(raw_accepted, n)[:10]
            ],
            "proposal_acceptance_rate": acceptance_rate,
        }

    finally:
        conn.close()

    return JSONResponse({
        "n":                    n,
        "active_time_minutes":  _stats(active_times),
        "rerun_count":          _stats(reruns),
        "acceptance_ratio":     _stats(accept_ratios),
        "turtle_lines_added":   _stats(turtle_added),
        "turtle_lines_removed": _stats(turtle_removed),
        "hermit_run_pct":       round(len(hermit_runs) / n * 100, 1) if n else None,
        "hermit_consistent_pct": hermit_ok_pct,
        "iof_complete_pct":     iof_complete_pct,
        "oops_critical_total":  total_oops_critical,
        "total_cost_usd":       total_cost,
        "axiom_mode_dist": {
            mode: sum(1 for d in data if d.get("axiom_mode") == mode)
            for mode in ("necessary", "equivalent", "mixed")
        },
        # ── New sections ─────────────────────────────────────────────────────
        "field_change_pareto":          field_change_pareto,
        "modification_type_distribution": mod_dist,
        "genus_usage":                  genus_usage,
    })


@router.get("/pareto/{dimension}", response_class=JSONResponse)
async def metrics_pareto(dimension: str):
    """
    Pareto table for one analytical dimension, ready for pandas/matplotlib.

    Dimensions:
      field_changes      — which atomic step fields are edited most often
      genus_proposed     — which genera the LLM most frequently proposes
      genus_accepted     — which genera remain after expert review
      modification_types — per-step distribution of the 5 modification categories

    Response columns (except modification_types):
      name, tc, mc, rtc, rmc, cumulative_rtc, cumulative_rmc

    TC  = total occurrences across all validated/exported enrichments
    MC  = distinct enrichments containing this item
    RTC = TC / sum(TC)   (Barcelos et al. 2025 convention)
    RMC = MC / N
    """
    if dimension not in _PARETO_DIMENSIONS:
        raise HTTPException(
            400,
            f"Unknown dimension {dimension!r}. "
            f"Valid values: {sorted(_PARETO_DIMENSIONS)}",
        )

    conn = _get_db()
    try:
        n = conn.execute(
            "SELECT COUNT(*) AS cnt FROM enrichment "
            "WHERE status IN ('validated', 'exported')"
        ).fetchone()["cnt"]

        if dimension == "field_changes":
            raw = _field_change_pareto_raw(conn)
            result = _pareto_table(raw, n)

        elif dimension == "genus_proposed":
            raw = _genus_pareto_raw(conn, "proposed_genus")
            result = _pareto_table(raw, n)

        elif dimension == "genus_accepted":
            raw = _genus_pareto_raw(conn, "accepted_genus")
            result = _pareto_table(raw, n)

        else:  # modification_types
            # Returns a nested structure: {step_1: {accepted_as_is: N, ...}, ...}
            result = _modification_type_distribution(conn)  # type: ignore[assignment]

    finally:
        conn.close()

    return JSONResponse(result)
