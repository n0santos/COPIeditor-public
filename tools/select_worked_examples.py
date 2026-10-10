#!/usr/bin/env python3
"""
Select two representative Worked Examples from enrichment.db for insertion into the
system prompt, then optionally apply the change.

Slot A — "clean" case: functional basis, equivalent axiom mode, T5+T2 flags.
Slot B — "rich" case: both/constructive basis, necessary axiom mode, T1/T3 diversity.

Modes:
  --dry-run  (default): print top-3 candidates per slot, write /tmp/worked_examples.md
  --apply:   insert into enrichment/prompts.py (auto-backup), then run validate + regression

Usage:
    python tools/select_worked_examples.py
    python tools/select_worked_examples.py --apply
    python tools/select_worked_examples.py --slot-a 147 --slot-b 166
    python tools/select_worked_examples.py --slot-a 147 --slot-b 166 --apply
"""

import argparse
import json
import re
import shutil
import sqlite3
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DB_PATH = _PROJECT_ROOT / "data" / "enrichment.db"
_PROMPTS_PATH = _PROJECT_ROOT / "enrichment" / "prompts.py"
_OUTPUT_PATH = Path("/tmp/worked_examples.md")

# Insertion marker: block is inserted just before "## Output Format"
_INSERT_BEFORE = "\n## Output Format\n"

_SLOT_A_TARGET = "functional"   # classification_basis
_SLOT_B_TARGET = "both"         # classification_basis (fallback: constructive)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_slot_a(r: dict) -> int:
    """Score a record for Slot A (clean functional/equivalent case). Higher = better."""
    score = 0
    p = r["proposal"]

    if r["basis"] == "functional" and r["axiom"] == "equivalent":
        score += 15
    elif r["basis"] == "functional":
        score += 8

    if r["conf"] == "high":
        score += 5

    if r["genus_enriched"]:
        score += 4

    if r["tks"] == "controlled":
        score += 4

    n_flags = len(r["flag_types"])
    if n_flags >= 2:
        score += 3
    if n_flags >= 3:
        score += 2
    if "T5_implicit_function" in r["flag_types"]:
        score += 2
    if "T2_granularity" in r["flag_types"]:
        score += 1

    n_parts = r["n_parts"]
    if 3 <= n_parts <= 6:
        score += 3
    elif n_parts >= 2:
        score += 1

    n_dw = r["n_dw"]
    if 1 <= n_dw <= 3:
        score += 2

    if r["has_case_ids"]:
        score += 3

    if r["status"] == "validated":
        score += 3

    if r["dw_all_in_db"]:
        score += 2

    # Soft penalty: parts with missing source_label trigger V5 warning
    # (most records predate the source_label feature; prefer records that have it)
    if r["parts_missing_source_label"] > 0:
        score -= 2

    return score


