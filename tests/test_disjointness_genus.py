"""Regression tests for issue #2 — the disjointness validator must compare the
*curated* `genus` column for both the proposal-under-test and its candidates,
not the frozen LLM `step2_genus` (which drifts stale after curation) and not
case-sensitively (the column is PascalCase, LLM text is lowercase-spaced)."""
import json

from enrichment.disjointness_validator import validate_disjointness


def _entry(genus, basis="constructive", kind="measurement_transduction"):
    """An ontology_state / candidate row shaped as validate_disjointness expects."""
    return {
        "cluster_label": "c",
        "genus": genus,
        "classification_basis": basis,
        "llm_raw_response": json.dumps({
            "classification_basis": basis,
            "step5_signature": {
                "transformation_kind": kind,
                "transformation_kind_status": "controlled",
            },
        }),
    }


def test_stale_step2_genus_uses_curated_column_not_llm():
    """X's frozen LLM step2_genus ('detecting element') is stale; the curated
    `genus` column says 'Instrument', same as the candidate. The validator must
    compare curated genera and NOT emit a false Case-4 'different genus' flag."""
    proposal = {
        "cluster_label": "temperature element",
        "step2_genus": {"genus_name": "detecting element"},  # stale LLM value
        "classification_basis": "constructive",
        "step5_signature": {
            "transformation_kind": "measurement_transduction",
            "transformation_kind_status": "controlled",
        },
        "disjoint_with": ["pressure element"],
        "disjointness_rationale": "C1: distinct sensing-element bodies (seal, body)",
    }
    ontology_state = {
        "temperature element": _entry("Instrument"),
        "pressure element": _entry("Instrument"),
    }
    res = validate_disjointness(proposal, ontology_state)
    offending = [r for _, r in res["rationale_invalid"]
                 if "different genus" in r or "Case 4" in r]
    assert not offending, f"stale step2_genus caused a false Case-4 mismatch: {offending}"


def test_genus_comparison_is_format_insensitive():
    """A new cluster (absent from ontology_state) falls back to its lowercase
    step2_genus; the candidate's curated genus is PascalCase. The same concept
    must compare equal ('pressure element' == 'PressureElement')."""
    proposal = {
        "cluster_label": "novel element xyz",  # not a real DB cluster -> fallback
        "step2_genus": {"genus_name": "pressure element"},
        "classification_basis": "constructive",
        "step5_signature": {
            "transformation_kind": "k", "transformation_kind_status": "controlled",
        },
        "disjoint_with": ["sibling element"],
        "disjointness_rationale": "C1: distinct bodies (body)",
    }
    ontology_state = {"sibling element": _entry("PressureElement", kind="k")}
    res = validate_disjointness(proposal, ontology_state)
    offending = [r for _, r in res["rationale_invalid"] if "different genus" in r]
    assert not offending, f"PascalCase vs lowercase caused a false mismatch: {offending}"


def test_disjoint_with_resolves_pascalcase_candidate():
    """disjoint_with often holds PascalCase class refs ('HeatExchanger') while
    cluster_labels are lowercase-spaced ('heat exchanger'). The candidate must
    still resolve, not be reported as 'not found in DB'."""
    proposal = {
        "cluster_label": "cooler xyz",  # not in ontology_state -> genus fallback
        "step2_genus": {"genus_name": "HeatExchanger"},
        "classification_basis": "constructive",
        "step5_signature": {"transformation_kind": "k", "transformation_kind_status": "controlled"},
        "disjoint_with": ["HeatExchanger"],  # PascalCase ref to 'heat exchanger'
        "disjointness_rationale": "C4: different bodies and kinds",
    }
    ontology_state = {"heat exchanger": _entry("PressureVessel", kind="k2")}
    res = validate_disjointness(proposal, ontology_state)
    assert not any("not found in DB" in r for _, r in res["rationale_invalid"]), res


def test_genuinely_different_genus_still_distinguished():
    """Guard against over-normalising: truly different genera must still be
    treated as different (not collapsed together)."""
    proposal = {
        "cluster_label": "novel widget xyz",
        "step2_genus": {"genus_name": "Valve"},
        "classification_basis": "constructive",
        "step5_signature": {
            "transformation_kind": "k1", "transformation_kind_status": "controlled",
        },
        "disjoint_with": ["some vessel"],
        "disjointness_rationale": "C4: different genus and incompatible kinds",
    }
    ontology_state = {"some vessel": _entry("Vessel", kind="k2")}
    res = validate_disjointness(proposal, ontology_state)
    # Valve vs Vessel are different -> Case 4 path -> with distinct controlled
    # kinds this is a *preserved* C4 disjointness, never same-genus.
    assert any(case == "C4" for _, case, _ in res["preserved"]), res
