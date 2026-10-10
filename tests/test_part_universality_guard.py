# tests/test_part_universality_guard.py
"""
Unit tests for validate_part_universality(): a necessary_part whose own
source_quote hedges the claim ("typically", "usually", "in most designs", ...)
belongs in candidate_parts, not necessary_parts, until a reviewer vets it as
genus-wide. This is the cheap, mechanical half of the genus-wide-applicability
check (see CLAUDE.md Step 2c) -- it catches the failure mode found in the
held-out experiments where a hedge noticed while reasoning about the axiom
never got propagated back to where the part was filed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "enrichment"))


def _vu(parts):
    import importlib
    import enrichment.enrichment_service as svc
    importlib.reload(svc)
    return svc.validate_part_universality(parts)


def test_empty_parts_list_passes():
    assert _vu([]) is None


def test_null_name_part_is_skipped():
    """Parts with name=null must be skipped regardless of hedge language."""
    parts = [{"name": None, "source_quote": "typically found in this design"}]
    assert _vu(parts) is None


def test_no_hedge_passes():
    parts = [{"name": "ValveBody", "source_quote": "The valve body houses the plug."}]
    assert _vu(parts) is None


def test_typically_hedge_blocks():
    parts = [{"name": "AdjustingRing",
              "source_quote": "An adjusting ring is typically fitted to calibrate set pressure."}]
    err = _vu(parts)
    assert err is not None
    assert "AdjustingRing" in err
    assert "candidate_parts" in err


def test_usually_hedge_blocks():
    """
    'usually include a conservator tank' hedges whether the part is PRESENT at
    all (an existence hedge), unlike 'usually dome-shaped' which hedges an
    attribute of a part already stated to exist -- see
    test_shape_attribute_hedge_does_not_block.
    """
    parts = [{"name": "ConservatorTank",
              "source_quote": "Units above 500 kVA usually include a conservator tank."}]
    err = _vu(parts)
    assert err is not None
    assert "ConservatorTank" in err


def test_in_most_designs_hedge_blocks():
    parts = [{"name": "WeldNib",
              "source_quote": "In most designs a weld nib prevents warping under welding current."}]
    err = _vu(parts)
    assert err is not None


def test_case_insensitive_hedge_match():
    parts = [{"name": "Cage",
              "source_quote": "The bag is TYPICALLY mounted on a wire cage."}]
    err = _vu(parts)
    assert err is not None


def test_missing_source_quote_does_not_trigger_hedge_check():
    """No source_quote at all is validate_necessary_parts_quotes's job, not this one's."""
    parts = [{"name": "ValveBody", "source_quote": None}]
    assert _vu(parts) is None


def test_multiple_parts_first_hedge_reported():
    parts = [
        {"name": "ValveBody", "source_quote": "The valve body houses the plug."},
        {"name": "AdjustingRing", "source_quote": "Typically used to calibrate set pressure."},
    ]
    err = _vu(parts)
    assert err is not None
    assert "AdjustingRing" in err


def test_shape_attribute_hedge_does_not_block():
    """
    'typically dome-shaped' hedges the Bonnet's SHAPE, not whether every
    instance of the genus has a Bonnet at all -- the part's existence is
    stated plainly ('The Bonnet is'). Blocking here would trade genuine
    differential loss for a false positive, exactly the risk flagged after
    the retroactive trigger-rate check found only 1/78 hits on real data.
    """
    parts = [{"name": "Bonnet",
              "source_quote": "The Bonnet is typically dome- or dish-shaped for strength."}]
    assert _vu(parts) is None


def test_material_attribute_hedge_does_not_block():
    parts = [{"name": "WeldNut",
              "source_quote": "Weld nuts are usually made of low carbon steel or stainless steel."}]
    assert _vu(parts) is None


def test_size_attribute_hedge_does_not_block():
    parts = [{"name": "ConcreteStave",
              "source_quote": "Staves are commonly sized around 10 in wide by 30 in tall."}]
    assert _vu(parts) is None


def test_existence_hedge_still_blocks_even_near_attribute_words():
    """
    The exemption must not swallow real existence hedges just because an
    attribute word appears somewhere later in the same quote.
    """
    parts = [{"name": "BraidedConductor",
              "source_quote": "Usually consisting of braided cables, wirelines are used to "
                               "perform wireline logging."}]
    err = _vu(parts)
    assert err is not None
    assert "BraidedConductor" in err
