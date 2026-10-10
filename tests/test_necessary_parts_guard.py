# tests/test_necessary_parts_guard.py
import sys, os, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "enrichment"))

import pytest


def _vq(parts, source_defs_json=None):
    import importlib
    import enrichment.enrichment_service as svc
    importlib.reload(svc)
    return svc.validate_necessary_parts_quotes(parts, source_defs_json)


def test_null_name_part_is_skipped():
    """Parts with name=null must be skipped regardless of source_quote."""
    parts = [{"name": None, "source_quote": None, "rationale": "optional concept"}]
    assert _vq(parts, '["The valve body houses the plug."]') is None


def test_missing_source_quote_returns_error():
    """A named part with no source_quote must fail validation."""
    parts = [{"name": "ValveBody", "source_quote": None}]
    err = _vq(parts, '["The valve body houses the plug."]')
    assert err is not None
    assert "ValveBody" in err
    assert "source_quote" in err.lower()


def test_empty_string_source_quote_returns_error():
    """An empty string source_quote must also fail (treated same as absent)."""
    parts = [{"name": "ValveBody", "source_quote": ""}]
    err = _vq(parts, '["The valve body houses the plug."]')
    assert err is not None
    assert "ValveBody" in err


def test_valid_verbatim_quote_passes():
    """A named part whose source_quote appears verbatim in source defs must pass."""
    parts = [{"name": "ValveBody", "source_quote": "The valve body houses the plug."}]
    assert _vq(parts, '["The valve body houses the plug."]') is None


def test_quote_not_in_source_defs_returns_error():
    """A source_quote that is not found in source_definitions_used must fail."""
    parts = [{"name": "Impeller", "source_quote": "The impeller spins the fluid."}]
    err = _vq(parts, '["A centrifugal pump moves fluid via rotation."]')
    assert err is not None
    assert "Impeller" in err


def test_no_source_defs_with_named_part_returns_error():
    """If source_definitions_used is null/empty and a named part exists, must fail."""
    parts = [{"name": "ValveBody", "source_quote": "The valve body houses the plug."}]
    err = _vq(parts, None)
    assert err is not None
    assert "ValveBody" in err


def test_empty_parts_list_passes():
    """An empty parts list requires no validation."""
    assert _vq([], '["Some text."]') is None


def test_case_insensitive_match():
    """Match must be case-insensitive."""
    parts = [{"name": "ValveBody", "source_quote": "THE VALVE BODY HOUSES THE PLUG."}]
    assert _vq(parts, '["The valve body houses the plug."]') is None


def test_whitespace_normalized_match():
    """Extra whitespace in the quote must not prevent a match."""
    parts = [{"name": "ValveBody", "source_quote": "The  valve   body houses the plug."}]
    assert _vq(parts, '["The valve body houses the plug."]') is None


# ── OWL generation guard tests ─────────────────────────────────────────────


