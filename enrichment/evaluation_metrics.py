"""
Evaluation metrics collection for COPI Editor.

Silently records ontologist interactions as side-effects of the normal workflow.
All public functions are fire-and-forget: errors are logged as warnings, never raised.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import logging
import sqlite3
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# ── Step field definitions ────────────────────────────────────────────────────

# Coarse step → fields (kept for backward compat with compute_axiom_diff)
_STEP_FIELDS: dict[str, list[str]] = {
    "step1": ["function_name", "process_name"],
    "step2": ["genus", "genus_bfo_root"],
    "step3": ["differentia_expression", "differentia_nl"],
    "step4": ["necessary_parts"],
    "step5": ["process_signature"],
}

# Atomic fields per step (1-indexed) — used for field-level diff and Pareto
_STEP_ATOMIC_FIELDS: dict[int, list[str]] = {
    1: ["function_name", "process_name", "function_rationale"],
    2: ["genus", "genus_bfo_root", "genus_rationale"],
    3: ["axiom_mode", "differentia_expression", "differentia_nl", "differentia_rationale"],
    4: ["necessary_parts", "parts_rationale"],
    5: ["process_signature", "signature_rationale"],
}

# Formal/content fields per step — rationale fields are the complement
_STEP_CONTENT_FIELDS: dict[int, frozenset[str]] = {
    1: frozenset({"function_name", "process_name"}),
    2: frozenset({"genus", "genus_bfo_root"}),
    3: frozenset({"axiom_mode", "differentia_expression", "differentia_nl"}),
    4: frozenset({"necessary_parts"}),
    5: frozenset({"process_signature"}),
}

# Known BFO class names for genus source classification (normalised, no spaces)
_BFO_CLASS_NAMES: frozenset[str] = frozenset({
    "materialentity", "object", "assembly", "materialartifact",
    "engineeredsystem", "site", "fiatobjectpart", "objectaggregate",
    "independentcontinuant", "process", "occurrent", "quality",
    "dispositionalmaterialentity", "objectboundary",
})


# ── Low-level helpers ─────────────────────────────────────────────────────────

def _canonicalize(val: Any) -> str:
    """Canonical string for a field value — used for equality checks and hashing."""
    if val is None:
        return ""
    if isinstance(val, (dict, list)):
        return json.dumps(val, sort_keys=True, ensure_ascii=False)
    if isinstance(val, str):
        stripped = val.strip()
        if not stripped or stripped in ("[]", "{}"):
            return stripped
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, (dict, list)):
                return json.dumps(parsed, sort_keys=True, ensure_ascii=False)
        except (json.JSONDecodeError, ValueError):
            pass
        return stripped
    return str(val).strip()


def _sha16(s: str) -> str:
    """First 16 hex chars of SHA-256 — compact hash for field_value_hash."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def _classify_genus_source(genus: str | None) -> str:
    """Map a genus name or IRI to bfo | iof-core | copi | other."""
    if not genus:
        return "other"
    g = genus.lower()
    if g.startswith("bfo:") or "purl.obolibrary.org/obo/bfo" in g:
        return "bfo"
    if g.startswith("iof") or "industrialontologies.org" in g:
        return "iof-core"
    if g.startswith("copi:") or "inf.ufrgs.br/ontologies/copi" in g:
        return "copi"
    g_norm = g.replace(" ", "").replace("-", "").replace("_", "")
    if g_norm in _BFO_CLASS_NAMES:
        return "bfo"
    return "other"


def _classify_step_modification_type(
    step_num: int,
    init_data: dict,
    final_data: dict,
    has_rerun: bool,
) -> str:
    """
    Classify how the ontologist modified one step into a mutually exclusive category.

    Categories (mirror Barcelos et al. 2025 stereotype classification):
      accepted_as_is  — no field changed between llm_initial and final_export
      minor_edit      — only rationale field(s) changed; formal content unchanged
      content_changed — at least one content field changed (manual edit, no rerun)
      rejected_empty  — initial had content; final export has all content fields empty
      rerun_resolved  — a rerun was requested AND at least one content field changed
    """
    content_fields = _STEP_CONTENT_FIELDS.get(step_num, frozenset())
    all_fields = _STEP_ATOMIC_FIELDS.get(step_num, [])

    content_changed = False
    any_changed = False
    final_content_empty = True
    init_has_content = False

    for field in all_fields:
        iv = _canonicalize(init_data.get(field))
        fv = _canonicalize(final_data.get(field))
        if field in content_fields:
            if iv not in ("", "[]", "{}"):
                init_has_content = True
            if fv not in ("", "[]", "{}"):
                final_content_empty = False
        if iv != fv:
            any_changed = True
            if field in content_fields:
                content_changed = True

    if init_has_content and final_content_empty:
        return "rejected_empty"
    if not any_changed:
        return "accepted_as_is"
    if not content_changed:
        return "minor_edit"
    if has_rerun:
        return "rerun_resolved"
    return "content_changed"


