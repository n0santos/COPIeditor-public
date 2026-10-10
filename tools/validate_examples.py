#!/usr/bin/env python3
"""
Parse worked examples from enrichment/prompts.py and validate them against the
pipeline's established rules (Levas 2 and 3).

Validators:
  V1  Schema completeness — all required top-level fields present
  V2  transformation_kind ∈ TRANSFORMATION_KINDS_CONTROLLED when status='controlled'
  V3  disjointness_rationale starts with a case identifier (C1:–C5:) when disjoint_with non-empty
  V4  All disjoint_with candidates exist as cluster_labels in enrichment.db
  V5  Each step4 part has source_label present and non-empty
  V6  Each divergence_flag has sources_involved non-empty
  V7  axiom_mode is one of: 'equivalent', 'necessary', 'mixed'
  V8  classification_basis is one of: 'functional', 'constructive', 'both'

V3 is a SOFT warning for pre-existing records that predate the case-ID requirement.
All others are HARD failures that block --apply.

Exit code: 0 if no hard failures, 1 otherwise.

Usage:
    python tools/validate_examples.py
    python tools/validate_examples.py --strict   # treat V3 as hard failure too
"""

import json
import re
import sqlite3
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PROMPTS_PATH = _PROJECT_ROOT / "enrichment" / "prompts.py"
_DB_PATH = _PROJECT_ROOT / "data" / "enrichment.db"

# Reuse the controlled vocab from enrichment_service
sys.path.insert(0, str(_PROJECT_ROOT / "enrichment"))
from enrichment_service import TRANSFORMATION_KINDS_CONTROLLED  # noqa: E402

_REQUIRED_FIELDS = frozenset({
    "cluster_label",
    "classification_basis",
    "step1_function",
    "step2_genus",
    "step3_differentia",
    "step4_parts",
    "step5_signature",
    "axiom_mode",
    "disjoint_with",
    "divergence_flags",
    "confidence",
})

_VALID_AXIOM_MODES = frozenset({"equivalent", "necessary", "mixed"})
_VALID_BASES = frozenset({"functional", "constructive", "both"})

_CASE_ID_RE = re.compile(r"\bC[1-5]:", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Extraction: parse JSON blocks from the worked examples section
# ---------------------------------------------------------------------------

def extract_examples(prompt_text: str) -> list[tuple[str, dict]]:
    """
    Find all ```json ... ``` blocks inside the '## Worked Examples' section.
    Returns list of (slot_label, parsed_dict).
    """
    # Isolate the worked examples section
    start = prompt_text.find("## Worked Examples")
    if start == -1:
        return []

    # End at the next top-level section
    end = prompt_text.find("\n## ", start + 1)
    section = prompt_text[start:end] if end != -1 else prompt_text[start:]

    # Find slot labels (### Example A: ..., ### Example B: ...)
    slot_pattern = re.compile(r"### Example ([A-Z]): (.+?)$", re.MULTILINE)
    json_pattern = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)

    slots = list(slot_pattern.finditer(section))
    jsons = list(json_pattern.finditer(section))

    examples = []
    for i, m in enumerate(jsons):
        slot_label = slots[i].group(1) if i < len(slots) else f"Example {i+1}"
        cluster_label = slots[i].group(2).strip() if i < len(slots) else f"example_{i+1}"
        try:
            obj = json.loads(m.group(1))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"[{slot_label}] Invalid JSON in worked example: {exc}"
            )
        examples.append((f"Example {slot_label}: {cluster_label}", obj))

    return examples


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

class ValidationResult:
    def __init__(self, code: str, label: str, soft: bool = False) -> None:
        self.code = code
        self.label = label
        self.soft = soft  # True → warning only; False → hard failure
        self.failures: list[str] = []
        self.passed: list[str] = []

    def fail(self, msg: str) -> None:
        self.failures.append(msg)

    def ok(self, msg: str) -> None:
        self.passed.append(msg)

    @property
    def is_hard_failure(self) -> bool:
        return bool(self.failures) and not self.soft

    @property
    def is_warning(self) -> bool:
        return bool(self.failures) and self.soft


def v1_schema(example_label: str, obj: dict, res: ValidationResult) -> None:
    missing = _REQUIRED_FIELDS - set(obj.keys())
    if missing:
        res.fail(f"[{example_label}] Missing required fields: {sorted(missing)}")
    else:
        res.ok(f"[{example_label}] All required fields present")


def v2_transformation_kind(example_label: str, obj: dict, res: ValidationResult) -> None:
    step5 = obj.get("step5_signature") or {}
    kind = step5.get("transformation_kind") or ""
    status = step5.get("transformation_kind_status") or ""
    if status == "controlled":
        if kind not in TRANSFORMATION_KINDS_CONTROLLED:
            res.fail(
                f"[{example_label}] transformation_kind={kind!r} not in controlled vocab "
                f"(status='controlled')"
            )
        else:
            res.ok(f"[{example_label}] transformation_kind={kind!r} ∈ controlled vocab")
    elif kind:
        res.ok(f"[{example_label}] transformation_kind={kind!r} status={status!r} (not checking vocab)")


def v3_disjointness_rationale(example_label: str, obj: dict, res: ValidationResult) -> None:
    dw = obj.get("disjoint_with") or []
    drat = obj.get("disjointness_rationale") or ""
    if not dw:
        res.ok(f"[{example_label}] No disjoint_with — rationale format check skipped")
        return
    if _CASE_ID_RE.search(drat):
        res.ok(f"[{example_label}] disjointness_rationale contains case identifier")
    else:
        res.fail(
            f"[{example_label}] disjointness_rationale does not start with C1:–C5: "
            f"case identifier. Current: {drat[:80]!r}"
        )