def _make_enrichment_db(tmp_path):
    """
    Create a minimal enrichment DB with all tables generate_turtle() touches.
    Returns (db_path, terms_path, enrichment_id) for a row with two parts:
      - ValveBody: has source_quote → must appear in TTL
      - FictionalSeal: no source_quote → must NOT appear in TTL
    """
    import sqlite3, json, importlib
    import enrichment.enrichment_service as svc
    importlib.reload(svc)

    db_path = tmp_path / "enrich.db"
    terms_path = tmp_path / "terms.db"

    # terms.db is left empty — get_cluster_definitions will return []
    sqlite3.connect(str(terms_path)).close()

    # Bootstrap enrichment schema then add additional_parents (not in init_enrichment_schema)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    # Delegate to init to create enrichment table, auxiliary_class, etc.
    # We can't call svc.init_enrichment_schema() here because svc.ENRICHMENT_DB_PATH
    # hasn't been patched yet — build the tables manually instead.
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS enrichment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cluster_label TEXT,
            label_pt TEXT,
            function_name TEXT,
            process_name TEXT,
            genus TEXT,
            genus_bfo_root TEXT,
            differentia_expression TEXT,
            differentia_nl TEXT,
            axiom_mode TEXT DEFAULT 'necessary',
            necessary_parts TEXT,
            disjoint_with TEXT,
            process_signature TEXT,
            qualities TEXT,
            custom_axioms TEXT,
            alt_labels TEXT,
            nl_definition_en TEXT,
            nl_definition_pt TEXT,
            semiformal_axiom TEXT,
            fol_axiom TEXT,
            primitive_rationale TEXT,
            function_parent TEXT,
            process_parent TEXT,
            llm_raw_response TEXT,
            source_definitions_used TEXT,
            second_reviewer_notes TEXT,
            status TEXT DEFAULT 'proposed'
        );
        CREATE TABLE IF NOT EXISTS auxiliary_class (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            bfo_category TEXT,
            label_en TEXT,
            label_pt TEXT,
            definition_en TEXT,
            source TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS additional_parents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cluster_label TEXT,
            parent_iri TEXT
        );
    """)

    parts = [
        {"name": "ValveBody", "parent": "MaterialArtifact",
         "relation": "hasComponentPartAtAllTimes",
         "source_quote": "The valve body is the main pressure-containing element."},
        {"name": "FictionalSeal", "parent": "MaterialArtifact",
         "relation": "hasComponentPartAtAllTimes",
         "source_quote": None},  # no quote — must be skipped
    ]
    conn.execute(
        "INSERT INTO enrichment (cluster_label, function_name, process_name, "
        "genus, genus_bfo_root, axiom_mode, necessary_parts) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("test valve guard", "TestValveGuardFunction", "TestValveGuardProcess",
         "MaterialArtifact", "MaterialArtifact", "necessary", json.dumps(parts))
    )
    conn.commit()
    eid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return db_path, terms_path, eid


def test_owl_guard_skips_part_without_source_quote(tmp_path, monkeypatch):
    """Parts with no source_quote must be absent from the generated TTL."""
    import importlib
    import enrichment.enrichment_service as svc

    db_path, terms_path, eid = _make_enrichment_db(tmp_path)

    importlib.reload(svc)
    monkeypatch.setattr(svc, "ENRICHMENT_DB_PATH", db_path)
    monkeypatch.setattr(svc, "TERMS_DB_PATH", terms_path)

    ttl = svc.generate_turtle(eid)

    assert "ValveBody" in ttl, "Part with source_quote must appear in TTL"
    assert "FictionalSeal" not in ttl, "Part without source_quote must be absent from TTL"


def test_owl_guard_includes_restriction_only_for_grounded_parts(tmp_path, monkeypatch):
    """The hasComponentPartAtAllTimes restriction must only appear for grounded parts."""
    import importlib
    import enrichment.enrichment_service as svc

    db_path, terms_path, eid = _make_enrichment_db(tmp_path)

    importlib.reload(svc)
    monkeypatch.setattr(svc, "ENRICHMENT_DB_PATH", db_path)
    monkeypatch.setattr(svc, "TERMS_DB_PATH", terms_path)

    ttl = svc.generate_turtle(eid)

    # The restriction on the equipment class must reference ValveBody (has quote)
    assert "someValuesFrom :ValveBody" in ttl
    # The restriction must NOT reference FictionalSeal (no quote)
    assert "someValuesFrom :FictionalSeal" not in ttl


# ── Prompt tests ───────────────────────────────────────────────────────────


def test_step4_prompt_uses_source_quote_not_source_label():
    """The Step 4 prompt must require source_quote, not source_label."""
    from pathlib import Path
    prompt_text = (
        Path(__file__).parent.parent / "enrichment" / "prompts.py"
    ).read_text()

    # source_label must be gone from the Step 4 section
    # (find the Step 4 block and check it doesn't contain source_label)
    step4_start = prompt_text.find("### Step 4:")
    step5_start = prompt_text.find("### Step 5:", step4_start)
    step4_text = prompt_text[step4_start:step5_start]

    assert "source_quote" in step4_text, "Step 4 must reference source_quote"
    assert "source_label" not in step4_text, "Step 4 must not reference source_label"
    assert "verbatim" in step4_text, "Step 4 must use the word 'verbatim'"
