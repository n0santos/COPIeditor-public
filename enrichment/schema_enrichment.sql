-- ============================================================================
-- Schema extension for RDL Enrichment Workflow
-- Stored in data/enrichment.db (separate from data/terms.db so re-ingestion never destroys enrichments)
-- ============================================================================

-- Stores one enrichment proposal per cluster (equipment concept).
-- Each row = one run of the 4-step method (LLM or manual).
CREATE TABLE IF NOT EXISTS enrichment (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cluster_label   TEXT NOT NULL,                   -- e.g. "pump", "separator"
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),

    -- Step 1: Identity-giving function
    function_name           TEXT,       -- e.g. "PumpingFunction"
    function_parent          TEXT DEFAULT 'DesignedFunction',
    process_name            TEXT,       -- e.g. "PumpingProcess"
    process_parent          TEXT DEFAULT 'PlannedProcess',
    function_rationale      TEXT,       -- LLM explanation for choice

    -- Step 2: Genus (genus proximum — may be any class name, e.g. "Valve", "Pump")
    genus                   TEXT,   -- the nearest superclass (e.g. "Valve", "Assembly")
    genus_bfo_root          TEXT CHECK(genus_bfo_root IN ('Assembly', 'MaterialArtifact', 'EngineeredSystem', 'Site', 'Object', 'ObjectAggregate', 'FiatObjectPart')),
    genus_rationale         TEXT,

    -- Step 3: Differentia specifica (Aristotelian differentia over the genus)
    -- What distinguishes THIS species from sibling species under the same genus.
    -- Only conditions NOT already entailed by the genus belong here.
    differentia_expression  TEXT,   -- formal: e.g. "∃hasPart.Actuator ⊓ ∃bearerOf.FlowControlFunction"
    differentia_nl          TEXT,   -- natural language statement of the differentia
    differentia_rationale   TEXT,   -- why these conditions are the correct differentia
    genus_already_provides  TEXT DEFAULT '[]',  -- JSON: conditions inherited from genus (for UI context)
    distinguishes_from      TEXT DEFAULT '{}',  -- JSON: {SiblingClass: "how it differs"}

    -- Step 4: Necessary parts (stored as JSON array)
    -- Each element: {"name": "PumpCasing", "parent": "MaterialArtifact",
    --                "relation": "hasComponentPartAtAllTimes", "source_quote": "..."}
    necessary_parts         TEXT DEFAULT '[]',
    parts_rationale         TEXT,
    -- Layered-source provenance (see CLAUDE.md "Interactive enrichment pipeline"):
    -- tertiary/patent findings that triangulated (>=2 independent sources) but did not
    -- pass the genus-wide-applicability check, so they never reach necessary_parts or
    -- OWL generation. Surfaced in the UI for a human reviewer to promote. Same element
    -- shape as necessary_parts.
    candidate_parts          TEXT DEFAULT '[]',

    -- Step 5: Process participation signature
    -- Stored as JSON: {"inputs": [...], "outputs": [...], "transformation": "..."}
    process_signature       TEXT DEFAULT '{}',
    signature_rationale     TEXT,

    -- Axiom type decision (the key ontological choice)
    axiom_mode      TEXT DEFAULT 'necessary'
                    CHECK(axiom_mode IN ('necessary', 'equivalent', 'mixed')),
    primitive_rationale     TEXT,       -- Why this universal is primitive (if necessary-only)

    -- Disjointness (JSON array of class names this is disjoint with)
    disjoint_with           TEXT DEFAULT '[]',
    disjointness_rationale  TEXT,

    -- ISA 5.1 P&ID symbol path (relative to data/raw/isa5_1/symbols/)
    symbol_path             TEXT,

    -- Cross-standard links (JSON array)
    -- Each: {"standard": "ISO15926-4", "class": "PUMP", "match": "exact"}
    cross_standard_links    TEXT DEFAULT '[]',

    -- Validation state
    status          TEXT DEFAULT 'proposed'
                    CHECK(status IN ('proposed', 'reviewed', 'validated', 'exported')),
    reviewer_notes  TEXT,

    -- Provenance: how this proposal was generated. Set on every write (see
    -- scripts/migrations/add_generation_path.py for the backfill of pre-existing
    -- rows). api_call_llm = the real Anthropic API call_llm() path (enrich_cluster()
    -- and the batch-import path both default here); skill_session = the
    -- .claude/skills/enrich-term/ skill, no API call; migration_script =
    -- checked-in scripts/migrations/*.py with hardcoded ENTRIES; manual =
    -- hand-written INSERT with no script artifact (e.g. a chat-session pilot batch).
    generation_path TEXT
                    CHECK(generation_path IN ('api_call_llm', 'skill_session',
                                               'migration_script', 'manual')),

    -- Natural language definitions (generated)
    nl_definition_en        TEXT,       -- NLD for the EQUIPMENT class
    nl_definition_pt        TEXT,
    function_nl_definition_en TEXT,     -- NLD for the FUNCTION class (IOF iof-av:naturalLanguageDefinition)
    function_nl_definition_pt TEXT,
    semiformal_axiom        TEXT,       -- Aristotelian definition
    fol_axiom               TEXT,       -- First-order logic

    -- Source tracking
    -- JSON array of layered-source provenance entries (see CLAUDE.md). Each element:
    --   {"tier": "primary"|"secondary"|"tertiary",
    --    "source_type": "standard"|"curated_dictionary"|"encyclopedia"|
    --                    "manufacturer_page"|"patent"|"web_glossary",
    --    "citation_mode": "verbatim"|"summary",
    --    "source": "iso15926" | "ISO 7241" | "John Zink" | "US4526689A" | ...,
    --    "term": "..."   (only when resolvable in terms.db),
    --    "url": "..."    (only for entries not in terms.db),
    --    "access": "raw_fetch"|"recovered_after_403"|"failed",
    --    "categories_covered": ["structure","profile","mechanism","function",
    --                           "application","subtype","parameter"],
    --    "quote": "..."}
    -- validate_tertiary_triangulation() requires >=2 independent tier='tertiary'
    -- entries (independence key: patent number for source_type='patent', else the
    -- URL's registrable domain) before any of them may back an axiom.
    source_definitions_used TEXT DEFAULT '[]',
    -- Pipeline-health signal, set at the end of Step 2b (CLAUDE.md) once secondary search is
    -- done. NOT tied to any reference/held-out definition -- see the methodological note in
    -- CLAUDE.md after Step 2c: recall-against-a-single-reference measures angle-overlap between
    -- two arbitrary choices, not enrichment quality. This field is the production-safe substitute.
    secondary_coverage      TEXT CHECK(secondary_coverage IN ('none', 'partial', 'full')),
    -- Set when secondary/tertiary evidence CONTRADICTS the ISO 15926-4 primary definition
    -- (not just supplements it) -- e.g. the primary's own genus/scope appears wrong given a
    -- real correlative standard. Found twice in held-out testing (a scope mismatch and an
    -- over-narrow definition) with no dedicated place to record it; see CLAUDE.md Step 2b/2c.
    -- NULL means no conflict found. Free text, not an enum -- the discrepancy needs describing.
    primary_definition_conflict TEXT,
    llm_model               TEXT,               -- e.g. "claude-sonnet-4-20250514"
    llm_raw_response        TEXT,               -- Full JSON response for audit

    -- Token usage & cost
    input_tokens            INTEGER DEFAULT 0,
    output_tokens           INTEGER DEFAULT 0,
    estimated_cost_usd      REAL DEFAULT 0.0,   -- approximate, based on public pricing

    -- Expert / domain specialist review
    -- JSON object: {"step1": {"status": "pending|accepted|disputed|revised", "note": "..."},
    --                "step2": {...}, "step3": {...}, "step4": {...}, "axiom_mode": {...}}
    expert_review           TEXT DEFAULT '{}',
    expert_reviewer         TEXT,               -- name of the domain expert

    -- ODK/GitHub IRI assignment (auto-assigned at first export)
    -- Stores the numeric suffix: 7 → COPPP_0000007
    coppp_id                INTEGER UNIQUE,

    UNIQUE(cluster_label, created_at)
);

-- Index for quick lookup by cluster
CREATE INDEX IF NOT EXISTS idx_enrichment_cluster ON enrichment(cluster_label);
CREATE INDEX IF NOT EXISTS idx_enrichment_status ON enrichment(status);

-- ============================================================================
-- Object / Datatype properties defined in COPPP
-- ============================================================================
CREATE TABLE IF NOT EXISTS coppp_relation (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,      -- e.g. "hasFluid"
    label_en        TEXT,                      -- "has fluid"
    label_pt        TEXT,                      -- "tem fluido"
    prop_type       TEXT DEFAULT 'ObjectProperty'
                    CHECK(prop_type IN ('ObjectProperty','DatatypeProperty')),
    domain          TEXT,                      -- class name, e.g. "Pump" (NULL = universal)
    range_type      TEXT,                      -- range class or XSD datatype
    parent_prop     TEXT,                      -- rdfs:subPropertyOf (local name or full IRI)
    is_functional   INTEGER DEFAULT 0,
    is_symmetric    INTEGER DEFAULT 0,
    is_transitive   INTEGER DEFAULT 0,
    inverse_of      TEXT,                      -- local name of inverse property
    definition_en   TEXT,
    definition_pt   TEXT,
    rationale       TEXT,                      -- why this property is modelled here
    status          TEXT DEFAULT 'proposed'
                    CHECK(status IN ('proposed','validated','exported')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_relation_status ON coppp_relation(status);

-- ============================================================================
-- Cross-Standard Divergence Log
-- ============================================================================
CREATE TABLE IF NOT EXISTS divergence_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    enrichment_id   INTEGER NOT NULL,
    cluster_label   TEXT NOT NULL,
    divergence_type TEXT NOT NULL CHECK(divergence_type IN ('T1','T2','T3','T4','T5')),
    divergence_label TEXT NOT NULL,
    detected_at_step INTEGER,
    source_a        TEXT,
    source_b        TEXT,
    description     TEXT NOT NULL,
    evidence        TEXT,
    resolution      TEXT,
    detected_by     TEXT DEFAULT 'auto' CHECK(detected_by IN ('auto','llm','manual')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (enrichment_id) REFERENCES enrichment(id)
);
CREATE INDEX IF NOT EXISTS idx_divergence_enrichment ON divergence_log(enrichment_id);
CREATE INDEX IF NOT EXISTS idx_divergence_type ON divergence_log(divergence_type);

-- ============================================================================
-- Evaluation Metrics (paper data collection — auto-recorded, no UI)
-- ============================================================================

-- Every ontologist action recorded as a timestamped event
CREATE TABLE IF NOT EXISTS eval_interaction_event (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    enrichment_id   INTEGER NOT NULL,
    event_type      TEXT NOT NULL CHECK(event_type IN (
                        'open','save','step_review','rerun_request','rerun_complete',
                        'axiom_mode_change','export_mark','restore_version',
                        'cq_link','turtle_preview','fol_preview')),
    event_detail    TEXT,   -- optional JSON payload
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    FOREIGN KEY (enrichment_id) REFERENCES enrichment(id)
);
CREATE INDEX IF NOT EXISTS idx_eval_event_enrichment_time ON eval_interaction_event(enrichment_id, created_at);
CREATE INDEX IF NOT EXISTS idx_eval_event_type ON eval_interaction_event(event_type);

-- Turtle + step data captured at two moments: right after LLM and at export
CREATE TABLE IF NOT EXISTS eval_axiom_snapshot (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    enrichment_id   INTEGER NOT NULL,
    snapshot_type   TEXT NOT NULL CHECK(snapshot_type IN ('llm_initial','final_export')),
    turtle_content  TEXT,
    step_data_json  TEXT,   -- JSON of key fields from all 5 steps
    axiom_mode      TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    FOREIGN KEY (enrichment_id) REFERENCES enrichment(id)
);
CREATE INDEX IF NOT EXISTS idx_eval_snapshot_enrichment ON eval_axiom_snapshot(enrichment_id, snapshot_type);

-- Verification state captured at export (one row per class, upserted)
CREATE TABLE IF NOT EXISTS eval_verification_snapshot (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    enrichment_id           INTEGER NOT NULL UNIQUE,
    hermit_consistent       INTEGER,        -- 1=consistent, 0=inconsistent, NULL=not run
    hermit_inferred         TEXT,           -- JSON array of inferred axioms
    hermit_error            TEXT,
    oops_critical_count     INTEGER DEFAULT 0,
    oops_important_count    INTEGER DEFAULT 0,
    oops_minor_count        INTEGER DEFAULT 0,
    oops_pitfalls_json      TEXT,
    has_nl_definition       INTEGER DEFAULT 0,  -- iof-av:naturalLanguageDefinition present
    has_semiformal_def      INTEGER DEFAULT 0,
    has_fol_axiom           INTEGER DEFAULT 0,
    has_primitive_rationale INTEGER DEFAULT 0,
    has_label_en            INTEGER DEFAULT 0,
    has_label_pt            INTEGER DEFAULT 0,
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    FOREIGN KEY (enrichment_id) REFERENCES enrichment(id)
);