def _parse_ts(ts: str) -> datetime:
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse timestamp: {ts!r}")


# ── Core logging helpers ───────────────────────────────────────────────────────

def log_event(
    db: sqlite3.Connection,
    enrichment_id: int,
    event_type: str,
    event_detail: dict | None = None,
) -> None:
    """Insert one interaction event. Fire-and-forget: never raises."""
    try:
        detail_json = json.dumps(event_detail, ensure_ascii=False) if event_detail else None
        db.execute(
            "INSERT INTO eval_interaction_event (enrichment_id, event_type, event_detail) "
            "VALUES (?, ?, ?)",
            (enrichment_id, event_type, detail_json),
        )
        db.commit()
    except Exception as exc:
        logger.warning("log_event(%s, %s) failed: %s", enrichment_id, event_type, exc)


def take_axiom_snapshot(
    db: sqlite3.Connection,
    enrichment_id: int,
    snapshot_type: str,
    turtle_content: str,
    step_data: dict,
    axiom_mode: str,
) -> None:
    """Persist a Turtle + step data snapshot. Fire-and-forget: never raises."""
    try:
        cur = db.execute(
            "INSERT INTO eval_axiom_snapshot "
            "(enrichment_id, snapshot_type, turtle_content, step_data_json, axiom_mode) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                enrichment_id,
                snapshot_type,
                turtle_content,
                json.dumps(step_data, ensure_ascii=False, default=str),
                axiom_mode,
            ),
        )
        snapshot_id = cur.lastrowid
        db.commit()

        # Populate field-level rows (additive, non-blocking)
        _populate_field_snapshots(
            db, enrichment_id, snapshot_id, snapshot_type, step_data, axiom_mode
        )

        # On final export, compute modification summary and genus usage
        if snapshot_type == "final_export":
            _populate_step_modification_summary(db, enrichment_id)
            _populate_genus_usage(db, enrichment_id)

    except Exception as exc:
        logger.warning("take_axiom_snapshot(%s, %s) failed: %s", enrichment_id, snapshot_type, exc)


def take_verification_snapshot(
    db: sqlite3.Connection,
    enrichment_id: int,
    hermit_result: dict | None,
    oops_result: dict | None,
    annotation_flags: dict | None,
) -> None:
    """
    Upsert a verification snapshot at export time. Fire-and-forget: never raises.

    hermit_result:    {consistent: bool, inferred: list, error: str|None}  or None
    oops_result:      {critical: int, important: int, minor: int, pitfalls: list}  or None
    annotation_flags: {has_nl_definition, has_semiformal_def, has_fol_axiom,
                       has_primitive_rationale, has_label_en, has_label_pt}  — all bool
    """
    try:
        hr = hermit_result or {}
        op = oops_result or {}
        af = annotation_flags or {}

        consistent_val = None
        if "consistent" in hr:
            consistent_val = 1 if hr["consistent"] else 0

        db.execute(
            """
            INSERT INTO eval_verification_snapshot (
                enrichment_id,
                hermit_consistent, hermit_inferred, hermit_error,
                oops_critical_count, oops_important_count, oops_minor_count, oops_pitfalls_json,
                has_nl_definition, has_semiformal_def, has_fol_axiom,
                has_primitive_rationale, has_label_en, has_label_pt
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(enrichment_id) DO UPDATE SET
                hermit_consistent    = excluded.hermit_consistent,
                hermit_inferred      = excluded.hermit_inferred,
                hermit_error         = excluded.hermit_error,
                oops_critical_count  = excluded.oops_critical_count,
                oops_important_count = excluded.oops_important_count,
                oops_minor_count     = excluded.oops_minor_count,
                oops_pitfalls_json   = excluded.oops_pitfalls_json,
                has_nl_definition    = excluded.has_nl_definition,
                has_semiformal_def   = excluded.has_semiformal_def,
                has_fol_axiom        = excluded.has_fol_axiom,
                has_primitive_rationale = excluded.has_primitive_rationale,
                has_label_en         = excluded.has_label_en,
                has_label_pt         = excluded.has_label_pt,
                created_at           = strftime('%Y-%m-%dT%H:%M:%f','now')
            """,
            (
                enrichment_id,
                consistent_val,
                json.dumps(hr.get("inferred", []), ensure_ascii=False),
                hr.get("error"),
                op.get("critical", 0),
                op.get("important", 0),
                op.get("minor", 0),
                json.dumps(op.get("pitfalls", []), ensure_ascii=False),
                1 if af.get("has_nl_definition") else 0,
                1 if af.get("has_semiformal_def") else 0,
                1 if af.get("has_fol_axiom") else 0,
                1 if af.get("has_primitive_rationale") else 0,
                1 if af.get("has_label_en") else 0,
                1 if af.get("has_label_pt") else 0,
            ),
        )
        db.commit()
    except Exception as exc:
        logger.warning("take_verification_snapshot(%s) failed: %s", enrichment_id, exc)


