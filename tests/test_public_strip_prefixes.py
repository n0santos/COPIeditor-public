def test_public_strip_prefixes_covers_all_sources():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'enrichment'))
    from enrichment_service import PUBLIC_STRIP_PREFIXES, _SRC_DISPLAY
    # Every display name must produce a prefix in the set
    for src_key, display_name in _SRC_DISPLAY.items():
        prefix = f"[{display_name}]"
        assert prefix in PUBLIC_STRIP_PREFIXES, (
            f"Missing prefix for {src_key}: expected '{prefix}' in PUBLIC_STRIP_PREFIXES"
        )


def test_public_strip_prefixes_includes_isa_and_ppdm():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'enrichment'))
    from enrichment_service import PUBLIC_STRIP_PREFIXES
    assert "[ISA 5.1]" in PUBLIC_STRIP_PREFIXES
    assert "[PPDM]" in PUBLIC_STRIP_PREFIXES


def test_class_page_public_export_hides_source_defs():
    """public_export=True must produce HTML with no source-tagged definition text."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'enrichment'))
    from enrichment_service import _class_page

    fake_entry = {
        "cluster_label": "test valve",
        "copi_id": None,
        "status": "validated",
        "axiom_mode": "necessary",
        "genus": "MaterialArtifact",
        "genus_bfo_root": "MaterialArtifact",
        "function_name": "TestFunction",
        "function_parent": "DesignedFunction",
        "process_name": "TestProcess",
        "process_parent": "PlannedProcess",
        "nl_definition_en": "A test valve.",
        "nl_definition_pt": None,
        "symbol_path": None,
        "differentia_expression": None,
        "differentia_nl": None,
        "semiformal_axiom": None,
        "fol_axiom": None,
        "necessary_parts": None,
        "process_signature": None,
        "disjoint_with": None,
        "function_rationale": None,
        "genus_rationale": None,
        "differentia_rationale": None,
        "parts_rationale": None,
        "signature_rationale": None,
        "disjointness_rationale": None,
        "primitive_rationale": None,
        "expert_review": None,
        "expert_reviewer": None,
        "updated_at": "2026-01-01",
        "created_at": "2026-01-01",
        "llm_model": "claude-sonnet-4-6",
        "excluded_definition_ids": [],
    }
    turtle_src = """
:BallValve a owl:Class ;
    skos:definition "[ISO 15926-4] A valve using a spherical closure element."@en ;
    skos:definition "[CFIHOS] A rotary valve that has a ball closure member."@en ;
    skos:definition "A ball valve is a valve that controls fluid flow."@en .
"""
    html = _class_page(fake_entry, turtle_src, "2026-01-01", public_export=True)
    for tag in ("[ISO 15926-4]", "[CFIHOS]", "[POSC Caesar]", "[SLB Glossary]",
                "[OnePetro]", "[DEXPI]", "[ISA 5.1]", "[PPDM]", "[ISO 14224]"):
        assert tag not in html, f"Public export HTML must not contain {tag}"
