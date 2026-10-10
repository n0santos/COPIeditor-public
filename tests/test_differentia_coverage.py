# tests/test_differentia_coverage.py
"""
Unit tests for the differentia coverage gate and the qualities-shape normalizer.

Two distinct defects motivated these:

1. `qualities` is written in two shapes -- the documented dict form
   ({"name": ...}) and a bare string form (["ElectricalCurrent"]). Every record
   in enrichment.db uses the string form, while generate_turtle() called
   q.get("name"), raising AttributeError. The combined generator swallowed the
   exception and published those classes as label-only stubs with no function
   restriction at all (COPI_0000724 'electrical switch' and COPI_0000731
   'stator winding' shipped that way: 5 triples, 0 restrictions). The
   normalizer must accept both shapes and must never raise on malformed input,
   because a bad quality entry costing a class its *other* axioms is exactly
   how that bug stayed invisible.

2. differentia_expression is free text that routinely names classes the
   structured fields never carry into OWL. extract_differentia_conjuncts() is
   the parser behind the ratchet gate in scripts/check_differentia_coverage.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "enrichment"))


def _svc():
    import enrichment.enrichment_service as svc
    return svc


# ── _normalize_qualities ─────────────────────────────────────────────────────

def test_normalize_qualities_accepts_bare_string_form():
    """The shape every record in the DB actually uses."""
    assert _svc()._normalize_qualities('["ElectricalCurrent"]') == [
        {"name": "ElectricalCurrent"}
    ]


def test_normalize_qualities_accepts_documented_dict_form():
    out = _svc()._normalize_qualities('[{"name": "MechanicalLoad", "unit": "N"}]')
    assert out == [{"name": "MechanicalLoad", "unit": "N"}]


def test_normalize_qualities_accepts_already_parsed_list():
    assert _svc()._normalize_qualities(["ElectricalCurrent"]) == [
        {"name": "ElectricalCurrent"}
    ]


def test_normalize_qualities_empty_and_null_inputs():
    n = _svc()._normalize_qualities
    assert n(None) == []
    assert n("") == []
    assert n("[]") == []


def test_normalize_qualities_never_raises_on_malformed_input():
    """A malformed quality must not cost the class its other axioms."""
    n = _svc()._normalize_qualities
    assert n("not json") == []
    assert n('{"name": "NotAList"}') == []
    assert n('[123, "", null, {"no_name": 1}]') == []


def test_normalize_qualities_mixed_shapes_in_one_list():
    out = _svc()._normalize_qualities('["ElectricalCurrent", {"name": "MechanicalForce"}]')
    assert out == [{"name": "ElectricalCurrent"}, {"name": "MechanicalForce"}]


# ── extract_differentia_conjuncts ────────────────────────────────────────────

def test_extract_conjuncts_parses_dl_notation():
    expr = "∃hasComponentPartAtAllTimes.Actuator ⊓ ∃bearerOf.FlowControlFunction"
    assert _svc().extract_differentia_conjuncts(expr) == [
        ("hasComponentPartAtAllTimes", "Actuator"),
        ("bearerOf", "FlowControlFunction"),
    ]


def test_extract_conjuncts_empty_input():
    e = _svc().extract_differentia_conjuncts
    assert e(None) == []
    assert e("") == []
    assert e("prose with no conjuncts at all") == []


def test_extract_conjuncts_deduplicates_preserving_order():
    expr = "∃hasPart.Seat ⊓ ∃hasPart.Stem ⊓ ∃hasPart.Seat"
    assert _svc().extract_differentia_conjuncts(expr) == [
        ("hasPart", "Seat"),
        ("hasPart", "Stem"),
    ]


def test_extract_conjuncts_requires_capitalized_target():
    """Targets are class names; a lowercase word after the dot is not one."""
    assert _svc().extract_differentia_conjuncts("∃hasPart.someValue") == []