# ── Field-level snapshot population ──────────────────────────────────────────

def _populate_field_snapshots(
    db: sqlite3.Connection,
    enrichment_id: int,
    snapshot_id: int,
    snapshot_type: str,
    step_data: dict,
    axiom_mode: str,
) -> None:
    """Normalize step_data fields into per-row eval_step_field_snapshot entries."""
    try:
        full = dict(step_data)
        full["axiom_mode"] = axiom_mode or ""

        rows = []
        for step_num, fields in _STEP_ATOMIC_FIELDS.items():
            for field in fields:
                val = _canonicalize(full.get(field))
                rows.append((
                    enrichment_id, snapshot_id, snapshot_type,
                    step_num, field, val, _sha16(val),
                ))

        db.executemany(
            """INSERT OR REPLACE INTO eval_step_field_snapshot
               (enrichment_id, snapshot_id, snapshot_type, step_number,
                field_name, field_value, field_value_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        db.commit()
    except Exception as exc:
        logger.warning("_populate_field_snapshots(%s) failed: %s", enrichment_id, exc)


def _populate_step_modification_summary(
    db: sqlite3.Connection,
    enrichment_id: int,
) -> None:
    """Compute and upsert per-step modification classification after final_export."""
    try:
        snapshots: dict[str, Any] = {}
        for row in db.execute(
            "SELECT snapshot_type, step_data_json, axiom_mode "
            "FROM eval_axiom_snapshot WHERE enrichment_id = ? ORDER BY created_at ASC",
            (enrichment_id,),
        ).fetchall():
            snapshots[row["snapshot_type"]] = row

        initial = snapshots.get("llm_initial")
        final   = snapshots.get("final_export")
        if not initial or not final:
            return

        try:
            init_data  = json.loads(initial["step_data_json"] or "{}")
            final_data = json.loads(final["step_data_json"]   or "{}")
        except (json.JSONDecodeError, TypeError):
            return

        init_data["axiom_mode"]  = initial["axiom_mode"] or ""
        final_data["axiom_mode"] = final["axiom_mode"]   or ""

        has_rerun = bool(db.execute(
            "SELECT 1 FROM eval_interaction_event "
            "WHERE enrichment_id = ? AND event_type = 'rerun_request' LIMIT 1",
            (enrichment_id,),
        ).fetchone())

        for step_num in range(1, 6):
            all_fields     = _STEP_ATOMIC_FIELDS.get(step_num, [])
            content_fields = _STEP_CONTENT_FIELDS.get(step_num, frozenset())

            changed_count = sum(
                1 for f in all_fields
                if _canonicalize(init_data.get(f)) != _canonicalize(final_data.get(f))
            )
            content_changed_count = sum(
                1 for f in content_fields
                if _canonicalize(init_data.get(f)) != _canonicalize(final_data.get(f))
            )
            mod_type = _classify_step_modification_type(
                step_num, init_data, final_data, has_rerun
            )

            db.execute(
                """INSERT INTO eval_step_modification_summary
                   (enrichment_id, step_number, modification_type,
                    total_field_count, changed_field_count, content_changed_count,
                    updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(enrichment_id, step_number) DO UPDATE SET
                       modification_type     = excluded.modification_type,
                       total_field_count     = excluded.total_field_count,
                       changed_field_count   = excluded.changed_field_count,
                       content_changed_count = excluded.content_changed_count,
                       updated_at            = excluded.updated_at""",
                (enrichment_id, step_num, mod_type,
                 len(all_fields), changed_count, content_changed_count),
            )
        db.commit()
    except Exception as exc:
        logger.warning("_populate_step_modification_summary(%s) failed: %s", enrichment_id, exc)


def _populate_genus_usage(
    db: sqlite3.Connection,
    enrichment_id: int,
) -> None:
    """Upsert genus usage record derived from llm_initial and final_export snapshots."""
    try:
        snapshots: dict[str, Any] = {}
        for row in db.execute(
            "SELECT snapshot_type, step_data_json "
            "FROM eval_axiom_snapshot WHERE enrichment_id = ? ORDER BY created_at ASC",
            (enrichment_id,),
        ).fetchall():
            snapshots[row["snapshot_type"]] = row

        initial = snapshots.get("llm_initial")
        final   = snapshots.get("final_export")
        if not initial or not final:
            return

        try:
            init_data  = json.loads(initial["step_data_json"] or "{}")
            final_data = json.loads(final["step_data_json"]   or "{}")
        except (json.JSONDecodeError, TypeError):
            return

        proposed = (init_data.get("genus") or "").strip() or None
        accepted = (final_data.get("genus") or "").strip() or None

        db.execute(
            """INSERT INTO eval_genus_usage
               (enrichment_id, proposed_genus, accepted_genus,
                proposed_source, accepted_source, changed_during_review)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(enrichment_id) DO UPDATE SET
                   proposed_genus        = excluded.proposed_genus,
                   accepted_genus        = excluded.accepted_genus,
                   proposed_source       = excluded.proposed_source,
                   accepted_source       = excluded.accepted_source,
                   changed_during_review = excluded.changed_during_review""",
            (
                enrichment_id,
                proposed, accepted,
                _classify_genus_source(proposed),
                _classify_genus_source(accepted),
                0 if proposed == accepted else 1,
            ),
        )
        db.commit()
    except Exception as exc:
        logger.warning("_populate_genus_usage(%s) failed: %s", enrichment_id, exc)


# ── Analytics ─────────────────────────────────────────────────────────────────

def compute_active_time_minutes(
    db: sqlite3.Connection,
    enrichment_id: int,
    idle_threshold_minutes: float = 15.0,
) -> float:
    """
    Estimate active editing time by summing inter-event gaps shorter than
    `idle_threshold_minutes`.  Returns total active minutes (float, 2 d.p.).
    """
    rows = db.execute(
        "SELECT created_at FROM eval_interaction_event "
        "WHERE enrichment_id = ? ORDER BY created_at ASC",
        (enrichment_id,),
    ).fetchall()

    if len(rows) < 2:
        return 0.0

    threshold_s = idle_threshold_minutes * 60.0
    times = [_parse_ts(str(r["created_at"])) for r in rows]
    total_s = 0.0
    for i in range(1, len(times)):
        delta = (times[i] - times[i - 1]).total_seconds()
        if 0 <= delta < threshold_s:
            total_s += delta

    return round(total_s / 60.0, 2)


def compute_axiom_diff(db: sqlite3.Connection, enrichment_id: int) -> dict[str, Any]:
    """
    Compare llm_initial vs final_export snapshots.

    Returns:
        {
          "has_initial": bool,
          "has_final":   bool,
          "acceptance_ratio": float | None,   # unchanged steps / 5
          "changed_steps":    list[str],       # e.g. ["step3", "step4"]
          "turtle_lines_added":   int,
          "turtle_lines_removed": int,
        }
    """
    rows = db.execute(
        "SELECT snapshot_type, turtle_content, step_data_json, axiom_mode "
        "FROM eval_axiom_snapshot WHERE enrichment_id = ? ORDER BY created_at ASC",
        (enrichment_id,),
    ).fetchall()

    snapshots: dict[str, Any] = {}
    for r in rows:
        snapshots[r["snapshot_type"]] = r  # last one wins per type

    initial = snapshots.get("llm_initial")
    final   = snapshots.get("final_export")

    result: dict[str, Any] = {
        "has_initial": initial is not None,
        "has_final":   final   is not None,
        "acceptance_ratio": None,
        "changed_steps": [],
        "turtle_lines_added": 0,
        "turtle_lines_removed": 0,
    }

    if not initial or not final:
        return result

    # --- step-level diff ---
    try:
        init_data  = json.loads(initial["step_data_json"] or "{}")
        final_data = json.loads(final["step_data_json"]   or "{}")
    except (json.JSONDecodeError, TypeError):
        return result

    changed_steps: list[str] = []
    for step_name, fields in _STEP_FIELDS.items():
        for field in fields:
            iv = init_data.get(field)
            fv = final_data.get(field)
            if isinstance(iv, (list, dict)):
                iv = json.dumps(iv, sort_keys=True)
            if isinstance(fv, (list, dict)):
                fv = json.dumps(fv, sort_keys=True)
            if iv != fv:
                changed_steps.append(step_name)
                break

    if initial["axiom_mode"] != final["axiom_mode"] and "step3" not in changed_steps:
        changed_steps.append("axiom_mode")

    n_steps = len(_STEP_FIELDS)
    n_content_changed = len([s for s in changed_steps if s != "axiom_mode"])
    result["acceptance_ratio"] = round((n_steps - n_content_changed) / n_steps, 3)
    result["changed_steps"] = changed_steps

    # --- turtle diff ---
    init_lines  = (initial["turtle_content"] or "").splitlines(keepends=True)
    final_lines = (final["turtle_content"]   or "").splitlines(keepends=True)
    added = removed = 0
    for line in difflib.unified_diff(init_lines, final_lines, n=0):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    result["turtle_lines_added"]   = added
    result["turtle_lines_removed"] = removed

    return result


def compute_field_level_diff(
    db: sqlite3.Connection,
    enrichment_id: int,
) -> dict[str, dict[str, str]]:
    """
    Field-level comparison of llm_initial vs final_export using pre-computed hashes.

    Returns:
        {
          "step_1": {"function_name": "unchanged", "process_name": "changed",
                     "function_rationale": "minor_edit"},
          ...
        }

    Field status values:
      "unchanged"  — hash identical between snapshots
      "changed"    — formal/content field differs
      "minor_edit" — rationale field differs (content fields all unchanged at step level)
    """
    snapshot_ids: dict[str, int] = {}
    for row in db.execute(
        "SELECT id, snapshot_type FROM eval_axiom_snapshot "
        "WHERE enrichment_id = ? ORDER BY created_at ASC",
        (enrichment_id,),
    ).fetchall():
        snapshot_ids[row["snapshot_type"]] = row["id"]

    if "llm_initial" not in snapshot_ids or "final_export" not in snapshot_ids:
        return {}

    def _get_hashes(snap_id: int) -> dict[tuple[int, str], str]:
        rows = db.execute(
            "SELECT step_number, field_name, field_value_hash "
            "FROM eval_step_field_snapshot WHERE snapshot_id = ?",
            (snap_id,),
        ).fetchall()
        return {(r["step_number"], r["field_name"]): r["field_value_hash"] for r in rows}

    init_h  = _get_hashes(snapshot_ids["llm_initial"])
    final_h = _get_hashes(snapshot_ids["final_export"])

    result: dict[str, dict[str, str]] = {}
    for step_num, fields in _STEP_ATOMIC_FIELDS.items():
        step_key = f"step_{step_num}"
        result[step_key] = {}
        content_fields = _STEP_CONTENT_FIELDS.get(step_num, frozenset())

        # Determine if any content field changed in this step
        step_content_changed = any(
            init_h.get((step_num, f)) != final_h.get((step_num, f))
            for f in content_fields
        )

        for field in fields:
            k = (step_num, field)
            if init_h.get(k) == final_h.get(k):
                result[step_key][field] = "unchanged"
            elif field in content_fields:
                result[step_key][field] = "changed"
            else:
                # Rationale field changed; label as minor_edit only when content is unchanged
                result[step_key][field] = "changed" if step_content_changed else "minor_edit"

    return result


def compute_time_per_step(
    db: sqlite3.Connection,
    enrichment_id: int,
    idle_threshold_minutes: float = 15.0,
) -> dict[str, float]:
    """
    Segment active editing time per step using ``step_focus`` interaction events.
    Returns {step_1: minutes, step_2: minutes, ...}.  Empty dict when no events exist.

    TODO (frontend): emit POST /enrich/{id}/event with
        {event_type: "step_focus", event_detail: {step_number: N}}
    whenever the ontologist expands a step accordion card in the detail editor.
    """
    rows = db.execute(
        "SELECT event_type, event_detail, created_at "
        "FROM eval_interaction_event WHERE enrichment_id = ? ORDER BY created_at ASC",
        (enrichment_id,),
    ).fetchall()

    focus_events = [r for r in rows if r["event_type"] == "step_focus"]
    if not focus_events:
        return {}

    threshold_s = idle_threshold_minutes * 60.0
    step_seconds: dict[int, float] = {}

    for i in range(len(focus_events) - 1):
        try:
            detail   = json.loads(focus_events[i]["event_detail"] or "{}")
            step_num = int(detail.get("step_number", 0))
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
        if step_num not in range(1, 6):
            continue

        t1 = _parse_ts(str(focus_events[i]["created_at"]))
        t2 = _parse_ts(str(focus_events[i + 1]["created_at"]))
        delta = (t2 - t1).total_seconds()

        if 0 <= delta < threshold_s:
            step_seconds[step_num] = step_seconds.get(step_num, 0.0) + delta

    return {f"step_{k}": round(v / 60.0, 2) for k, v in sorted(step_seconds.items())}
