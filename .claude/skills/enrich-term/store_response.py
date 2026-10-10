#!/usr/bin/env python3
"""
Step 2 of the enrich-term skill: parse the response the Claude Code session
produced (in place of the Anthropic API call), run it through the exact same
parsing and validators the production pipeline runs, and store it via the
real _store_proposal() write path with generation_path='skill_session'.

Usage:
    python .claude/skills/enrich-term/store_response.py <response_file> <model_id>

<response_file> is a plain text file containing the raw response text (the
JSON the 5-step method produces, possibly wrapped in markdown fences -- same
as what call_llm() receives from the Anthropic API and parses).

Requires .enrich_context.json (written by render_prompt.py in the same run)
to be present in this directory.

Runs, in order:
  1. JSON parsing (markdown-fence stripping) -- identical logic to call_llm()
  2. _validate_part_source_labels()      -- creation-time, non-blocking
  3. _validate_transformation_kind()     -- creation-time, non-blocking
     find_unvetted_participants()        -- creation-time, non-blocking (warns; blocks validation later)
  4. validate_disjointness()             -- creation-time, non-blocking (logs only)
  5. validate_tertiary_triangulation()   -- /update-path, BLOCKING
  6. validate_necessary_parts_quotes()   -- /update-path, BLOCKING
  7. validate_part_universality()        -- /update-path, BLOCKING
  8. _store_proposal(..., generation_path='skill_session')  -- the real write path

A BLOCKING validator failure prints the error and exits 1 without writing
anything -- matching what the /update route does (HTTP 422, no write).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "enrichment"))

from enrichment_service import (  # noqa: E402
    _validate_part_source_labels,
    _validate_transformation_kind,
    find_unvetted_participants,
    validate_necessary_parts_quotes,
    validate_part_universality,
    validate_tertiary_triangulation,
    _store_proposal,
)
from disjointness_validator import validate_disjointness  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent


def parse_llm_style_json(text: str) -> dict:
    """Identical logic to call_llm()'s parsing (enrichment_service.py) --
    strip markdown fences, then json.loads(). Raises ValueError on failure,
    same as call_llm() does."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned invalid JSON: {e}\nRaw: {text[:500]}")


def main():
    # The model is passed explicitly: a hardcoded constant silently misattributed
    # rows whenever the session ran on a different model than the one written here.
    if len(sys.argv) != 3:
        print("usage: store_response.py <response_file> <model_id>  "
              "(model_id = the model running this session, e.g. claude-opus-5)", file=sys.stderr)
        sys.exit(1)
    SKILL_MODEL = sys.argv[2]

    context_path = SKILL_DIR / ".enrich_context.json"
    if not context_path.exists():
        print(f"ERROR: {context_path} not found -- run render_prompt.py first.", file=sys.stderr)
        sys.exit(1)
    context = json.loads(context_path.read_text(encoding="utf-8"))
    cluster_label = context["cluster_label"]
    definitions = context["definitions"]
    component_terms = context["component_terms"]

    raw_text = Path(sys.argv[1]).read_text(encoding="utf-8")

    # 1. Parse
    try:
        proposal = parse_llm_style_json(raw_text)
    except ValueError as e:
        print(f"PARSE FAILED: {e}", file=sys.stderr)
        sys.exit(1)
    print("1. Parsed OK:", list(proposal.keys()))

    # 2-4. Creation-time, non-blocking checks (mirrors enrich_cluster())
    _validate_part_source_labels(proposal, component_terms, definitions)
    _validate_transformation_kind(proposal)
    disjointness_result = validate_disjointness(proposal)
    for candidate, case_id, reason in disjointness_result.get("rejected", []):
        print(f"   disjointness_rejected: candidate={candidate!r} case={case_id} reason={reason}")
    for candidate, reason in disjointness_result.get("rationale_invalid", []):
        print(f"   disjointness_rationale_invalid: candidate={candidate!r} reason={reason}")
    for warning in disjointness_result.get("asymmetry_warnings", []):
        print(f"   disjointness_asymmetry: {warning}")
    print("2-4. Creation-time checks done (non-blocking).")

    # Participant vocabulary -- non-blocking here (the row is stored as 'proposed'),
    # but it will block validation, so say so now while the session can still fix it.
    unvetted = find_unvetted_participants(proposal.get("step5_signature") or {})
    if unvetted:
        print(f"   WARNING participant types not in COPI vocabulary: {', '.join(unvetted)} -- "
              "this proposal cannot be validated until they are fixed; use the "
              "model-participant skill.")

    # Build source_definitions_used exactly as _store_proposal() will write it
    # (the OLD flat {source, term} shape -- _store_proposal() has not been
    # updated for the new tier/quote shape; using it verbatim is deliberate,
    # per instruction, not a skill bug -- see the session's finding on this).
    src_defs_json = json.dumps([{"source": d["source"], "term": d["term"]} for d in definitions])

    step4 = proposal.get("step4_parts") or proposal.get("step3_parts") or {}
    parts = step4.get("parts") or []

    # 5. validate_tertiary_triangulation -- /update path, BLOCKING
    tri_err = validate_tertiary_triangulation(src_defs_json)
    if tri_err:
        print(f"BLOCKED by validate_tertiary_triangulation: {tri_err}")
        sys.exit(1)
    print("5. validate_tertiary_triangulation: OK")

    # 6. validate_necessary_parts_quotes -- /update path, BLOCKING
    if parts:
        part_err = validate_necessary_parts_quotes(parts, src_defs_json)
        if part_err:
            print(f"BLOCKED by validate_necessary_parts_quotes: {part_err}")
            sys.exit(1)
        print("6. validate_necessary_parts_quotes: OK")

        # 7. validate_part_universality -- /update path, BLOCKING
        univ_err = validate_part_universality(parts)
        if univ_err:
            print(f"BLOCKED by validate_part_universality: {univ_err}")
            sys.exit(1)
        print("7. validate_part_universality: OK")
    else:
        print("6-7. No necessary_parts proposed -- quote/universality checks skipped (nothing to check).")

    # 8. Store -- the real write path
    proposal_id = _store_proposal(
        cluster_label, proposal, definitions, SKILL_MODEL,
        input_tokens=0, output_tokens=0, estimated_cost_usd=0.0,
        cache_write_tokens=0, cache_read_tokens=0,
        generation_path="skill_session",
    )
    print(f"8. Stored as enrichment.id={proposal_id}, status='proposed', "
          f"generation_path='skill_session', llm_model={SKILL_MODEL!r}")


if __name__ == "__main__":
    main()