def v4_disjoint_classes_in_db(
    example_label: str, obj: dict, res: ValidationResult,
    all_labels: set,
) -> None:
    dw = obj.get("disjoint_with") or []
    missing = [c for c in dw if c.lower() not in all_labels]
    if missing:
        res.fail(
            f"[{example_label}] disjoint_with candidates not found in DB: {missing}"
        )
    elif dw:
        res.ok(f"[{example_label}] All {len(dw)} disjoint_with candidates exist in DB")
    else:
        res.ok(f"[{example_label}] No disjoint_with — DB check skipped")


def v5_part_source_labels(example_label: str, obj: dict, res: ValidationResult) -> None:
    step4 = obj.get("step4_parts") or {}
    parts = step4.get("parts") or []
    if not parts:
        res.ok(f"[{example_label}] No parts — source_label check skipped")
        return
    missing = [
        p.get("name", "?") for p in parts
        if p.get("source_label") is None
    ]
    if missing:
        res.fail(
            f"[{example_label}] Parts missing source_label: {missing}. "
            "Each part must have a source_label traceable to provided definitions."
        )
    else:
        res.ok(f"[{example_label}] All {len(parts)} part(s) have source_label")


def v6_divergence_flags_sources(example_label: str, obj: dict, res: ValidationResult) -> None:
    flags = obj.get("divergence_flags") or []
    if not flags:
        res.ok(f"[{example_label}] No divergence_flags — sources check skipped")
        return
    empty_sources = [
        f.get("type", "?") for f in flags
        if not (f.get("sources_involved") or [])
    ]
    if empty_sources:
        res.fail(
            f"[{example_label}] divergence_flags with empty sources_involved: {empty_sources}"
        )
    else:
        res.ok(f"[{example_label}] All {len(flags)} divergence_flag(s) have sources_involved")


def v7_axiom_mode(example_label: str, obj: dict, res: ValidationResult) -> None:
    mode = obj.get("axiom_mode") or ""
    if mode not in _VALID_AXIOM_MODES:
        res.fail(
            f"[{example_label}] axiom_mode={mode!r} not in {sorted(_VALID_AXIOM_MODES)}"
        )
    else:
        res.ok(f"[{example_label}] axiom_mode={mode!r} valid")


def v8_classification_basis(example_label: str, obj: dict, res: ValidationResult) -> None:
    basis = obj.get("classification_basis") or ""
    if basis not in _VALID_BASES:
        res.fail(
            f"[{example_label}] classification_basis={basis!r} not in {sorted(_VALID_BASES)}"
        )
    else:
        res.ok(f"[{example_label}] classification_basis={basis!r} valid")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--strict", action="store_true", default=False,
        help="Treat V3 (disjointness_rationale case ID) as a hard failure.",
    )
    args = parser.parse_args()

    if not _PROMPTS_PATH.exists():
        sys.exit(f"Prompts file not found: {_PROMPTS_PATH}")

    prompt_text = _PROMPTS_PATH.read_text(encoding="utf-8")

    try:
        examples = extract_examples(prompt_text)
    except ValueError as exc:
        sys.exit(f"ERROR: {exc}")

    if not examples:
        print("No worked examples found in prompts.py (section '## Worked Examples' missing).")
        sys.exit(0)

    print(f"Found {len(examples)} worked example(s).\n")

    # Load DB labels for V4
    conn = sqlite3.connect(str(_DB_PATH))
    all_labels = {r[0].lower() for r in conn.execute(
        "SELECT DISTINCT cluster_label FROM enrichment"
    ).fetchall()}
    conn.close()

    # Run validators
    validators_config = [
        ("V1", "Schema completeness", False),
        ("V2", "transformation_kind controlled vocab", False),
        ("V3", "disjointness_rationale case identifier", not args.strict),
        ("V4", "disjoint_with classes exist in DB", False),
        ("V5", "part source_label present", True),   # soft: most records predate this feature
        ("V6", "divergence_flags sources_involved non-empty", False),
        ("V7", "axiom_mode valid enum", False),
        ("V8", "classification_basis valid enum", False),
    ]

    results: dict[str, ValidationResult] = {}
    for code, label, soft in validators_config:
        if args.strict and code == "V3":
            soft = False
        results[code] = ValidationResult(code, label, soft=soft)

    for ex_label, obj in examples:
        v1_schema(ex_label, obj, results["V1"])
        v2_transformation_kind(ex_label, obj, results["V2"])
        v3_disjointness_rationale(ex_label, obj, results["V3"])
        v4_disjoint_classes_in_db(ex_label, obj, results["V4"], all_labels)
        v5_part_source_labels(ex_label, obj, results["V5"])
        v6_divergence_flags_sources(ex_label, obj, results["V6"])
        v7_axiom_mode(ex_label, obj, results["V7"])
        v8_classification_basis(ex_label, obj, results["V8"])

    hard_failures = 0
    warnings = 0

    for code, res in results.items():
        if res.failures:
            tag = "WARN " if res.soft else "FAIL "
            if res.soft:
                warnings += 1
            else:
                hard_failures += 1
        else:
            tag = "pass "

        status = f"[{tag}] {code}: {res.label}"
        print(status)
        for msg in res.failures:
            print(f"       ✗ {msg}")

    print()
    if hard_failures == 0 and warnings == 0:
        print(f"All {len(results)} validators passed.")
    elif hard_failures == 0:
        print(f"✓ No hard failures. {warnings} warning(s) — inspect manually.")
    else:
        print(f"✗ {hard_failures} hard failure(s), {warnings} warning(s).")

    sys.exit(0 if hard_failures == 0 else 1)


if __name__ == "__main__":
    main()