def _score_slot_b(r: dict) -> int:
    """Score a record for Slot B (rich constructive/both case). Higher = better."""
    score = 0

    if r["basis"] == "both" and r["axiom"] == "necessary":
        score += 15
    elif r["basis"] in ("constructive", "both") and r["axiom"] == "necessary":
        score += 10

    if r["basis"] == "both":
        score += 4  # prefer 'both' over purely constructive

    if r["conf"] == "high":
        score += 5

    if r["genus_enriched"]:
        score += 4

    if r["tks"] == "controlled":
        score += 4

    n_flags = len(r["flag_types"])
    if n_flags >= 3:
        score += 5
    elif n_flags >= 2:
        score += 2

    # T3 or T1 diversity is especially valuable for Slot B
    if "T3_identity" in r["flag_types"]:
        score += 2
    if "T1_categorical" in r["flag_types"]:
        score += 2

    n_parts = r["n_parts"]
    if n_parts >= 5:
        score += 4
    elif n_parts >= 3:
        score += 2

    if r["has_is_ss_mix"]:
        score += 3

    n_dw = r["n_dw"]
    if n_dw >= 2:
        score += 3
    elif n_dw >= 1:
        score += 1

    if r["has_case_ids"]:
        score += 3

    if r["status"] == "validated":
        score += 3

    if r["dw_all_in_db"]:
        score += 2

    # Soft penalty: parts with missing source_label trigger V5 warning
    if r["parts_missing_source_label"] > 0:
        score -= 2

    return score


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_all_labels(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT DISTINCT cluster_label FROM enrichment").fetchall()
    return {r[0].lower() for r in rows}


def _dw_all_in_db(dw_list: list, all_labels: set) -> bool:
    for item in dw_list:
        if item.lower() not in all_labels:
            return False
    return True


def load_candidates(conn: sqlite3.Connection) -> list[dict]:
    """Load one record per cluster (latest), returning scored candidate dicts."""
    rows = conn.execute(
        "SELECT id, cluster_label, status, llm_raw_response, "
        "divergence_flags, disjointness_rationale FROM enrichment ORDER BY id DESC"
    ).fetchall()

    all_labels = _load_all_labels(conn)

    seen: set = set()
    candidates: list[dict] = []

    for row in rows:
        lbl = row["cluster_label"]
        if lbl in seen:
            continue
        seen.add(lbl)

        try:
            p = json.loads(row["llm_raw_response"] or "{}")
        except Exception:
            continue

        flags_raw = row["divergence_flags"] or "[]"
        try:
            flags: list = json.loads(flags_raw)
        except Exception:
            flags = []

        basis = p.get("classification_basis") or ""
        axiom = p.get("axiom_mode") or ""
        conf = (p.get("confidence") or {}).get("overall") or ""
        ge = bool((p.get("step2_genus") or {}).get("genus_enriched"))
        step5 = p.get("step5_signature") or {}
        tks = step5.get("transformation_kind_status") or ""
        step4 = p.get("step4_parts") or {}
        parts = step4.get("parts") or []
        dw = p.get("disjoint_with") or []
        drat = row["disjointness_rationale"] or ""
        flag_types = [f.get("type", "") for f in flags]
        has_case_ids = any(f"C{i}:" in drat for i in range(1, 6))
        has_is_ss_mix = (
            any(pt.get("is_subtype_specific") is True for pt in parts)
            and any(pt.get("is_subtype_specific") is False for pt in parts)
        )
        # V5 pre-check: parts with source_label=None will fail validation
        parts_missing_source_label = sum(
            1 for pt in parts if pt.get("source_label") is None
        )

        candidates.append({
            "id": row["id"],
            "label": lbl,
            "status": row["status"],
            "basis": basis,
            "axiom": axiom,
            "conf": conf,
            "genus_enriched": ge,
            "tks": tks,
            "n_parts": len(parts),
            "n_dw": len(dw),
            "flag_types": flag_types,
            "has_case_ids": has_case_ids,
            "has_is_ss_mix": has_is_ss_mix,
            "dw_all_in_db": _dw_all_in_db(dw, all_labels),
            "parts_missing_source_label": parts_missing_source_label,
            "proposal": p,
            "flags": flags,
            "drat": drat,
        })

    return candidates


# ---------------------------------------------------------------------------
# Candidate ranking
# ---------------------------------------------------------------------------

def rank_candidates(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    slot_a = sorted(candidates, key=_score_slot_a, reverse=True)
    slot_b = sorted(candidates, key=_score_slot_b, reverse=True)
    return slot_a[:3], slot_b[:3]


def _relaxed_criteria(rec: dict, slot: str) -> list[str]:
    """List criteria that were relaxed for this record."""
    relaxed = []
    if slot == "A":
        if rec["basis"] != "functional":
            relaxed.append(f"classification_basis={rec['basis']!r} (target: 'functional')")
        if rec["axiom"] != "equivalent":
            relaxed.append(f"axiom_mode={rec['axiom']!r} (target: 'equivalent')")
        if not rec["genus_enriched"]:
            relaxed.append("genus_enriched=False")
        if len(rec["flag_types"]) < 2:
            relaxed.append(f"only {len(rec['flag_types'])} flag type(s) (target: ≥2)")
        if not (3 <= rec["n_parts"] <= 6):
            relaxed.append(f"parts={rec['n_parts']} (target: 3-6)")
    else:
        if rec["basis"] not in ("both", "constructive"):
            relaxed.append(f"classification_basis={rec['basis']!r} (target: 'both'/'constructive')")
        if rec["axiom"] != "necessary":
            relaxed.append(f"axiom_mode={rec['axiom']!r} (target: 'necessary')")
        if len(rec["flag_types"]) < 3:
            relaxed.append(f"only {len(rec['flag_types'])} flag type(s) (target: ≥3)")
        if rec["n_parts"] < 5:
            relaxed.append(f"parts={rec['n_parts']} (target: ≥5)")
        if not rec["has_is_ss_mix"]:
            relaxed.append("no is_subtype_specific mix in parts")
    if not rec["has_case_ids"]:
        relaxed.append("disjointness_rationale lacks C1:-C5: case identifiers")
    if not rec["dw_all_in_db"]:
        relaxed.append("some disjoint_with candidates not found in DB")
    if rec["parts_missing_source_label"] > 0:
        relaxed.append(
            f"{rec['parts_missing_source_label']} part(s) missing source_label (will fail V5)"
        )
    return relaxed


# ---------------------------------------------------------------------------
# Preview formatting
# ---------------------------------------------------------------------------

def _flag_summary(flags: list) -> str:
    types = sorted({f.get("type", "")[:2] for f in flags if f.get("type", "")})
    return f"[{', '.join(types)}]" if types else "[]"


def print_top3(top3: list[dict], slot: str) -> None:
    label = "A (functional/equivalent clean)" if slot == "A" else "B (both/necessary rich)"
    print(f"\n{'='*60}")
    print(f"Top-3 candidates for Slot {label}:")
    score_fn = _score_slot_a if slot == "A" else _score_slot_b
    for rank, rec in enumerate(top3, start=1):
        score = score_fn(rec)
        relaxed = _relaxed_criteria(rec, slot)
        flag_str = _flag_summary(rec["flags"])
        print(f"\n  #{rank} [{rec['id']}] '{rec['label']}' ({rec['status']}) — score={score}")
        print(f"       basis={rec['basis']} | axiom={rec['axiom']} | conf={rec['conf']}")
        print(f"       ge={rec['genus_enriched']} | tks={rec['tks']}")
        print(f"       parts={rec['n_parts']} | dw={rec['n_dw']} | flags={flag_str}")
        print(f"       case_ids={rec['has_case_ids']} | dw_all_in_db={rec['dw_all_in_db']} | miss_src={rec['parts_missing_source_label']}")
        if relaxed:
            print(f"       ⚠ relaxed: {'; '.join(relaxed)}")
        else:
            print(f"       ✓ all quality criteria met")


# ---------------------------------------------------------------------------
# "Why this example" notes
# ---------------------------------------------------------------------------

def _why_a(rec: dict) -> str:
    parts = []
    parts.append(
        f"Illustrates the **functional classification** path: the concept is defined "
        f"by its identity-giving function, yielding an `equivalent` axiom mode that "
        f"enables automatic reasoner classification."
    )
    flag_short = sorted({f.get("type", "")[:2] for f in rec["flags"] if f.get("type", "")})
    if flag_short:
        parts.append(
            f"Cross-standard divergence types present: {', '.join(flag_short)} — "
            f"showing how multiple divergence patterns co-occur in well-studied industrial equipment."
        )
    if rec["n_dw"] >= 1:
        parts.append(
            f"Disjointness assertions ({rec['n_dw']} candidate(s)) demonstrate the signature-based "
            f"disjointness decision procedure."
        )
    return " ".join(parts)


def _why_b(rec: dict) -> str:
    parts = []
    basis_str = rec["basis"]
    parts.append(
        f"Illustrates the **{basis_str} classification** path: the concept has "
        + ("both functional and constructive defining characteristics, " if basis_str == "both" else "")
        + f"yielding a `necessary`-only axiom mode (OWA prevents equivalence for constructive types)."
    )
    flag_short = sorted({f.get("type", "")[:2] for f in rec["flags"] if f.get("type", "")})
    if len(flag_short) >= 3:
        parts.append(
            f"Richer divergence profile ({', '.join(flag_short)}) demonstrates reasoning "
            f"across multiple divergence types simultaneously."
        )
    if rec["has_is_ss_mix"]:
        parts.append(
            "Step 4 parts include a mix of `is_subtype_specific: true/false`, showing "
            "how genus-level parts differ from subtype-specific differentia."
        )
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Soft-warning patches (--patch-soft-warnings)
# ---------------------------------------------------------------------------

def _camel_to_words(name: str) -> str:
    """'ValveBody' → 'valve body'"""
    return re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name).strip()


def _infer_source_label(
    part_name: str,
    component_terms: list[dict],
    definitions: list[dict],
) -> str | None:
    """
    Try to find `part_name` (CamelCase or plain) in component_terms labels
    or definition texts.  Returns the exact string as it appears in the source,
    or None if no match.
    """
    words = _camel_to_words(part_name)            # "ValveBody" → "Valve Body"
    words_lower = words.lower()                    # "valve body"
    name_lower = part_name.lower()                 # "valvebody"

    # Build lookup: lowercase → original label
    comp_by_lower = {
        (t.get("label") or "").strip().lower(): (t.get("label") or "").strip()
        for t in component_terms
    }

    # 1. Exact case-insensitive match in component labels
    for key, orig in comp_by_lower.items():
        if key in (name_lower, words_lower):
            return orig

    # 2. Literal substring in component labels (word boundary)
    for key, orig in comp_by_lower.items():
        if words_lower in key or name_lower in key:
            return orig

    # 3. Substring match in definition texts
    for d in definitions:
        text = d.get("definition") or ""
        for variant in (part_name, words, words.title()):
            if variant and variant in text:
                return variant

    return None


def patch_source_labels(
    proposal: dict,
    cluster_label: str,
) -> tuple[dict, list[str]]:
    """
    Populate missing source_label in step4_parts.parts using component_terms
    and cluster definitions from terms.db.
    Returns (patched_proposal, notes).
    """
    step4 = proposal.get("step4_parts") or {}
    parts = step4.get("parts") or []
    if not parts:
        return proposal, []

    sys.path.insert(0, str(_PROJECT_ROOT / "enrichment"))
    from enrichment_service import get_component_terms, get_cluster_definitions  # noqa: E402

    component_terms = get_component_terms(cluster_label)
    definitions = get_cluster_definitions(cluster_label)

    notes: list[str] = []
    for part in parts:
        if part.get("source_label") is not None:
            continue
        name = part.get("name") or ""
        inferred = _infer_source_label(name, component_terms, definitions)
        if inferred:
            part["source_label"] = inferred
            notes.append(f"  source_label inferred for '{name}': {inferred!r}")
        else:
            # Leave source_label absent; annotate rationale for transparency
            existing_rat = part.get("rationale") or ""
            part["rationale"] = (
                f"[source_label inference failed] {existing_rat}".strip()
            )
            notes.append(f"  source_label inference FAILED for '{name}'")

    proposal = dict(proposal)
    proposal["step4_parts"] = {**step4, "parts": parts}
    return proposal, notes


def patch_disjointness_rationale(
    proposal: dict,
    ontology_state: dict,
    norm_index: dict,
) -> tuple[dict, list[str]]:
    """
    Prefix disjointness_rationale with C1:–C5: case identifiers derived from the
    5-case decision tree.  Removes pairs rejected by the tree.
    Returns (patched_proposal, notes).
    """
    sys.path.insert(0, str(_PROJECT_ROOT / "enrichment"))
    from disjointness_validator import (  # noqa: E402
        normalise_label,
        validate_pair_structural,
        _step5_of,
    )

    dw: list = list(proposal.get("disjoint_with") or [])
    drat: str = proposal.get("disjointness_rationale") or ""

    if not dw:
        return proposal, []

    # Already has case IDs — nothing to do
    if any(f"C{i}:" in drat for i in range(1, 6)):
        return proposal, ["  rationale already has case identifiers — skipped"]

    x_label = proposal.get("cluster_label") or ""
    x_basis = proposal.get("classification_basis") or ""
    x_genus = (proposal.get("step2_genus") or {}).get("genus_name") or ""
    step5_x = proposal.get("step5_signature") or {}
    x_kind = step5_x.get("transformation_kind") or ""
    x_kind_status = step5_x.get("transformation_kind_status") or ""

    preserved: list[tuple[str, str, str]] = []   # (c_label, case_id, reason)
    rejected: list[tuple[str, str, str]] = []    # (c_label, case_id, reason)
    unverifiable: list[tuple[str, str]] = []     # (c_label, reason)

    for candidate in dw:
        c_row = ontology_state.get(candidate)
        resolved = candidate
        if c_row is None:
            resolved = norm_index.get(normalise_label(candidate), "")
            if resolved:
                c_row = ontology_state[resolved]

        if c_row is None:
            unverifiable.append((candidate, "not found in DB"))
            continue

        c_basis = c_row.get("classification_basis") or ""
        # genus stored in SQL column or inside proposal JSON
        raw_c = c_row.get("llm_raw_response") or "{}"
        parsed_c = json.loads(raw_c) if isinstance(raw_c, str) else raw_c
        c_genus = (
            c_row.get("genus")
            or (parsed_c.get("step2_genus") or {}).get("genus_name")
            or ""
        )
        step5_c = _step5_of(c_row)
        c_kind = step5_c.get("transformation_kind") or ""
        c_kind_status = step5_c.get("transformation_kind_status") or ""

        classification, case_id, reason = validate_pair_structural(
            x_label, x_basis, x_genus, x_kind, x_kind_status,
            resolved or candidate, c_basis, c_genus, c_kind, c_kind_status,
        )

        if classification == "preserved_by_structure":
            preserved.append((candidate, case_id, reason))
        elif classification == "rejected_by_structure":
            rejected.append((candidate, case_id, reason))
        else:
            unverifiable.append((candidate, reason))

    notes: list[str] = []

    # Remove rejected items
    for c_label, case_id, reason in rejected:
        if c_label in dw:
            dw.remove(c_label)
            notes.append(f"  REMOVED (rejected {case_id}): '{c_label}' — {reason}")

    # Build prefix: group preserved by case_id, then unverifiable
    by_case: dict[str, list[str]] = defaultdict(list)
    for c_label, case_id, _ in preserved:
        case_key = case_id if case_id.startswith("C") else f"C{case_id}"
        by_case[case_key].append(c_label)

    prefix_parts: list[str] = []
    for case_key in sorted(by_case.keys()):
        cs = ", ".join(by_case[case_key])
        prefix_parts.append(f"{case_key}: {cs}")
        notes.append(f"  prefixed {case_key}: {cs}")

    for c_label, reason in unverifiable:
        prefix_parts.append(f"C?: {c_label} [unverifiable]")
        notes.append(f"  unverifiable: '{c_label}' — {reason}")

    new_drat = (". ".join(prefix_parts) + ". " + drat).strip() if prefix_parts else drat

    proposal = dict(proposal)
    proposal["disjoint_with"] = dw
    proposal["disjointness_rationale"] = new_drat
    return proposal, notes


def apply_soft_warning_patches(
    rec_a: dict,
    rec_b: dict,
) -> tuple[dict, dict]:
    """
    Apply source_label and disjointness patches to both example proposals in-place.
    Returns (patched_rec_a, patched_rec_b).
    """
    sys.path.insert(0, str(_PROJECT_ROOT / "enrichment"))
    from disjointness_validator import (  # noqa: E402
        build_ontology_state,
        build_normalised_index,
    )

    print("\nLoading ontology state for disjointness patches...", flush=True)
    ontology_state = build_ontology_state()
    norm_index = build_normalised_index(ontology_state)

    patched_records = []
    for slot, rec in [("A", rec_a), ("B", rec_b)]:
        proposal = dict(rec["proposal"])
        # Merge divergence_flags from SQL column if absent in JSON
        if not proposal.get("divergence_flags"):
            proposal["divergence_flags"] = rec["flags"]

        label = rec["label"]
        print(f"\n  Slot {slot} — '{label}':")

        # Patch 1: source_label
        print("    Patch 1: source_label inference...", flush=True)
        proposal, notes1 = patch_source_labels(proposal, label)
        for note in notes1:
            print(note)

        # Patch 2: disjointness rationale
        print("    Patch 2: disjointness rationale case IDs...", flush=True)
        proposal, notes2 = patch_disjointness_rationale(
            proposal, ontology_state, norm_index
        )
        for note in notes2:
            print(note)

        patched_rec = dict(rec)
        patched_rec["proposal"] = proposal
        # Update metadata to reflect patch results
        patched_rec["flags"] = proposal.get("divergence_flags") or []
        patched_records.append(patched_rec)

    return patched_records[0], patched_records[1]


# ---------------------------------------------------------------------------
# Inline validation (used after --patch-soft-warnings)
# ---------------------------------------------------------------------------

def _run_inline_validation(md_block: str) -> tuple[int, int]:
    """
    Import validate_examples, extract JSON blocks from md_block, and run all
    validators inline (no file write required).
    Returns (hard_failures, warnings).
    """
    sys.path.insert(0, str(_PROJECT_ROOT / "tools"))
    sys.path.insert(0, str(_PROJECT_ROOT / "enrichment"))
    import validate_examples as ve  # noqa: E402

    # Wrap in synthetic prompt text so extract_examples() finds the section
    fake_prompt = md_block + "\n## Output Format\n"
    examples = ve.extract_examples(fake_prompt)

    if not examples:
        print("  (no examples found in block — skipping validation)")
        return 0, 0

    # Load DB labels for V4
    conn = sqlite3.connect(str(_DB_PATH))
    all_labels = {r[0].lower() for r in conn.execute(
        "SELECT DISTINCT cluster_label FROM enrichment"
    ).fetchall()}
    conn.close()

    validators_config = [
        ("V1", "Schema completeness", False),
        ("V2", "transformation_kind controlled vocab", False),
        ("V3", "disjointness_rationale case identifier", True),
        ("V4", "disjoint_with classes exist in DB", False),
        ("V5", "part source_label present", True),
        ("V6", "divergence_flags sources_involved non-empty", False),
        ("V7", "axiom_mode valid enum", False),
        ("V8", "classification_basis valid enum", False),
    ]

    results: dict[str, ve.ValidationResult] = {
        code: ve.ValidationResult(code, label, soft=soft)
        for code, label, soft in validators_config
    }

    for ex_label, obj in examples:
        ve.v1_schema(ex_label, obj, results["V1"])
        ve.v2_transformation_kind(ex_label, obj, results["V2"])
        ve.v3_disjointness_rationale(ex_label, obj, results["V3"])
        ve.v4_disjoint_classes_in_db(ex_label, obj, results["V4"], all_labels)
        ve.v5_part_source_labels(ex_label, obj, results["V5"])
        ve.v6_divergence_flags_sources(ex_label, obj, results["V6"])
        ve.v7_axiom_mode(ex_label, obj, results["V7"])
        ve.v8_classification_basis(ex_label, obj, results["V8"])

    hard_failures = 0
    warnings = 0

    print(f"\nPost-patch validation ({len(examples)} example(s)):")
    for code, res in results.items():
        if res.failures:
            tag = "WARN" if res.soft else "FAIL"
            if res.soft:
                warnings += 1
            else:
                hard_failures += 1
        else:
            tag = "pass"
        print(f"  [{tag}] {code}: {res.label}")
        for msg in res.failures:
            print(f"         ✗ {msg}")

    print()
    if hard_failures == 0 and warnings == 0:
        print(f"  All {len(results)} validators passed.")
    elif hard_failures == 0:
        print(f"  ✓ No hard failures. {warnings} warning(s).")
    else:
        print(f"  ✗ {hard_failures} hard failure(s), {warnings} warning(s).")

    return hard_failures, warnings


# ---------------------------------------------------------------------------
# JSON preparation for prompt insertion
# ---------------------------------------------------------------------------

_FIELDS_ORDER = [
    "cluster_label", "classification_basis", "classification_basis_rationale",
    "step1_function", "step2_genus", "step3_differentia", "step4_parts",
    "step5_signature", "axiom_mode", "primitive_rationale",
    "disjoint_with", "disjointness_rationale",
    "definitions", "divergence_flags", "cross_standard_notes", "confidence",
]


def _ordered_proposal(p: dict) -> dict:
    """Return proposal dict with fields in canonical order for readability."""
    result = {}
    for key in _FIELDS_ORDER:
        if key in p:
            result[key] = p[key]
    # Append any remaining fields not in the canonical order
    for key in p:
        if key not in result:
            result[key] = p[key]
    return result


# ---------------------------------------------------------------------------
# Markdown generation
# ---------------------------------------------------------------------------

def render_worked_examples(rec_a: dict, rec_b: dict) -> str:
    lines: list[str] = [
        "## Worked Examples",
        "",
        "The examples below demonstrate the complete output format for representative cases.",
        "Use them as a reference for structure and level of detail expected.",
        "Do NOT copy content verbatim — always ground the output in the actual definitions",
        "provided in the user prompt.",
        "",
    ]

    for slot, rec, why_fn in [("A", rec_a, _why_a), ("B", rec_b, _why_b)]:
        lbl = rec["label"]
        flag_short = sorted({f.get("type", "")[:2] for f in rec["flags"] if f.get("type", "")})
        flag_str = f"[{', '.join(flag_short)}]" if flag_short else "none"
        relaxed = _relaxed_criteria(rec, slot)

        lines += [
            f"### Example {slot}: {lbl}",
            "",
            f"**Why this example:** {why_fn(rec)}",
            "",
        ]
        if relaxed:
            lines += [
                f"_Note: criteria relaxed for this selection: {'; '.join(relaxed)}._",
                "",
            ]

        # Merge divergence_flags from SQL column if not present in proposal JSON
        # (old records store divergence_flags in a separate DB column, not in llm_raw_response)
        base = dict(rec["proposal"])
        if not base.get("divergence_flags"):
            base["divergence_flags"] = rec["flags"]
        proposal = _ordered_proposal(base)
        json_str = json.dumps(proposal, indent=2, ensure_ascii=False)

        lines += [
            "```json",
            json_str,
            "```",
            "",
        ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompt insertion
# ---------------------------------------------------------------------------

def _backup_prompt() -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = _PROMPTS_PATH.with_name(f"prompts_backup_{ts}.py")
    shutil.copy2(_PROMPTS_PATH, bak)
    print(f"  Backup: {bak}")
    return bak


def _prompt_already_has_examples(text: str) -> bool:
    return "## Worked Examples" in text


def apply_to_prompt(md_block: str) -> Path:
    """Insert worked examples into prompts.py. Returns backup path."""
    text = _PROMPTS_PATH.read_text(encoding="utf-8")

    if _prompt_already_has_examples(text):
        print("  ⚠ '## Worked Examples' already present — removing old block before inserting.")
        # Find start: look for the section header inside the prompt string
        start_marker = "## Worked Examples"
        end_marker = "\n## Output Format"
        start = text.find(start_marker)
        end = text.find(end_marker, start)
        if start != -1 and end != -1:
            text = text[:start] + text[end + 1:]  # +1 strips leading \n
        else:
            sys.exit("  ERROR: Could not locate old Worked Examples block boundaries.")

    if _INSERT_BEFORE not in text:
        sys.exit(f"  ERROR: Insertion marker not found in {_PROMPTS_PATH}:\n  {_INSERT_BEFORE!r}")

    bak = _backup_prompt()

    new_text = text.replace(
        _INSERT_BEFORE,
        "\n" + md_block + "\n" + _INSERT_BEFORE,
        1,
    )
    _PROMPTS_PATH.write_text(new_text, encoding="utf-8")
    return bak


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--apply", action="store_true", default=False,
        help="Insert into prompts.py, run validate_examples.py and regression compare.",
    )
    parser.add_argument(
        "--slot-a", type=int, metavar="ID",
        help="Override Slot A: use record with this enrichment ID.",
    )
    parser.add_argument(
        "--slot-b", type=int, metavar="ID",
        help="Override Slot B: use record with this enrichment ID.",
    )
    parser.add_argument(
        "--output", default=str(_OUTPUT_PATH),
        help=f"Output path for worked_examples.md (default: {_OUTPUT_PATH}).",
    )
    parser.add_argument(
        "--patch-soft-warnings", action="store_true", default=False,
        help=(
            "Infer missing source_labels for Step 4 parts (Patch 1) and prefix "
            "disjointness_rationale with C1:–C5: case IDs (Patch 2). "
            "Validates the patched block; aborts --apply on remaining hard failures."
        ),
    )
    args = parser.parse_args()

    if not _DB_PATH.exists():
        sys.exit(f"Enrichment DB not found: {_DB_PATH}")

    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row

    print("Loading candidates...", flush=True)
    candidates = load_candidates(conn)
    print(f"  {len(candidates)} unique clusters loaded", flush=True)

    top_a, top_b = rank_candidates(candidates)

    print_top3(top_a, "A")
    print_top3(top_b, "B")

    # Select (override or auto-pick)
    by_id = {r["id"]: r for r in candidates}

    if args.slot_a:
        rec_a = by_id.get(args.slot_a)
        if rec_a is None:
            sys.exit(f"ERROR: --slot-a {args.slot_a} not found in candidates.")
        print(f"\n⇒ Slot A override: [{rec_a['id']}] '{rec_a['label']}'")
    else:
        rec_a = top_a[0]
        print(f"\n⇒ Slot A auto-selected: [{rec_a['id']}] '{rec_a['label']}'")

    if args.slot_b:
        rec_b = by_id.get(args.slot_b)
        if rec_b is None:
            sys.exit(f"ERROR: --slot-b {args.slot_b} not found in candidates.")
        print(f"⇒ Slot B override: [{rec_b['id']}] '{rec_b['label']}'")
    else:
        rec_b = top_b[0]
        print(f"⇒ Slot B auto-selected: [{rec_b['id']}] '{rec_b['label']}'")

    conn.close()

    # Warn if both slots picked the same record
    if rec_a["id"] == rec_b["id"]:
        print(f"\n  ⚠ Both slots selected the same record [{rec_a['id']}]."
              f" Use --slot-a / --slot-b to override.")
        rec_b = top_b[1] if len(top_b) > 1 and top_b[1]["id"] != rec_a["id"] else top_b[-1]
        print(f"  Auto-bumped Slot B to [{rec_b['id']}] '{rec_b['label']}'")

    # Apply soft-warning patches before rendering (if requested)
    if args.patch_soft_warnings:
        print("\nApplying soft-warning patches...")
        rec_a, rec_b = apply_soft_warning_patches(rec_a, rec_b)

    md_block = render_worked_examples(rec_a, rec_b)

    out_path = Path(args.output)
    out_path.write_text(md_block, encoding="utf-8")
    print(f"\nWorked examples written to: {out_path}")

    # Prompt size estimate
    prompt_text = _PROMPTS_PATH.read_text(encoding="utf-8")
    added_chars = len(md_block)
    existing_chars = len(prompt_text)
    print(f"\nPrompt size estimate:")
    print(f"  Current: ~{existing_chars:,} chars")
    print(f"  Addition: ~{added_chars:,} chars ({round(100*added_chars/existing_chars,1)}% increase)")
    tokens_approx = (existing_chars + added_chars) // 4
    print(f"  Estimated total: ~{tokens_approx:,} tokens (÷4 heuristic)")

    # Inline validation after patching (shown in both dry-run and apply modes)
    if args.patch_soft_warnings:
        hard_failures, _ = _run_inline_validation(md_block)
        if args.apply and hard_failures > 0:
            sys.exit(
                f"\n✗ Aborting --apply: {hard_failures} hard failure(s) remain after patch. "
                "Fix the examples or remove --apply."
            )

    if not args.apply:
        print("\n[DRY-RUN] Pass --apply to insert into prompts.py.")
        return

    # --- APPLY ---
    print("\nApplying to prompts.py...")
    bak = apply_to_prompt(md_block)
    print("  Inserted successfully.")

    # Validate
    validate_script = _PROJECT_ROOT / "tools" / "validate_examples.py"
    if validate_script.exists():
        print("\nRunning validate_examples.py...")
        result = subprocess.run(
            [sys.executable, str(validate_script)],
            capture_output=True, text=True,
        )
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        if result.returncode != 0:
            print("  ✗ Validation failed. Rolling back...")
            shutil.copy2(bak, _PROMPTS_PATH)
            print(f"  Restored from backup: {bak}")
            sys.exit(1)
        print("  ✓ Validation passed.")
    else:
        print("  (validate_examples.py not found — skipping validation)")

    # Regression compare
    regression_script = _PROJECT_ROOT / "tests" / "regression.py"
    if regression_script.exists():
        api_key = __import__("os").environ.get("ANTHROPIC_API_KEY", "")
        if api_key:
            print("\nRunning regression compare...")
            result = subprocess.run(
                [sys.executable, str(regression_script), "compare"],
                capture_output=True, text=True,
                env={**__import__("os").environ},
            )
            print(result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout)
            if result.returncode != 0:
                print("  ⚠ Regression differences detected (see output above).")
                print("  Prompt change is preserved — review diffs manually and update baselines if expected.")
            else:
                print("  ✓ All regression baselines match.")
        else:
            print("\n  (ANTHROPIC_API_KEY not set — skipping regression compare)")
    else:
        print("  (regression.py not found — skipping)")

    print(f"\n✓ Done. Worked examples inserted into {_PROMPTS_PATH}")
    print(f"  Backup: {bak}")


if __name__ == "__main__":
    main()
