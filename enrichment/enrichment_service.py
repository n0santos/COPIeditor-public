"""
Enrichment service: LLM-assisted 5-step RDL axiomatization.

Orchestrates:
  1. Gathering definitions from the existing terms.db
  2. Building prompts via prompts.py
  3. Calling the Anthropic API
  4. Parsing + storing proposals in the enrichment table
  5. Generating OWL/Turtle output from validated proposals
"""

import json
import logging
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from textwrap import dedent

import httpx

from prompts import build_enrichment_prompt

# COPI constants — defined in config.py at project root
sys.path.insert(0, str(Path(__file__).parent.parent))
try:
    from config import (
        COPI_IRI, COPI_NS, COPI_VERSION,
        COPI_GITHUB, COPI_GROUP, COPI_CNPQ,
        COPI_PROJECT, COPI_PROJECT_FULL, COPI_RESEARCH_GROUP,
        COPI_PUBLISHER, COPI_AUTHOR, COPI_SCOPE_NOTES, COPI_CONTRIBUTORS,
        COPI_DESCRIPTION, COPI_LICENSE,
    )
except ImportError:
    COPI_IRI            = "https://www.inf.ufrgs.br/ontologies/copi"
    COPI_NS             = "https://www.inf.ufrgs.br/ontologies/copi/"
    COPI_VERSION        = "0.1.0-draft"
    COPI_GITHUB         = "https://github.com/INF-UFRGS-Ontologies/copi"
    COPI_GROUP          = "INF-UFRGS-Ontologies"
    COPI_CNPQ           = "INF-UFRGS-ENERGIA"
    COPI_PROJECT        = "OntoKG"
    COPI_PROJECT_FULL   = "OntoKG - Petrobras"
    COPI_RESEARCH_GROUP = "INF-UFRGS-ENERGIA"
    COPI_SCOPE_NOTES    = []
    COPI_CONTRIBUTORS   = []
    COPI_PROJECT        = "OntoKG"
    COPI_PUBLISHER      = "Universidade Federal do Rio Grande do Sul (UFRGS)"
    COPI_AUTHOR         = ""
    COPI_DESCRIPTION    = ("", "")
    COPI_LICENSE        = ("CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Auxiliary-class BFO IRI map and valid categories
# ---------------------------------------------------------------------------

_AUX_BFO_IRI: dict[str, str] = {
    "Object":                   "bfo:BFO_0000030",
    "ObjectAggregate":          "bfo:BFO_0000027",
    "FiatObjectPart":           "bfo:BFO_0000024",
    "MaterialArtifact":         "iof-core:MaterialArtifact",
    "Quality":                  "bfo:BFO_0000019",
    "Role":                     "bfo:BFO_0000023",
    "Disposition":              "bfo:BFO_0000016",
    "InformationContentEntity": "iof-core:InformationContentEntity",
    "MeasurementICE":           "iof-core:MeasurementInformationContentEntity",
    "Process":                  "bfo:BFO_0000015",
}

_AUX_VALID_CATEGORIES: frozenset[str] = frozenset(_AUX_BFO_IRI.keys())

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TERMS_DB_PATH      = Path(__file__).parent.parent / "data" / "terms.db"
ENRICHMENT_DB_PATH = Path(__file__).parent.parent / "data" / "enrichment.db"
_COPI_IRI_MAP_PATH = Path(__file__).parent / "ontologies" / "copi-context" / "copi-iri-map.tsv"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4096

# ---------------------------------------------------------------------------
# Transformation-kind controlled vocabulary
# ---------------------------------------------------------------------------

TRANSFORMATION_KINDS_CONTROLLED: frozenset[str] = frozenset({
    "flow_regulation",
    "flow_isolation",
    "flow_direction_control",
    "pressure_increase",
    "pressure_reduction",
    "mechanical_power_transmission",
    "electrical_power_conversion",
    "thermal_energy_transfer",
    "phase_separation",
    "mass_transfer",
    "mechanical_filtration",
    "chemical_transformation",
    "measurement_transduction",
    "fluid_transport",
    "subsurface_access",
    "containment",
    "mixing",
})

_SNAKE_CASE_RE = re.compile(r'^[a-z][a-z0-9]*(?:_[a-z][a-z0-9]*)*$')


def _validate_transformation_kind(proposal: dict) -> None:
    """
    Validate and repair transformation_kind fields in an LLM proposal.

    Rules (all violations are warnings, not hard errors):
    - If status='controlled' but term not in TRANSFORMATION_KINDS_CONTROLLED,
      demote to status='proposed' and auto-generate a rationale note.
    - If status='proposed' and proposed_kind_rationale is empty, log a warning.
    - If status='proposed', check snake_case convention and length <= 50.
    """
    step5 = proposal.get("step5_signature") or {}
    kind   = step5.get("transformation_kind")
    status = step5.get("transformation_kind_status")

    if not kind:
        return  # field absent — caller may be a backfill; skip silently

    if status == "controlled" and kind not in TRANSFORMATION_KINDS_CONTROLLED:
        logger.warning(
            "transformation_kind '%s' marked controlled but not in vocabulary; "
            "demoting to proposed.", kind,
        )
        step5["transformation_kind_status"] = "proposed"
        step5["proposed_kind_rationale"] = (
            "LLM marked status=controlled but term is not in the canonical vocabulary. "
            "Review and either correct the term or promote this extension."
        )

    if step5.get("transformation_kind_status") == "proposed":
        if not step5.get("proposed_kind_rationale"):
            logger.warning(
                "transformation_kind '%s' is proposed but proposed_kind_rationale is empty.", kind,
            )
        if not _SNAKE_CASE_RE.match(kind or ""):
            logger.warning(
                "Proposed transformation_kind '%s' violates snake_case convention.", kind,
            )
        if len(kind or "") > 50:
            logger.warning(
                "Proposed transformation_kind '%s' exceeds 50-character limit (%d chars).",
                kind, len(kind),
            )


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_terms_db() -> sqlite3.Connection:
    """Read-only connection to the terms/ingestion database."""
    conn = sqlite3.connect(str(TERMS_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def get_enrichment_db(actor: str | None = None) -> sqlite3.Connection:
    """
    Read-write connection to the enrichment database (separate from terms.db).

    actor: best-effort write attribution for write_audit_log (#33) — the route or function
    name making this connection. Always sets _write_actor explicitly (to `actor`, or to NULL
    when omitted) so a connection that doesn't pass one can't inherit a stale value left by a
    previous connection. Silently a no-op if _write_actor doesn't exist yet (pre-migration #33
    databases, or terms.db-style call sites that never write).
    """
    conn = sqlite3.connect(str(ENRICHMENT_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        conn.execute("UPDATE _write_actor SET actor = ? WHERE id = 1", (actor,))
    except sqlite3.OperationalError:
        pass  # _write_actor not present yet — migration #33 not applied
    return conn


def _clear_write_actor(conn: sqlite3.Connection) -> None:
    """
    Reset _write_actor to NULL right after a tagged write commits (#33), so the
    staleness window (a later connection that never sets its own actor inheriting
    this one's) is bounded to "between this commit and the next get_enrichment_db()
    call" rather than persisting indefinitely. Call before conn.commit()/conn.close().
    No-op, silently, if _write_actor doesn't exist yet.
    """
    try:
        conn.execute("UPDATE _write_actor SET actor = NULL WHERE id = 1")
    except sqlite3.OperationalError:
        pass


# Keep legacy alias so enrichment_routes.py can import get_db for terms reads
# without needing a code change there.
def get_db() -> sqlite3.Connection:
    return get_terms_db()


def init_enrichment_schema():
    """Create/migrate the enrichment schema in enrichment.db."""
    schema_sql = Path(__file__).parent / "schema_enrichment.sql"
    if not schema_sql.exists():
        return

    conn = get_enrichment_db()

    # If the table has the old CHECK(genus IN ...) constraint, recreate it
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='enrichment'"
    ).fetchone()
    if row and row[0] and "CHECK(genus IN" in row[0]:
        logger.info("Migrating enrichment table: removing genus CHECK constraint, adding genus_bfo_root.")
        conn.execute("ALTER TABLE enrichment RENAME TO enrichment_v1")
        conn.executescript(schema_sql.read_text())
        # Copy all existing data; genus_bfo_root defaults to NULL (old rows had genus = bfo root)
        conn.execute("""
            INSERT INTO enrichment
            SELECT id, cluster_label, created_at, updated_at,
                   function_name, function_parent, process_name, process_parent, function_rationale,
                   genus, genus AS genus_bfo_root, genus_rationale,
                   necessary_parts, parts_rationale, process_signature, signature_rationale,
                   axiom_mode, primitive_rationale, disjoint_with, disjointness_rationale,
                   cross_standard_links, status, reviewer_notes,
                   nl_definition_en, nl_definition_pt, semiformal_axiom, fol_axiom,
                   source_definitions_used, llm_model, llm_raw_response,
                   input_tokens, output_tokens, estimated_cost_usd,
                   expert_review, expert_reviewer
            FROM enrichment_v1
        """)
        conn.execute("DROP TABLE enrichment_v1")
        conn.commit()
    else:
        conn.executescript(schema_sql.read_text())

    # If table has old 3-value genus_bfo_root CHECK, recreate with expanded 7-value CHECK
    row2 = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='enrichment'"
    ).fetchone()
    old_sql2 = row2[0] if row2 and row2[0] else ""
    old_bfr_check = "CHECK(genus_bfo_root IN ('Assembly', 'MaterialArtifact', 'EngineeredSystem'))"
    if old_bfr_check in old_sql2:
        logger.info("Migrating enrichment table: expanding genus_bfo_root CHECK to 7 values.")
        conn.execute("ALTER TABLE enrichment RENAME TO enrichment_old_bfr")
        conn.executescript(schema_sql.read_text())
        conn.execute("""
            INSERT INTO enrichment (
                id, cluster_label, created_at, updated_at,
                function_name, function_parent, process_name, process_parent, function_rationale,
                genus, genus_bfo_root, genus_rationale,
                necessary_parts, parts_rationale, process_signature, signature_rationale,
                axiom_mode, primitive_rationale, disjoint_with, disjointness_rationale,
                cross_standard_links, status, reviewer_notes,
                nl_definition_en, nl_definition_pt, semiformal_axiom, fol_axiom,
                source_definitions_used, llm_model, llm_raw_response,
                input_tokens, output_tokens, estimated_cost_usd,
                expert_review, expert_reviewer, symbol_path,
                differentia_expression, differentia_nl, differentia_rationale,
                genus_already_provides, distinguishes_from, alt_labels, qualities, custom_axioms,
                copi_id, cache_write_tokens, cache_read_tokens,
                is_role, role_bearer, role_bearer_rationale
            )
            SELECT
                id, cluster_label, created_at, updated_at,
                function_name, function_parent, process_name, process_parent, function_rationale,
                genus, genus_bfo_root, genus_rationale,
                necessary_parts, parts_rationale, process_signature, signature_rationale,
                axiom_mode, primitive_rationale, disjoint_with, disjointness_rationale,
                cross_standard_links, status, reviewer_notes,
                nl_definition_en, nl_definition_pt, semiformal_axiom, fol_axiom,
                source_definitions_used, llm_model, llm_raw_response,
                input_tokens, output_tokens, estimated_cost_usd,
                expert_review, expert_reviewer, symbol_path,
                differentia_expression, differentia_nl, differentia_rationale,
                genus_already_provides, distinguishes_from, alt_labels, qualities, custom_axioms,
                copi_id, cache_write_tokens, cache_read_tokens,
                is_role, role_bearer, role_bearer_rationale
            FROM enrichment_old_bfr
        """)
        conn.execute("DROP TABLE enrichment_old_bfr")
        conn.commit()

    # Create cluster_scope table if it doesn't exist
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cluster_scope (
            cluster_label TEXT PRIMARY KEY,
            out_of_scope  INTEGER NOT NULL DEFAULT 0,
            reason        TEXT DEFAULT '',
            updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)

    # Create copi_relation table if it doesn't exist (added in schema v2)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS copi_relation (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL UNIQUE,
            label_en        TEXT,
            label_pt        TEXT,
            prop_type       TEXT DEFAULT 'ObjectProperty'
                            CHECK(prop_type IN ('ObjectProperty','DatatypeProperty')),
            domain          TEXT,
            range_type      TEXT,
            parent_prop     TEXT,
            is_functional   INTEGER DEFAULT 0,
            is_symmetric    INTEGER DEFAULT 0,
            is_transitive   INTEGER DEFAULT 0,
            inverse_of      TEXT,
            definition_en   TEXT,
            definition_pt   TEXT,
            rationale       TEXT,
            status          TEXT DEFAULT 'proposed'
                            CHECK(status IN ('proposed','validated','exported')),
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_relation_status ON copi_relation(status);
    """)

    # Create enrichment_job table for batch processing queue
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS enrichment_job (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            cluster_label   TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending'
                            CHECK(status IN ('pending','running','done','failed','skipped')),
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            started_at      TEXT,
            completed_at    TEXT,
            enrichment_id   INTEGER,
            error_msg       TEXT,
            batch_id        TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_job_status ON enrichment_job(status);
    """)

    # Create batch_submissions table for Anthropic Message Batches tracking
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS batch_submissions (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            anthropic_batch_id  TEXT NOT NULL UNIQUE,
            model               TEXT,
            status              TEXT NOT NULL DEFAULT 'in_progress',
            job_count           INTEGER DEFAULT 0,
            succeeded           INTEGER DEFAULT 0,
            errored             INTEGER DEFAULT 0,
            expired             INTEGER DEFAULT 0,
            results_imported    INTEGER NOT NULL DEFAULT 0,
            created_at          TEXT NOT NULL DEFAULT (datetime('now')),
            ended_at            TEXT
        );
    """)

    # Create validate_tests table for intended-model test cases
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS validate_tests (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            name                  TEXT NOT NULL,
            description           TEXT,
            individual_class      TEXT NOT NULL,
            extra_classes         TEXT DEFAULT '[]',
            expected_inferred     TEXT DEFAULT '[]',
            expected_not_inferred TEXT DEFAULT '[]',
            expect_inconsistent   INTEGER DEFAULT 0,
            last_result           TEXT,
            result_detail         TEXT,
            last_run_at           TEXT,
            created_at            TEXT DEFAULT (datetime('now'))
        );
    """)

    # Annotations: per-field threaded comments for collaborative review
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS annotations (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            enrichment_id INTEGER NOT NULL,
            field         TEXT,
            author        TEXT NOT NULL DEFAULT 'anonymous',
            body          TEXT NOT NULL,
            resolved      INTEGER NOT NULL DEFAULT 0,
            resolved_by   TEXT,
            created_at    TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_annotations_enrichment ON annotations(enrichment_id);
    """)

    # Q&A usage log
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS qa_log (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            question           TEXT NOT NULL,
            input_tokens       INTEGER DEFAULT 0,
            output_tokens      INTEGER DEFAULT 0,
            estimated_cost_usd REAL DEFAULT 0.0,
            llm_model          TEXT,
            created_at         TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)

    # Create enrichment_history table for version snapshots
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS enrichment_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            enrichment_id   INTEGER NOT NULL,
            snapshot_at     TEXT NOT NULL DEFAULT (datetime('now')),
            trigger         TEXT DEFAULT 'rerun',
            snapshot_json   TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_history_enrichment_id ON enrichment_history(enrichment_id);
    """)

    # Additive migrations: add columns that may not exist in older databases
    existing = {row[1] for row in conn.execute("PRAGMA table_info(enrichment)").fetchall()}
    for col, definition in [
        ("input_tokens",          "INTEGER DEFAULT 0"),
        ("output_tokens",         "INTEGER DEFAULT 0"),
        ("estimated_cost_usd",    "REAL DEFAULT 0.0"),
        ("expert_review",         "TEXT DEFAULT '{}'"),
        ("expert_reviewer",       "TEXT"),
        ("genus_bfo_root",        "TEXT"),
        ("symbol_path",           "TEXT"),
        ("differentia_expression","TEXT"),
        ("differentia_nl",        "TEXT"),
        ("differentia_rationale", "TEXT"),
        ("genus_already_provides","TEXT DEFAULT '[]'"),
        ("distinguishes_from",    "TEXT DEFAULT '{}'"),
        ("alt_labels",            "TEXT DEFAULT '[]'"),
        ("qualities",             "TEXT DEFAULT '[]'"),
        ("custom_axioms",         "TEXT DEFAULT '[]'"),
        ("copi_id",              "INTEGER"),
        ("cache_write_tokens",    "INTEGER DEFAULT 0"),
        ("cache_read_tokens",     "INTEGER DEFAULT 0"),
        ("is_role",                   "INTEGER DEFAULT 0"),
        ("role_bearer",               "TEXT"),
        ("role_bearer_rationale",     "TEXT"),
        ("excluded_definition_ids",       "TEXT DEFAULT '[]'"),
        ("label_pt",                      "TEXT"),
        ("function_nl_definition_en",     "TEXT"),
        ("function_nl_definition_pt",     "TEXT"),
        ("last_edited_by",               "TEXT"),
        ("last_edited_at",               "TEXT"),
        ("second_reviewer",              "TEXT"),
        ("second_reviewer_notes",        "TEXT"),
        # ODR-022 §15: cluster_label of the class this entry was merged into, when two
        # entries turn out to be one universal named differently by two standards. The
        # merged-away class is REMOVED from the ontology, not deprecated: COPI has no
        # external consumers yet, so a redirect stanza would be clutter carrying no
        # benefit. The row stays in the DB as the provenance record of the decision.
        ("deprecated_in_favor_of",       "TEXT"),
        ("deprecation_rationale",        "TEXT"),
        # Layered-source provenance: tertiary/patent findings that passed triangulation
        # but not the genus-wide-applicability check, surfaced for human review instead
        # of feeding necessary_parts (and therefore never reaching OWL generation).
        ("candidate_parts",              "TEXT DEFAULT '[]'"),
        # Pipeline-health signal (none/partial/full) — see CLAUDE.md Step 2b. No CHECK
        # constraint on an additive ALTER TABLE column (SQLite limitation); enforced at the
        # application layer instead, same as every other additive column here.
        ("secondary_coverage",           "TEXT"),
        # Set when evidence contradicts (not just supplements) the ISO 15926-4 primary
        # definition — see CLAUDE.md Step 2b/2c. NULL means no conflict found.
        ("primary_definition_conflict",  "TEXT"),
        # COPI-Core anchoring (core_operations.py): JSON {kind: out_of_scope|core_coverage_gap,
        # nearest_operation, rationale} when process_parent resolves to no COPI-Core operation.
        # NULL when the process is anchored.
        ("core_operation_gap",           "TEXT"),
    ]:
        if col not in existing:
            conn.execute(f"ALTER TABLE enrichment ADD COLUMN {col} {definition}")

    # Additive migration: batch_id on enrichment_job
    job_cols = {row[1] for row in conn.execute("PRAGMA table_info(enrichment_job)").fetchall()}
    if "batch_id" not in job_cols:
        conn.execute("ALTER TABLE enrichment_job ADD COLUMN batch_id TEXT")
    conn.commit()

    # Backfill symbol_path for existing rows that have none
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, cluster_label FROM enrichment WHERE symbol_path IS NULL OR symbol_path = ''"
    ).fetchall()
    backfilled = 0
    for row in rows:
        path = get_symbol_for_cluster(row["cluster_label"])
        if path:
            conn.execute("UPDATE enrichment SET symbol_path = ? WHERE id = ?", (path, row["id"]))
            backfilled += 1
    if backfilled:
        conn.commit()
        logger.info("Backfilled symbol_path for %d enrichment rows.", backfilled)

    # cluster_alias table: maps one cluster label to another as equivalent/related
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cluster_alias (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            source_label    TEXT NOT NULL,
            target_label    TEXT,
            target_enrichment_id INTEGER,
            relation_type   TEXT NOT NULL DEFAULT 'exactMatch'
                            CHECK(relation_type IN ('exactMatch','equivalentClass','broadMatch','narrowMatch')),
            confidence      REAL DEFAULT 1.0,
            detected_by     TEXT DEFAULT 'manual'
                            CHECK(detected_by IN ('manual','label_sim')),
            status          TEXT NOT NULL DEFAULT 'proposed'
                            CHECK(status IN ('proposed','accepted','rejected')),
            notes           TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(source_label, target_label)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_alias_source ON cluster_alias(source_label)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_alias_target ON cluster_alias(target_label)")

    # divergence_log table (added in v2)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS divergence_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            enrichment_id   INTEGER NOT NULL,
            cluster_label   TEXT NOT NULL,
            divergence_type TEXT NOT NULL,
            divergence_label TEXT NOT NULL,
            detected_at_step INTEGER,
            source_a        TEXT,
            source_b        TEXT,
            description     TEXT NOT NULL,
            evidence        TEXT,
            resolution      TEXT,
            detected_by     TEXT DEFAULT 'auto',
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (enrichment_id) REFERENCES enrichment(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_divergence_enrichment ON divergence_log(enrichment_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_divergence_type ON divergence_log(divergence_type)")
    conn.commit()

    # Evaluation metrics tables (silent data collection for paper)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS eval_interaction_event (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            enrichment_id   INTEGER NOT NULL,
            event_type      TEXT NOT NULL CHECK(event_type IN (
                                'open','save','step_review','rerun_request','rerun_complete',
                                'axiom_mode_change','export_mark','restore_version',
                                'cq_link','turtle_preview','fol_preview')),
            event_detail    TEXT,
            created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
            FOREIGN KEY (enrichment_id) REFERENCES enrichment(id)
        );
        CREATE INDEX IF NOT EXISTS idx_eval_event_enrichment_time
            ON eval_interaction_event(enrichment_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_eval_event_type
            ON eval_interaction_event(event_type);

        CREATE TABLE IF NOT EXISTS eval_axiom_snapshot (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            enrichment_id   INTEGER NOT NULL,
            snapshot_type   TEXT NOT NULL CHECK(snapshot_type IN ('llm_initial','final_export')),
            turtle_content  TEXT,
            step_data_json  TEXT,
            axiom_mode      TEXT,
            created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
            FOREIGN KEY (enrichment_id) REFERENCES enrichment(id)
        );
        CREATE INDEX IF NOT EXISTS idx_eval_snapshot_enrichment
            ON eval_axiom_snapshot(enrichment_id, snapshot_type);

        CREATE TABLE IF NOT EXISTS eval_verification_snapshot (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            enrichment_id           INTEGER NOT NULL UNIQUE,
            hermit_consistent       INTEGER,
            hermit_inferred         TEXT,
            hermit_error            TEXT,
            oops_critical_count     INTEGER DEFAULT 0,
            oops_important_count    INTEGER DEFAULT 0,
            oops_minor_count        INTEGER DEFAULT 0,
            oops_pitfalls_json      TEXT,
            has_nl_definition       INTEGER DEFAULT 0,
            has_semiformal_def      INTEGER DEFAULT 0,
            has_fol_axiom           INTEGER DEFAULT 0,
            has_primitive_rationale INTEGER DEFAULT 0,
            has_label_en            INTEGER DEFAULT 0,
            has_label_pt            INTEGER DEFAULT 0,
            created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
            FOREIGN KEY (enrichment_id) REFERENCES enrichment(id)
        );
    """)
    # Migration: add step_focus event type to eval_interaction_event CHECK constraint
    _iev_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='eval_interaction_event'"
    ).fetchone()
    if _iev_row and _iev_row[0] and "'step_focus'" not in _iev_row[0]:
        logger.info("Migrating eval_interaction_event: adding step_focus event type.")
        conn.execute("ALTER TABLE eval_interaction_event RENAME TO eval_interaction_event_old")
        conn.execute("""
            CREATE TABLE eval_interaction_event (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                enrichment_id   INTEGER NOT NULL,
                event_type      TEXT NOT NULL CHECK(event_type IN (
                                    'open','save','step_review','rerun_request','rerun_complete',
                                    'axiom_mode_change','export_mark','restore_version',
                                    'cq_link','turtle_preview','fol_preview','step_focus')),
                event_detail    TEXT,
                created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
                FOREIGN KEY (enrichment_id) REFERENCES enrichment(id)
            )
        """)
        conn.execute(
            "INSERT INTO eval_interaction_event SELECT * FROM eval_interaction_event_old"
        )
        conn.execute("DROP TABLE eval_interaction_event_old")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_eval_event_enrichment_time "
            "ON eval_interaction_event(enrichment_id, created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_eval_event_type "
            "ON eval_interaction_event(event_type)"
        )
        conn.commit()

    # New granular eval tables for Pareto / field-level analysis
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS eval_step_field_snapshot (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            enrichment_id   INTEGER NOT NULL,
            snapshot_id     INTEGER NOT NULL,
            snapshot_type   TEXT NOT NULL,
            step_number     INTEGER NOT NULL CHECK(step_number BETWEEN 1 AND 5),
            field_name      TEXT NOT NULL,
            field_value     TEXT,
            field_value_hash TEXT,
            created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
            FOREIGN KEY (enrichment_id) REFERENCES enrichment(id),
            FOREIGN KEY (snapshot_id)   REFERENCES eval_axiom_snapshot(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_step_field_unique
            ON eval_step_field_snapshot(snapshot_id, step_number, field_name);
        CREATE INDEX IF NOT EXISTS idx_step_field_enrichment
            ON eval_step_field_snapshot(enrichment_id, snapshot_type);

        CREATE TABLE IF NOT EXISTS eval_step_modification_summary (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            enrichment_id         INTEGER NOT NULL,
            step_number           INTEGER NOT NULL CHECK(step_number BETWEEN 1 AND 5),
            modification_type     TEXT NOT NULL CHECK(modification_type IN (
                                      'accepted_as_is','minor_edit','content_changed',
                                      'rejected_empty','rerun_resolved')),
            total_field_count     INTEGER DEFAULT 0,
            changed_field_count   INTEGER DEFAULT 0,
            content_changed_count INTEGER DEFAULT 0,
            created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
            updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
            UNIQUE(enrichment_id, step_number),
            FOREIGN KEY (enrichment_id) REFERENCES enrichment(id)
        );
        CREATE INDEX IF NOT EXISTS idx_step_mod_enrichment
            ON eval_step_modification_summary(enrichment_id);

        CREATE TABLE IF NOT EXISTS eval_genus_usage (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            enrichment_id   INTEGER NOT NULL UNIQUE,
            proposed_genus  TEXT,
            accepted_genus  TEXT,
            proposed_source TEXT CHECK(proposed_source IN ('bfo','iof-core','copi','other')),
            accepted_source TEXT CHECK(accepted_source IN ('bfo','iof-core','copi','other')),
            changed_during_review INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
            FOREIGN KEY (enrichment_id) REFERENCES enrichment(id)
        );
    """)

    # VIEW: aggregates per-class metrics (created separately — executescript commits first)
    conn.execute("""
        CREATE VIEW IF NOT EXISTS eval_metrics_summary AS
        SELECT
            e.id                                                AS enrichment_id,
            e.cluster_label,
            e.status,
            e.axiom_mode,
            e.llm_model,
            e.input_tokens,
            e.output_tokens,
            e.estimated_cost_usd,
            e.created_at,
            e.updated_at,
            COALESCE(ev.open_count,        0)                  AS open_count,
            COALESCE(ev.save_count,        0)                  AS save_count,
            COALESCE(ev.rerun_count,       0)                  AS rerun_count,
            COALESCE(ev.review_count,      0)                  AS review_count,
            COALESCE(ev.export_mark_count, 0)                  AS export_mark_count,
            COALESCE(ev.total_events,      0)                  AS total_events,
            vs.hermit_consistent,
            vs.oops_critical_count,
            vs.oops_important_count,
            vs.oops_minor_count,
            vs.has_nl_definition,
            vs.has_semiformal_def,
            vs.has_fol_axiom,
            vs.has_primitive_rationale,
            vs.has_label_en,
            vs.has_label_pt
        FROM enrichment e
        LEFT JOIN (
            SELECT enrichment_id,
                SUM(CASE WHEN event_type='open'          THEN 1 ELSE 0 END) AS open_count,
                SUM(CASE WHEN event_type='save'          THEN 1 ELSE 0 END) AS save_count,
                SUM(CASE WHEN event_type='rerun_request' THEN 1 ELSE 0 END) AS rerun_count,
                SUM(CASE WHEN event_type='step_review'   THEN 1 ELSE 0 END) AS review_count,
                SUM(CASE WHEN event_type='export_mark'   THEN 1 ELSE 0 END) AS export_mark_count,
                COUNT(*)                                                      AS total_events
            FROM eval_interaction_event
            GROUP BY enrichment_id
        ) ev ON ev.enrichment_id = e.id
        LEFT JOIN eval_verification_snapshot vs ON vs.enrichment_id = e.id
        WHERE e.status IN ('validated', 'exported')
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS auxiliary_class (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT NOT NULL UNIQUE,
            bfo_category  TEXT CHECK(bfo_category IN (
                            'Object',
                            'ObjectAggregate',
                            'FiatObjectPart',
                            'Quality',
                            'Role',
                            'Disposition',
                            'InformationContentEntity',
                            'MeasurementICE',
                            'Process'
                          )),
            label_en      TEXT,
            label_pt      TEXT,
            definition_en TEXT,
            source        TEXT DEFAULT 'auto_signature'
                          CHECK(source IN ('auto_signature','manual')),
            status        TEXT DEFAULT 'pending'
                          CHECK(status IN ('pending','validated')),
            created_at    TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_aux_status ON auxiliary_class(status)")

    # Single source of pt-br labels and natural-language definitions for the
    # non-equipment classes generate_turtle() emits (functions, processes, their
    # parent stubs, part stubs). See _class_annotation_ttl().
    conn.execute("""
        CREATE TABLE IF NOT EXISTS class_annotation (
            class_name      TEXT PRIMARY KEY,
            kind            TEXT CHECK(kind IN ('function','process','part','quality','other')),
            label_pt        TEXT,
            definition_en   TEXT,
            definition_pt   TEXT,
            origin_label_pt TEXT,
            origin_en       TEXT,
            origin_pt       TEXT,
            status          TEXT NOT NULL DEFAULT 'proposed'
                            CHECK(status IN ('proposed','reviewed')),
            notes           TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    conn.commit()

    conn.close()
    logger.info("Enrichment schema initialized in enrichment.db.")


def _terms_table_info(conn: sqlite3.Connection) -> tuple[str | None, str | None, str | None, str | None]:
    """Return (terms_table, name_col, def_col, source_col) or Nones on failure."""
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row["name"] for row in cursor.fetchall()]
    terms_table = next((t for t in ["terms", "term", "entries", "glossary"] if t in tables), None)
    if not terms_table:
        return None, None, None, None
    columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({terms_table})").fetchall()]
    name_col   = _find_col(columns, ["preferred_label", "term", "name", "label", "title", "concept"])
    def_col    = _find_col(columns, ["definition", "def", "description", "text"])
    source_col = _find_col(columns, ["source", "origin", "standard", "provider", "dataset"])
    return terms_table, name_col, def_col, source_col


def _normalize_for_matching(label: str) -> str:
    """Collapse hyphens/underscores to spaces, lowercase, strip, compress whitespace."""
    return re.sub(r"\s+", " ", label.lower().replace("-", " ").replace("_", " ")).strip()


def _label_variants(cluster_label: str) -> list[str]:
    """
    Return a deduplicated list of lowercase label variants to use in SQL IN clauses.
    Covers: exact, plural/singular, and hyphen↔space swaps.
    """
    label_lower = cluster_label.lower().strip()
    candidates = [label_lower]

    # Singular/plural
    if label_lower.endswith("s"):
        candidates.append(label_lower[:-1])
    else:
        candidates.append(label_lower + "s")

    # Hyphen ↔ space variants for each candidate so far
    extra: list[str] = []
    for c in candidates:
        if "-" in c:
            extra.append(c.replace("-", " "))
        if " " in c:
            extra.append(c.replace(" ", "-"))
    candidates.extend(extra)

    # Deduplicate while preserving order
    seen: set[str] = set()
    variants: list[str] = []
    for v in candidates:
        if v not in seen:
            seen.add(v)
            variants.append(v)
    return variants


def get_label_aggregation_info(cluster_label: str) -> dict:
    """
    Return information about how the cluster label is resolved in the DB.

    Result keys:
      - "included_variants": list[dict]  — variant labels (e.g. hyphen form) that
        ARE captured by _label_variants() and exist in the DB with a different
        spelling than the cluster label itself. Lets the UI show "also pulled in from:".
      - "near_matches": list[dict]  — labels that normalize to the same form but
        are NOT in _label_variants() (still uncovered alternative spellings).

    Each dict has: {label, sources: [str], count: int}
    """
    target_norm = _normalize_for_matching(cluster_label)
    cluster_lower = cluster_label.lower().strip()
    covered = set(_label_variants(cluster_label))

    conn = get_terms_db()
    try:
        rows = conn.execute(
            "SELECT preferred_label, source FROM terms"
        ).fetchall()
    except Exception:
        conn.close()
        return {"included_variants": [], "near_matches": []}
    conn.close()

    included: dict[str, dict] = {}
    near: dict[str, dict] = {}

    for row in rows:
        label = row[0] or ""
        source = row[1] or "unknown"
        label_lower = label.lower().strip()

        if label_lower == cluster_lower:
            continue  # skip the canonical form itself

        norm = _normalize_for_matching(label)
        if norm != target_norm:
            continue

        bucket = included if label_lower in covered else near
        if label_lower not in bucket:
            bucket[label_lower] = {"label": label, "sources": set(), "count": 0}
        bucket[label_lower]["sources"].add(source)
        bucket[label_lower]["count"] += 1

    def _to_list(d: dict) -> list[dict]:
        return [
            {"label": v["label"], "sources": sorted(v["sources"]), "count": v["count"]}
            for v in d.values()
        ]

    return {
        "included_variants": _to_list(included),
        "near_matches": _to_list(near),
    }


# Keep the old name as a thin wrapper for backwards compatibility
def get_near_match_labels(cluster_label: str) -> list[dict]:
    return get_label_aggregation_info(cluster_label)["near_matches"]


def get_cluster_definitions(cluster_label: str) -> list[dict]:
    """
    Fetch definitions that directly name this cluster (exact + plural/singular
    variants). Does NOT include subtypes — use get_cluster_subtypes() for those.
    """
    conn = get_terms_db()
    terms_table, name_col, def_col, source_col = _terms_table_info(conn)
    if not terms_table or not name_col:
        conn.close()
        return []

    variants = _label_variants(cluster_label)
    placeholders = ",".join("?" * len(variants))

    rows = conn.execute(
        f"SELECT * FROM {terms_table} WHERE LOWER({name_col}) IN ({placeholders})",
        variants,
    ).fetchall()

    definitions = []
    for row in rows:
        d = dict(row)
        raw_def = d.get(def_col, "") if def_col else ""
        if not raw_def or str(raw_def).strip() in ("", "(no definition)", "None"):
            continue
        src = d.get(source_col, "unknown") if source_col else "unknown"
        _SOURCE_VERSIONS = {
            "iso15926": "2019", "posc_caesar": "", "cfihos": "V2.0",
            "dexpi": "", "slb_glossary": "", "iso14224": "2016",
            "isa5_1": "2022", "onepetro_glossary": "", "ppdm": "R-2.4",
        }
        _SKIP_COLS = {"id", "created_at", "updated_at", source_col, def_col, name_col}
        definitions.append({
            "id": d.get("id"),
            "source": src,
            "source_version": _SOURCE_VERSIONS.get(src, ""),
            "term": d.get(name_col, ""),
            "definition": raw_def,
            "source_uri": d.get("source_uri") or "",
            "term_type": d.get("term_type") or "",
            "properties": {
                k: v for k, v in d.items()
                if k not in _SKIP_COLS and k not in ("source_uri", "term_type") and v is not None
            },
        })

    conn.close()
    return definitions


def validate_necessary_parts_quotes(
    parts: list, source_defs_json: str | None
) -> str | None:
    """
    Enforce that every named part carries a verbatim source_quote grounded in
    source_definitions_used.  Returns an error message string on the first
    violation, or None if all parts are valid.
    """
    import re as _re

    def _norm(s: str) -> str:
        return _re.sub(r"\s+", " ", s.lower().strip())

    source_text = ""
    if source_defs_json:
        try:
            defs = json.loads(source_defs_json)
            if isinstance(defs, list):
                source_text = " ".join(str(d) for d in defs)
            else:
                source_text = str(defs)
        except (json.JSONDecodeError, TypeError):
            source_text = str(source_defs_json)

    norm_source = _norm(source_text)

    for part in parts:
        if not part.get("name"):
            continue
        name = part["name"]
        quote = (part.get("source_quote") or "").strip()
        if not quote:
            return (
                f"Part '{name}' requires a source_quote (a verbatim passage from "
                "source_definitions_used that names this component)."
            )
        if not norm_source:
            return (
                f"Part '{name}' cannot be grounded: no source definitions are stored "
                "for this enrichment entry."
            )
        if _norm(quote) not in norm_source:
            return (
                f"Part '{name}' source_quote not found verbatim in "
                "source_definitions_used."
            )

    return None


_UNIVERSALITY_HEDGES = (
    "typically", "usually", "in most designs", "commonly", "generally",
    "often", "some designs", "in one design", "in this design",
    "one documented", "may be", "can be", "in some",
)

# A hedge word immediately followed by one of these describes an ATTRIBUTE of a
# part whose existence is already stated plainly elsewhere in the quote ("The
# Bonnet is typically dome-shaped") -- not whether every instance of the genus
# has the part at all. Retroactively checking all 78 named necessary_parts
# already in enrichment.db found only 1 hedge hit (1.3%), and it was a genuine
# existence hedge ("Usually consisting of braided cables..."); this exemption
# exists so the check doesn't start rejecting attribute prose once Step 2b/2c
# routinely pulls in real correlative-standard text, which hedges shape/
# material/size far more often than it hedges a part's existence.
_ATTRIBUTE_HEDGE_EXEMPT_WORDS = (
    "shaped", "shape", "diameter", "material", "made of", "constructed of",
    "colour", "color", "size", "sized", "thickness", "weight",
)
_ATTRIBUTE_EXEMPTION_WINDOW = 30  # chars scanned after the hedge word


def validate_part_universality(parts: list) -> str | None:
    """
    Flag a necessary_part whose own source_quote hedges the claim (see
    CLAUDE.md Step 2c, safeguard 3). Hedged content belongs in candidate_parts
    until a reviewer confirms it holds for the whole genus, not just some
    documented instances. Returns an error message on the first hedge found,
    or None if every named part's quote is unhedged (or only hedges an
    incidental attribute -- see _ATTRIBUTE_HEDGE_EXEMPT_WORDS).
    """
    for part in parts:
        if not part.get("name"):
            continue
        quote = (part.get("source_quote") or "").lower()
        if not quote:
            continue
        for hedge in _UNIVERSALITY_HEDGES:
            idx = quote.find(hedge)
            if idx == -1:
                continue
            window_after = quote[idx: idx + len(hedge) + _ATTRIBUTE_EXEMPTION_WINDOW]
            if any(w in window_after for w in _ATTRIBUTE_HEDGE_EXEMPT_WORDS):
                continue
            return (
                f"Part '{part['name']}' source_quote hedges universality "
                f"(contains '{hedge}') -- move to candidate_parts until a "
                "reviewer confirms it applies to the entire genus, not just "
                "some documented instances."
            )

    return None


# A differentia conjunct, as written by Step 3, looks like "hasPart.Actuator" or
# "∃bearerOf.FlowControlFunction ⊓ ∃participatesIn.RotationalMotionProcess".
# We only need the (predicate, Target) pairs; the ∃/⊓ decoration is irrelevant.
_DIFFERENTIA_CONJUNCT_RE = re.compile(
    r"([a-zA-Z_][a-zA-Z0-9_]*)\s*\.\s*([A-Z][A-Za-z0-9_]*)"
)


def _normalize_qualities(qualities_raw) -> list[dict]:
    """
    Accept either documented shape of the `qualities` field and return dicts.

    Documented:  [{"name": "ElectricalCurrent", "definition": ..., "unit": ...}]
    Also in use: ["ElectricalCurrent"]

    Every record currently in enrichment.db uses the bare-string form, so the
    dict-only assumption in generate_turtle() meant those classes raised and
    shipped as label-only stubs. Unknown element types are skipped rather than
    raising -- a malformed quality must not cost the class its other axioms.
    """
    if not qualities_raw:
        return []
    if isinstance(qualities_raw, str):
        try:
            qualities_raw = json.loads(qualities_raw)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(qualities_raw, list):
        return []

    out: list[dict] = []
    for q in qualities_raw:
        if isinstance(q, dict):
            if q.get("name"):
                out.append(q)
        elif isinstance(q, str) and q.strip():
            out.append({"name": q.strip()})
    return out


def _filter_excluded_definitions(definitions: list[dict], excluded) -> list[dict]:
    """
    Drop the terms.db definitions a reviewer excluded from a cluster.

    `excluded_definition_ids` is stored as a JSON string but callers may hold it
    already parsed. Any malformed value keeps every definition: a bad exclusion
    must not silently cost a class its source definitions.
    """
    if isinstance(excluded, str):
        try:
            excluded = json.loads(excluded) if excluded.strip() else []
        except json.JSONDecodeError:
            excluded = []
    if not isinstance(excluded, list) or not excluded:
        return definitions
    return [d for d in definitions if d.get("id") not in excluded]


_CLASS_ANNOTATION_CACHE: dict = {"stamp": None, "rows": {}}


def _lookup_class_annotation(class_name: str) -> dict | None:
    """Row of class_annotation for a readable class name, or None.

    generate_combined_turtle() asks for thousands of classes, so the table is
    read once and re-read only when enrichment.db (or its WAL) changes on disk.
    """
    db_path = Path(ENRICHMENT_DB_PATH)
    stamp = tuple(p.stat().st_mtime_ns if p.exists() else 0
                  for p in (db_path, db_path.with_name(db_path.name + "-wal")))
    if stamp != _CLASS_ANNOTATION_CACHE["stamp"]:
        # Read-only on purpose: get_enrichment_db() issues an audit UPDATE, which
        # blocks on the write transaction generate_turtle() keeps open meanwhile.
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = {r["class_name"]: {"label_pt": r["label_pt"], "definition_en": r["definition_en"],
                                      "definition_pt": r["definition_pt"]}
                    for r in conn.execute("SELECT * FROM class_annotation")}
        except sqlite3.OperationalError:  # table not created yet
            rows = {}
        finally:
            conn.close()
        _CLASS_ANNOTATION_CACHE.update(stamp=stamp, rows=rows)
    return _CLASS_ANNOTATION_CACHE["rows"].get(class_name)


def _class_annotation_ttl(
    class_name: str,
    label_pt: str | None = None,
    definition_en: str | None = None,
    definition_pt: str | None = None,
) -> str:
    """
    Turtle annotation lines (each prefixed ' ;\\n    ') for a non-equipment class.

    class_annotation wins field by field; the arguments are the fallbacks used
    when the registry has no row or leaves that field empty. Because every entry
    that emits a shared class (e.g. FlowControlFunction) resolves to the same
    registry row, the combined ontology carries exactly one value per language.
    Arguments are raw text; escaping happens here.
    """
    reg = _lookup_class_annotation(class_name) or {}
    pt_label = (reg.get("label_pt") or label_pt or "").strip()
    def_en = (reg.get("definition_en") or definition_en or "").strip()
    def_pt = (reg.get("definition_pt") or definition_pt or "").strip()
    out = ""
    if pt_label:
        out += f' ;\n    rdfs:label "{_safe_ttl(pt_label)}"@pt-br'
    if def_en:
        out += f' ;\n    iof-av:naturalLanguageDefinition "{_safe_ttl(def_en)}"@en'
        out += f' ;\n    skos:definition "{_safe_ttl(def_en)}"@en'
    if def_pt:
        out += f' ;\n    iof-av:naturalLanguageDefinition "{_safe_ttl(def_pt)}"@pt-br'
    return out


def _function_definitions(e: dict) -> tuple[str, str]:
    """
    (English, Portuguese) natural-language definition of an entry's function.

    The reviewer-editable function_nl_definition_en / _pt columns win; the
    English definition falls back to the one stored in llm_raw_response.
    """
    en = (e.get("function_nl_definition_en") or "").strip()
    pt = (e.get("function_nl_definition_pt") or "").strip()
    if not en:
        try:
            raw = json.loads(e.get("llm_raw_response") or "{}") or {}
        except (json.JSONDecodeError, TypeError):
            raw = {}
        step1 = raw.get("step1_function", {}) if isinstance(raw, dict) else {}
        if isinstance(step1, dict):
            en = (step1.get("function_nl_definition") or "").strip()
    return en, pt


def _source_link_ttl(source_uri: str | None) -> str | None:
    """
    Turtle IRI reference for a source definition's URI, or None if it has none.

    Characters that are illegal inside a Turtle IRI (a couple of ISO 15926-4
    item IRIs contain them) are percent-encoded; everything that is already a
    valid IRI character, including existing %-escapes, is left alone.
    """
    from urllib.parse import quote

    if not source_uri or not source_uri.strip():
        return None
    return "<" + quote(source_uri.strip(), safe=":/?#[]@!$&'()*+,;=%-._~") + ">"


def extract_differentia_conjuncts(differentia_expression: str | None) -> list[tuple[str, str]]:
    """
    Parse a Step 3 differentia_expression into its (predicate, target-class) pairs.

    Returns [] for empty/None input. Deduplicates while preserving order.
    """
    if not differentia_expression:
        return []
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for pred, target in _DIFFERENTIA_CONJUNCT_RE.findall(differentia_expression):
        key = (pred, target)
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def find_unrendered_differentia(
    enrichment_id: int, turtle_src: str | None = None
) -> list[tuple[str, str]]:
    """
    Return the (predicate, target) differentia conjuncts that never reach the OWL.

    Step 3 writes `differentia_expression` as free text, but only the structured
    fields (genus, function, necessary_parts, qualities, process_signature) drive
    generate_turtle(). Any conjunct naming a class that does not appear in the
    generated Turtle is stated in the documentation but absent from the artifact
    -- the class is published weaker than it reads.

    This is a *detector*, not a repair: the right fix per conjunct is either to
    ground it into the field that carries it (necessary_parts / qualities) or to
    trim the differentia text, and that judgement needs source evidence. Emitting
    a restriction for every conjunct would publish ungrounded classes and invent
    object properties that BFO/IOF-Core does not define.

    Pass `turtle_src` to avoid regenerating when the caller already has it.
    """
    conn = get_enrichment_db()
    row = conn.execute(
        "SELECT differentia_expression FROM enrichment WHERE id = ?", (enrichment_id,)
    ).fetchone()
    conn.close()
    if not row:
        return []

    conjuncts = extract_differentia_conjuncts(row["differentia_expression"])
    if not conjuncts:
        return []

    if turtle_src is None:
        turtle_src = generate_turtle(enrichment_id)

    unrendered = []
    for pred, target in conjuncts:
        # Classes are emitted as `:LocalName` in the generated Turtle; the word
        # boundary keeps `:Piston` from matching `:PistonCheckValve`.
        if not re.search(rf":{re.escape(target)}\b", turtle_src):
            unrendered.append((pred, target))
    return unrendered


_SECONDARY_COVERAGE_CATEGORY_THRESHOLD = 4


def compute_secondary_coverage(source_defs_json: str | None) -> str:
    """
    Deterministic replacement for eyeballing "does secondary coverage look
    full or partial" (see CLAUDE.md Step 2b). "full" requires at least one
    tier='secondary' entry with citation_mode='verbatim', and the union of
    categories_covered across all secondary entries spans at least
    _SECONDARY_COVERAGE_CATEGORY_THRESHOLD of the 7 differential categories.
    Any secondary entry short of that is "partial"; no secondary entry at all
    is "none". Tertiary/primary entries never count toward this.
    """
    if not source_defs_json:
        return "none"
    try:
        entries = json.loads(source_defs_json)
    except (json.JSONDecodeError, TypeError):
        return "none"
    if not isinstance(entries, list):
        return "none"

    secondary = [e for e in entries if isinstance(e, dict) and e.get("tier") == "secondary"]
    if not secondary:
        return "none"

    has_verbatim = any(e.get("citation_mode") == "verbatim" for e in secondary)
    categories = set()
    for e in secondary:
        categories.update(e.get("categories_covered") or [])

    if has_verbatim and len(categories) >= _SECONDARY_COVERAGE_CATEGORY_THRESHOLD:
        return "full"
    return "partial"


def _tertiary_independence_key(entry: dict) -> str:
    """
    The unit of "independence" for triangulating a tertiary source.  A patent's
    key is its number (two different patents both hosted on patents.google.com
    must not collide on domain); everything else keys on the registrable
    domain of its URL, falling back to the bare `source` name.
    """
    if entry.get("source_type") == "patent":
        return (entry.get("source") or "").strip().upper()

    url = entry.get("url") or ""
    if url:
        from urllib.parse import urlparse
        netloc = urlparse(url).netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc

    return (entry.get("source") or "").strip().lower()


CORE_ANCHORING_BASELINE_PATH = Path(__file__).parent.parent / "scripts" / "core-anchoring-baseline.txt"


def validate_core_anchoring(cluster_label: str, process_name, process_parent, signature,
                            core_operation_gap) -> str | None:
    """Error message when a validated entry's process reaches no COPI-Core operation without a
    recorded gap, or its transformation_kind disagrees with the anchor. Grandfathered
    `cluster_label|finding` keys in scripts/core-anchoring-baseline.txt pass."""
    from core_operations import KIND_TO_OPERATIONS, anchoring_findings

    conn = get_enrichment_db()
    try:
        parents = {r["process_name"]: r["process_parent"] for r in conn.execute(
            "SELECT process_name, process_parent FROM enrichment WHERE process_name IS NOT NULL")}
    finally:
        conn.close()
    baseline = set()
    if CORE_ANCHORING_BASELINE_PATH.exists():
        baseline = {l.strip() for l in CORE_ANCHORING_BASELINE_PATH.read_text(encoding="utf-8").splitlines()
                    if l.strip() and not l.lstrip().startswith("#")}
    new = [f for f in anchoring_findings(process_name, process_parent, signature, core_operation_gap, parents)
           if f"{cluster_label}|{f}" not in baseline]
    if not new:
        return None
    parts = []
    for f in new:
        if f == "unanchored":
            parts.append("the process reaches no COPI-Core operation: set Process Parent to an operation, "
                         "or record a core operation gap (out of scope / coverage gap) with a rationale")
        else:
            kind = f.split(":", 1)[1]
            allowed = KIND_TO_OPERATIONS.get(kind) or ()
            parts.append(f"transformation_kind '{kind}' does not agree with the anchor "
                         f"(allowed: {', '.join(allowed) if allowed else 'none — record a core operation gap'})")
    return "COPI-Core anchoring: " + "; ".join(parts) + "."


def normalize_core_operation_gap(raw) -> dict | None:
    """Accept the Step 1 core_operation_gap as the model returns it (object, JSON string,
    null, or an unfilled template placeholder) and return a clean dict or None."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "").strip()
    if kind not in ("out_of_scope", "core_coverage_gap"):
        return None
    return {
        "kind": kind,
        "nearest_operation": (raw.get("nearest_operation") or None),
        "rationale": str(raw.get("rationale") or "").strip(),
    }


# ---------------------------------------------------------------------------
# Participant vocabulary gate
# ---------------------------------------------------------------------------
#
# Participant types — portions, ICE, qualities — are hand-authored vocabulary in
# copi-vocab (CLAUDE.md, ODR-022 §2): the 5-step method presupposes a function they
# do not bear, so the pipeline must not mint them. generate_turtle() emits whatever
# process_signature names, and allocate_missing_iris() then gives an unknown name a
# fresh COPI IRI — which is how LLM-invented types (MovingObject, Surface, SteelPipe)
# were published as COPI classes. auxiliary_class.status is no safeguard: 74 of its
# 80 rows were marked 'validated' in one bulk name-pattern run (bulk_classify_aux.py).

PARTICIPANT_VOCAB_BASELINE_PATH = (
    Path(__file__).parent.parent / "scripts" / "participant-vocabulary-baseline.txt"
)
_COPI_BASE_MODULE_FILES = (
    Path(__file__).parent / "ontologies" / "copi-context" / "copi-core.ttl",
    Path(__file__).parent / "ontologies" / "copi-context" / "copi-vocab.ttl",
)
_TERMINAL_ENRICHMENT_STATUSES = ("validated", "exported")
_base_module_cache: dict = {}


def _copi_base_module_classes() -> frozenset[str]:
    """IRIs declared as owl:Class in copi-core.ttl / copi-vocab.ttl. Re-parsed when
    either file changes, so a long-running app picks up new vocabulary."""
    key = tuple(p.stat().st_mtime_ns for p in _COPI_BASE_MODULE_FILES)
    if _base_module_cache.get("key") != key:
        from rdflib import Graph, OWL, RDF, URIRef
        g = Graph()
        for path in _COPI_BASE_MODULE_FILES:
            g.parse(path)
        _base_module_cache["key"] = key
        _base_module_cache["classes"] = frozenset(
            str(s) for s in g.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef)
        )
    return _base_module_cache["classes"]


def _validated_equipment_class_names() -> frozenset[str]:
    """PascalCase class names of validated/exported entries — a participant may be
    another pipeline-produced equipment class (e.g. a pig in a pig launcher)."""
    conn = get_enrichment_db()
    try:
        rows = conn.execute(
            "SELECT cluster_label FROM enrichment WHERE status IN (?, ?)",
            _TERMINAL_ENRICHMENT_STATUSES,
        ).fetchall()
    finally:
        conn.close()
    return frozenset(_to_pascal_case(r["cluster_label"]) for r in rows)


def participant_types(signature) -> list[str]:
    """PascalCase participant type names exactly as generate_turtle() emits them."""
    if isinstance(signature, str):
        try:
            signature = json.loads(signature)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(signature, dict):
        return []
    names: list[str] = []
    for item in (signature.get("inputs") or []) + (signature.get("outputs") or []):
        if isinstance(item, dict) and (item.get("type") or "").strip():
            names.append(_to_pascal_case(item["type"].strip()))
    return list(dict.fromkeys(names))


def find_unvetted_participants(signature) -> list[str]:
    """Participant types that are neither copi-core/copi-vocab classes, redirects to
    BFO / IOF-Core, nor validated equipment classes. A redirect to a role-defined upstream
    class (iof-core:PieceOfEquipment, MaterialComponent) is also unvetted: membership in it
    is inferred from a role, not a type to assert."""
    types = participant_types(signature)
    if not types:
        return []
    from participant_vocabulary import role_defined_upstream_iris
    iri_map = _load_copi_iri_map()
    declared = _copi_base_module_classes()
    equipment = _validated_equipment_class_names()
    role_defined = role_defined_upstream_iris()
    unvetted = []
    for name in types:
        target = iri_map.get(f"{_COPI_NS}{name}", f"{_COPI_NS}{name}")
        if target in role_defined:
            unvetted.append(name)   # e.g. EquipmentItem -> iof-core:PieceOfEquipment: inferred from a role
            continue
        if not target.startswith(_COPI_NS) or target in declared or name in equipment:
            continue
        unvetted.append(name)
    return unvetted


def load_participant_vocabulary_baseline() -> set[str]:
    """Grandfathered ``cluster_label|Type`` keys (published before the gate existed)."""
    if not PARTICIPANT_VOCAB_BASELINE_PATH.exists():
        return set()
    return {
        line.strip()
        for line in PARTICIPANT_VOCAB_BASELINE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def validate_participant_vocabulary(cluster_label: str, signature) -> str | None:
    """Return an error message if a validated entry names an unvetted participant type."""
    baseline = load_participant_vocabulary_baseline()
    offending = [
        t for t in find_unvetted_participants(signature)
        if f"{cluster_label}|{t}" not in baseline
    ]
    if not offending:
        return None
    return (
        "Participant type(s) not in COPI vocabulary: " + ", ".join(offending) + ". "
        "Participant types are hand-authored in copi-vocab (ODR-022 §2) — the pipeline "
        "must not mint them. Replace each with an existing copi-vocab type, redirect it to "
        "a BFO / IOF-Core class in copi-iri-map.tsv, or add it to copi-vocab.ttl first."
    )


def validate_tertiary_triangulation(source_defs_json: str | None) -> str | None:
    """
    Enforce that any tier='tertiary' entry in source_definitions_used is
    corroborated by at least one other tertiary entry from an independent
    source before it can back an axiom. Returns an error message, or None
    if the triangulation requirement is satisfied (or does not apply).
    """
    if not source_defs_json:
        return None
    try:
        entries = json.loads(source_defs_json)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(entries, list):
        return None

    tertiary = [e for e in entries if isinstance(e, dict) and e.get("tier") == "tertiary"]
    if not tertiary:
        return None

    keys = {k for e in tertiary if (k := _tertiary_independence_key(e))}
    if len(keys) < 2:
        return (
            "Tertiary source(s) require triangulation: at least 2 independent "
            "tertiary sources (different manufacturers, patents, or domains) are "
            "needed before a tertiary-sourced claim can back an axiom."
        )
    return None


def get_cluster_properties(cluster_label: str) -> list[dict]:
    """
    Fetch CFIHOS (and DEXPI) properties for terms matching this cluster label.
    Returns deduplicated property list sorted by name.
    """
    conn = get_terms_db()
    variants = _label_variants(cluster_label)
    placeholders = ",".join("?" * len(variants))
    try:
        rows = conn.execute(f"""
            SELECT DISTINCT p.name, p.definition, p.datatype, p.unit, p.is_required
            FROM terms t
            JOIN properties p ON p.term_id = t.id
            WHERE LOWER(t.preferred_label) IN ({placeholders})
              AND t.source IN ('cfihos', 'dexpi')
            ORDER BY p.name
        """, variants).fetchall()
    except Exception:
        rows = []
    conn.close()
    return [dict(r) for r in rows]


def get_cluster_iso14224_properties(cluster_label: str) -> dict:
    """
    Fetch ISO 14224 properties for terms matching this cluster label.

    Returns a dict with two keys:
      - "main_function": str | None  — the 'Main function' valid-values string,
        e.g. "Flow control, on/off, non-return, Pressure relief, …"
      - "attributes": list[dict]    — all other non-failure_modes properties,
        each with keys: name, definition, datatype, unit, is_required
    """
    conn = get_terms_db()
    variants = _label_variants(cluster_label)
    placeholders = ",".join("?" * len(variants))
    try:
        rows = conn.execute(f"""
            SELECT DISTINCT p.name, p.definition, p.datatype, p.unit, p.is_required
            FROM terms t
            JOIN properties p ON p.term_id = t.id
            WHERE LOWER(t.preferred_label) IN ({placeholders})
              AND t.source = 'iso14224'
            ORDER BY p.name
        """, variants).fetchall()
    except Exception:
        rows = []
    conn.close()

    main_function: str | None = None
    attributes: list[dict] = []
    for row in rows:
        r = dict(row)
        if r["name"] == "Main function":
            main_function = r.get("unit") or r.get("definition") or None
        elif r["name"] != "failure_modes":
            attributes.append(r)

    return {"main_function": main_function, "attributes": attributes}


def get_cluster_subtypes(cluster_label: str, limit: int = 30) -> list[dict]:
    """
    Fetch known subtypes / specialisations of this cluster — terms whose label
    CONTAINS the cluster label but is not equal to it.  Returned as lightweight
    dicts {source, term, definition} for the LLM's contextual awareness
    (informs which parts/differentia belong at the subtype level, not here).
    """
    conn = get_terms_db()
    terms_table, name_col, def_col, source_col = _terms_table_info(conn)
    if not terms_table or not name_col:
        conn.close()
        return []

    label_lower = cluster_label.lower().strip()
    variants = _label_variants(cluster_label)
    placeholders = ",".join("?" * len(variants))

    rows = conn.execute(
        f"""SELECT {name_col}, {source_col or "'unknown'"}, {def_col or "NULL"}
            FROM {terms_table}
            WHERE LOWER({name_col}) LIKE ?
              AND LOWER({name_col}) NOT IN ({placeholders})
            ORDER BY {source_col or "1"}, {name_col}
            LIMIT ?""",
        [f"%{label_lower}%"] + variants + [limit],
    ).fetchall()

    conn.close()
    return [
        {"term": r[0], "source": r[1] or "unknown", "definition": r[2]}
        for r in rows
    ]


def get_component_terms(cluster_label: str, limit: int = 40) -> list[dict]:
    """
    Fetch terms from terms.db that are plausible part/component names for this cluster.

    Source: compound labels that start with '{cluster_label} ' (e.g. 'pump casing').
    `hierarchy` in this DB stores only subClassOf edges (confirmed: 100% of rows are
    relation_type='subClassOf', no part-of relation exists) -- a "hierarchy child" of
    the cluster is a SUBTYPE (e.g. 'DIAPHRAGM PUMP' under 'reciprocating pump'), never
    a component part, so an earlier version of this function that queried hierarchy
    children as component candidates was removed (both because its JOIN referenced
    columns -- h.parent_label / h.term_id -- that don't exist on this schema, and
    because even a corrected JOIN would have surfaced subtypes, not parts).

    The compound-label naming convention itself is ALSO ambiguous in ISO 15926-4: it's
    used both for genuine parts ('BUTTERFLY VALVE CLOSURE MEMBER') and for subtype
    variants ('CENTRIFUGAL PUMP WITH AXIALLY SPLIT CASING', 'ANGLE VALVE 45 DEGREE').
    The two are disambiguated by checking the candidate's OWN subClassOf parent: if
    the cluster label (or a variant) is among the candidate's hierarchy parents, the
    candidate is a subtype of the cluster and is excluded; a candidate whose parents
    are a distinct structural-component class (e.g. 'VALVE CLOSURE MEMBER', 'CHECK
    VALVE BODY') is kept.

    Returns deduplicated list of {label, source, definition} dicts.
    These are passed to the LLM as the only allowed vocabulary for Step 4 part names.
    """
    conn = get_terms_db()
    variants = _label_variants(cluster_label)
    variant_set = set(variants)

    seen: set[str] = set()
    results: list[dict] = []

    try:
        for v in variants:
            rows = conn.execute("""
                SELECT DISTINCT t.id, t.preferred_label, t.source, t.definition
                FROM terms t
                WHERE LOWER(t.preferred_label) LIKE ?
                  AND LOWER(t.preferred_label) != ?
                ORDER BY t.source, t.preferred_label
                LIMIT ?
            """, (v + " %", v, limit)).fetchall()
            for row in rows:
                key = row["preferred_label"].lower()
                if key in seen:
                    continue
                parent_labels = {
                    p[0].lower() for p in conn.execute("""
                        SELECT parent.preferred_label
                        FROM hierarchy h
                        JOIN terms parent ON parent.id = h.parent_term_id
                        WHERE h.child_term_id = ?
                    """, (row["id"],)).fetchall()
                }
                if parent_labels & variant_set:
                    continue  # candidate is a subtype of the cluster, not a part of it
                seen.add(key)
                results.append({"label": row["preferred_label"], "source": row["source"], "definition": row["definition"]})
    except Exception:
        pass

    conn.close()
    return results[:limit]


def _find_col(columns: list[str], candidates: list[str]) -> str | None:
    """Find the first column name that matches any candidate."""
    cols_lower = {c.lower(): c for c in columns}
    for candidate in candidates:
        if candidate in cols_lower:
            return cols_lower[candidate]
    return None


def get_related_concepts(cluster_label: str, limit: int = 10) -> list[str]:
    """Find other clusters in the DB that might be related (for context)."""
    conn = get_terms_db()
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row["name"] for row in cursor.fetchall()]

    terms_table = "terms" if "terms" in tables else None
    if not terms_table:
        conn.close()
        return []

    cursor = conn.execute(f"PRAGMA table_info({terms_table})")
    columns = [row["name"] for row in cursor.fetchall()]
    name_col = _find_col(columns, ["preferred_label", "term", "name", "label", "title", "concept"])

    if not name_col:
        conn.close()
        return []

    rows = conn.execute(
        f"SELECT DISTINCT LOWER({name_col}) as concept FROM {terms_table} LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()

    return [row["concept"] for row in rows if row["concept"] != cluster_label.lower()]


def get_parent_candidates(cluster_label: str) -> list[dict]:
    """
    Walk the source hierarchies to find parent classes of this cluster.

    Returns a list of dicts, each with:
      - label: str        — preferred label of the parent class
      - source: str       — which standard it comes from
      - enriched: bool    — whether it has already been enriched in our ontology

    Ordered by source priority (iso15926 > cfihos > dexpi) then deduplicated
    by label so the LLM sees the most authoritative name first.
    """
    label_lower = cluster_label.lower().strip()
    variants = [label_lower]
    if label_lower.endswith("s"):
        variants.append(label_lower[:-1])
    else:
        variants.append(label_lower + "s")

    conn_terms = get_terms_db()
    placeholders = ",".join("?" * len(variants))

    rows = conn_terms.execute(f"""
        SELECT DISTINCT tp.preferred_label AS parent_label, tp.source
        FROM hierarchy h
        JOIN terms tc ON tc.id = h.child_term_id
        JOIN terms tp ON tp.id = h.parent_term_id
        WHERE LOWER(tc.preferred_label) IN ({placeholders})
        ORDER BY
            CASE tp.source
                WHEN 'iso15926' THEN 1
                WHEN 'cfihos'   THEN 2
                WHEN 'dexpi'    THEN 3
                ELSE 4
            END,
            tp.preferred_label
    """, variants).fetchall()
    conn_terms.close()

    if not rows:
        return []

    # Check which parent labels have already been enriched
    conn_enrich = get_enrichment_db()
    enriched_set = set()
    for r in rows:
        hit = conn_enrich.execute(
            "SELECT id FROM enrichment WHERE LOWER(cluster_label) = LOWER(?)",
            (r["parent_label"],)
        ).fetchone()
        if hit:
            enriched_set.add(r["parent_label"].lower())
    conn_enrich.close()

    seen: set[str] = set()
    result = []
    for r in rows:
        key = r["parent_label"].lower()
        if key not in seen:
            seen.add(key)
            result.append({
                "label": r["parent_label"],
                "source": r["source"],
                "enriched": key in enriched_set,
            })
    return result


# ---------------------------------------------------------------------------
# ISA 5.1 / Wikimedia symbol lookup
# ---------------------------------------------------------------------------

_SYMBOL_MAP_PATH = Path(__file__).parent.parent / "app" / "static" / "isa5_1" / "equipment_map.json"
_WIKIMEDIA_MAP_PATH = Path(__file__).parent.parent / "app" / "static" / "isa5_1" / "wikimedia" / "wikimedia_map.json"
_symbol_map_cache: dict | None = None
_wikimedia_map_cache: dict | None = None


def _load_symbol_map() -> dict:
    global _symbol_map_cache
    if _symbol_map_cache is None:
        if _SYMBOL_MAP_PATH.exists():
            _symbol_map_cache = json.loads(_SYMBOL_MAP_PATH.read_text())
        else:
            _symbol_map_cache = {}
    return _symbol_map_cache


def _load_wikimedia_map() -> dict:
    global _wikimedia_map_cache
    if _wikimedia_map_cache is None:
        if _WIKIMEDIA_MAP_PATH.exists():
            _wikimedia_map_cache = json.loads(_WIKIMEDIA_MAP_PATH.read_text())
        else:
            _wikimedia_map_cache = {}
    return _wikimedia_map_cache


def _lookup_in_map(sym_map: dict, label: str) -> str | None:
    """Apply 3-tier fuzzy lookup against a symbol map."""
    # 1. Exact match
    if label in sym_map:
        return sym_map[label]

    # 2. Cluster label contains a map key — prefer LONGEST (most specific)
    best_key = max(
        (k for k in sym_map if k in label),
        key=len,
        default=None,
    )
    if best_key:
        return sym_map[best_key]

    # 3. A map key contains the cluster label — prefer SHORTEST (closest match)
    best_key = min(
        (k for k in sym_map if label in k),
        key=len,
        default=None,
    )
    if best_key:
        return sym_map[best_key]

    return None


def get_symbol_for_cluster(cluster_label: str) -> str | None:
    """
    Return the symbol path (relative to app/static/isa5_1/) for the
    given cluster label, or None if not found.

    Wikimedia SVGs are preferred over extracted PNGs when available.

    Matching strategy (in order, applied to each map):
      1. Exact lowercase match
      2. Cluster label contains a map key (longest key wins)
      3. A map key contains the cluster label (shortest key wins)
    """
    label = cluster_label.lower().strip()

    # Prefer Wikimedia SVGs (clean vector graphics)
    wiki_result = _lookup_in_map(_load_wikimedia_map(), label)
    if wiki_result:
        return wiki_result

    # Fall back to extracted ISA 5.1 PNGs
    return _lookup_in_map(_load_symbol_map(), label)


# ---------------------------------------------------------------------------
# LLM interaction
# ---------------------------------------------------------------------------

# Pricing per million tokens (approximate public rates, update as needed)
# Prompt caching rates for Claude Sonnet 4:
#   cache_write: $3.75/MTok  (25% premium to write the cache entry)
#   cache_read:  $0.30/MTok  (90% discount vs normal input on cache hits)
_COST_PER_MTOK = {
    "input":       3.00,   # USD/MTok — Claude Sonnet 4 (uncached input)
    "cache_write": 3.75,   # USD/MTok — cache creation tokens
    "cache_read":  0.30,   # USD/MTok — cache hit tokens (90% savings)
    "output":     15.00,
}


def _compute_cost(
    input_tokens: int,
    output_tokens: int,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    return (
        input_tokens       * _COST_PER_MTOK["input"]       / 1_000_000
        + output_tokens    * _COST_PER_MTOK["output"]      / 1_000_000
        + cache_write_tokens * _COST_PER_MTOK["cache_write"] / 1_000_000
        + cache_read_tokens  * _COST_PER_MTOK["cache_read"]  / 1_000_000
    )


async def call_llm(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
    temperature: float | None = None,
) -> tuple[dict, int, int, float, int, int]:
    """
    Call the Anthropic API and return
    (parsed_json, input_tokens, output_tokens, cost_usd, cache_write_tokens, cache_read_tokens).

    Prompt caching is enabled: the system prompt is sent as a cacheable content block.
    On the first call the cache entry is written (~25% premium); subsequent calls with
    the same system prompt pay only $0.30/MTok instead of $3.00/MTok (90% savings).
    Retries up to 3 times on 429 with exponential backoff (10s, 30s, 60s).
    """
    import asyncio as _asyncio
    _backoffs = [10, 30, 60]
    _payload = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        **({"temperature": temperature} if temperature is not None else {}),
        "system": [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [{"role": "user", "content": user_prompt}],
    }
    _headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "prompt-caching-2024-07-31",
    }
    for _attempt, _backoff in enumerate([0] + _backoffs):
        if _backoff:
            logger.warning("429 Too Many Requests — retrying in %ds (attempt %d/%d).", _backoff, _attempt, len(_backoffs))
            await _asyncio.sleep(_backoff)
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(ANTHROPIC_API_URL, headers=_headers, json=_payload)
        if response.status_code == 429 and _attempt < len(_backoffs):
            continue
        response.raise_for_status()
        break

    data = response.json()
    usage = data.get("usage", {})
    input_tokens       = usage.get("input_tokens", 0)
    output_tokens      = usage.get("output_tokens", 0)
    cache_write_tokens = usage.get("cache_creation_input_tokens", 0)
    cache_read_tokens  = usage.get("cache_read_input_tokens", 0)
    cost = _compute_cost(input_tokens, output_tokens, cache_write_tokens, cache_read_tokens)

    # Extract text content
    text = ""
    for block in data.get("content", []):
        if block.get("type") == "text":
            text += block.get("text", "")

    # Parse JSON — strip any markdown fences if present
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        result = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response: {e}\nRaw: {text[:500]}")
        raise ValueError(f"LLM returned invalid JSON: {e}")

    cache_info = ""
    if cache_write_tokens:
        cache_info = f", cache_write: {cache_write_tokens}"
    elif cache_read_tokens:
        cache_info = f", cache_read: {cache_read_tokens} (saved ${cache_read_tokens * (_COST_PER_MTOK['input'] - _COST_PER_MTOK['cache_read']) / 1_000_000:.4f})"
    logger.info(f"LLM usage — in: {input_tokens}, out: {output_tokens}{cache_info}, cost: ${cost:.4f}")
    return result, input_tokens, output_tokens, cost, cache_write_tokens, cache_read_tokens


# ---------------------------------------------------------------------------
# Part source-label validator
# ---------------------------------------------------------------------------

def _validate_part_source_labels(
    proposal: dict,
    component_terms: list[dict],
    definitions: list[dict],
) -> None:
    """
    Annotate each step4 part with a part_name_unverified flag (in-place).

    Flag semantics:
      False  — source_label found literally in component_terms labels or definition texts
      True   — source_label present but cannot be traced to any provided source (log warning)
      None   — source_label absent (old record or name=null); auditability unknown

    Never raises; insertion is not blocked.
    """
    step4 = proposal.get("step4_parts")
    if not step4:
        return
    parts = step4.get("parts") or []
    if not parts:
        return

    component_labels = {(t.get("label") or "").strip() for t in component_terms}
    definition_texts = [d.get("definition") or "" for d in definitions]
    cluster = proposal.get("cluster_label", "?")

    for part in parts:
        name = part.get("name")
        source_label = part.get("source_label")

        if name is None:
            continue

        if source_label is None:
            part["part_name_unverified"] = None
            continue

        if source_label in component_labels or any(source_label in t for t in definition_texts):
            part["part_name_unverified"] = False
        else:
            part["part_name_unverified"] = True
            logger.warning(
                "part_name_unverified: cluster=%r part=%r source_label=%r "
                "— not found in component terms or source definitions.",
                cluster, name, source_label,
            )


# ---------------------------------------------------------------------------
# Enrichment orchestration
# ---------------------------------------------------------------------------

async def enrich_cluster(
    cluster_label: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
    reviewer_notes: str | None = None,
    expert_review: dict | None = None,
) -> dict:
    """
    Full enrichment pipeline for a single cluster:
      1. Gather definitions
      2. Build prompt (optionally including reviewer notes from a previous run)
      3. Call LLM
      4. Store proposal in DB
      5. Return proposal
    """
    # 1. Gather
    definitions = get_cluster_definitions(cluster_label)
    if not definitions:
        raise ValueError(f"No definitions found for cluster '{cluster_label}'")

    subtypes = get_cluster_subtypes(cluster_label)
    related = get_related_concepts(cluster_label)
    parent_candidates = get_parent_candidates(cluster_label)
    existing_context = get_existing_ontology_context()
    cfihos_properties = get_cluster_properties(cluster_label)
    iso14224_data = get_cluster_iso14224_properties(cluster_label)
    component_terms = get_component_terms(cluster_label)

    # 2. Build prompt
    system_prompt, user_prompt = build_enrichment_prompt(
        cluster_label=cluster_label,
        definitions=definitions,
        subtypes=subtypes,
        related_concepts=related,
        parent_candidates=parent_candidates,
        existing_ontology=existing_context,
        reviewer_notes=reviewer_notes,
        expert_review=expert_review,
        cfihos_properties=cfihos_properties,
        iso14224_main_function=iso14224_data["main_function"],
        iso14224_attributes=iso14224_data["attributes"],
        component_terms=component_terms,
    )

    # 3. Call LLM
    proposal, input_tokens, output_tokens, cost, cache_write, cache_read = await call_llm(
        system_prompt, user_prompt, api_key, model
    )

    # 3b. Validate part source labels against component terms and definitions
    _validate_part_source_labels(proposal, component_terms, definitions)

    # 3c. Validate transformation_kind vocabulary compliance
    _validate_transformation_kind(proposal)

    # 3d. Validate disjointness decision tree
    from enrichment.disjointness_validator import validate_disjointness
    disjointness_result = validate_disjointness(proposal)
    for candidate, case_id, reason in disjointness_result["rejected"]:
        logger.warning(
            "disjointness_rejected: cluster=%r candidate=%r case=%s reason=%s",
            cluster_label, candidate, case_id, reason,
        )
    for candidate, reason in disjointness_result["rationale_invalid"]:
        logger.warning(
            "disjointness_rationale_invalid: cluster=%r candidate=%r reason=%s",
            cluster_label, candidate, reason,
        )
    for warning in disjointness_result["asymmetry_warnings"]:
        logger.warning("disjointness_asymmetry: cluster=%r %s", cluster_label, warning)

    # 4. Store in DB
    proposal_id = _store_proposal(
        cluster_label, proposal, definitions, model,
        input_tokens, output_tokens, cost, cache_write, cache_read,
    )
    proposal["id"] = proposal_id
    proposal["input_tokens"] = input_tokens
    proposal["output_tokens"] = output_tokens
    proposal["estimated_cost_usd"] = cost

    return proposal


async def reenrich_proposal(
    enrichment_id: int,
    api_key: str,
    model: str = DEFAULT_MODEL,
) -> dict:
    """
    Re-run enrichment for an existing proposal, injecting its reviewer_notes
    and expert_review as context so the LLM addresses the feedback.
    Overwrites the existing DB row, preserving reviewer_notes and expert fields.
    """
    conn = get_enrichment_db()
    try:
        row = conn.execute(
            "SELECT cluster_label, reviewer_notes, expert_review, expert_reviewer "
            "FROM enrichment WHERE id = ?", (enrichment_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Enrichment {enrichment_id} not found")

        cluster_label = row["cluster_label"]
        reviewer_notes = row["reviewer_notes"] or None
        expert_review_raw = row["expert_review"] or "{}"
        try:
            expert_review = json.loads(expert_review_raw) if expert_review_raw else {}
        except Exception:
            expert_review = {}
        expert_reviewer = row["expert_reviewer"]

        # Run with notes injected into the prompt
        proposal = await enrich_cluster(
            cluster_label=cluster_label,
            api_key=api_key,
            model=model,
            reviewer_notes=reviewer_notes,
            expert_review=expert_review,
        )

        new_id = proposal["id"]

        # Carry forward reviewer fields and set status back to "proposed"
        conn.execute(
            "UPDATE enrichment SET reviewer_notes = ?, expert_review = ?, expert_reviewer = ?, "
            "status = 'proposed' WHERE id = ?",
            (reviewer_notes, expert_review_raw, expert_reviewer, new_id),
        )
        conn.commit()
        return proposal
    finally:
        conn.close()


def _store_proposal(
    cluster_label: str,
    proposal: dict,
    definitions: list[dict],
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    estimated_cost_usd: float = 0.0,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
    generation_path: str = "api_call_llm",
) -> int:
    """Persist an LLM proposal to the enrichment table."""
    conn = get_enrichment_db(actor="_store_proposal")

    step1 = proposal.get("step1_function", {})
    step2 = proposal.get("step2_genus", {})
    step3 = proposal.get("step3_differentia", {})
    step4 = proposal.get("step4_parts", {})
    step5 = proposal.get("step5_signature", {})
    # backwards compat: old runs used step3_parts / step4_signature
    if not step4 and proposal.get("step3_parts"):
        step4 = proposal.get("step3_parts", {})

    # Sanitize genus_bfo_root: DB CHECK only allows these values (or NULL)
    _BFO_ROOTS = {"Assembly", "MaterialArtifact", "EngineeredSystem",
                  "Site", "Object", "ObjectAggregate", "FiatObjectPart"}
    raw_root = step2.get("genus_bfo_root")
    genus_bfo_root = raw_root if raw_root in _BFO_ROOTS else None
    if not step5 and proposal.get("step4_signature"):
        step5 = proposal.get("step4_signature", {})
    defs = proposal.get("definitions", {})

    symbol_path = get_symbol_for_cluster(cluster_label)

    conn.execute("""
        INSERT INTO enrichment (
            cluster_label,
            function_name, function_parent, process_name, process_parent, function_rationale,
            genus, genus_bfo_root, genus_rationale,
            differentia_expression, differentia_nl, differentia_rationale,
            genus_already_provides, distinguishes_from,
            necessary_parts, parts_rationale,
            process_signature, signature_rationale,
            axiom_mode, primitive_rationale,
            disjoint_with, disjointness_rationale,
            cross_standard_links,
            divergence_flags,
            nl_definition_en, nl_definition_pt, semiformal_axiom, fol_axiom,
            source_definitions_used, llm_model, llm_raw_response,
            input_tokens, output_tokens, estimated_cost_usd,
            cache_write_tokens, cache_read_tokens,
            symbol_path, status, generation_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        cluster_label,
        step1.get("function_name"),
        step1.get("function_parent", "DesignedFunction"),
        step1.get("process_name"),
        step1.get("process_parent", "PlannedProcess"),
        step1.get("rationale"),
        step2.get("genus_name"),
        genus_bfo_root,
        step2.get("rationale"),
        step3.get("differentia_expression"),
        step3.get("differentia_nl"),
        step3.get("rationale"),
        json.dumps(step3.get("genus_already_provides", [])),
        json.dumps(step3.get("distinguishes_from", {})),
        json.dumps(step4.get("parts", [])),
        step4.get("rationale"),
        json.dumps(step5),
        step5.get("rationale"),
        proposal.get("axiom_mode", "necessary"),
        proposal.get("primitive_rationale"),
        json.dumps(proposal.get("disjoint_with", [])),
        proposal.get("disjointness_rationale"),
        json.dumps(proposal.get("cross_standard_notes", "")),
        json.dumps(proposal.get("divergence_flags", [])),
        defs.get("nl_definition_en"),
        defs.get("nl_definition_pt"),
        defs.get("semiformal_axiom"),
        defs.get("fol_axiom"),
        json.dumps([{"source": d["source"], "term": d["term"]} for d in definitions]),
        model,
        json.dumps(proposal),
        input_tokens,
        output_tokens,
        estimated_cost_usd,
        cache_write_tokens,
        cache_read_tokens,
        symbol_path,
        "proposed",
        generation_path,
    ))
    try:
        _clear_write_actor(conn)
        conn.commit()
        proposal_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    # COPI-Core anchoring gap (Step 1). Stored separately from the positional INSERT above.
    _gap = normalize_core_operation_gap(step1.get("core_operation_gap"))
    if _gap:
        update_enrichment(proposal_id, {"core_operation_gap": json.dumps(_gap)})

    # Prompt-compliance check: warn when the LLM returned a specific
    # function_parent but omitted the function_parent_enriched boolean.
    # This does not block insertion; it surfaces non-compliance for audit.
    _fp = step1.get("function_parent", "DesignedFunction") or "DesignedFunction"
    if _fp != "DesignedFunction" and "function_parent_enriched" not in step1:
        logger.warning(
            "fpe_missing: cluster=%r function_parent=%r — LLM omitted "
            "function_parent_enriched from step1_function; "
            "run tools/backfill_function_parent_enriched.py to fix",
            cluster_label, _fp,
        )

    return proposal_id


# ---------------------------------------------------------------------------
# OWL/Turtle generation
# ---------------------------------------------------------------------------

def _turtle_prefixes() -> str:
    return dedent(f"""\
    @prefix copi:    <{COPI_NS}> .
    @prefix :         <{COPI_NS}> .
    @prefix owl:      <http://www.w3.org/2002/07/owl#> .
    @prefix rdf:      <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
    @prefix rdfs:     <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:      <http://www.w3.org/2001/XMLSchema#> .
    @prefix bfo:      <http://purl.obolibrary.org/obo/> .
    @prefix iof-core: <https://spec.industrialontologies.org/ontology/construct/> .
    @prefix iof-av:   <https://spec.industrialontologies.org/ontology/annotation/> .
    @prefix skos:     <http://www.w3.org/2004/02/skos/core#> .
    @prefix qudt:     <http://qudt.org/schema/qudt/> .
    @prefix dcterms:  <http://purl.org/dc/terms/> .
    @prefix foaf:     <http://xmlns.com/foaf/0.1/> .
    @prefix apv:      <http://inf.ufrgs.br/ontologies/apv#> .

""")


def _generate_role_turtle(e: dict) -> str:  # kept for reference only; no longer called
    """Retained but unused. All enrichments are now modelled as kinds.
    Role modelling is delegated to Pillar 1 (FL/site assertions) and Pillar 3 (OMIS).
    """
    label     = e["cluster_label"]
    cls_name  = _to_pascal_case(label) + "Role"
    bearer    = _to_pascal_case(e.get("role_bearer") or "")

    ttl = _turtle_prefixes()

    # Ontology header (reuse same pattern as generate_turtle)
    _scope_ttl = "".join(
        f'    skos:scopeNote "{_safe_ttl(n)}"@{lang} ;\n'
        for n, lang in COPI_SCOPE_NOTES
    )
    _contributor_ttl = "".join(
        f'    dcterms:contributor "{c}" ;\n'
        for c in COPI_CONTRIBUTORS
    )
    ttl += f"""### COPI — Core Ontology for Petroleum Installations
### Role module: {cls_name}
<{COPI_IRI}>
    rdf:type owl:Ontology ;
    dcterms:title "Core Ontology for Petroleum Installations (COPI)"@en ;
    dcterms:title "Ontologia Core para Instalações de Petróleo (COPI)"@pt-br ;
    dcterms:description "BFO/IOF-Core conformant ontology of equipment classes for petroleum production plants, developed using the five-step RDL enrichment method."@en ;
{_scope_ttl}    owl:versionInfo "{COPI_VERSION}" ;
    owl:imports <https://spec.industrialontologies.org/ontology/core/Core/> ;
    owl:imports <http://purl.obolibrary.org/obo/bfo/2020/bfo.owl> ;
    dcterms:creator "{COPI_AUTHOR}"@en ;
{_contributor_ttl}    dcterms:isPartOf <https://inf.ufrgs.br/projetos/{COPI_PROJECT}> ;
    dcterms:publisher "{COPI_PUBLISHER}"@en ;
    dcterms:license <https://creativecommons.org/licenses/by/4.0/> ;
    dcterms:created "2026-04-08"^^xsd:date ;
    dcterms:modified "{datetime.now().strftime('%Y-%m-%d')}"^^xsd:date ;
    apv:GlobalMinLanguageCoverage "en pt-br" ;
    apv:ClassURIFormationRule "https://www[.]inf[.]ufrgs[.]br/ontologies/copi/(COPI_[0-9]{{7}}|[A-Z][A-Za-z0-9]*)" ;
    apv:ClassMinAnnotationCoverage "rdfs:label https://spec.industrialontologies.org/ontology/annotation/naturalLanguageDefinition" .

iof-av:naturalLanguageDefinition rdf:type owl:AnnotationProperty ;
    apv:MinAnnotationLength 20 .

"""

    # Role class
    ttl += f"""### Role: {cls_name}
:{cls_name} rdf:type owl:Class ;
    rdfs:subClassOf bfo:BFO_0000023 ;  # bfo:Role
    rdfs:label "{_to_label(cls_name)}"@en ;
"""
    if e.get("nl_definition_en"):
        ttl += f'    iof-av:naturalLanguageDefinition "{_safe_ttl(e["nl_definition_en"])}"@en ;\n'
    if e.get("nl_definition_pt"):
        ttl += f'    iof-av:naturalLanguageDefinition "{_safe_ttl(e["nl_definition_pt"])}"@pt-br ;\n'
    if e.get("role_bearer_rationale"):
        ttl += f'    rdfs:comment "{_safe_ttl(e["role_bearer_rationale"])}"@en ;\n'

    # Source definitions as annotations
    source_defs = get_cluster_definitions(label)
    for d in source_defs:
        src_name = _SRC_DISPLAY.get(d["source"], d["source"])
        def_text = _safe_ttl((d.get("definition") or "").strip())
        if def_text:
            ttl += f'    skos:definition "[{src_name}] {def_text}"@en ;\n'

    ttl = ttl.rstrip(" ;\n") + " .\n\n"

    # Bearer restriction: :Bearer rdfs:subClassOf [bfo:BFO_0000197 some :RoleClass]
    # BFO_0000197 = bearerOf
    if bearer:
        ttl += f"""### Bearer restriction for {cls_name}
:{bearer} rdf:type owl:Class ;
    rdfs:subClassOf [
        rdf:type owl:Restriction ;
        owl:onProperty bfo:BFO_0000197 ;  # bearerOf
        owl:someValuesFrom :{cls_name}
    ] .

"""
    return ttl


# Word-by-word translation for CamelCase stub class names.
# Key = English word as it appears after splitting CamelCase (title-cased).
# Value = Portuguese translation used in compound construction.
_WORD_PT: dict[str, str] = {
    # Adjective-type modifiers (used as adjectives when they are the sole modifier)
    "Acoustic": "acústico", "Active": "ativo", "Alternating": "alternado",
    "Analogue": "analógico", "Automatic": "automático", "Axial": "axial",
    "Chemical": "químico", "Clean": "limpo", "Cleaned": "limpo",
    "Compressed": "comprimido", "Condensed": "condensado", "Continuous": "contínuo",
    "Curved": "curvo", "Deaerated": "desaerado", "Deformable": "deformável",
    "Dense": "denso", "Depleted": "esgotado", "Diesel": "diesel",
    "Discrete": "discreto", "Diverging": "divergente", "Dry": "seco",
    "Electric": "elétrico", "Electrical": "elétrico",
    "Electromagnetic": "eletromagnético", "Electronic": "eletrônico",
    "Enclosed": "fechado", "Expanded": "expandido", "External": "externo",
    "Filtered": "filtrado", "Flexible": "flexível", "Gaseous": "gasoso",
    "Grooved": "ranhurado", "High": "alto", "Hydraulic": "hidráulico",
    "Inner": "interno", "Internal": "interno", "Kinetic": "cinético",
    "Light": "leve", "Liquid": "líquido", "Local": "local", "Low": "baixo",
    "Magnetic": "magnético", "Manual": "manual", "Mechanical": "mecânico",
    "Metallic": "metálico", "Mixed": "misto", "Multiphase": "multifásico",
    "Multiple": "múltiplo", "Pneumatic": "pneumático", "Polyphase": "polifásico",
    "Primary": "primário", "Protected": "protegido", "Protective": "protetor",
    "Protruding": "saliente", "Raised": "saliente", "Reciprocating": "alternativo",
    "Reinforced": "reforçado", "Replaceable": "substituível", "Restricted": "restrito",
    "Rich": "rico", "Rotary": "rotativo", "Rotating": "rotativo",
    "Rotational": "rotacional", "Sealed": "selado", "Separated": "separado",
    "Solid": "sólido", "Spatial": "espacial", "Standardized": "padronizado",
    "Steel": "de aço", "Suppressed": "suprimido", "Tangential": "tangencial",
    "Thermal": "térmico", "Visual": "visual", "Wet": "úmido",
    # Noun-type words (used in "de + noun" constructions)
    "Access": "acesso", "Air": "ar", "Assembly": "conjunto",
    "Backup": "reserva", "Bearing": "mancal", "Bit": "broca",
    "Body": "corpo", "Bottom": "fundo", "Braided": "trançado",
    "Branch": "ramal", "Bundle": "feixe", "Burner": "queimador",
    "Cable": "cabo", "Captured": "capturado", "Carrier": "portador",
    "Cartridge": "cartucho", "Casing": "invólucro", "Cavity": "cavidade",
    "Chamber": "câmara", "Christmas": "árvore de natal",
    "Chromatographic": "cromatográfico", "Chromatography": "cromatografia",
    "Closure": "fechamento", "Collar": "broca de perfuração",
    "Column": "coluna", "Combustion": "combustão", "Comparison": "comparação",
    "Compensation": "compensação", "Composition": "composição",
    "Compression": "compressão", "Condensate": "condensado",
    "Condensation": "condensação", "Conical": "cônico",
    "Connection": "conexão", "Connector": "conector",
    "Contact": "contato", "Control": "controle", "Conversion": "conversão",
    "Coolant": "refrigerante", "Cooled": "resfriado", "Coriolis": "Coriolis",
    "Corrosion": "corrosão", "Current": "corrente", "Cutting": "perfuração",
    "Cuttings": "cascalhos", "Cyclic": "cíclico", "Cyclonic": "ciclônico",
    "Cylinder": "cilindro", "Degassing": "degaseificação",
    "Detection": "detecção", "Diaphragm": "diafragma",
    "Differential": "diferencial", "Discharge": "descarga",
    "Displacement": "deslocamento", "Display": "display",
    "Disturbance": "perturbação", "Downhole": "fundo de poço",
    "Drive": "acionamento", "Drill": "perfuração", "Drilling": "perfuração",
    "Drop": "gota", "Droplet": "gota", "Drum": "tambor",
    "Drying": "secagem", "Elbow": "cotovelo", "Energy": "energia",
    "Equipment": "equipamento", "Exhaust": "escapamento",
    "Facility": "instalação", "Feed": "alimentação", "Filter": "filtro",
    "Filtration": "filtração", "Fin": "aleta", "Finned": "aletado",
    "Flame": "chama", "Flange": "flange", "Flare": "flare",
    "Flow": "fluxo", "Fluid": "fluido", "Force": "força",
    "Formation": "formação", "Fuel": "combustível", "Fuse": "fusível",
    "Gas": "gás", "Gear": "engrenagem", "Guide": "guia",
    "Heat": "calor", "Heating": "aquecimento", "Hub": "cubo",
    "Humidity": "umidade", "Hydrocarbon": "hidrocarboneto",
    "Ignition": "ignição", "Indication": "indicação",
    "Information": "informação", "Injection": "injeção", "Inlet": "entrada",
    "Intake": "admissão", "Isolation": "isolamento", "Key": "chaveta",
    "Launcher": "lançador", "Layer": "camada", "Level": "nível",
    "Lining": "revestimento", "Load": "carga", "Logging": "perfilagem",
    "Mass": "massa", "Master": "principal", "Material": "material",
    "Measurement": "medição", "Mechanism": "mecanismo", "Medium": "meio",
    "Mixing": "mistura", "Module": "módulo", "Moisture": "umidade",
    "Motion": "movimento", "Motive": "motriz", "Motor": "motor",
    "Mounting": "suporte de montagem", "Mud": "lama",
    "Nozzle": "bocal", "Object": "objeto", "Oil": "óleo",
    "Opening": "abertura", "Oscillation": "oscilação", "Outlet": "saída",
    "Output": "saída", "Overflow": "transbordamento", "Overhead": "topo",
    "Overload": "sobrecarga", "Panel": "painel", "Part": "parte",
    "Passage": "passagem", "Pathway": "caminho", "Phase": "fase",
    "Pig": "pig", "Pilot": "piloto", "Pipe": "tubo",
    "Pipeline": "pipeline", "Piston": "pistão", "Point": "ponto",
    "Position": "posição", "Power": "potência", "Pressure": "pressão",
    "Process": "processo", "Processing": "processamento",
    "Products": "produtos", "Protection": "proteção", "Probe": "sonda",
    "Pump": "bomba", "Ram": "aríete", "Reading": "leitura",
    "Converter": "conversor", "Reducer": "redutor",
    "Reference": "referência", "Referencee": "referência",
    "Reinforcement": "reforço", "Relay": "relé", "Removal": "remoção",
    "Removed": "removido", "Rotation": "rotação", "Run": "operação",
    "Rupture": "ruptura", "Sample": "amostra", "Scraping": "raspagem",
    "Seal": "vedação", "Sealing": "vedação", "Sensing": "sensoriamento",
    "Sensor": "sensor", "Separation": "separação", "Set": "ajuste",
    "Shaft": "eixo", "Shell": "casco", "Signal": "sinal",
    "Silencer": "silenciador", "Silo": "silo", "Sleeve": "manga",
    "Solid": "sólido", "Spark": "centelha", "Stack": "chaminé",
    "Standard": "padrão", "Stator": "estator", "Steam": "vapor",
    "Storage": "armazenamento", "String": "coluna", "Structure": "estrutura",
    "Sub": "sub", "Suction": "sucção", "Supply": "suprimento",
    "Support": "suporte", "Surface": "superfície", "Switch": "interruptor",
    "Switching": "chaveamento", "System": "sistema",
    "Temperature": "temperatura", "Terminal": "terminal",
    "Tower": "torre", "Transfer": "transferência",
    "Transduction": "transdução", "Transformer": "transformador",
    "Transmission": "transmissão", "Treatment": "tratamento",
    "Tube": "tubo", "Tubing": "coluna de produção",
    "Turbine": "turbina", "Underflow": "subfluxo",
    "Unknown": "desconhecido", "Vacuum": "vácuo",
    "Valve": "válvula", "Vapor": "vapor", "Variable": "variável",
    "Ventura": "venturi", "Vessel": "vaso", "Vibration": "vibração",
    "Waste": "resíduo", "Water": "água", "Weight": "peso",
    "Well": "poço", "Wellhead": "cabeçal de poço",
    "Winding": "enrolamento", "Wing": "ala",
    # Additional words for stub class translation
    "AC": "CA", "Absorbent": "absorvente", "Actuating": "atuação",
    "Adjustment": "ajuste", "Admission": "admissão", "Agitator": "agitador",
    "Analysis": "análise", "And": "e", "Arrest": "bloqueio",
    "Artifact": "artefato", "Base": "base", "Basin": "bacia",
    "Bent": "curvado", "Blade": "lâmina", "Blades": "lâminas",
    "Block": "bloco", "Bolt": "parafuso", "Bore": "furo",
    "Boundary": "limite", "Bowl": "tigela", "Braking": "frenagem",
    "Cell": "célula", "Channel": "canal", "Circuit": "circuito",
    "Coil": "bobina", "Collection": "coleta", "Compartment": "compartimento",
    "Component": "componente", "Compressor": "compressor",
    "Conditioner": "condicionador", "Conditioning": "condicionamento",
    "Conducting": "condutor", "Conductivity": "condutividade",
    "Conductor": "condutor", "Connections": "conexões",
    "Constituents": "constituintes", "Contacts": "contatos",
    "Containment": "contenção", "Contaminants": "contaminantes",
    "Contaminated": "contaminado", "Content": "conteúdo",
    "Core": "núcleo", "Cylindrical": "cilíndrico",
    "Data": "dados", "Demisting": "eliminação de névoa",
    "Detecting": "detecção", "Detector": "detector", "Device": "dispositivo",
    "Dial": "mostrador", "Dried": "seco", "Driver": "acionador",
    "Edge": "borda", "Element": "elemento", "Enclosure": "invólucro",
    "End": "extremidade", "Enlarged": "ampliado", "Entity": "entidade",
    "Entry": "entrada", "Exchange": "troca", "Exchanger": "trocador",
    "Field": "campo", "Floor": "piso", "Flowline": "linha de fluxo",
    "Frame": "estrutura", "From": "proveniente de",
    "Generation": "geração", "Handling": "manuseio",
    "Hanger": "suspensor", "Hole": "furo", "Housing": "carcaça",
    "Humid": "úmido", "Indicator": "indicador", "Input": "entrada",
    "Interaction": "interação", "Interface": "interface",
    "Interior": "interior", "Internals": "internos",
    "Interrupting": "interrupção", "Item": "item", "Joint": "junta",
    "Loading": "carregamento", "Mating": "encaixe", "Measuring": "medição",
    "Member": "membro", "Mixture": "mistura", "Movement": "movimento",
    "Moving": "móvel", "On": "em", "Or": "ou", "Orifice": "orifício",
    "Pair": "par", "Phenomenon": "fenômeno", "Physical": "físico",
    "Plunger": "êmbolo", "Pointer": "ponteiro", "Port": "bocal",
    "Portion": "porção", "Pressurized": "pressurizado",
    "Processor": "processador", "Product": "produto",
    "Radiation": "radiação", "Rate": "taxa", "Receiving": "receptor",
    "Region": "região", "Relief": "alívio", "Rim": "aro",
    "Rock": "rocha", "Safety": "segurança", "Seating": "assentamento",
    "Secondary": "secundário", "Section": "seção", "Separate": "separado",
    "Separator": "separador", "Sequence": "sequência",
    "Shaking": "agitação", "Shaped": "perfilado", "Shearing": "cisalhamento",
    "Sheathing": "revestimento", "Side": "lateral", "Source": "fonte",
    "Space": "espaço", "Spool": "spool", "Stabilizer": "estabilizador",
    "Stem": "haste", "Stimulus": "estímulo", "Structural": "estrutural",
    "Subsurface": "subsuperfície", "Supported": "suportado",
    "Supporting": "suporte", "Tee": "tê", "Terminals": "terminais",
    "Throat": "garganta", "Tip": "ponta", "To": "para",
    "Tool": "ferramenta", "Top": "superior", "Trays": "bandejas",
    "Treating": "tratamento", "Tree": "árvore", "Tubes": "tubos",
    "Tubular": "tubular", "Unit": "unidade", "Vane": "palheta",
    "Vanes": "palhetas", "Vapour": "vapor", "Wall": "parede",
    "Work": "trabalho",
}

# Adjective words that go AFTER the noun in Portuguese (no "de")
_ADJ_WORDS: frozenset[str] = frozenset({
    "Acoustic", "Active", "Alternating", "Analogue", "Automatic", "Axial",
    "Bent", "Chemical", "Clean", "Cleaned", "Compressed", "Condensed",
    "Contaminated", "Continuous", "Curved", "Cylindrical", "Deaerated",
    "Deformable", "Dense", "Depleted", "Diesel", "Discrete", "Diverging",
    "Dried", "Dry", "Electric", "Electrical", "Electromagnetic", "Electronic",
    "Enclosed", "Enlarged", "Expanded", "External", "Filtered", "Flexible",
    "Gaseous", "Grooved", "High", "Humid", "Hydraulic",
    "Inner", "Internal", "Kinetic", "Light", "Liquid", "Local", "Low",
    "Magnetic", "Manual", "Mechanical", "Metallic", "Mixed", "Moving",
    "Multiphase", "Multiple", "Physical", "Pneumatic", "Polyphase",
    "Pressurized", "Primary", "Protected", "Protective", "Protruding",
    "Raised", "Reciprocating", "Reinforced", "Replaceable", "Restricted",
    "Rich", "Rotary", "Rotating", "Rotational", "Secondary", "Sealed",
    "Separate", "Separated", "Side", "Standardized", "Structural",
    "Suppressed", "Supported", "Tangential", "Thermal", "Top", "Tubular",
    "Visual", "Wet",
})


def _camel_split(name: str) -> list[str]:
    """Split CamelCase name into component words."""
    import re as _re
    # Insert space before uppercase letters that follow lowercase or digits
    words = _re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', name)
    # Insert space before runs of uppercase followed by lowercase (e.g. "ACElectric" → "AC Electric")
    words = _re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', words)
    return [w for w in words.split() if w]


def _stub_label_pt_fn(name: str) -> str | None:
    """
    Derive a Portuguese rdfs:label for an auto-generated stub class.
    Returns None when no translation can be built.
    """
    # All-uppercase names handled in caller (DB lookup)
    if name.isupper():
        return None
    words = _camel_split(name)
    if not words:
        return None
    # Translate each word; bail out if any word is unknown
    translated = []
    for w in words:
        pt = _WORD_PT.get(w)
        if pt is None:
            return None
        translated.append((w, pt))
    if len(translated) == 1:
        return translated[0][1]
    # Head noun is the last word
    head_word, head_pt = translated[-1]
    modifiers = translated[:-1]
    # Build Portuguese phrase: head_noun + adjectives (same position) + "de" + noun_modifiers
    adj_parts = [pt for w, pt in modifiers if w in _ADJ_WORDS]
    noun_parts = [pt for w, pt in modifiers if w not in _ADJ_WORDS]
    result = head_pt
    if adj_parts:
        result += " " + " ".join(adj_parts)
    if noun_parts:
        result += " de " + " de ".join(noun_parts)
    return result


# Portuguese labels for function/process stems (key = CamelCase name without
# the trailing "Function" or "Process" suffix).
_STEM_PT: dict[str, str] = {
    "Absorption":                          "absorção",
    "Accumulation":                        "acumulação",
    "Actuation":                           "atuação",
    "Agitation":                           "agitação",
    "Anode":                               "proteção anódica",
    "AxialDisplacementTransmission":       "transmissão de deslocamento axial",
    "BackflowPrevention":                  "prevenção de refluxo",
    "BinaryFlowControl":                   "controle binário de fluxo",
    "Boiling":                             "ebulição",
    "BottomHoleDrilling":                  "perfuração de fundo de poço",
    "Braking":                             "frenagem",
    "CableSupport":                        "suporte de cabos",
    "CathodicProtection":                  "proteção catódica",
    "ChromatographicAnalysis":             "análise cromatográfica",
    "CircuitProtection":                   "proteção de circuito",
    "Coalescence":                         "coalescência",
    "Combustion":                          "combustão",
    "Compression":                         "compressão",
    "Condensation":                        "condensação",
    "ConductivityTransmission":            "transmissão de condutividade",
    "Connection":                          "conexão",
    "Containment":                         "contenção",
    "Control":                             "controle",
    "Cooling":                             "resfriamento",
    "Damping":                             "amortecimento",
    "Deaeration":                          "desaeração",
    "Degassing":                           "degaseificação",
    "Dehumidification":                    "desumidificação",
    "Dehydration":                         "desidratação",
    "Demisting":                           "separação de névoa",
    "DensityMeasurement":                  "medição de densidade",
    "Detection":                           "detecção",
    "DewPointMeasurement":                 "medição de ponto de orvalho",
    "DifferentialPressureMeasurement":     "medição de pressão diferencial",
    "DifferentialPressureMeasurementAndTransmission": "medição e transmissão de pressão diferencial",
    "DifferentialPressureSwitching":       "chaveamento por pressão diferencial",
    "DifferentialPressureTransmission":    "transmissão de pressão diferencial",
    "Distillation":                        "destilação",
    "Diverting":                           "desvio de fluxo",
    "DrillingFluidConduction":             "condução de fluido de perfuração",
    "Drying":                              "secagem",
    "ElectricEnergyGeneration":            "geração de energia elétrica",
    "ElectricToMechanicalConversion":      "conversão elétrico-mecânica",
    "ElectricalCircuitControl":            "controle de circuito elétrico",
    "ElectricalConduction":                "condução elétrica",
    "ElectricalConnection":                "conexão elétrica",
    "ElectricalCurrentInterruption":       "interrupção de corrente elétrica",
    "ElectricalPowerTransformation":       "transformação de energia elétrica",
    "ElectrochemicalOxidation":            "oxidação eletroquímica",
    "EmergencyShutDown":                   "parada de emergência",
    "Enclosure":                           "proteção e invólucro",
    "EnergyDiffusion":                     "difusão de energia",
    "EnergyExtraction":                    "extração de energia",
    "EnergyTransfer":                      "transferência de energia",
    "EquipmentSupport":                    "suporte de equipamento",
    "Filtration":                          "filtração",
    "FiredHeating":                        "aquecimento a combustão",
    "FlameArrest":                         "contenção de chama",
    "FlameDetection":                      "detecção de chama",
    "FlashVaporization":                   "vaporização flash",
    "FlowControl":                         "controle de fluxo",
    "FlowIndication":                      "indicação de fluxo",
    "FlowMeasurement":                     "medição de fluxo",
    "FlowModification":                    "modificação de fluxo",
    "FlowRestriction":                     "restrição de fluxo",
    "FlowSignalTransmission":              "transmissão de sinal de fluxo",
    "FlowSwitching":                       "chaveamento de fluxo",
    "FluidConduction":                     "condução de fluido",
    "FluidDirection":                      "direcionamento de fluido",
    "FluidDistribution":                   "distribuição de fluido",
    "FluidTransport":                      "transporte de fluido",
    "ForceToElectricalTransduction":       "transdução força-elétrica",
    "ForceTransmission":                   "transmissão de força",
    "GasAbsorption":                       "absorção de gás",
    "GasDetection":                        "detecção de gás",
    "GasMovement":                         "movimentação de gás",
    "GravitySeparation":                   "separação gravitacional",
    "HeatTransfer":                        "transferência de calor",
    "Heating":                             "aquecimento",
    "HumidityMeasurement":                 "medição de umidade",
    "HydraulicPumping":                    "bombeamento hidráulico",
    "Indication":                          "indicação",
    "InformationDisplay":                  "exibição de informação",
    "Injection":                           "injeção",
    "Instrumentation":                     "instrumentação",
    "Interfacing":                         "interfaceamento",
    "KnockOutSeparation":                  "separação knock-out",
    "LevelDetection":                      "detecção de nível",
    "LevelIndication":                     "indicação de nível",
    "LevelMeasurementAndTransmission":     "medição e transmissão de nível",
    "LevelSwitching":                      "chaveamento de nível",
    "MaterialProcessing":                  "processamento de material",
    "MechanicalEnergyGeneration":          "geração de energia mecânica",
    "Mixing":                              "mistura",
    "MovementCompensation":                "compensação de movimentação",
    "MultiServiceTransmission":            "transmissão de múltiplos serviços",
    "NoiseSilencing":                      "silenciamento de ruído",
    "PhaseSequenceMeasurement":            "medição de sequência de fases",
    "PigLaunchingAndReceiving":            "lançamento e recebimento de pig",
    "PigLaunching":                        "lançamento de pig",
    "PigReceiving":                        "recebimento de pig",
    "PipeShearing":                        "corte de tubulação",
    "PneumaticEnergyConversion":           "conversão de energia pneumática",
    "PneumaticMotor":                      "acionamento pneumático",
    "PositionLimitDetection":              "detecção de limite de posição",
    "PositionMeasurementAndTransmission":  "medição e transmissão de posição",
    "PositionTransmission":                "transmissão de posição",
    "PowerTransmission":                   "transmissão de potência",
    "PressureContainment":                 "contenção de pressão",
    "PressureIndicatingAndTransmission":   "indicação e transmissão de pressão",
    "PressureMeasurement":                 "medição de pressão",
    "PressureReduction":                   "redução de pressão",
    "PressureRelief":                      "alívio de pressão",
    "PressureSensing":                     "sensoriamento de pressão",
    "PressureSignalTransmission":          "transmissão de sinal de pressão",
    "PressureTransmission":                "transmissão de pressão",
    "ProcessControlledFlow":               "controle de fluxo de processo",
    "Pumping":                             "bombeamento",
    "RapidDepressurization":               "despressurização rápida",
    "ReactiveHeating":                     "aquecimento reativo",
    "Reboiling":                           "refervimento",
    "RotationalEnergyTransfer":            "transferência de energia rotacional",
    "SafetyRelief":                        "alívio de segurança",
    "SafetyVenting":                       "ventilação de segurança",
    "Scraping":                            "raspagem",
    "Sealing":                             "vedação",
    "Separation":                          "separação",
    "Shaking":                             "agitação mecânica",
    "SignalRelay":                         "retransmissão de sinal",
    "SignalTransmission":                  "transmissão de sinal",
    "SolidBulkStorage":                    "armazenamento de sólidos a granel",
    "SolidStorageAndDispensing":           "armazenamento e distribuição de sólidos",
    "Spacing":                             "espaçamento",
    "StationaryMachineComponent":          "componente estacionário de máquina",
    "Storage":                             "armazenamento",
    "StructuralSupport":                   "suporte estrutural",
    "SubsurfaceAccess":                    "acesso subsuperficial",
    "SubsurfaceResourceInteraction":       "interação com recursos subsuperficiais",
    "SubsurfaceSafety":                    "segurança subsuperficial",
    "Support":                             "suporte",
    "Supporting":                          "suporte",
    "TemperatureIndication":               "indicação de temperatura",
    "TemperatureMeasurement":              "medição de temperatura",
    "TemperatureMeasurementAndTransmission": "medição e transmissão de temperatura",
    "TemperatureSensing":                  "sensoriamento de temperatura",
    "TemperatureSensorProtection":         "proteção de sensor de temperatura",
    "ThermalExpansionAccommodation":       "acomodação de expansão térmica",
    "ThreePhaseSeparation":               "separação trifásica",
    "Transduction":                        "transdução",
    "TubingSupportAndConnection":          "suporte e conexão de coluna de produção",
    "TubingSupport":                       "suporte de coluna de produção",
    "TurbomachineryPowerGeneration":       "geração de energia por turbomáquina",
    "UninterruptedPowerSupply":            "fornecimento ininterrupto de energia",
    "VibrationMeasurementAndTransmission": "medição e transmissão de vibração",
    "VibrationTransmission":               "transmissão de vibração",
    "VisualInspection":                    "inspeção visual",
    "WasteCombustion":                     "combustão de resíduos",
    "WasteGasBurning":                     "queima de gás residual",
    "WasteGasDisposal":                    "descarte de gás residual",
    "WellFluidControl":                    "controle de fluido de poço",
    "WellSurfaceControl":                  "controle de superfície do poço",
    "WirelineLogging":                     "perfilagem por wireline",
    # --- newest batch (proposed entries) ---
    "Aeration":                            "aeração",
    "Conversion":                          "conversão",
    "Conveying":                           "transporte de material",
    "Evaporation":                         "evaporação",
    "FlueGasExhaustion":                   "exaustão de gases de combustão",
    "GaugeMeasurement":                    "medição por indicador local",
    "Ignition":                            "ignição",
    "Lifting":                             "elevação de carga",
    "LiveWellToolDeployment":              "introdução de ferramentas em poço vivo",
}


def _func_label_pt(name: str) -> str | None:
    """Return a pt-br rdfs:label for a function class, or None if not known."""
    stem = name.removesuffix("Function")
    pt = _STEM_PT.get(stem)
    return f"função de {pt}" if pt else None


def _proc_label_pt(name: str) -> str | None:
    """Return a pt-br rdfs:label for a process class, or None if not known."""
    stem = name.removesuffix("Process")
    pt = _STEM_PT.get(stem)
    return f"processo de {pt}" if pt else None


def _fol_annotations_suppressed(e: dict) -> bool:
    """ODR-020 §5: entries carrying a `fol_stale` divergence flag have their stored
    fol_axiom / semiformal_axiom SUPPRESSED from emission until the FOL regeneration
    pass (debt-(c)) clears the flag. After participant migration the stored text still
    names participants the migration removed, so it is provably false; in a released
    artifact an *absent* annotation is safer than a *false* one. This is an
    emission-time guard only — it does not alter the stored text."""
    raw = e.get("divergence_flags")
    if not raw:
        return False
    try:
        flags = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return False
    return any(isinstance(f, dict) and f.get("type") == "fol_stale"
               for f in (flags or []))


def generate_turtle(enrichment_id: int) -> str:
    """
    Generate OWL/Turtle axioms from a validated enrichment proposal.
    """
    conn = get_enrichment_db()
    row = conn.execute("SELECT * FROM enrichment WHERE id = ?", (enrichment_id,)).fetchone()
    conn.close()

    if not row:
        raise ValueError(f"Enrichment {enrichment_id} not found")

    e = dict(row)
    label = e["cluster_label"]
    cls_name = _to_pascal_case(label)
    func_name = e["function_name"] or f"{cls_name}Function"
    proc_name = e["process_name"] or f"{cls_name}Process"
    genus_name = e["genus"] or "MaterialArtifact"
    # genus_bfo_root: the BFO/IOF-Core root (Assembly/MaterialArtifact/EngineeredSystem/Site/…).
    # Falls back to genus itself for old rows where genus was always a root class.
    _BFO_ROOTS = {"Assembly", "MaterialArtifact", "EngineeredSystem",
                  "Site", "Object", "ObjectAggregate", "FiatObjectPart"}
    # BFO Site and Object branches use bfo: prefix directly; IOF-Core roots use iof-core:
    _BFO_DIRECT = {"Site", "Object", "ObjectAggregate", "FiatObjectPart"}
    _BFO_IRIS = {
        "Site":           "bfo:BFO_0000029",
        "Object":         "bfo:BFO_0000030",
        "ObjectAggregate":"bfo:BFO_0000027",
        "FiatObjectPart": "bfo:BFO_0000024",
    }
    genus_bfo_root = e.get("genus_bfo_root") or (
        genus_name if genus_name in _BFO_ROOTS else "MaterialArtifact"
    )
    _is_site = genus_bfo_root == "Site"
    # IRI: BFO direct classes use bfo: IRI; IOF-Core roots use iof-core:; others use ":"
    if genus_name in _BFO_DIRECT:
        genus_iri = _BFO_IRIS[genus_name]
    elif genus_name in _BFO_ROOTS:
        genus_iri = f"iof-core:{genus_name}"
    else:
        genus_iri = f":{_to_pascal_case(genus_name)}"
    parts = json.loads(e["necessary_parts"]) if e["necessary_parts"] else []
    axiom_mode = e["axiom_mode"] or "necessary"
    disjoint = json.loads(e["disjoint_with"]) if e["disjoint_with"] else []
    signature = json.loads(e["process_signature"]) if e["process_signature"] else {}

    ttl = _turtle_prefixes()

    # Ontology header
    _scope_ttl = "".join(
        f'    skos:scopeNote "{_safe_ttl(n)}"@{lang} ;\n'
        for n, lang in COPI_SCOPE_NOTES
    )
    _contributor_ttl = "".join(
        f'    dcterms:contributor "{c}" ;\n'
        for c in COPI_CONTRIBUTORS
    )
    ttl += f"""### COPI — Core Ontology for Petroleum Installations
### Class module: {cls_name}
<{COPI_IRI}>
    rdf:type owl:Ontology ;
    dcterms:title "Core Ontology for Petroleum Installations (COPI)"@en ;
    dcterms:title "Ontologia Core para Instalações de Petróleo (COPI)"@pt-br ;
    dcterms:description "BFO/IOF-Core conformant ontology of equipment classes for petroleum production plants, developed using the five-step RDL enrichment method."@en ;
{_scope_ttl}    owl:versionInfo "{COPI_VERSION}" ;
    owl:imports <https://spec.industrialontologies.org/ontology/core/Core/> ;
    owl:imports <http://purl.obolibrary.org/obo/bfo/2020/bfo.owl> ;
    dcterms:creator "{COPI_AUTHOR}"@en ;
{_contributor_ttl}    dcterms:isPartOf <https://inf.ufrgs.br/projetos/{COPI_PROJECT}> ;
    dcterms:publisher "{COPI_PUBLISHER}"@en ;
    dcterms:license <https://creativecommons.org/licenses/by/4.0/> ;
    dcterms:created "2026-04-08"^^xsd:date ;
    dcterms:modified "{datetime.now().strftime('%Y-%m-%d')}"^^xsd:date ;
    apv:GlobalMinLanguageCoverage "en pt-br" ;
    apv:ClassURIFormationRule "https://www[.]inf[.]ufrgs[.]br/ontologies/copi/(COPI_[0-9]{{7}}|[A-Z][A-Za-z0-9]*)" ;
    apv:ClassMinAnnotationCoverage "rdfs:label https://spec.industrialontologies.org/ontology/annotation/naturalLanguageDefinition" .

iof-av:naturalLanguageDefinition rdf:type owl:AnnotationProperty ;
    apv:MinAnnotationLength 20 .

"""

    # Site is a bfo:ImmaterialEntity — no identity-giving function or planned process.
    # Parse function_nl_definition and process_nl_definition from the stored LLM response.
    _raw_proposal = {}
    try:
        _raw_proposal = json.loads(e.get("llm_raw_response") or "{}") or {}
    except (json.JSONDecodeError, TypeError):
        pass
    _step1_raw = _raw_proposal.get("step1_function", {}) if isinstance(_raw_proposal, dict) else {}
    _func_def_en, _func_def_pt = _function_definitions(e)
    _proc_def_en = (_step1_raw.get("process_nl_definition") or "").strip()

    if not _is_site:
        # ── function_parent: direct superclass; iof-core:DesignedFunction as fallback ──
        _fp_name = _to_pascal_case(e.get("function_parent") or "") or "DesignedFunction"
        if _fp_name in _BFO_DIRECT:
            _fp_iri = _BFO_IRIS[_fp_name]
        elif _fp_name in _BFO_ROOTS or _fp_name == "DesignedFunction":
            _fp_iri = f"iof-core:{_fp_name}"
        else:
            _fp_iri = f":{_fp_name}"

        # Function class
        ttl += f"### Identity-giving function\n"
        ttl += f":{func_name} rdf:type owl:Class ;\n"
        ttl += f"    rdfs:subClassOf {_fp_iri} ;\n"
        ttl += f"    rdfs:subClassOf [\n"
        ttl += f"        rdf:type owl:Restriction ;\n"
        ttl += f"        owl:onProperty bfo:BFO_0000054 ;  # realizedIn\n"
        ttl += f"        owl:allValuesFrom :{proc_name}\n"
        ttl += f"    ] ;\n"
        ttl += f"    rdfs:subClassOf [\n"
        ttl += f"        rdf:type owl:Restriction ;\n"
        ttl += f"        owl:onProperty bfo:BFO_0000054 ;  # realizedIn\n"
        ttl += f"        owl:someValuesFrom :{proc_name}\n"
        ttl += f"    ] ;\n"
        ttl += f'    rdfs:label "{_to_label(func_name)}"@en'
        ttl += _class_annotation_ttl(func_name, _func_label_pt(func_name), _func_def_en, _func_def_pt)
        ttl += " .\n\n"

        # Stub for local function parent (no-op in combined TTL when parent has its own enrichment)
        if not _fp_iri.startswith("iof-core:") and not _fp_iri.startswith("bfo:"):
            ttl += f":{_fp_name} rdf:type owl:Class{_class_annotation_ttl(_fp_name, _func_label_pt(_fp_name))} .\n\n"

        # ── process_parent: direct superclass; iof-core:PlannedProcess as fallback ──
        _pp_name = _to_pascal_case(e.get("process_parent") or "") or "PlannedProcess"
        if _pp_name == "PlannedProcess":
            _pp_iri = "iof-core:PlannedProcess"
        elif _pp_name in _BFO_DIRECT:
            _pp_iri = _BFO_IRIS[_pp_name]
        elif _pp_name in _BFO_ROOTS:
            _pp_iri = f"iof-core:{_pp_name}"
        else:
            _pp_iri = f":{_pp_name}"

        # Process class
        ttl += f"### Process type\n"
        ttl += f":{proc_name} rdf:type owl:Class ;\n"
        ttl += f"    rdfs:subClassOf {_pp_iri} ;\n"
        ttl += f'    rdfs:label "{_to_label(proc_name)}"@en'
        ttl += _class_annotation_ttl(proc_name, _proc_label_pt(proc_name), _proc_def_en)
        ttl += " .\n\n"

        # Stub for local process parent
        if not _pp_iri.startswith("iof-core:") and not _pp_iri.startswith("bfo:"):
            ttl += f":{_pp_name} rdf:type owl:Class{_class_annotation_ttl(_pp_name, _proc_label_pt(_pp_name))} .\n\n"

    # Add input/output restrictions to process if signature exists
    inputs = signature.get("inputs", [])
    outputs = signature.get("outputs", [])
    if inputs or outputs and not _is_site:
        restrictions = []
        for inp in inputs:
            inp_type = _to_pascal_case(inp.get("type", "Continuant"))
            restrictions.append(f"""    rdfs:subClassOf [
        rdf:type owl:Restriction ;
        owl:onProperty iof-core:hasInput ;
        owl:someValuesFrom :{inp_type}
    ]""")
        for out in outputs:
            out_type = _to_pascal_case(out.get("type", "Continuant"))
            restrictions.append(f"""    rdfs:subClassOf [
        rdf:type owl:Restriction ;
        owl:onProperty iof-core:hasOutput ;
        owl:someValuesFrom :{out_type}
    ]""")

        if restrictions:
            # Reopen the process class to add restrictions
            ttl += f":{proc_name}\n" + " ;\n".join(restrictions) + " .\n\n"

        # Participant types are only referenced above; the ones that are not
        # copi-vocab classes get their annotations from class_annotation here.
        # Annotation triples only -- declaring the class here would bypass the
        # anchoring the publish pipeline gives referenced participant types.
        for _pt in sorted({_to_pascal_case(x.get("type", "")) for x in inputs + outputs}):
            _pt_ann = _class_annotation_ttl(_pt) if _pt and _lookup_class_annotation(_pt) else ""
            if _pt_ann:
                ttl += f":{_pt}\n    " + _pt_ann.removeprefix(" ;\n    ") + " .\n\n"

    # Equipment universal
    subsumption_op = "owl:equivalentClass" if axiom_mode == "equivalent" else "rdfs:subClassOf"

    # EngineeredSystem ⊑ bfo:ObjectAggregate (collection of interacting Objects,
    # no single causal boundary). Uses bearerOf (BFO_0000196) per IOF-Core definition.
    # MaterialArtifact/Assembly ⊑ bfo:Object (causally unified). Uses hasFunction.
    # These branches are disjoint in BFO — a concept cannot be both.
    # Site is a bfo:ImmaterialEntity — it does not bear designed functions in the BFO sense.
    # Object/ObjectAggregate/FiatObjectPart: use appropriate property.
    if not _is_site:
        if genus_bfo_root in ("EngineeredSystem", "ObjectAggregate"):
            function_restriction = f"""[
        rdf:type owl:Restriction ;
        owl:onProperty bfo:BFO_0000196 ;  # bearerOf — ObjectAggregate branch
        owl:someValuesFrom :{func_name}
    ]"""
        else:
            function_restriction = f"""[
        rdf:type owl:Restriction ;
        owl:onProperty iof-core:hasFunction ;  # Object branch (MaterialArtifact/Assembly/Object/FiatObjectPart)
        owl:someValuesFrom :{func_name}
    ]"""

    # Build the class expression
    conjuncts = [genus_iri]
    if not _is_site:
        conjuncts.append(function_restriction)

    for part in parts:
        if not part.get("name"):
            continue
        if not part.get("source_quote"):
            continue
        part_name = _to_pascal_case(part["name"])
        relation = part.get("relation", "hasComponentPartAtAllTimes")
        conjuncts.append(f"""[
        rdf:type owl:Restriction ;
        owl:onProperty iof-core:{relation} ;
        owl:someValuesFrom :{part_name}
    ]""")

    ttl += f"""### Equipment universal: {cls_name}
:{cls_name} rdf:type owl:Class ;
"""

    if axiom_mode == "equivalent":
        ttl += f"    owl:equivalentClass [\n"
        ttl += f"        rdf:type owl:Class ;\n"
        ttl += f"        owl:intersectionOf (\n"
        for c in conjuncts:
            ttl += f"            {c}\n"
        ttl += f"        )\n"
        ttl += f"    ] ;\n"
    else:
        for c in conjuncts:
            ttl += f"    rdfs:subClassOf {c} ;\n"

    # Additional asserted parents from additional_parents table.
    # These are explicit ODR-mandated superclasses beyond the genus (e.g. ControlValve ⊑ iof:Assembly
    # per ODR-013). genus_bfo_root is NOT emitted here — it remains display-only metadata.
    _ap_conn = get_enrichment_db()
    _ap_rows = _ap_conn.execute(
        "SELECT parent_iri FROM additional_parents WHERE cluster_label = ? ORDER BY id",
        (label,)
    ).fetchall()
    _ap_conn.close()
    for _ap in _ap_rows:
        ttl += f"    rdfs:subClassOf <{_ap['parent_iri']}> ;\n"

    # Annotations
    ttl += f'    rdfs:label "{_to_label(cls_name)}"@en ;\n'
    if e.get("label_pt"):
        ttl += f'    rdfs:label "{_safe_ttl(e["label_pt"])}"@pt-br ;\n'

    if e.get("nl_definition_en"):
        ttl += f'    iof-av:naturalLanguageDefinition "{_safe_ttl(e["nl_definition_en"])}"@en ;\n'
        ttl += f'    skos:definition "{_safe_ttl(e["nl_definition_en"])}"@en ;\n'

    if e.get("nl_definition_pt"):
        ttl += f'    iof-av:naturalLanguageDefinition "{_safe_ttl(e["nl_definition_pt"])}"@pt-br ;\n'

    # ODR-020 §5: suppress fol_stale annotations (provably-false until regenerated)
    _fol_ok = not _fol_annotations_suppressed(e)
    if _fol_ok and e.get("semiformal_axiom"):
        ttl += f'    iof-av:semiFormalNaturalLanguageAxiom "{_safe_ttl(e["semiformal_axiom"])}"@en ;\n'

    if _fol_ok and e.get("fol_axiom"):
        ttl += f'    iof-av:firstOrderLogicAxiom "{_safe_ttl(e["fol_axiom"])}"@en ;\n'

    if axiom_mode == "necessary":
        ttl += f'    iof-av:isPrimitive "true"^^xsd:boolean ;\n'
        if e.get("primitive_rationale"):
            ttl += f'    iof-av:primitiveRationale "{_safe_ttl(e["primitive_rationale"])}"@en ;\n'

    # Alternative labels
    alt_labels = json.loads(e["alt_labels"]) if e.get("alt_labels") else []
    for lbl in alt_labels:
        lbl = lbl.strip()
        if lbl:
            lang = "pt" if any(c in lbl for c in "ãâçéêíõôúàáü") else "en"
            ttl += f'    skos:altLabel "{lbl}"@{lang} ;\n'

    # Quality restrictions (bearerOf each selected quality)
    #
    # The field is written in two shapes in practice: the documented dict form
    # ({"name": ..., "definition": ..., "unit": ...}) and a bare string form
    # (["ElectricalCurrent"]). Every record that reached the DB uses the string
    # form, which used to raise AttributeError here ('str' has no attribute
    # 'get'); the combined generator swallowed it and published the class as a
    # label-only stub with no function restriction at all. Normalize instead of
    # assuming a shape.
    qualities = _normalize_qualities(e["qualities"] if e.get("qualities") else None)
    for q in qualities:
        q_name = _to_pascal_case(q.get("name", "Quality"))
        ttl += f"""    rdfs:subClassOf [
        rdf:type owl:Restriction ;
        owl:onProperty bfo:BFO_0000086 ;  # has quality
        owl:someValuesFrom :{q_name}
    ] ;\n"""

    # Custom axioms (user-defined restrictions, appended verbatim)
    custom_axioms = json.loads(e["custom_axioms"]) if e.get("custom_axioms") else []
    for ax in custom_axioms:
        turtle_block = (ax.get("turtle") or "").strip()
        if turtle_block:
            ttl += f"    {turtle_block} ;\n"

    # Source definitions from industrial standards, minus reviewer exclusions
    # (homonyms, corrupted source text). The standards are copyrighted, so the
    # class links to each source definition instead of reproducing its text.
    # ISO 15926-4 item IRIs are the official identifiers from the ISO RDL
    # spreadsheets; they identify the item but do not all dereference.
    source_defs = _filter_excluded_definitions(
        get_cluster_definitions(label), e.get("excluded_definition_ids")
    )
    _source_links: list[str] = []
    for d in source_defs:
        link = _source_link_ttl(d.get("source_uri"))
        if link and link not in _source_links:
            _source_links.append(link)
    for link in _source_links:
        ttl += f"    dcterms:source {link} ;\n"

    ttl = ttl.rstrip(" ;\n") + " .\n\n"

    # Part classes (stubs) — look up DB label first to stay consistent with
    # classes that have their own enrichment entries.
    _part_label_conn = get_enrichment_db()
    for part in parts:
        if not part.get("name"):
            continue
        if not part.get("source_quote"):
            continue
        part_name = _to_pascal_case(part["name"])
        part_parent = part.get("parent", "MaterialArtifact")
        if ":" in part_parent:
            parent_iri = part_parent  # already a full IRI or prefixed
        elif part_parent in _BFO_DIRECT:
            parent_iri = _BFO_IRIS[part_parent]
        elif part_parent in _BFO_ROOTS:
            parent_iri = f"iof-core:{part_parent}"
        else:
            parent_iri = f":{_to_pascal_case(part_parent)}"
        _part_db_row = _part_label_conn.execute(
            "SELECT label_pt FROM enrichment WHERE cluster_label = ? LIMIT 1",
            (_to_label(part_name),)
        ).fetchone()
        _part_pt = (
            (_part_db_row["label_pt"] if _part_db_row and _part_db_row["label_pt"] else None)
            or _stub_label_pt_fn(part_name)
        )
        ttl += (
            f":{part_name} rdf:type owl:Class ;\n"
            f"    rdfs:subClassOf {parent_iri} ;\n"
            f'    rdfs:label "{_to_label(part_name)}"@en'
            f"{_class_annotation_ttl(part_name, _part_pt)} .\n\n"
        )
    _part_label_conn.close()

    # Quality classes (stubs)
    for q in qualities:
        q_name  = _to_pascal_case(q.get("name", "Quality"))
        q_label = q.get("name", "quality").lower()
        q_def   = (q.get("definition") or "").replace('"', '\\"')
        q_unit  = q.get("unit", "")
        _q_pt = _stub_label_pt_fn(q_name)
        ttl += (
            f":{q_name} rdf:type owl:Class ;\n"
            f"    rdfs:subClassOf bfo:BFO_0000019 ;  # Quality\n"
            f"    rdfs:subClassOf [\n"
            f"        rdf:type owl:Restriction ;\n"
            f"        owl:onProperty bfo:BFO_0000052 ;  # inheres in\n"
            f"        owl:someValuesFrom :{cls_name}\n"
            f"    ] ;\n"
        )
        if _q_pt:
            ttl += f'    rdfs:label "{_q_pt}"@pt-br ;\n'
        ttl += f'    rdfs:label "{q_label}"@en'
        if q_def:
            ttl += f' ;\n    iof-av:naturalLanguageDefinition "{q_def}"@en'
        if q_unit:
            ttl += f' ;\n    rdfs:comment "Unit: {q_unit}"'
        ttl += " .\n\n"

    # Disjointness axioms
    if disjoint:
        for other in disjoint:
            other_cls = _to_pascal_case(other)
            ttl += f"""# Disjointness: {cls_name} and {other_cls}
[] rdf:type owl:AllDisjointClasses ;
    owl:members ( :{cls_name} :{other_cls} ) .

"""

    return ttl


# ---------------------------------------------------------------------------
# Retrieval helpers
# ---------------------------------------------------------------------------

def list_enrichments(status: str | None = None, deduplicate: bool = False) -> list[dict]:
    """List enrichment proposals, optionally filtered by status.

    When deduplicate=True, returns only one row per cluster_label: the
    'exported' one if it exists, otherwise the most recently updated one.
    """
    conn = get_enrichment_db()
    if status:
        rows = conn.execute(
            "SELECT id, cluster_label, status, axiom_mode, genus, genus_bfo_root, function_name, nl_definition_pt, label_pt, created_at, updated_at, input_tokens, output_tokens, estimated_cost_usd, secondary_coverage, primary_definition_conflict "
            "FROM enrichment WHERE status = ? ORDER BY updated_at DESC", (status,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, cluster_label, status, axiom_mode, genus, genus_bfo_root, function_name, nl_definition_pt, label_pt, created_at, updated_at, input_tokens, output_tokens, estimated_cost_usd, secondary_coverage, primary_definition_conflict "
            "FROM enrichment ORDER BY updated_at DESC"
        ).fetchall()
    conn.close()
    all_rows = [dict(r) for r in rows]
    if not deduplicate:
        return all_rows

    # Keep one per cluster_label: prefer 'exported', then most recent (already sorted DESC)
    STATUS_PRIORITY = {"exported": 0, "validated": 1, "reviewed": 2, "proposed": 3}
    seen: dict[str, dict] = {}
    for row in all_rows:
        label = row["cluster_label"]
        if label not in seen:
            seen[label] = row
        else:
            existing = seen[label]
            if STATUS_PRIORITY.get(row["status"], 9) < STATUS_PRIORITY.get(existing["status"], 9):
                seen[label] = row
    return list(seen.values())


def get_enrichment(enrichment_id: int) -> dict | None:
    """Get full enrichment proposal by ID."""
    conn = get_enrichment_db()
    row = conn.execute("SELECT * FROM enrichment WHERE id = ?", (enrichment_id,)).fetchone()
    conn.close()
    if row:
        result = dict(row)
        # Parse JSON fields
        for field in ["necessary_parts", "candidate_parts", "process_signature", "disjoint_with",
                       "cross_standard_links", "source_definitions_used", "expert_review",
                       "llm_raw_response", "excluded_definition_ids", "core_operation_gap"]:
            if result.get(field):
                try:
                    result[field] = json.loads(result[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        return result
    return None


_ENRICHMENT_UPDATABLE_COLS: frozenset[str] = frozenset({
    "status", "axiom_mode", "genus", "genus_bfo_root", "genus_rationale",
    "function_name", "process_name", "function_rationale",
    "function_parent", "function_parent_enriched",
    "differentia_expression", "differentia_nl", "differentia_rationale",
    "necessary_parts", "parts_rationale",
    "process_signature", "signature_rationale",
    "primitive_rationale", "disjoint_with", "disjointness_rationale",
    "cross_standard_notes", "cross_standard_links",
    "divergence_flags", "divergence_case_id",
    "reviewer_notes", "expert_review", "expert_reviewer", "expert_status",
    "label_en", "label_pt", "nl_definition_en", "nl_definition_pt",
    "semiformal_axiom", "fol_axiom",
    "symbol_path", "alt_labels", "qualities", "custom_axioms",
    "excluded_definition_ids",
    "updated_at", "copi_id", "scope",
    "last_edited_by", "last_edited_at",
    "second_reviewer", "second_reviewer_notes",
    "secondary_coverage", "primary_definition_conflict", "core_operation_gap",
})


def update_enrichment(enrichment_id: int, updates: dict) -> bool:
    """Update an enrichment proposal (for human validation edits)."""
    unknown = set(updates.keys()) - _ENRICHMENT_UPDATABLE_COLS
    if unknown:
        raise ValueError(f"update_enrichment: unknown column(s): {sorted(unknown)}")

    # "cross_standard_notes" is the LLM response key; there is no such column --
    # the insert path stores it in cross_standard_links, so updates do the same.
    if "cross_standard_notes" in updates:
        if "cross_standard_links" in updates:
            raise ValueError(
                "update_enrichment: pass either cross_standard_notes or "
                "cross_standard_links, not both (they are the same column)"
            )
        updates["cross_standard_links"] = json.dumps(updates.pop("cross_standard_notes"))

    conn = get_enrichment_db(actor="update_enrichment")

    # Serialize JSON fields
    for field in ["necessary_parts", "process_signature", "disjoint_with",
                   "cross_standard_links", "expert_review",
                   "alt_labels", "qualities", "custom_axioms"]:
        if field in updates and isinstance(updates[field], (list, dict)):
            updates[field] = json.dumps(updates[field])

    updates["updated_at"] = datetime.now().isoformat()

    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    values = list(updates.values()) + [enrichment_id]

    conn.execute(f"UPDATE enrichment SET {set_clause} WHERE id = ?", values)
    _clear_write_actor(conn)
    conn.commit()
    conn.close()
    return True


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def get_existing_ontology_context(include_proposed: bool = True) -> list[dict]:
    """
    Return a deduplicated summary of enriched classes (one entry per cluster_label,
    latest revision) so the LLM can reuse existing function_names and genera.

    include_proposed=True  (default): include all statuses.
    include_proposed=False: return only status='validated' entries — use when
      you want future enrichments to see only peer-reviewed concepts.

    Returns list of dicts: {cluster_label, function_name, genus, status}
    """
    conn = get_enrichment_db()
    if include_proposed:
        rows = conn.execute(
            """
            SELECT cluster_label, function_name, genus, status
              FROM enrichment
             WHERE id IN (SELECT MAX(id) FROM enrichment GROUP BY cluster_label)
             ORDER BY cluster_label
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT cluster_label, function_name, genus, status
              FROM enrichment
             WHERE id IN (SELECT MAX(id) FROM enrichment GROUP BY cluster_label)
               AND status = 'validated'
             ORDER BY cluster_label
            """
        ).fetchall()
    conn.close()
    result = [dict(r) for r in rows]
    status_counts: dict[str, int] = {}
    for r in result:
        status_counts[r["status"] or "unknown"] = status_counts.get(r["status"] or "unknown", 0) + 1
    breakdown = ", ".join(f"{s}={n}" for s, n in sorted(status_counts.items()))
    logger.info("Built existing-ontology block: %d unique clusters (%s)", len(result), breakdown)
    return result


# ---------------------------------------------------------------------------
# Relation (object/datatype property) CRUD
# ---------------------------------------------------------------------------

def list_relations(status: str | None = None) -> list[dict]:
    conn = get_enrichment_db()
    if status:
        rows = conn.execute(
            "SELECT * FROM copi_relation WHERE status = ? ORDER BY name", (status,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM copi_relation ORDER BY prop_type, name"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_relation(relation_id: int) -> dict | None:
    conn = get_enrichment_db()
    row = conn.execute("SELECT * FROM copi_relation WHERE id = ?", (relation_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_relation(data: dict) -> dict:
    conn = get_enrichment_db()
    conn.execute("""
        INSERT INTO copi_relation
            (name, label_en, label_pt, prop_type, domain, range_type,
             parent_prop, is_functional, is_symmetric, is_transitive,
             inverse_of, definition_en, definition_pt, rationale, status)
        VALUES
            (:name, :label_en, :label_pt, :prop_type, :domain, :range_type,
             :parent_prop, :is_functional, :is_symmetric, :is_transitive,
             :inverse_of, :definition_en, :definition_pt, :rationale, :status)
    """, {
        "name":          data.get("name", ""),
        "label_en":      data.get("label_en", ""),
        "label_pt":      data.get("label_pt", ""),
        "prop_type":     data.get("prop_type", "ObjectProperty"),
        "domain":        data.get("domain", ""),
        "range_type":    data.get("range_type", ""),
        "parent_prop":   data.get("parent_prop", ""),
        "is_functional": int(data.get("is_functional", 0)),
        "is_symmetric":  int(data.get("is_symmetric", 0)),
        "is_transitive": int(data.get("is_transitive", 0)),
        "inverse_of":    data.get("inverse_of", ""),
        "definition_en": data.get("definition_en", ""),
        "definition_pt": data.get("definition_pt", ""),
        "rationale":     data.get("rationale", ""),
        "status":        data.get("status", "proposed"),
    })
    row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    return get_relation(row_id)


def update_relation(relation_id: int, data: dict) -> None:
    fields = [
        "name", "label_en", "label_pt", "prop_type", "domain", "range_type",
        "parent_prop", "is_functional", "is_symmetric", "is_transitive",
        "inverse_of", "definition_en", "definition_pt", "rationale", "status",
    ]
    updates = {k: data[k] for k in fields if k in data}
    if not updates:
        return
    updates["updated_at"] = datetime.now().isoformat()
    updates["id"] = relation_id
    set_clause = ", ".join(f"{k} = :{k}" for k in updates if k != "id")
    conn = get_enrichment_db()
    conn.execute(f"UPDATE copi_relation SET {set_clause} WHERE id = :id", updates)
    conn.commit()
    conn.close()


def delete_relation(relation_id: int) -> None:
    conn = get_enrichment_db()
    conn.execute("DELETE FROM copi_relation WHERE id = ?", (relation_id,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Cluster scope
# ---------------------------------------------------------------------------

def get_out_of_scope_clusters() -> set[str]:
    """Return the set of cluster labels manually marked as out-of-scope."""
    conn = get_enrichment_db()
    rows = conn.execute(
        "SELECT cluster_label FROM cluster_scope WHERE out_of_scope = 1"
    ).fetchall()
    conn.close()
    return {row["cluster_label"] for row in rows}


def set_cluster_scope(cluster_label: str, out_of_scope: bool, reason: str = "") -> None:
    """Mark or unmark a cluster as out-of-scope."""
    conn = get_enrichment_db()
    conn.execute(
        """INSERT INTO cluster_scope (cluster_label, out_of_scope, reason, updated_at)
           VALUES (?, ?, ?, datetime('now'))
           ON CONFLICT(cluster_label) DO UPDATE SET
               out_of_scope = excluded.out_of_scope,
               reason       = excluded.reason,
               updated_at   = excluded.updated_at""",
        (cluster_label, 1 if out_of_scope else 0, reason),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Scope classification — Anthropic Message Batch
# ---------------------------------------------------------------------------

SCOPE_DEFINITION = (
    "COPI (Core Ontology for Petroleum Installations) scope: "
    "material artifacts (bfo:MaterialEntity) that (i) are part of a petroleum "
    "production plant, and (ii) bear at least one function whose realization "
    "involves the transport (e.g. production/injection lines), processing "
    "(e.g. separation, compression, heating), control, monitoring, measurement, "
    "containment or offloading of material or energy. "
    "OUT OF SCOPE: abstract quantities (wavelength, frequency, pressure as a concept), "
    "communication/IT equipment unless used for plant process control, office/building "
    "equipment, biological entities, activities, events, roles, organizations, "
    "documents, information objects, spatial locations, coding schemes, and anything "
    "not physically present in an oil & gas production plant."
)

_SCOPE_BATCH_HAIKU = "claude-haiku-4-5-20251001"


def _ensure_scope_batch_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scope_batch_submissions (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            anthropic_batch_id  TEXT UNIQUE NOT NULL,
            model               TEXT,
            request_count       INTEGER DEFAULT 0,
            label_count         INTEGER DEFAULT 0,
            status              TEXT DEFAULT 'in_progress',
            results_imported    INTEGER DEFAULT 0,
            succeeded           INTEGER DEFAULT 0,
            created_at          TEXT DEFAULT (datetime('now')),
            ended_at            TEXT
        )
    """)
    conn.commit()


async def scope_batch_submit(api_key: str, batch_size: int = 100) -> dict:
    """
    Submit all unclassified cluster labels to the Anthropic Message Batches API
    for scope classification against the COPI material-artifact scope.

    Labels are grouped into chunks of `batch_size` (default 100); each chunk
    becomes one request within a single Anthropic batch.  Uses Claude Haiku
    (cheap, fast) with the standard 50% batch discount.

    Returns {batch_id, request_count, label_count}.
    """
    # --- collect unclassified labels ---
    econn = get_enrichment_db()
    econn.row_factory = sqlite3.Row
    scoped = {r["cluster_label"].lower() for r in econn.execute(
        "SELECT cluster_label FROM cluster_scope"
    ).fetchall()}
    econn.close()

    tconn = sqlite3.connect(str(TERMS_DB_PATH))
    tconn.row_factory = sqlite3.Row
    all_labels: list[str] = [
        r["preferred_label"]
        for r in tconn.execute(
            "SELECT DISTINCT preferred_label FROM terms "
            "WHERE preferred_label IS NOT NULL ORDER BY preferred_label"
        ).fetchall()
    ]
    tconn.close()

    unclassified = [lbl for lbl in all_labels if lbl.lower() not in scoped]
    if not unclassified:
        return {"submitted": 0, "label_count": 0, "message": "All clusters already classified"}

    # --- build one request per chunk ---
    chunks = [unclassified[i:i + batch_size] for i in range(0, len(unclassified), batch_size)]
    requests_payload: list[dict] = []
    for idx, chunk in enumerate(chunks):
        items_text = "\n".join(f"{i + 1}. {lbl}" for i, lbl in enumerate(chunk))
        user_msg = (
            f"{SCOPE_DEFINITION}\n\n"
            "For each term below, reply with ONLY a JSON array where each element is "
            '{"label": "...", "in_scope": true/false, "reason": "one sentence"}.\n\n'
            f"{items_text}"
        )
        requests_payload.append({
            "custom_id": f"scope-{idx:05d}",
            "params": {
                "model": _SCOPE_BATCH_HAIKU,
                "max_tokens": 8192,
                "messages": [{"role": "user", "content": user_msg}],
            },
        })

    # --- submit to Anthropic ---
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            BATCH_API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "message-batches-2024-09-24",
                "content-type": "application/json",
            },
            json={"requests": requests_payload},
        )
        resp.raise_for_status()
        batch_data = resp.json()

    anthropic_batch_id = batch_data["id"]

    conn = get_enrichment_db()
    _ensure_scope_batch_table(conn)
    conn.execute(
        """INSERT INTO scope_batch_submissions
               (anthropic_batch_id, model, request_count, label_count, status, created_at)
           VALUES (?, ?, ?, ?, 'in_progress', datetime('now'))""",
        (anthropic_batch_id, _SCOPE_BATCH_HAIKU, len(requests_payload), len(unclassified)),
    )
    conn.commit()
    conn.close()

    logger.info(
        "Scope batch %s submitted: %d requests, %d labels",
        anthropic_batch_id, len(requests_payload), len(unclassified),
    )
    return {
        "batch_id": anthropic_batch_id,
        "request_count": len(requests_payload),
        "label_count": len(unclassified),
    }


async def scope_batch_poll(anthropic_batch_id: str, api_key: str) -> dict:
    """Check the processing status of a scope batch and update the local DB."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{BATCH_API_URL}/{anthropic_batch_id}",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "message-batches-2024-09-24",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    conn = get_enrichment_db()
    _ensure_scope_batch_table(conn)
    conn.execute(
        "UPDATE scope_batch_submissions SET status=?, ended_at=? WHERE anthropic_batch_id=?",
        (data.get("processing_status", "unknown"), data.get("ended_at"), anthropic_batch_id),
    )
    conn.commit()
    conn.close()
    return data


async def scope_batch_import(anthropic_batch_id: str, api_key: str) -> dict:
    """
    Download JSONL results from a completed scope batch and write them into
    cluster_scope.  Each result line covers up to `batch_size` labels.
    """
    async with httpx.AsyncClient(timeout=300.0) as client:
        # Get results URL from batch metadata
        meta_resp = await client.get(
            f"{BATCH_API_URL}/{anthropic_batch_id}",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "message-batches-2024-09-24",
            },
        )
        meta_resp.raise_for_status()
        meta = meta_resp.json()
        results_url = meta.get("results_url")
        if not results_url:
            raise RuntimeError("Batch not complete yet — no results_url")

        # Fetch JSONL
        res_resp = await client.get(
            results_url,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "message-batches-2024-09-24",
            },
        )
        res_resp.raise_for_status()
        content = res_resp.text

    conn = get_enrichment_db()
    _ensure_scope_batch_table(conn)

    imported = 0
    errors: list[str] = []

    for raw_line in content.strip().splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            item = json.loads(raw_line)
        except json.JSONDecodeError:
            continue

        custom_id = item.get("custom_id", "")
        result = item.get("result", {})
        if result.get("type") != "succeeded":
            errors.append(f"{custom_id}: {result.get('type', 'unknown')}")
            continue

        text = (result.get("message", {}).get("content") or [{}])[0].get("text", "")
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if not m:
            errors.append(f"{custom_id}: no JSON array in response")
            continue

        try:
            classifications = json.loads(m.group())
        except json.JSONDecodeError as exc:
            errors.append(f"{custom_id}: JSON parse error — {exc}")
            continue

        for entry in classifications:
            label = (entry.get("label") or "").strip()
            if not label:
                continue
            in_scope = bool(entry.get("in_scope", True))
            reason = entry.get("reason", "scope batch")
            conn.execute(
                """INSERT INTO cluster_scope (cluster_label, out_of_scope, reason, updated_at)
                   VALUES (?, ?, ?, datetime('now'))
                   ON CONFLICT(cluster_label) DO UPDATE SET
                       out_of_scope = excluded.out_of_scope,
                       reason       = excluded.reason,
                       updated_at   = excluded.updated_at""",
                (label, 0 if in_scope else 1, reason),
            )
            imported += 1

    conn.execute(
        "UPDATE scope_batch_submissions SET results_imported=1, succeeded=? WHERE anthropic_batch_id=?",
        (imported, anthropic_batch_id),
    )
    conn.commit()
    conn.close()

    logger.info("Scope batch %s imported: %d labels, %d errors", anthropic_batch_id, imported, len(errors))
    return {"imported": imported, "errors": errors}


def list_scope_batch_submissions() -> list[dict]:
    """Return all scope batch submissions ordered newest-first."""
    conn = get_enrichment_db()
    _ensure_scope_batch_table(conn)
    rows = conn.execute(
        "SELECT * FROM scope_batch_submissions ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def detect_aliases(threshold: float = 0.75) -> list[dict]:
    """
    Scan all cluster labels (from terms.db) against enriched cluster labels
    and insert proposed alias rows for pairs above the similarity threshold.

    Uses difflib.SequenceMatcher for fast in-process similarity.
    Skips pairs that are identical or already in cluster_alias.
    Returns list of newly inserted alias dicts.
    """
    import difflib

    econn = get_enrichment_db()
    tconn = get_terms_db()

    # All enriched cluster labels (status validated or exported preferred, but any)
    enriched_rows = econn.execute(
        "SELECT DISTINCT cluster_label FROM enrichment ORDER BY cluster_label"
    ).fetchall()
    enriched_labels = [r["cluster_label"] for r in enriched_rows]

    # All cluster labels from terms.db
    all_labels = [r["preferred_label"] for r in tconn.execute(
        "SELECT DISTINCT preferred_label FROM terms WHERE preferred_label IS NOT NULL"
    ).fetchall()]
    tconn.close()

    # Existing alias pairs (to avoid duplicates)
    existing = {
        (r["source_label"], r["target_label"])
        for r in econn.execute("SELECT source_label, target_label FROM cluster_alias").fetchall()
    }

    inserted = []
    for src in all_labels:
        src_norm = src.lower().strip()
        for tgt in enriched_labels:
            if src == tgt:
                continue
            tgt_norm = tgt.lower().strip()
            if (src, tgt) in existing:
                continue
            score = difflib.SequenceMatcher(None, src_norm, tgt_norm).ratio()
            if score >= threshold:
                try:
                    econn.execute(
                        """INSERT OR IGNORE INTO cluster_alias
                           (source_label, target_label, relation_type, confidence, detected_by, status)
                           VALUES (?, ?, 'exactMatch', ?, 'label_sim', 'proposed')""",
                        (src, tgt, round(score, 3)),
                    )
                    inserted.append({"source_label": src, "target_label": tgt, "confidence": round(score, 3)})
                except Exception:
                    pass
    econn.commit()
    econn.close()
    return inserted


def list_aliases(status: str | None = None) -> list[dict]:
    """Return cluster_alias rows with optional status filter, newest first."""
    conn = get_enrichment_db()
    if status:
        rows = conn.execute(
            "SELECT * FROM cluster_alias WHERE status = ? ORDER BY confidence DESC, id DESC",
            (status,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM cluster_alias ORDER BY confidence DESC, id DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_alias(alias_id: int, status: str, notes: str | None = None) -> bool:
    """Accept or reject an alias proposal."""
    conn = get_enrichment_db()
    conn.execute(
        "UPDATE cluster_alias SET status = ?, notes = COALESCE(?, notes), updated_at = datetime('now') WHERE id = ?",
        (status, notes, alias_id),
    )
    conn.commit()
    changes = conn.total_changes
    conn.close()
    return changes > 0


def create_alias(source_label: str, target_label: str, relation_type: str = "exactMatch",
                 notes: str | None = None) -> int:
    """Manually create an alias mapping."""
    conn = get_enrichment_db()
    conn.execute(
        """INSERT OR REPLACE INTO cluster_alias
           (source_label, target_label, relation_type, confidence, detected_by, status, notes)
           VALUES (?, ?, ?, 1.0, 'manual', 'proposed', ?)""",
        (source_label, target_label, relation_type, notes),
    )
    conn.commit()
    row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return row_id


def generate_combined_turtle() -> str:
    """
    Merge all validated or exported enrichments into a single Turtle file.
    Strips per-class ontology headers (keeps only the first), then concatenates
    the class axioms from each enrichment.
    """
    conn = get_enrichment_db()
    rows = conn.execute(
        "SELECT id, cluster_label, deprecated_in_favor_of "
        "FROM enrichment WHERE status IN ('validated', 'exported') ORDER BY cluster_label"
    ).fetchall()
    conn.close()

    if not rows:
        return "# No validated or exported enrichments found.\n"

    # ODR-022 §15: entries merged into another universal emit nothing at all. COPI has no
    # external consumers yet, so the merged-away class is removed outright rather than kept
    # as an owl:deprecated redirect — a stanza no one would follow is just clutter. Every
    # reference to it is repointed to the canonical class by
    # scripts/migrations/odr022_merge_duplicate_classes.py, and copi-iri-map.tsv sends its
    # readable name to the canonical numeric IRI so nothing dangles.
    merged = {r["id"] for r in rows if r["deprecated_in_favor_of"]}

    combined = ""
    header_written = False
    for row in rows:
        if row["id"] in merged:
            continue
        try:
            ttl = generate_turtle(row["id"])
        except Exception as e:
            combined += f"# Error generating Turtle for id={row['id']}: {e}\n\n"
            continue

        if not header_written:
            combined += ttl
            header_written = True
        else:
            # Strip prefix declarations and ontology header (everything up to first ###)
            idx = ttl.find("\n### ")
            if idx != -1:
                combined += ttl[idx + 1:]  # skip leading newline
            else:
                combined += ttl

    # Append validated/exported relations (object/datatype properties)
    relations = list_relations()
    validated_rels = [r for r in relations if r["status"] in ("validated", "exported")]
    if validated_rels:
        combined += "\n# ── Object / Datatype Properties ──────────────────────────────────\n\n"
        for rel in validated_rels:
            prop_type = rel["prop_type"] or "ObjectProperty"
            combined += f"copi:{rel['name']} rdf:type owl:{prop_type}"
            if rel.get("parent_prop"):
                pp = rel["parent_prop"]
                if ":" not in pp:
                    pp = f"copi:{pp}"
                combined += f" ;\n    rdfs:subPropertyOf {pp}"
            if rel.get("domain"):
                dom = rel["domain"]
                dom_iri = f"iof-core:{dom}" if dom in {"EngineeredSystem","MaterialArtifact","Assembly"} else f"copi:{_to_pascal_case(dom)}"
                combined += f" ;\n    rdfs:domain {dom_iri}"
            if rel.get("range_type"):
                rng = rel["range_type"]
                if rng.startswith("xsd:") or rng.startswith("rdfs:"):
                    rng_iri = rng
                elif ":" in rng:
                    rng_iri = rng
                else:
                    rng_iri = f"copi:{_to_pascal_case(rng)}"
                combined += f" ;\n    rdfs:range {rng_iri}"
            if rel.get("is_functional"):
                combined += f" ;\n    rdf:type owl:FunctionalProperty"
            if rel.get("is_symmetric"):
                combined += f" ;\n    rdf:type owl:SymmetricProperty"
            if rel.get("is_transitive"):
                combined += f" ;\n    rdf:type owl:TransitiveProperty"
            if rel.get("inverse_of"):
                combined += f" ;\n    owl:inverseOf copi:{rel['inverse_of']}"
            if rel.get("label_en"):
                combined += f' ;\n    rdfs:label "{rel["label_en"]}"@en'
            if rel.get("label_pt"):
                combined += f' ;\n    rdfs:label "{rel["label_pt"]}"@pt-br'
            if rel.get("definition_en"):
                safe = rel["definition_en"].replace('"', '\\"')
                combined += f' ;\n    iof-av:naturalLanguageDefinition "{safe}"@en'
            combined += " .\n\n"

    # Emit accepted alias axioms
    alias_conn = get_enrichment_db()
    accepted_aliases = alias_conn.execute(
        "SELECT * FROM cluster_alias WHERE status='accepted'"
    ).fetchall()
    alias_conn.close()
    if accepted_aliases:
        combined += "\n# ── Alias / Equivalence Axioms ────────────────────────────────────\n\n"
        for alias in accepted_aliases:
            src_lbl = (alias["source_label"] or "").strip()
            tgt_cls = _to_pascal_case(alias["target_label"])
            rel = alias["relation_type"]
            if not src_lbl:
                continue
            if rel == "equivalentClass":
                combined += f":{_to_pascal_case(src_lbl)} owl:equivalentClass :{tgt_cls} .\n\n"
            else:
                # ODR-022 §1.4: a source-system label (ISO 15926 "ACTUATOR", CFIHOS
                # "PRESSURE RELIEF VALVE") is a lexical variant of the COPI class, not a
                # separate universal. Minting :ACTUATOR in the copi namespace created a
                # class with no numeric IRI, no axioms and no BFO anchor, whose only
                # triple was skos:exactMatch back to the real class. Record the variant
                # as a label on the target instead.
                safe = src_lbl.replace("\\", "\\\\").replace('"', '\\"')
                combined += f':{tgt_cls} skos:altLabel "{safe}"@en .\n\n'

    # ── Genus / component stubs ───────────────────────────────────────────────
    # Some COPI classes appear as rdfs:subClassOf targets or in restriction
    # fillers without having their own class declaration (e.g. genus classes
    # whose enrichment is still 'proposed', or component classes referenced by
    # other clusters' necessary_parts but never independently validated).
    # OOPS! P04 flags these as "unconnected".  Emit minimal stubs so they are
    # properly anchored in the hierarchy.
    import re as _re

    _BFO_ROOTS_S = {"Assembly", "MaterialArtifact", "EngineeredSystem",
                    "Site", "Object", "ObjectAggregate", "FiatObjectPart"}
    _BFO_DIRECT_S = {"Site", "Object", "ObjectAggregate", "FiatObjectPart"}
    _BFO_IRI_S = {
        "Site": "bfo:BFO_0000029", "Object": "bfo:BFO_0000030",
        "ObjectAggregate": "bfo:BFO_0000027", "FiatObjectPart": "bfo:BFO_0000024",
    }

    # Find all COPI short-form names referenced in the combined TTL
    _copi_all_refs = set(_re.findall(r'(?<!\w):([A-Z][A-Za-z0-9]+)', combined))

    # A class is "connected" when its declaration continues with ";" (meaning
    # more triples follow, e.g. rdfs:subClassOf or owl:equivalentClass).
    # A trailing "." is an orphan stub with no hierarchy axiom.
    _copi_connected: set[str] = set(_re.findall(
        r':([A-Z][A-Za-z0-9]+)\s+rdf:type\s+owl:Class\s*;', combined
    ))

    _undeclared = _copi_all_refs - _copi_connected
    # All-caps names (e.g. ACCUMULATOR) come from cluster_alias source_label IRIs;
    # they are already related to their PascalCase counterpart via skos:exactMatch.
    # Generating a stub class declaration for them creates duplicates that confuse HermiT.
    _undeclared = {n for n in _undeclared if not n.isupper()}
    if _undeclared:
        combined += "\n# ── Genus / component stubs (auto-generated) ─────────────────────────\n\n"
        _stub_conn = get_enrichment_db()
        for _stub_name in sorted(_undeclared):
            # All-uppercase names (e.g. ISO 15926-4 aliases) need special handling
            if _stub_name.isupper():
                _stub_label = _stub_name.lower()
                _cluster_lbl = _stub_label
            else:
                _stub_label = _to_label(_stub_name)
                _cluster_lbl = _stub_label.lower()
            _stub_row = _stub_conn.execute(
                "SELECT genus, genus_bfo_root, label_pt FROM enrichment "
                "WHERE cluster_label = ? ORDER BY updated_at DESC LIMIT 1",
                (_cluster_lbl,)
            ).fetchone()
            if _stub_row:
                _g = (_stub_row["genus"] or "MaterialArtifact").strip()
                if _g in _BFO_DIRECT_S:
                    _parent = _BFO_IRI_S[_g]
                elif _g in _BFO_ROOTS_S:
                    _parent = f"iof-core:{_g}"
                else:
                    _parent = f":{_to_pascal_case(_g)}"
                _stub_label_pt = _stub_row["label_pt"] or _stub_label_pt_fn(_stub_name)
            else:
                # Name-based heuristic when not in DB
                if _stub_name.endswith("Function"):
                    _parent = "iof-core:DesignedFunction"
                    _stub_label_pt = _func_label_pt(_stub_name) or _stub_label_pt_fn(_stub_name)
                elif _stub_name.endswith("Process"):
                    _parent = "iof-core:PlannedProcess"
                    _stub_label_pt = _proc_label_pt(_stub_name) or _stub_label_pt_fn(_stub_name)
                else:
                    _aux_row = _stub_conn.execute(
                        "SELECT bfo_category FROM auxiliary_class "
                        "WHERE name = ? AND status = 'validated'",
                        (_stub_name,)
                    ).fetchone()
                    if _aux_row and _aux_row["bfo_category"]:
                        _parent = _AUX_BFO_IRI[_aux_row["bfo_category"]]
                    else:
                        _parent = "owl:Thing"
                    _stub_label_pt = _stub_label_pt_fn(_stub_name)
            # class_annotation is the single source of pt-br labels and definitions
            # for non-equipment classes; a stub that skipped it shipped without the
            # naturalLanguageDefinition APV requires (FluidPort, SubsurfaceAccessProcess).
            combined += (
                f":{_stub_name} rdf:type owl:Class ;\n"
                f"    rdfs:subClassOf {_parent} ;\n"
                f'    rdfs:label "{_stub_label}"@en'
                f"{_class_annotation_ttl(_stub_name, _stub_label_pt)} .\n\n"
            )
        _stub_conn.close()

    return combined


# ---------------------------------------------------------------------------
# IRI assignment and OWL Functional Syntax export
# ---------------------------------------------------------------------------

#: IRI template for COPI classes.  Number is zero-padded to 7 digits.
_COPI_CLASS_IRI = "https://www.inf.ufrgs.br/ontologies/copi/COPI_{:07d}"
#: IRI prefix for custom annotation properties (COPI_0000045+)
_COPI_ANNPROP_BASE = 45


def _esc(s: str) -> str:
    """Escape a string for use inside OWL Functional Syntax double-quoted literals."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def assign_copi_ids() -> dict[int, int]:
    """
    Assign COPI numeric IDs to validated/exported enrichments that lack one.

    Lookup order per cluster_label:
      1. _SCOPE_MAP alias (e.g. "absorber" → "GasAbsorber" → TSV)
      2. _GENUS_MAP alias (e.g. "heat exchanger" → "HeatExchanger" → TSV)
      3. PascalCase(cluster_label) → TSV

    Raises ValueError if a label cannot be resolved — never assigns a
    sequential integer that may collide with the core ontology IRI space.
    Returns {enrichment_db_id: copi_id} for newly assigned rows.
    """
    COPI_BASE = "https://www.inf.ufrgs.br/ontologies/copi/"
    _SCOPE_ALIAS = {
        "pump": "Pump",
        "compressor": "Compressor",
        "absorber": "GasAbsorber",
        "temperature element": "TemperatureSensor",
        "shell and tube heat exchanger": "ShellAndTubeHeatExchanger",
    }
    _GENUS_ALIAS = {
        "pressure vessel": "PressureVessel",
        "instrument": "Instrument",
        "heat exchanger": "HeatExchanger",
    }

    iri_map = _load_copi_iri_map()

    def _resolve(label: str) -> int:
        for alias_map in (_SCOPE_ALIAS, _GENUS_ALIAS):
            name = alias_map.get(label)
            if name:
                v = iri_map.get(f"{COPI_BASE}{name}")
                if v:
                    return int(re.search(r"COPI_(\d+)", v).group(1))
        pascal = "".join(w.capitalize() for w in re.split(r"[\s\-_]+", label))
        v = iri_map.get(f"{COPI_BASE}{pascal}")
        if v:
            return int(re.search(r"COPI_(\d+)", v).group(1))
        raise ValueError(
            f"No IRI in copi-iri-map.tsv for cluster_label={label!r}. "
            "Add an entry before validating this enrichment."
        )

    conn = get_enrichment_db()
    unassigned = conn.execute(
        "SELECT id, cluster_label FROM enrichment WHERE copi_id IS NULL "
        "AND status IN ('validated', 'exported') ORDER BY cluster_label, id"
    ).fetchall()

    assigned: dict[int, int] = {}
    for r in unassigned:
        try:
            copi_id = _resolve(r["cluster_label"])
        except ValueError:
            logger.warning("assign_copi_ids: no IRI for %r — skipping", r["cluster_label"])
            continue
        conn.execute("UPDATE enrichment SET copi_id = ? WHERE id = ?", (copi_id, r["id"]))
        assigned[r["id"]] = copi_id

    conn.commit()
    conn.close()
    return assigned


def _load_copi_iri_map() -> dict[str, str]:
    """
    Load copi-iri-map.tsv → {old_iri: new_iri}.
    Comments (lines starting with #) and the header row are skipped.
    Raises FileNotFoundError if the map file is missing.
    """
    result: dict[str, str] = {}
    with open(_COPI_IRI_MAP_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) != 2 or parts[0] == "old_iri":
                continue
            result[parts[0]] = parts[1]
    return result


_COPI_NS = "https://www.inf.ufrgs.br/ontologies/copi/"
_TTL_UPSTREAM_PREFIXES = (
    ("http://purl.obolibrary.org/obo/", "bfo:"),
    ("https://spec.industrialontologies.org/ontology/construct/", "iof-core:"),
)
# A double-quoted string literal, or a comment running to end of line.
_TTL_SKIP_RE = re.compile(r'"(?:[^"\\]|\\.)*"|#.*$')
_TTL_COPI_NAME_RE = re.compile(
    r"<https://www\.inf\.ufrgs\.br/ontologies/copi/([A-Za-z_]\w*)>"
    r"|(?<![\w:/.#-])((?:copi)?:)([A-Za-z_]\w*)"
)


def remap_turtle_to_numeric_iris(ttl: str, iri_map: dict[str, str] | None = None) -> str:
    """Display-only remap of readable-name COPI IRIs to numeric COPI_* IRIs.

    Unlike regen_enriched_owl.remap_graph() (rdflib round-trip), this works on the
    text line by line so comments and layout survive — it's for the /turtle preview
    and the doc page, never for anything the pipeline parses. Comments and string
    literals are left alone; names missing from copi-iri-map.tsv stay readable.
    Canonical upstream names the map redirects (e.g. ``:MeasurementProcess`` ->
    ``iof-core:MeasurementProcess``) are rendered in their own namespace, exactly as
    the publish path does, so the preview never shows them as COPI classes.
    Each remapped line gets a trailing ``# ReadableName`` so the snippet stays legible.
    """
    if iri_map is None:
        try:
            iri_map = _load_copi_iri_map()
        except FileNotFoundError:
            return ttl
    # readable local name -> target IRI. Targets are numeric COPI IRIs or, for canonical
    # upstream names (MaterialEntity, MeasurementProcess, ...), the BFO / IOF-Core IRI.
    targets = {
        old[len(_COPI_NS):]: new
        for old, new in iri_map.items()
        if old.startswith(_COPI_NS)
    }

    def _render(target: str, copi_prefix: str | None) -> str:
        if target.startswith(_COPI_NS):
            local_name = target[len(_COPI_NS):]
            return f"{copi_prefix}{local_name}" if copi_prefix else f"<{target}>"
        for ns, pfx in _TTL_UPSTREAM_PREFIXES:
            if target.startswith(ns):
                return f"{pfx}{target[len(ns):]}"
        return f"<{target}>"

    out_lines = []
    for line in ttl.split("\n"):
        if line.lstrip().startswith("@prefix"):
            out_lines.append(line)
            continue
        replaced: list[str] = []

        def _sub(m: re.Match) -> str:
            name = m.group(1) or m.group(3)
            target = targets.get(name)
            if target is None:
                return m.group(0)
            rendered = _render(target, None if m.group(1) else m.group(2))
            # Annotate only when the rendered IRI doesn't already say what it is.
            if not re.search(rf"[:/]{re.escape(name)}>?$", rendered):
                replaced.append(name)
            return rendered

        pieces, comment, pos = [], "", 0
        for sm in _TTL_SKIP_RE.finditer(line):
            pieces.append(_TTL_COPI_NAME_RE.sub(_sub, line[pos:sm.start()]))
            if sm.group(0).startswith("#"):
                comment = sm.group(0)
            else:
                pieces.append(sm.group(0))
            pos = sm.end()
            if comment:
                break
        if not comment:
            pieces.append(_TTL_COPI_NAME_RE.sub(_sub, line[pos:]))
        code = "".join(pieces)

        if replaced:
            names = ", ".join(dict.fromkeys(replaced))
            if comment:
                code = f"{code}# {names} · {comment[1:].lstrip()}"
            else:
                code = f"{code.rstrip()}  # {names}"
        else:
            code += comment
        out_lines.append(code)
    return "\n".join(out_lines)


def generate_nivel1_enriched() -> str:
    """
    Generate the Nível 1 Turtle for copi-enriched, db-driven.

    Scope filter (serializer-side): cluster_label → (canonical equip class name, op IRI or None).
    None op → iof-constr:MeasurementProcess.

    For each in-scope cluster:
      - Query enrichment.db: function_name, genus_bfo_root, axiom_mode (status must be 'validated').
      - Resolve function_name and equip class name → numeric IRI via copi-iri-map.tsv.
      - Emit function leaf + equipment leaf axioms (identical pattern to hardwired version).

    Skips non-validated clusters with a warning to stderr.
    Raises ValueError on missing required DB fields or unresolvable IRIs.
    """
    COPI_BASE = "https://www.inf.ufrgs.br/ontologies/copi/"
    IOF_NS    = "https://spec.industrialontologies.org/ontology/construct/"
    BFO_NS    = "http://purl.obolibrary.org/obo/"
    ONTO_IRI  = f"{COPI_BASE}copi-enriched"

    # Scope filter: (cluster_label, canonical_equip_class_name, op_local_or_None)
    # op_local = None → use iof-constr:MeasurementProcess
    _SCOPE_MAP = [
        ("pump",                          "Pump",                        "COPI_0000011"),
        ("compressor",                    "Compressor",                  "COPI_0000012"),
        ("absorber",                      "GasAbsorber",                 "COPI_0000013"),
        ("temperature element",           "TemperatureSensor",           None),
        ("shell and tube heat exchanger", "ShellAndTubeHeatExchanger",   "COPI_0000089"),
    ]

    _GENUS_TTL = {
        "Assembly":         "iof-constr:Assembly",
        "MaterialArtifact": "iof-constr:MaterialArtifact",
        # Nível 2 Incremento 2a structural genera (ODR-018)
        "pressure vessel":  "copi:COPI_0000090",
        "instrument":       "copi:COPI_0000091",
        "heat exchanger":   "copi:COPI_0000092",
    }

    iri_map = _load_copi_iri_map()

    def _resolve(class_name: str) -> str:
        key = f"{COPI_BASE}{class_name}"
        new_iri = iri_map.get(key)
        if not new_iri:
            raise ValueError(f"IRI not found in copi-iri-map.tsv for: {class_name!r}")
        return "copi:" + new_iri.split("/")[-1]

    def _camel_label(name: str) -> str:
        return re.sub(r"(?<!^)(?=[A-Z])", " ", name).lower()

    conn = get_enrichment_db()

    lines = [
        f"@prefix copi:       <{COPI_BASE}> .",
        f"@prefix iof-av:     <https://spec.industrialontologies.org/ontology/annotation/> .",
        f"@prefix iof-constr: <{IOF_NS}> .",
        f"@prefix obo:        <{BFO_NS}> .",
        "@prefix owl:        <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdf:        <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix rdfs:       <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix xsd:        <http://www.w3.org/2001/XMLSchema#> .",
        "",
        f"<{ONTO_IRI}> a owl:Ontology ;",
        f'    rdfs:label "COPI Enriched — Nível 1"@en ;',
        f"    owl:imports <{COPI_BASE}copi-core> .",
        "",
    ]

    generated: list[str] = []
    skipped:   list[str] = []

    for cluster, equip_class, op_id in _SCOPE_MAP:
        row = conn.execute(
            "SELECT function_name, genus, genus_bfo_root, axiom_mode, status, "
            "fol_axiom, nl_definition_en, nl_definition_pt, "
            "function_nl_definition_en, function_nl_definition_pt "
            "FROM enrichment WHERE cluster_label = ?",
            (cluster,),
        ).fetchone()

        if row is None:
            skipped.append(f"{cluster!r} — not found in DB")
            continue

        row = dict(row)

        if row["status"] != "validated":
            skipped.append(f"{cluster!r} — status={row['status']!r} (not validated)")
            continue

        for field in ("function_name", "genus_bfo_root", "axiom_mode"):
            if not row.get(field):
                conn.close()
                raise ValueError(f"Cluster {cluster!r}: required field {field!r} is NULL in DB")

        func_name = row["function_name"]
        # Use the specific genus if present in _GENUS_TTL; fall back to genus_bfo_root (Assembly/MaterialArtifact)
        genus = row.get("genus") or row["genus_bfo_root"]
        if genus not in _GENUS_TTL:
            genus = row["genus_bfo_root"]

        if genus not in _GENUS_TTL:
            conn.close()
            raise ValueError(
                f"Cluster {cluster!r}: genus_bfo_root={genus!r} not in supported set "
                f"{set(_GENUS_TTL)}"
            )

        func_ref    = _resolve(func_name)
        equip_ref   = _resolve(equip_class)
        op_ref      = f"copi:{op_id}" if op_id else "iof-constr:MeasurementProcess"
        genus_ref   = _GENUS_TTL[genus]
        func_local  = func_ref.split(":")[1]
        equip_local = equip_ref.split(":")[1]
        axiom_mode  = row["axiom_mode"]

        _func_nl_en = _safe_ttl(row.get("function_nl_definition_en") or "")
        _func_nl_pt = _safe_ttl(row.get("function_nl_definition_pt") or "")

        func_lines = [
            f"### {_camel_label(func_name).title()}  ({func_local})",
            f"{func_ref} a owl:Class ;",
            f"    rdfs:subClassOf iof-constr:DesignedFunction ;",
            f"    rdfs:subClassOf [ a owl:Restriction ; owl:onProperty obo:BFO_0000054 ; owl:someValuesFrom {op_ref} ] ;",
            f"    rdfs:subClassOf [ a owl:Restriction ; owl:onProperty obo:BFO_0000054 ; owl:allValuesFrom {op_ref} ] ;",
            f'    rdfs:label "{_camel_label(func_name)}"@en ;',
        ]
        if _func_nl_en:
            func_lines.append(f'    iof-av:naturalLanguageDefinition "{_func_nl_en}"@en ;')
        if _func_nl_pt:
            func_lines.append(f'    iof-av:naturalLanguageDefinition "{_func_nl_pt}"@pt-br ;')
        func_lines += [
            f"    rdfs:isDefinedBy <{ONTO_IRI}> .",
            "",
        ]

        if axiom_mode == "equivalent":
            equip_lines = [
                f"### {_camel_label(equip_class).title()}  ({equip_local})",
                f"{equip_ref} a owl:Class ;",
                f"    owl:equivalentClass [ a owl:Class ; owl:intersectionOf ( {genus_ref}",
                f"        [ a owl:Restriction ; owl:onProperty iof-constr:hasFunction ; owl:someValuesFrom {func_ref} ]",
                f"    ) ] ;",
                f"    rdfs:subClassOf {genus_ref} ;",
                f'    rdfs:label "{_camel_label(equip_class)}"@en ;',
            ]
            if row.get("nl_definition_en"):
                equip_lines.append(f'    iof-av:naturalLanguageDefinition "{_safe_ttl(row["nl_definition_en"])}"@en ;')
            if row.get("nl_definition_pt"):
                equip_lines.append(f'    iof-av:naturalLanguageDefinition "{_safe_ttl(row["nl_definition_pt"])}"@pt-br ;')
            if row.get("fol_axiom") and "→" in row["fol_axiom"] and "↔" not in row["fol_axiom"]:
                equip_lines.append(f'    iof-av:firstOrderLogicAxiom "{_safe_ttl(row["fol_axiom"])}"@en ;')
            equip_lines += [f"    rdfs:isDefinedBy <{ONTO_IRI}> .", ""]
        else:  # necessary — primitive class, no equivalentClass
            equip_lines = [
                f"### {_camel_label(equip_class).title()}  ({equip_local})",
                f"{equip_ref} a owl:Class ;",
                f"    rdfs:subClassOf {genus_ref} ;",
                f"    rdfs:subClassOf [ a owl:Restriction ; owl:onProperty iof-constr:hasFunction ; owl:someValuesFrom {func_ref} ] ;",
                f'    rdfs:label "{_camel_label(equip_class)}"@en ;',
            ]
            if row.get("nl_definition_en"):
                equip_lines.append(f'    iof-av:naturalLanguageDefinition "{_safe_ttl(row["nl_definition_en"])}"@en ;')
            if row.get("nl_definition_pt"):
                equip_lines.append(f'    iof-av:naturalLanguageDefinition "{_safe_ttl(row["nl_definition_pt"])}"@pt-br ;')
            if row.get("fol_axiom") and "→" in row["fol_axiom"] and "↔" not in row["fol_axiom"]:
                equip_lines.append(f'    iof-av:firstOrderLogicAxiom "{_safe_ttl(row["fol_axiom"])}"@en ;')
            equip_lines += [f"    rdfs:isDefinedBy <{ONTO_IRI}> .", ""]

        lines += func_lines + equip_lines
        generated.append(cluster)

    conn.close()

    if skipped:
        print("[generate_nivel1_enriched] Skipped:", file=sys.stderr)
        for s in skipped:
            print(f"  SKIP {s}", file=sys.stderr)
    print(f"[generate_nivel1_enriched] Generated: {generated}", file=sys.stderr)

    return "\n".join(lines)


def _inline_symbol(sym_file: "Path", max_px: int = 64) -> str:
    """Return an HTML fragment that safely embeds an ISA 5.1 symbol file.

    SVG files are inlined as raw markup.  PNG (and any other binary) files are
    base64-encoded and wrapped in an <img> tag so binary bytes never land in
    the HTML text stream.
    """
    import base64
    suffix = sym_file.suffix.lower()
    if suffix == ".svg":
        try:
            return sym_file.read_text(encoding="utf-8")
        except Exception:
            return ""
    else:
        try:
            b64 = base64.b64encode(sym_file.read_bytes()).decode("ascii")
            mime = "image/png" if suffix == ".png" else "image/jpeg"
            return (
                f'<img src="data:{mime};base64,{b64}" '
                f'style="max-width:{max_px}px;max-height:{max_px}px;object-fit:contain;" '
                f'alt="ISA 5.1 symbol" loading="lazy">'
            )
        except Exception:
            return ""


def _safe_ttl(s: str) -> str:
    """Escape a string for use inside a Turtle single-line string literal."""
    return (
        str(s)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", " ")
        .replace("\r", " ")
    )


def _to_pascal_case(s: str) -> str:
    """Convert 'pump casing' or 'PumpCasing' or 'in-line filter' to 'PumpCasing'."""
    if not s:
        return "Unknown"
    # Already PascalCase (no spaces, underscores, or hyphens)?
    if s[0].isupper() and " " not in s and "_" not in s and "-" not in s:
        return s
    return "".join(word.capitalize() for word in re.split(r"[\s_-]+", s))


def _to_label(pascal: str) -> str:
    """Convert 'PumpingFunction' to 'pumping function'."""
    import re
    words = re.sub(r'([A-Z])', r' \1', pascal).strip().lower()
    return words


# ---------------------------------------------------------------------------
# History / versioning
# ---------------------------------------------------------------------------

def queue_add(cluster_labels: list[str]) -> list[dict]:
    """Add clusters to the enrichment job queue (skip duplicates with pending/running status)."""
    conn = get_enrichment_db()
    added = []
    for label in cluster_labels:
        existing = conn.execute(
            "SELECT id FROM enrichment_job WHERE cluster_label = ? AND status IN ('pending','running')",
            (label,),
        ).fetchone()
        if existing:
            continue
        cur = conn.execute(
            "INSERT INTO enrichment_job (cluster_label) VALUES (?)", (label,)
        )
        added.append({"id": cur.lastrowid, "cluster_label": label, "status": "pending"})
    conn.commit()
    conn.close()
    return added


def queue_list(status: str | None = None) -> list[dict]:
    """Return jobs, optionally filtered by status."""
    conn = get_enrichment_db()
    if status:
        rows = conn.execute(
            "SELECT * FROM enrichment_job WHERE status = ? ORDER BY id", (status,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM enrichment_job ORDER BY id DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def queue_next_pending() -> dict | None:
    """Return the oldest pending job (not yet started)."""
    conn = get_enrichment_db()
    row = conn.execute(
        "SELECT * FROM enrichment_job WHERE status = 'pending' ORDER BY id LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def queue_set_running(job_id: int) -> None:
    conn = get_enrichment_db()
    conn.execute(
        "UPDATE enrichment_job SET status='running', started_at=datetime('now') WHERE id=?",
        (job_id,),
    )
    conn.commit()
    conn.close()


def queue_set_done(job_id: int, enrichment_id: int) -> None:
    conn = get_enrichment_db()
    conn.execute(
        "UPDATE enrichment_job SET status='done', completed_at=datetime('now'), enrichment_id=? WHERE id=?",
        (enrichment_id, job_id),
    )
    conn.commit()
    conn.close()


def queue_set_failed(job_id: int, error: str) -> None:
    conn = get_enrichment_db()
    conn.execute(
        "UPDATE enrichment_job SET status='failed', completed_at=datetime('now'), error_msg=? WHERE id=?",
        (error[:500], job_id),
    )
    conn.commit()
    conn.close()


def queue_clear_done() -> int:
    """Delete all done/failed/skipped jobs. Returns count deleted."""
    conn = get_enrichment_db()
    cur = conn.execute(
        "DELETE FROM enrichment_job WHERE status IN ('done','failed','skipped')"
    )
    count = cur.rowcount
    conn.commit()
    conn.close()
    return count


# ---------------------------------------------------------------------------
# Anthropic Message Batches API  (50% cost savings, async processing)
# ---------------------------------------------------------------------------

BATCH_API_URL = "https://api.anthropic.com/v1/messages/batches"


async def batch_submit_pending(api_key: str, model: str = DEFAULT_MODEL) -> dict:
    """
    Take all pending queue jobs, build their prompts, and submit them as a
    single Anthropic Message Batch.  Returns {batch_id, submitted, skipped}.

    Batch pricing is 50% of standard rates and stacks with prompt caching.
    Results are NOT available immediately — use batch_poll_status() and
    batch_import_results() to retrieve them (typically within 1 hour).
    """
    jobs = queue_list(status="pending")
    if not jobs:
        return {"error": "No pending jobs in queue"}

    existing_context = get_existing_ontology_context()
    requests_payload: list[dict] = []
    skipped: list[str] = []

    for job in jobs:
        label = job["cluster_label"]
        definitions = get_cluster_definitions(label)
        if not definitions:
            skipped.append(label)
            continue

        iso14224_data = get_cluster_iso14224_properties(label)
        system_prompt, user_prompt = build_enrichment_prompt(
            cluster_label=label,
            definitions=definitions,
            subtypes=get_cluster_subtypes(label),
            related_concepts=get_related_concepts(label),
            parent_candidates=get_parent_candidates(label),
            existing_ontology=existing_context,
            cfihos_properties=get_cluster_properties(label),
            iso14224_main_function=iso14224_data["main_function"],
            iso14224_attributes=iso14224_data["attributes"],
            component_terms=get_component_terms(label),
        )

        requests_payload.append({
            "custom_id": f"job-{job['id']}",
            "params": {
                "model": model,
                "max_tokens": MAX_TOKENS,
                # Cache the static system prompt — discounts stack with batch 50% off
                "system": [
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                "messages": [{"role": "user", "content": user_prompt}],
            },
        })

    if not requests_payload:
        return {"error": "No clusters with definitions found for pending jobs"}

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            BATCH_API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "prompt-caching-2024-07-31",
                "content-type": "application/json",
            },
            json={"requests": requests_payload},
        )
        resp.raise_for_status()
        batch_data = resp.json()

    anthropic_batch_id = batch_data["id"]

    submitted_ids = {int(r["custom_id"].split("-")[1]) for r in requests_payload}

    conn = get_enrichment_db()
    conn.execute(
        "INSERT INTO batch_submissions (anthropic_batch_id, model, job_count, status) VALUES (?, ?, ?, 'in_progress')",
        (anthropic_batch_id, model, len(requests_payload)),
    )
    for job in jobs:
        if job["id"] in submitted_ids:
            conn.execute(
                "UPDATE enrichment_job SET status='running', batch_id=?, started_at=datetime('now') WHERE id=?",
                (anthropic_batch_id, job["id"]),
            )
        else:
            # job was skipped (no definitions found) — leave as pending so it can be retried
            conn.execute(
                "UPDATE enrichment_job SET status='skipped' WHERE id=?",
                (job["id"],),
            )
    conn.commit()
    conn.close()

    logger.info(
        "Submitted Anthropic batch %s: %d requests, %d skipped",
        anthropic_batch_id, len(requests_payload), len(skipped),
    )
    return {
        "batch_id": anthropic_batch_id,
        "submitted": len(requests_payload),
        "skipped": skipped,
    }


async def batch_poll_status(anthropic_batch_id: str, api_key: str) -> dict:
    """Check the processing status of a submitted batch.  Updates the local DB row."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{BATCH_API_URL}/{anthropic_batch_id}",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    conn = get_enrichment_db()
    conn.execute(
        "UPDATE batch_submissions SET status=?, ended_at=? WHERE anthropic_batch_id=?",
        (data.get("processing_status", "unknown"), data.get("ended_at"), anthropic_batch_id),
    )
    conn.commit()
    conn.close()
    return data


async def batch_import_results(anthropic_batch_id: str, api_key: str) -> dict:
    """
    Download and import results from a completed batch.

    For each succeeded request:
      - Parses the LLM JSON response
      - Calls _store_proposal() to save the enrichment
      - Marks the queue job as done
    Applies the 50% batch pricing discount when recording costs.
    """
    # Fetch model from our local record so _store_proposal can log it correctly
    conn = get_enrichment_db(actor="batch_import_results")
    row = conn.execute(
        "SELECT model FROM batch_submissions WHERE anthropic_batch_id=?",
        (anthropic_batch_id,),
    ).fetchone()
    conn.close()
    model = (dict(row)["model"] if row else DEFAULT_MODEL) or DEFAULT_MODEL

    # Stream JSONL results from Anthropic
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.get(
            f"{BATCH_API_URL}/{anthropic_batch_id}/results",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        resp.raise_for_status()
        content = resp.text

    imported = 0
    errors: list[str] = []

    for line in content.strip().splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue

        custom_id = item.get("custom_id", "")
        if not custom_id.startswith("job-"):
            continue

        try:
            job_id = int(custom_id[4:])
        except ValueError:
            continue

        result = item.get("result", {})
        result_type = result.get("type")

        if result_type != "succeeded":
            queue_set_failed(job_id, f"Batch result type: {result_type}")
            errors.append(f"{custom_id}: {result_type}")
            continue

        message = result.get("message", {})
        usage = message.get("usage", {})
        input_tokens       = usage.get("input_tokens", 0)
        output_tokens      = usage.get("output_tokens", 0)
        cache_write_tokens = usage.get("cache_creation_input_tokens", 0)
        cache_read_tokens  = usage.get("cache_read_input_tokens", 0)
        # Apply 50% batch discount on top of normal pricing
        cost = _compute_cost(input_tokens, output_tokens, cache_write_tokens, cache_read_tokens) * 0.5

        # Extract and parse JSON from the assistant response
        text = "".join(
            b.get("text", "") for b in message.get("content", []) if b.get("type") == "text"
        ).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            proposal = json.loads(text)
        except json.JSONDecodeError as exc:
            queue_set_failed(job_id, f"Invalid JSON in batch response: {exc}")
            errors.append(f"{custom_id}: JSON parse error")
            continue

        # Resolve the cluster label from the job record
        conn_e = get_enrichment_db()
        job_row = conn_e.execute(
            "SELECT cluster_label FROM enrichment_job WHERE id=?", (job_id,)
        ).fetchone()
        conn_e.close()
        if not job_row:
            errors.append(f"{custom_id}: job {job_id} not found")
            continue
        cluster_label = dict(job_row)["cluster_label"]

        definitions = get_cluster_definitions(cluster_label)
        enrichment_id = _store_proposal(
            cluster_label, proposal, definitions, model,
            input_tokens, output_tokens, cost, cache_write_tokens, cache_read_tokens,
        )
        queue_set_done(job_id, enrichment_id)
        imported += 1
        logger.info("Batch imported: %s → enrichment #%d (cost $%.4f)", cluster_label, enrichment_id, cost)

        # Metrics: snapshot LLM initial output (read from DB to get normalised field names)
        try:
            import evaluation_metrics as _em
            _e = get_enrichment(enrichment_id) or {}
            _ttl = generate_turtle(enrichment_id)
            _snap_conn = get_enrichment_db()
            _step_data = {
                "function_name":         _e.get("function_name"),
                "process_name":          _e.get("process_name"),
                "function_rationale":    _e.get("function_rationale"),
                "genus":                 _e.get("genus"),
                "genus_bfo_root":        _e.get("genus_bfo_root"),
                "genus_rationale":       _e.get("genus_rationale"),
                "differentia_expression":_e.get("differentia_expression"),
                "differentia_nl":        _e.get("differentia_nl"),
                "differentia_rationale": _e.get("differentia_rationale"),
                "necessary_parts":       _e.get("necessary_parts"),
                "parts_rationale":       _e.get("parts_rationale"),
                "process_signature":     _e.get("process_signature"),
                "signature_rationale":   _e.get("signature_rationale"),
            }
            _em.take_axiom_snapshot(
                _snap_conn, enrichment_id, "llm_initial", _ttl,
                _step_data, _e.get("axiom_mode", "necessary"),
            )
            _snap_conn.close()
        except Exception as _exc:
            logger.warning("batch llm_initial snapshot(%s) failed: %s", enrichment_id, _exc)

        # Divergence detection (heuristic)
        try:
            detect_divergences(enrichment_id)
        except Exception as _exc:
            logger.warning("batch detect_divergences(%s) failed: %s", enrichment_id, _exc)

    conn = get_enrichment_db()
    conn.execute(
        "UPDATE batch_submissions SET results_imported=1, succeeded=? WHERE anthropic_batch_id=?",
        (imported, anthropic_batch_id),
    )
    conn.commit()
    conn.close()

    return {"imported": imported, "errors": errors}


def list_batch_submissions() -> list[dict]:
    """Return all batch submission records, newest first."""
    conn = get_enrichment_db()
    rows = conn.execute(
        "SELECT * FROM batch_submissions ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def generate_fol_theory(e: dict) -> list[dict]:
    """
    Derive a complete FOL theory from structured step data.
    Returns list of {"step": str, "label": str, "fol": str, "note": str}.
    All five steps are represented as separate named axioms.
    """
    results: list[dict] = []

    cls   = _to_pascal_case(e.get("cluster_label") or "?")
    genus = _to_pascal_case(e.get("genus") or "MaterialArtifact")
    fn    = _to_pascal_case(e.get("function_name") or "")
    mode  = e.get("axiom_mode") or "necessary"

    biconditional = mode in ("equivalent", "functional")
    conn = "↔" if biconditional else "→"

    # ── Steps 1-3: definition (genus + identity-giving function + differentia) ──
    if fn:
        fn_clause = f"∃f ({fn}(f) ∧ bearerOf(x,f))"
        diff_expr = (e.get("differentia_expression") or "").strip()

        def _diff_is_pure_function_restatement(diff: str, func: str) -> bool:
            """True when diff adds nothing beyond the fn_clause already in the formula.
            Catches patterns like ∃bearerOf.Func or ∃hasFunction.Func (single restriction,
            no ⊓ conjuncts) where Func matches the enrichment's function_name."""
            import re as _re
            if not diff or not func or "⊓" in diff:
                return False
            return bool(_re.match(
                rf"^∃(?:bearerOf|hasFunction)\.{_re.escape(func)}$", diff.strip()
            ))

        rhs = f"{genus}(x) ∧ {fn_clause}"
        if diff_expr and mode not in ("constructive", "necessary"):
            if not _diff_is_pure_function_restatement(diff_expr, fn):
                rhs += f" ∧ {diff_expr}"

        label = "Definition" if biconditional else "Necessary condition"
        note  = "Steps 1–3: genus + identity-giving function"

        results.append({
            "step": "1–3",
            "label": label,
            "fol": f"∀x ({cls}(x) {conn} {rhs})",
            "note": note,
        })

        # Step 1 function-class axiom: ∀ + ∃ realizedIn pairing
        results.append({
            "step": "1",
            "label": f"Function axiom: {fn}",
            "fol": (
                f"∀f ({fn}(f) → "
                f"∀p (realizedIn(f,p) → {_to_pascal_case(e.get('process_name') or fn.replace('Function','Process'))}(p))"
                f" ∧ ∃p ({_to_pascal_case(e.get('process_name') or fn.replace('Function','Process'))}(p) ∧ realizedIn(f,p)))"
            ),
            "note": "Step 1: ∀ preserves type-type identity; ∃ rules out vacuous functions never realised",
        })

        # For constructive/necessary, differentia as separate necessary axiom
        if diff_expr and mode in ("constructive", "necessary"):
            results.append({
                "step": "3",
                "label": "Structural differentia (necessary only)",
                "fol": f"∀x ({cls}(x) → {diff_expr})",
                "note": "Step 3: structural property — necessary condition, not sufficient (OWA prevents ≡)",
            })

    # ── Step 4: necessary parts ──
    parts = e.get("necessary_parts") or []
    if isinstance(parts, str):
        try:
            import json as _json
            parts = _json.loads(parts)
        except Exception:
            parts = []

    for part in parts:
        if isinstance(part, dict):
            part_cls  = _to_pascal_case(part.get("name") or "?")
            rel       = part.get("relation") or "hasComponentPartAtAllTimes"
        else:
            part_cls  = _to_pascal_case(str(part))
            rel       = "hasComponentPartAtAllTimes"
        results.append({
            "step": "4",
            "label": f"Necessary part: {part_cls}",
            "fol": f"∀x ({cls}(x) → ∃p ({part_cls}(p) ∧ {rel}(x,p)))",
            "note": "Step 4: mereological commitment — every instance must have this part",
        })

    # ── Step 5: process participation signature ──
    sig = e.get("process_signature") or {}
    if isinstance(sig, str):
        try:
            import json as _json
            sig = _json.loads(sig)
        except Exception:
            sig = {}

    if sig and fn:
        inputs  = sig.get("inputs")  or []
        outputs = sig.get("outputs") or []
        # Process type comes from the controlled `transformation_kind` vocabulary,
        # never the free-text `transformation` prose (which is descriptive and would
        # produce a giant, sometimes syntactically-invalid class name). The prose is
        # displayed separately as a human-readable note.
        transformation_kind = (sig.get("transformation_kind") or "").strip()

        # Participants belong to the process p that realizes the function f (the same
        # realizedIn relation the Step 1 function axiom uses), never to f itself: a
        # function is a disposition and has no participants.
        antecedent = f"({cls}(x) ∧ {fn}(f) ∧ bearerOf(x,f) ∧ realizedIn(f,p))"
        def _sig_label(item) -> str:
            """Extract a usable class name from a sig item (str or dict)."""
            if isinstance(item, dict):
                return item.get("class") or item.get("type") or item.get("name") or item.get("label") or "Participant"
            return str(item)

        consequents = []
        for i, inp in enumerate(inputs):
            v = f"m{i+1}" if len(inputs) > 1 else "m"
            consequents.append(f"∃{v} ({_to_pascal_case(_sig_label(inp))}({v}) ∧ hasInput(p,{v}))")
        for i, out in enumerate(outputs):
            v = f"e{i+1}" if len(outputs) > 1 else "e"
            consequents.append(f"∃{v} ({_to_pascal_case(_sig_label(out))}({v}) ∧ hasOutput(p,{v}))")

        if consequents:
            sep = " ∧\n      "
            note = "Step 5: typed inputs and outputs of the process p that realises the function"
            if transformation_kind:
                # The controlled kind selects the COPI-Core operation anchor (Step 1);
                # it is not a term of this formula.
                note += f" (transformation kind: {transformation_kind})"
            results.append({
                "step": "5",
                "label": "Process participation signature",
                "fol": f"∀x ∀f ∀p ({antecedent} →\n      {sep.join(consequents)})",
                "note": note,
            })

    return results


def generate_cqs_csv() -> str:
    """Export all competency questions as a CSV string for requirements/cqs.csv."""
    import csv, io
    conn = get_enrichment_db()
    try:
        rows = conn.execute(
            "SELECT id, text, formal_expr, status, linked_classes, notes, created_at "
            "FROM competency_questions ORDER BY id"
        ).fetchall()
    except Exception:
        conn.close()
        return "id,text,formal_expr,status,linked_classes,notes,created_at\n"
    conn.close()

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["id", "text", "formal_expr", "status", "linked_classes", "notes", "created_at"])
    for row in rows:
        d = dict(row)
        # Flatten linked_classes JSON array to semicolon-separated string
        try:
            classes = json.loads(d.get("linked_classes") or "[]")
            d["linked_classes"] = "; ".join(classes)
        except Exception:
            d["linked_classes"] = d.get("linked_classes") or ""
        writer.writerow([
            d.get("id", ""),
            d.get("text", ""),
            d.get("formal_expr", "") or "",
            d.get("status", ""),
            d["linked_classes"],
            d.get("notes", "") or "",
            (d.get("created_at") or "")[:10],
        ])
    return buf.getvalue()


def get_linked_cqs(cluster_label: str) -> list[dict]:
    """Return competency questions that list cluster_label in their linked_classes JSON array."""
    conn = get_enrichment_db()
    try:
        rows = conn.execute(
            "SELECT id, text, status, linked_classes, notes FROM competency_questions ORDER BY status, id"
        ).fetchall()
    except Exception:
        conn.close()
        return []
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        try:
            classes = json.loads(d.get("linked_classes") or "[]")
        except Exception:
            classes = []
        # Case-insensitive match
        if any(c.strip().lower() == cluster_label.lower() for c in classes):
            d["linked_classes"] = classes
            result.append(d)
    return result


def snapshot_enrichment(enrichment_id: int, trigger: str = "rerun") -> None:
    """Save a snapshot of the current enrichment row into enrichment_history."""
    conn = get_enrichment_db(actor="snapshot_enrichment")
    row = conn.execute(
        "SELECT * FROM enrichment WHERE id = ?", (enrichment_id,)
    ).fetchone()
    if row is None:
        conn.close()
        return
    snapshot = json.dumps(dict(row), ensure_ascii=False, default=str)
    conn.execute(
        "INSERT INTO enrichment_history (enrichment_id, trigger, snapshot_json) VALUES (?,?,?)",
        (enrichment_id, trigger, snapshot),
    )
    _clear_write_actor(conn)
    conn.commit()
    conn.close()


def list_history(enrichment_id: int) -> list[dict]:
    """Return all snapshots for an enrichment, newest first."""
    conn = get_enrichment_db()
    rows = conn.execute(
        "SELECT id, snapshot_at, trigger FROM enrichment_history "
        "WHERE enrichment_id = ? ORDER BY id DESC",
        (enrichment_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_history_snapshot(history_id: int) -> dict | None:
    """Return the full snapshot dict for a single history entry."""
    conn = get_enrichment_db()
    row = conn.execute(
        "SELECT * FROM enrichment_history WHERE id = ?", (history_id,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    d = dict(row)
    try:
        d["snapshot"] = json.loads(d["snapshot_json"])
    except Exception:
        d["snapshot"] = {}
    return d


def restore_enrichment_snapshot(enrichment_id: int) -> bool:
    """Restore the most recent history snapshot for an enrichment row.

    Snapshots the current state first (trigger='undo') so the undo itself
    is reversible. Returns True if restored, False if no history exists.
    """
    history = list_history(enrichment_id)
    if not history:
        return False
    snap = get_history_snapshot(history[0]["id"])
    if not snap:
        return False
    snapshot_data: dict = snap.get("snapshot", {})
    # Snapshot current state so this undo can itself be undone
    snapshot_enrichment(enrichment_id, trigger="undo")
    # Restore all updatable fields from the snapshot
    restorable = {
        k: v for k, v in snapshot_data.items()
        if k in _ENRICHMENT_UPDATABLE_COLS
    }
    if restorable:
        update_enrichment(enrichment_id, restorable)
    return True


# ---------------------------------------------------------------------------
# Chowlk neighborhood diagram
# ---------------------------------------------------------------------------

def build_chowlk_neighborhood(enrichment_id: int) -> dict:
    """Return nodes + edges for a Chowlk-style OWL diagram of one enriched class."""
    conn = get_enrichment_db()

    row = conn.execute(
        "SELECT id, cluster_label, genus, genus_bfo_root, axiom_mode, "
        "function_name, function_parent, necessary_parts, disjoint_with "
        "FROM enrichment WHERE id = ?",
        (enrichment_id,),
    ).fetchone()
    if row is None:
        conn.close()
        raise ValueError(f"Enrichment {enrichment_id} not found")
    row = dict(row)

    all_rows = conn.execute(
        "SELECT id, cluster_label, genus, genus_bfo_root, axiom_mode "
        "FROM enrichment WHERE status IN ('validated', 'exported')"
    ).fetchall()
    conn.close()

    # Build lookup: PascalCase label → enrichment row
    validated_map: dict[str, dict] = {}
    for r in all_rows:
        d = dict(r)
        validated_map[_to_pascal_case(d["cluster_label"])] = d

    # IOF-Core upper-level classes — appear with iof: prefix in diagrams
    IOF_ROOTS = {"Assembly", "MaterialArtifact", "EngineeredSystem",
                 "DesignedFunction", "PlannedProcess", "FunctionBearingEntity"}

    nodes: list[dict] = []
    edges: list[dict] = []
    node_ids: set[str] = set()

    def add_node(nid: str, label: str, node_type: str, extra: dict | None = None):
        if nid not in node_ids:
            n = {"id": nid, "label": label, "node_type": node_type}
            if extra:
                n.update(extra)
            nodes.append(n)
            node_ids.add(nid)

    def add_edge(source: str, target: str, etype: str, prop: str = ""):
        eid = f"{source}__{etype}__{target}"
        edges.append({"id": eid, "source": source, "target": target, "type": etype, "property": prop})

    def iof_or_copi(pascal_name: str) -> str:
        return "iof" if pascal_name in IOF_ROOTS else "copi"

    # ── Target node ──────────────────────────────────────────────────────────
    target_pascal = _to_pascal_case(row["cluster_label"])
    target_id = f"copi:{target_pascal}"
    add_node(target_id, row["cluster_label"], "class_target",
             {"axiom_mode": row["axiom_mode"] or "", "enrichment_id": row["id"]})

    # ── Genus chain ──────────────────────────────────────────────────────────
    current_id = target_id
    current_genus = (row["genus"] or "").strip()
    while current_genus:
        genus_pascal = _to_pascal_case(current_genus)
        if genus_pascal in IOF_ROOTS:
            iof_id = f"iof:{genus_pascal}"
            add_node(iof_id, genus_pascal, "bfo")
            add_edge(current_id, iof_id, "subClassOf")
            break
        if genus_pascal in validated_map:
            vrow = validated_map[genus_pascal]
            genus_id = f"copi:{genus_pascal}"
            add_node(genus_id, vrow["cluster_label"], "class_genus",
                     {"axiom_mode": vrow["axiom_mode"] or "", "enrichment_id": vrow["id"]})
            if row["axiom_mode"] == "equivalent" and current_id == target_id:
                add_edge(current_id, genus_id, "equivalentClass")
            else:
                add_edge(current_id, genus_id, "subClassOf")
            current_id = genus_id
            current_genus = (vrow["genus"] or "").strip()
        else:
            # Unknown genus — treat as IOF-Core terminal
            prefix = iof_or_copi(genus_pascal)
            unknown_id = f"{prefix}:{genus_pascal}"
            add_node(unknown_id, genus_pascal, "bfo")
            add_edge(current_id, unknown_id, "subClassOf")
            break

    # ── IOF-Core root from genus_bfo_root field ───────────────────────────────
    bfo_root = (row.get("genus_bfo_root") or "").strip()
    if bfo_root and bfo_root in IOF_ROOTS:
        iof_root_id = f"iof:{bfo_root}"
        add_node(iof_root_id, bfo_root, "bfo")

    # ── Direct subclasses ─────────────────────────────────────────────────────
    for vrow in validated_map.values():
        if vrow["id"] == enrichment_id:
            continue
        sub_pascal = _to_pascal_case(vrow["cluster_label"])
        sub_genus_pascal = _to_pascal_case(vrow["genus"] or "")
        if sub_genus_pascal == target_pascal:
            sub_id = f"copi:{sub_pascal}"
            add_node(sub_id, vrow["cluster_label"], "class_sub",
                     {"axiom_mode": vrow["axiom_mode"] or "", "enrichment_id": vrow["id"]})
            if vrow["axiom_mode"] == "equivalent":
                add_edge(sub_id, target_id, "equivalentClass")
            else:
                add_edge(sub_id, target_id, "subClassOf")

    # ── Function nodes ────────────────────────────────────────────────────────
    func_name = (row.get("function_name") or "").strip()
    func_parent = (row.get("function_parent") or "").strip()
    if func_name:
        func_pascal = _to_pascal_case(func_name)
        func_id = f"copi:{func_pascal}"          # specific functions are COPI-defined
        add_node(func_id, func_name, "function")
        add_edge(target_id, func_id, "restriction", "∃ bearerOf")
        if func_parent:
            parent_pascal = _to_pascal_case(func_parent)
            parent_prefix = iof_or_copi(parent_pascal)
            parent_id = f"{parent_prefix}:{parent_pascal}"
            add_node(parent_id, func_parent, "function")
            add_edge(func_id, parent_id, "subClassOf")
            if parent_prefix != "iof":
                # chain up to iof:DesignedFunction
                df_id = "iof:DesignedFunction"
                add_node(df_id, "DesignedFunction", "bfo")
                add_edge(parent_id, df_id, "subClassOf")
        else:
            df_id = "iof:DesignedFunction"
            add_node(df_id, "DesignedFunction", "bfo")
            add_edge(func_id, df_id, "subClassOf")

    # ── Necessary parts ───────────────────────────────────────────────────────
    try:
        parts = json.loads(row.get("necessary_parts") or "[]")
    except Exception:
        parts = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if part.get("is_subtype_specific") is True or str(part.get("is_subtype_specific", "")).lower() == "true":
            continue
        part_name = (part.get("part_class") or part.get("name") or "").strip()
        if not part_name:
            continue
        part_pascal = _to_pascal_case(part_name)
        part_id = f"copi:{part_pascal}"          # parts are COPI-defined component classes
        add_node(part_id, part_name, "part")
        add_edge(target_id, part_id, "restriction", "∃ hasComponentPart")

    # ── IOF-Core backbone edges ───────────────────────────────────────────────
    backbone = [
        ("iof:Assembly", "iof:MaterialArtifact"),
        ("iof:EngineeredSystem", "iof:MaterialArtifact"),
    ]
    for src, tgt in backbone:
        if src in node_ids and tgt in node_ids:
            add_edge(src, tgt, "subClassOf")

    return {
        "nodes": nodes,
        "edges": edges,
        "target_id": target_id,
        "target_label": row["cluster_label"],
        "axiom_mode": row["axiom_mode"] or "",
    }


# ---------------------------------------------------------------------------
# Ontology consequence graph
# ---------------------------------------------------------------------------

def build_consequence_graph() -> dict:
    """
    Build a consequence graph using HermiT OWL reasoner via owlready2.

    Generates the full OWL/Turtle from all validated/exported enrichments
    (including custom axioms and relations), loads it into owlready2, runs
    HermiT, and extracts inferred superclass chains and disjointness violations.

    Returns a dict with: nodes, edges, individuals, stats.
    """
    import os
    import tempfile
    import owlready2

    conn = get_enrichment_db()
    rows = conn.execute(
        "SELECT id, cluster_label, axiom_mode, genus, genus_bfo_root, "
        "function_name, function_parent, function_rationale, process_name, process_parent, "
        "necessary_parts, disjoint_with, status, "
        "nl_definition_en, nl_definition_pt, differentia_nl, process_signature "
        "FROM enrichment WHERE status IN ('validated', 'exported', 'proposed') ORDER BY cluster_label"
    ).fetchall()
    conn.close()

    if not rows:
        return {"nodes": [], "edges": [], "individuals": [], "stats": {
            "total_classes": 0, "equivalent_classes": 0, "necessary_classes": 0,
            "consistent": True, "violation_count": 0,
            "reasoner": "HermiT (owlready2)",
        }}

    BFO_ROOTS = {"MaterialArtifact", "Assembly", "EngineeredSystem"}

    # ── 1. Generate combined Turtle, convert to RDF/XML, load into owlready2 ──
    # owlready2's built-in parser only understands RDF/XML and NTriples;
    # use rdflib to convert Turtle → RDF/XML first.
    import rdflib

    ttl = generate_combined_turtle()

    g = rdflib.Graph()
    g.parse(data=ttl, format="turtle")
    rdfxml = g.serialize(format="xml")

    fd, owl_path = tempfile.mkstemp(suffix=".owl")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(rdfxml)

        world = owlready2.World()
        onto  = world.get_ontology(f"file://{owl_path}").load()
    finally:
        try:
            os.unlink(owl_path)
        except OSError:
            pass

    # ── 2. Run HermiT ─────────────────────────────────────────────────────────
    consistent = True
    try:
        with onto:
            owlready2.sync_reasoner_hermit(world, infer_property_values=False)
    except owlready2.OwlReadyInconsistentOntologyError:
        consistent = False

    # ── 3. Collect inferred ancestors per class ───────────────────────────────
    def _local(cls_obj) -> str:
        """Return a short readable name for an owlready2 class."""
        iri = getattr(cls_obj, "iri", None) or ""
        if "#" in iri:
            return iri.split("#")[-1]
        if "/" in iri:
            return iri.rstrip("/").split("/")[-1]
        return getattr(cls_obj, "name", str(cls_obj))

    hermit_ancestors: dict[str, set[str]] = {}
    for row in rows:
        r = dict(row)
        if r.get("status") == "proposed":
            continue  # proposed nodes are not in the reasoned Turtle
        cls_name = _to_pascal_case(r["cluster_label"])
        owl_cls  = world.search_one(iri=f"{COPI_NS}{cls_name}")
        if owl_cls is None:
            hermit_ancestors[cls_name] = set()
            continue
        try:
            ancestors = set()
            for anc in owl_cls.ancestors():
                if anc is owl_cls:
                    continue
                local = _local(anc)
                if local in ("Thing", "Nothing", ""):
                    continue
                ancestors.add(local)
            hermit_ancestors[cls_name] = ancestors
        except Exception:
            hermit_ancestors[cls_name] = set()

    # ── 4. Build graph nodes and edges (from DB metadata) ────────────────────
    nodes: dict[str, dict] = {}
    edge_set: set[tuple]   = set()

    def add_node(node_id: str, **kwargs) -> None:
        # Enriched nodes always take precedence; genus/bfo_root nodes never overwrite them.
        if node_id not in nodes:
            nodes[node_id] = {"id": node_id, **kwargs}
        elif kwargs.get("node_type") == "enriched" and nodes[node_id].get("node_type") != "enriched":
            nodes[node_id] = {"id": node_id, **kwargs}

    def add_edge(src: str, tgt: str, etype: str) -> None:
        if src and tgt and src != tgt:
            edge_set.add((src, tgt, etype))

    # Pass 1 — pre-register every enriched node so genus references can never overwrite them.
    _row_data: list[dict] = []
    for row in rows:
        e          = dict(row)
        cls        = _to_pascal_case(e["cluster_label"])
        genus      = _to_pascal_case(e.get("genus") or "MaterialArtifact")
        genus_root = e.get("genus_bfo_root") or "MaterialArtifact"
        if genus_root not in BFO_ROOTS:
            genus_root = "MaterialArtifact"
        func = _to_pascal_case(e.get("function_name") or "")
        proc = _to_pascal_case(e.get("process_name")  or "")
        mode = e.get("axiom_mode") or "necessary"

        try:
            parts = json.loads(e["necessary_parts"]) if e.get("necessary_parts") else []
        except Exception:
            parts = []
        try:
            disjoint = json.loads(e["disjoint_with"]) if e.get("disjoint_with") else []
        except Exception:
            disjoint = []

        part_classes     = [_to_pascal_case(p["name"]) for p in parts
                            if isinstance(p, dict) and p.get("name")]
        disjoint_classes = [_to_pascal_case(d) for d in disjoint if d]

        d2 = dict(e,
            _cls=cls, _genus=genus, _genus_root=genus_root,
            _func=func, _proc=proc, _mode=mode,
            _parts=part_classes, _disjoint=disjoint_classes,
        )
        _row_data.append(d2)

        enr_status = e.get("status", "validated")
        nodes[cls] = {
            "id": cls,
            "label": e["cluster_label"],
            "node_type": "proposed" if enr_status == "proposed" else "enriched",
            "status": enr_status,
            "axiom_mode": mode,
            "enrichment_id": e["id"],
            "genus": genus,
            "genus_root": genus_root,
            "function": func,
            "function_name": e.get("function_name") or "",
            "function_parent": e.get("function_parent") or "DesignedFunction",
            "function_rationale": e.get("function_rationale") or "",
            "process_name": e.get("process_name") or "",
            "process_parent": e.get("process_parent") or "PlannedProcess",
            "differentia_nl": e.get("differentia_nl") or "",
            "process_signature": e.get("process_signature") or "{}",
            "necessary_parts_raw": parts,
            "process": proc,
            "parts": part_classes,
            "disjoint_with": disjoint_classes,
            "definition_en": e.get("nl_definition_en") or "",
            "definition_pt": e.get("nl_definition_pt") or "",
        }

    # Pass 2 — build genus/function/process/part nodes and all edges.
    for d2 in _row_data:
        cls            = d2["_cls"]
        genus          = d2["_genus"]
        genus_root     = d2["_genus_root"]
        func           = d2["_func"]
        proc           = d2["_proc"]
        mode           = d2["_mode"]
        part_classes   = d2["_parts"]
        disjoint_classes = d2["_disjoint"]

        if genus in nodes and nodes[genus]["node_type"] == "enriched":
            # Genus is itself an enriched COPI class — no intermediate genus node needed.
            pass
        elif genus not in BFO_ROOTS:
            add_node(genus, label=genus, node_type="genus", genus_root=genus_root)
            add_node(genus_root, label=genus_root, node_type="bfo_root")
            add_edge(genus, genus_root, "subClassOf")
        else:
            add_node(genus, label=genus, node_type="bfo_root")
        sub_op = "equivalentClass" if mode == "equivalent" else "subClassOf"
        add_edge(cls, genus, sub_op)

        if func:
            func_parent = _to_pascal_case(d2.get("function_parent") or "") or "DesignedFunction"
            add_node(func, label=func, node_type="function")
            add_node("DesignedFunction", label="DesignedFunction", node_type="bfo_root")
            if func_parent and func_parent != func:
                if func_parent != "DesignedFunction":
                    add_node(func_parent, label=func_parent, node_type="function")
                    add_edge(func_parent, "DesignedFunction", "subClassOf")
                add_edge(func, func_parent, "subClassOf")
            else:
                add_edge(func, "DesignedFunction", "subClassOf")
            add_edge(cls, func, "hasFunction")
        if proc:
            proc_parent = _to_pascal_case(d2.get("process_parent") or "") or "PlannedProcess"
            add_node(proc, label=proc, node_type="process")
            add_node("PlannedProcess", label="PlannedProcess", node_type="bfo_root")
            if proc_parent and proc_parent != proc and proc_parent != "PlannedProcess":
                add_node(proc_parent, label=proc_parent, node_type="process")
                add_edge(proc_parent, "PlannedProcess", "subClassOf")
                add_edge(proc, proc_parent, "subClassOf")
            else:
                add_edge(proc, "PlannedProcess", "subClassOf")
            if func:
                add_edge(func, proc, "realizedIn")

        for part in part_classes:
            add_node(part, label=part, node_type="part")
            add_edge(cls, part, "hasPart")

        for d in disjoint_classes:
            edge_set.add(tuple(sorted([cls, d])) + ("disjointWith",))

    # ── 4b. IOF-Core internal hierarchy edges ─────────────────────────────────
    # These are fixed axioms from IOF-Core 2.0 that are not derivable from the
    # enrichment data but must be visible in the graph.
    add_edge("Assembly", "MaterialArtifact", "subClassOf")
    add_edge("EngineeredSystem", "MaterialArtifact", "subClassOf")

    # ── 5. Assemble individuals using HermiT inferences ───────────────────────
    KNOWN_ROOTS = {"MaterialArtifact", "Assembly", "EngineeredSystem",
                   "DesignedFunction", "PlannedProcess"}

    individuals = []
    for cls_id, cls_node in nodes.items():
        if cls_node["node_type"] not in ("enriched", "proposed"):
            continue

        is_proposed = cls_node.get("status") == "proposed"
        ancestors = set() if is_proposed else hermit_ancestors.get(cls_id, set())

        violations = []
        if not is_proposed:
            if not consistent:
                violations.append({"class": "owl:Nothing", "reason": "ontology is inconsistent"})
            else:
                for d in cls_node.get("disjoint_with", []):
                    if d in ancestors:
                        violations.append({"class": d, "reason": "disjoint ancestor inferred"})
                for other_id, other_node in nodes.items():
                    if other_node["node_type"] == "enriched" and other_id != cls_id:
                        if cls_id in other_node.get("disjoint_with", []) and other_id in ancestors:
                            violations.append({"class": other_id, "reason": "reverse disjoint ancestor"})

        individuals.append({
            "class": cls_id,
            "label": cls_node["label"],
            "status": cls_node.get("status", "validated"),
            "axiom_mode": cls_node.get("axiom_mode"),
            "enrichment_id": cls_node.get("enrichment_id"),
            "definition_en": cls_node.get("definition_en", ""),
            "definition_pt": cls_node.get("definition_pt", ""),
            "function_name": cls_node.get("function_name", ""),
            "function_parent": cls_node.get("function_parent", "DesignedFunction"),
            "function_rationale": cls_node.get("function_rationale", ""),
            "process_name": cls_node.get("process_name", ""),
            "process_parent": cls_node.get("process_parent", "PlannedProcess"),
            "differentia_nl": cls_node.get("differentia_nl", ""),
            "process_signature": cls_node.get("process_signature", "{}"),
            "necessary_parts": cls_node.get("necessary_parts_raw", []),
            "inferred_types": sorted(ancestors - KNOWN_ROOTS),
            "inferred_roots":  sorted(ancestors & KNOWN_ROOTS),
            "violations": violations,
        })

    edges = [
        {"source": src, "target": tgt, "edge_type": etype}
        for src, tgt, etype in edge_set
        if src in nodes and tgt in nodes
    ]

    total = len([n for n in nodes.values() if n["node_type"] == "enriched"])
    equiv = len([n for n in nodes.values()
                 if n["node_type"] == "enriched" and n.get("axiom_mode") == "equivalent"])
    viol  = sum(len(i["violations"]) for i in individuals)

    return {
        "nodes":       list(nodes.values()),
        "edges":       edges,
        "individuals": individuals,
        "stats": {
            "total_classes":      total,
            "equivalent_classes": equiv,
            "necessary_classes":  total - equiv,
            "consistent":         consistent and viol == 0,
            "violation_count":    viol,
            "reasoner":           "HermiT (owlready2)",
        },
    }


# ---------------------------------------------------------------------------
# Validate: Q&A context builder
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Annotations
# ---------------------------------------------------------------------------

def list_annotations(enrichment_id: int) -> list[dict]:
    conn = get_enrichment_db()
    rows = conn.execute(
        "SELECT * FROM annotations WHERE enrichment_id = ? ORDER BY field, created_at",
        (enrichment_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_annotation(enrichment_id: int, field: str | None, author: str, body: str) -> dict:
    conn = get_enrichment_db()
    cur = conn.execute(
        "INSERT INTO annotations (enrichment_id, field, author, body) VALUES (?,?,?,?)",
        (enrichment_id, field or None, author.strip() or "anonymous", body.strip())
    )
    row = conn.execute("SELECT * FROM annotations WHERE id = ?", (cur.lastrowid,)).fetchone()
    conn.commit()
    conn.close()
    return dict(row)


def resolve_annotation(ann_id: int, resolved_by: str) -> dict:
    conn = get_enrichment_db()
    conn.execute(
        "UPDATE annotations SET resolved=1, resolved_by=?, updated_at=datetime('now') WHERE id=?",
        (resolved_by or "anonymous", ann_id)
    )
    row = conn.execute("SELECT * FROM annotations WHERE id = ?", (ann_id,)).fetchone()
    conn.commit()
    conn.close()
    return dict(row)


def delete_annotation(ann_id: int) -> None:
    conn = get_enrichment_db()
    conn.execute("DELETE FROM annotations WHERE id = ?", (ann_id,))
    conn.commit()
    conn.close()


def get_open_annotation_counts() -> dict[int, int]:
    """Return {enrichment_id: unresolved_count} for all enrichments with open annotations."""
    conn = get_enrichment_db()
    rows = conn.execute(
        "SELECT enrichment_id, COUNT(*) as cnt FROM annotations WHERE resolved=0 GROUP BY enrichment_id"
    ).fetchall()
    conn.close()
    return {r["enrichment_id"]: r["cnt"] for r in rows}


# ---------------------------------------------------------------------------
# Q&A usage log
# ---------------------------------------------------------------------------

def log_qa_usage(question: str, input_tokens: int, output_tokens: int,
                 cost: float, model: str) -> None:
    conn = get_enrichment_db()
    conn.execute(
        "INSERT INTO qa_log (question, input_tokens, output_tokens, estimated_cost_usd, llm_model)"
        " VALUES (?,?,?,?,?)",
        (question[:500], input_tokens, output_tokens, cost, model)
    )
    conn.commit()
    conn.close()


def list_qa_log() -> list[dict]:
    conn = get_enrichment_db()
    rows = conn.execute(
        "SELECT * FROM qa_log ORDER BY created_at DESC LIMIT 200"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# COPI class names (for domain/range pickers)
# ---------------------------------------------------------------------------

def get_copi_class_names() -> list[str]:
    conn = get_enrichment_db()
    rows = conn.execute(
        "SELECT DISTINCT cluster_label FROM enrichment ORDER BY cluster_label"
    ).fetchall()
    conn.close()
    return [r["cluster_label"] for r in rows]


_BFO_IOF_CONTEXT = """\
## BFO 2020 — Basic Formal Ontology (upper-level)

BFO divides entities into **Continuants** (exist wholly at each time) and **Occurrents** (unfold over time).

Key Continuant branches relevant to COPI:
- **bfo:MaterialEntity** — has mass; concrete physical object
  - **bfo:Object** — maximally self-connected material entity (e.g. a pump, a valve)
  - **bfo:ObjectAggregate** — collection of objects (e.g. a processing train)
  - **bfo:Fiat Object Part** — designated portion of an object (e.g. a flange)
- **bfo:IndependentContinuant** — exists independently (includes MaterialEntity + Site + SpatialRegion)
- **bfo:SpecificallyDependentContinuant** — depends on a bearer for existence
  - **bfo:Quality** — e.g. temperature, pressure of a fluid
  - **bfo:RealizableEntity** — can be realised in a process
    - **bfo:Disposition** — tendency (e.g. tendency to corrode)
    - **bfo:Function** — proper function: what the entity was designed to do

Key Occurrent branches:
- **bfo:Process** — occurs over time, has participants
- **bfo:ProcessBoundary** — instantaneous boundary of a process
- **bfo:TemporalRegion** / **bfo:SpatialRegion** — regions

OWL 2 DL note: BFO uses OWL 2 DL; existential restrictions use owl:someValuesFrom;
universal restrictions use owl:allValuesFrom.

---

## IOF-Core Release_202603 — Industrial Ontology Foundry Core

IOF-Core extends BFO 2020 with industrial mid-level concepts.

Key classes (all are subclasses of BFO classes):
- **iof-core:MaterialArtifact** ⊑ bfo:Object — physical artifact intentionally made
- **iof-core:Assembly** ⊑ bfo:Object — artifact that is an assembled combination of parts;
  can be disassembled without destroying the parts (pump unit, heat exchanger)
- **iof-core:EngineeredSystem** ⊑ bfo:ObjectAggregate — system-of-systems or
  sociotechnical system; disjoint from Assembly and MaterialArtifact
- **iof-core:DesignedFunction** ⊑ bfo:Function — function an artifact was designed to realise
- **iof-core:PlannedProcess** ⊑ bfo:Process — process carried out according to a plan;
  the type of process a DesignedFunction is realised in
- **iof-core:FunctionalPart** ⊑ bfo:Object — part of an artifact that has its own function
- **iof-core:MaintenanceTask** ⊑ iof-core:PlannedProcess — planned maintenance process

Key object properties in IOF-Core:
- **iof-core:hasFunction** — links an artifact to its DesignedFunction
- **iof-core:isRealizedIn** — links a Function to the PlannedProcess that realises it
- **iof-core:hasComponentPartAtAllTimes** — mereological: X has Y as a permanent component

COPI axiom patterns:
- Equipment classes use **equivalent** axioms (≡) for functional classification:
  X ≡ MaterialArtifact ⊓ ∃hasFunction.XFunction
  (this is a "defined class" — the reasoner can classify instances automatically)
- Constructive subtypes use **subClassOf** (⊑) — necessary conditions only;
  OWA means equivalence would produce false positives
- The genus is the most specific known IOF-Core or COPI superclass, not just Assembly

---
"""


def build_qa_context() -> str:
    """Build a structured ontology context string for Q&A LLM calls."""
    conn = get_enrichment_db()
    rows = conn.execute(
        "SELECT * FROM enrichment WHERE status IN ('validated','exported') ORDER BY cluster_label"
    ).fetchall()
    conn.close()

    ctx  = _BFO_IOF_CONTEXT
    ctx += "# COPI — Core Ontology for Petroleum Installations\n"
    ctx += "OWL 2 DL ontology based on BFO 2020 and IOF-Core.\n"
    ctx += "Domain: material artifacts in petroleum production plants.\n\n"

    if not rows:
        ctx += "No validated classes in the ontology yet.\n"
        return ctx

    ctx += "## Validated COPI Classes\n\n"

    for row in rows:
        e = dict(row)
        cls_name = _to_pascal_case(e["cluster_label"])
        mode = e.get("axiom_mode") or "necessary"
        ctx += f"### copi:{cls_name}  ({e['cluster_label']})\n"
        ctx += f"- Axiom mode: **{mode}** "
        ctx += ("(defined class — sufficient AND necessary conditions)\n"
                if mode == "equivalent"
                else "(primitive class — necessary conditions only; OWA applies)\n")
        if e.get("genus"):
            ctx += f"- Genus (direct superclass): {e['genus']}\n"
        if e.get("genus_bfo_root"):
            ctx += f"- BFO root: {e['genus_bfo_root']}\n"
        if e.get("nl_definition_en"):
            ctx += f"- Definition (EN): {e['nl_definition_en']}\n"
        if e.get("nl_definition_pt"):
            ctx += f"- Definition (PT): {e['nl_definition_pt']}\n"
        if e.get("function_name"):
            ctx += f"- Identity-giving function: {e['function_name']}\n"
        if e.get("process_name"):
            ctx += f"- Realized in: {e['process_name']}\n"
        try:
            parts = json.loads(e["necessary_parts"]) if e.get("necessary_parts") else []
            part_names = [p["name"] for p in parts if isinstance(p, dict) and p.get("name")]
            if part_names:
                ctx += f"- Necessary parts (owl:someValuesFrom): {', '.join(part_names)}\n"
        except Exception:
            pass
        try:
            disjoint = json.loads(e["disjoint_with"]) if e.get("disjoint_with") else []
            if disjoint:
                ctx += f"- Disjoint with: {', '.join(disjoint)}\n"
        except Exception:
            pass
        try:
            custom = json.loads(e["custom_axioms"]) if e.get("custom_axioms") else []
            for ax in custom:
                t = (ax.get("turtle") or "").strip()
                if t:
                    ctx += f"- Custom axiom: `{t}`\n"
        except Exception:
            pass
        if e.get("differentia_expression"):
            ctx += f"- Differentia: {e['differentia_expression']}\n"
        ctx += "\n"

    rels = [r for r in list_relations() if r.get("status") in ("validated", "exported")]
    if rels:
        ctx += "## Object/Datatype Properties\n\n"
        for rel in rels:
            ctx += f"- **copi:{rel['name']}** ({rel.get('prop_type','ObjectProperty')})"
            if rel.get("domain"):
                ctx += f" — domain: {rel['domain']}"
            if rel.get("range_type"):
                ctx += f", range: {rel['range_type']}"
            if rel.get("definition_en"):
                ctx += f" — {rel['definition_en']}"
            ctx += "\n"

    return ctx


# ---------------------------------------------------------------------------
# Validate: Test cases (intended-model checking)
# ---------------------------------------------------------------------------

def list_validate_tests() -> list[dict]:
    conn = get_enrichment_db()
    rows = conn.execute(
        "SELECT * FROM validate_tests ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    tests = []
    for r in rows:
        d = dict(r)
        for field in ("extra_classes", "expected_inferred", "expected_not_inferred"):
            try:
                d[field] = json.loads(d.get(field) or "[]")
            except Exception:
                d[field] = []
        if d.get("result_detail"):
            try:
                d["result_detail"] = json.loads(d["result_detail"])
            except Exception:
                pass
        tests.append(d)
    return tests


def create_validate_test(data: dict) -> dict:
    conn = get_enrichment_db()
    conn.execute(
        """INSERT INTO validate_tests
           (name, description, individual_class, extra_classes,
            expected_inferred, expected_not_inferred, expect_inconsistent)
           VALUES (?,?,?,?,?,?,?)""",
        (
            data["name"],
            data.get("description") or None,
            data["individual_class"],
            json.dumps(data.get("extra_classes") or []),
            json.dumps(data.get("expected_inferred") or []),
            json.dumps(data.get("expected_not_inferred") or []),
            1 if data.get("expect_inconsistent") else 0,
        ),
    )
    conn.commit()
    row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return {"id": row_id}


def delete_validate_test(test_id: int) -> None:
    conn = get_enrichment_db()
    conn.execute("DELETE FROM validate_tests WHERE id = ?", (test_id,))
    conn.commit()
    conn.close()


def run_validate_test(test_id: int) -> dict:
    """Run a single test case against HermiT and save the result."""
    import os
    import tempfile
    import owlready2
    import rdflib

    conn = get_enrichment_db()
    row = conn.execute(
        "SELECT * FROM validate_tests WHERE id = ?", (test_id,)
    ).fetchone()
    conn.close()
    if not row:
        return {"result": "error", "error": "Test not found"}

    test = dict(row)
    try:
        expected_inf     = json.loads(test.get("expected_inferred")     or "[]")
        expected_not_inf = json.loads(test.get("expected_not_inferred") or "[]")
        extra_classes    = json.loads(test.get("extra_classes")         or "[]")
    except Exception:
        expected_inf = expected_not_inf = extra_classes = []

    expect_incons = bool(test.get("expect_inconsistent"))
    cls_name = _to_pascal_case(test["individual_class"])
    ind_id   = f"testInd{test_id}"

    # Build individual Turtle block
    extra_types = "".join(
        f",\n    copi:{_to_pascal_case(ec)}" for ec in extra_classes
    )
    ind_ttl = (
        f"\n# --- validate_test {test_id}: {test['name']} ---\n"
        f"copi:{ind_id} rdf:type owl:NamedIndividual ,\n"
        f"    copi:{cls_name}{extra_types} .\n"
    )
    full_ttl = generate_combined_turtle() + ind_ttl

    # Parse TTL → RDF/XML for owlready2
    g = rdflib.Graph()
    try:
        g.parse(data=full_ttl, format="turtle")
    except Exception as exc:
        return {"result": "error", "error": f"Turtle parse error: {exc}"}

    rdfxml = g.serialize(format="xml")
    fd, owl_path = tempfile.mkstemp(suffix=".owl")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(rdfxml)

        world = owlready2.World()
        onto  = world.get_ontology(f"file://{owl_path}").load()

        consistent = True
        try:
            with onto:
                owlready2.sync_reasoner_hermit(world, infer_property_values=False)
        except owlready2.OwlReadyInconsistentOntologyError:
            consistent = False

        if not consistent:
            result   = "pass" if expect_incons else "fail"
            failures = [] if expect_incons else ["Ontology became inconsistent (not expected)"]
            detail   = {"inferred": [], "failures": failures, "inconsistent": True}
        else:
            ind = world.search_one(iri=f"{COPI_NS}{ind_id}")
            if ind is None:
                return {"result": "error", "error": "Individual not found after reasoning"}

            inferred: set[str] = set()
            for cls_obj in list(ind.is_a) + list(ind.INDIRECT_is_a):
                loc = _local(cls_obj)
                if loc and loc not in ("Thing", "Nothing", ""):
                    inferred.add(loc)

            failures = []
            for exp in expected_inf:
                if _to_pascal_case(exp) not in inferred:
                    failures.append(f"Expected '{exp}' to be inferred — not found")
            for exp in expected_not_inf:
                if _to_pascal_case(exp) in inferred:
                    failures.append(f"Expected '{exp}' NOT to be inferred — but it was")
            if expect_incons:
                failures.append("Expected inconsistency — but ontology is consistent")

            result = "pass" if not failures else "fail"
            detail = {
                "inferred":     sorted(inferred),
                "failures":     failures,
                "inconsistent": False,
            }

        conn = get_enrichment_db()
        conn.execute(
            "UPDATE validate_tests SET last_result=?, result_detail=?, last_run_at=datetime('now') WHERE id=?",
            (result, json.dumps(detail), test_id),
        )
        conn.commit()
        conn.close()
        return {"result": result, **detail}

    finally:
        try:
            os.unlink(owl_path)
        except OSError:
            pass


# ── Static documentation generator ────────────────────────────────────────────
# Produces self-contained HTML files that mirror the live /enrich/docs pages.
# Output: dict[relative_path, html_str] — caller commits them to GitHub.

def _h(v) -> str:
    """HTML-escape a value (returns '' for None)."""
    import html as _html_mod
    return _html_mod.escape(str(v)) if v is not None else ""


def _bi(en: str, pt: str) -> str:
    """Return a bilingual span pair — EN visible by default; PT shown when html.lang-pt is active."""
    return f'<span class="t-en">{en}</span><span class="t-pt">{pt}</span>'


def _copi_label(cid: int | None) -> str:
    return f"COPI_{cid:07d}" if cid else ""


# Compact hex-badge inline SVG (36px) used in the navbar of static docs
_NAV_BADGE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="14 8 80 92" width="28" height="34"'
    ' style="vertical-align:middle;margin-right:.35rem;flex-shrink:0;">'
    '<polygon points="54,8 93.8,31 93.8,77 54,100 14.2,77 14.2,31" fill="#0e2040"/>'
    '<g stroke="#38bdf8" stroke-width="1" stroke-opacity="0.45" fill="none">'
    '<line x1="54" y1="27" x2="54" y2="54"/>'
    '<line x1="77.4" y1="40.5" x2="54" y2="54"/>'
    '<line x1="77.4" y1="67.5" x2="54" y2="54"/>'
    '<line x1="54" y1="81" x2="54" y2="54"/>'
    '<line x1="30.6" y1="67.5" x2="54" y2="54"/>'
    '<line x1="30.6" y1="40.5" x2="54" y2="54"/>'
    '</g>'
    '<circle cx="54" cy="54" r="10" fill="#07101e" stroke="#2563eb" stroke-width="1.6"/>'
    '<path d="M 54,45 C 60,48 60,52 60,53 A 6,6 0 0,1 48,53 C 48,52 48,48 54,45 Z" fill="#f59e0b"/>'
    '<polygon points="54,8 93.8,31 93.8,77 54,100 14.2,77 14.2,31"'
    ' fill="none" stroke="#2563eb" stroke-width="2" stroke-opacity="0.72"/>'
    '</svg>'
)


_STATIC_BOOTSTRAP = (
    '<link rel="stylesheet" '
    'href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" '
    'integrity="sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH" '
    'crossorigin="anonymous">'
)

_STATIC_SHARED_CSS = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Serif:ital,wght@0,400;0,600;1,400&display=swap');
  :root{
    --accent:#1e3a5f;--accent2:#2563eb;--border:#dee2e6;--muted:#6c757d;--light:#f8fafc;
    /* Layer identity colours — used for section headers, card left borders, and TOC indicators */
    --layer-core:#1e3a5f;   /* copi-core:  deep navy — foundational taxonomy */
    --layer-vocab:#0f766e;  /* copi-vocab: teal      — semantic vocabulary  */
    --layer-leaf:#b45309;   /* leaf classes: amber   — concrete, material   */
  }
  body{font-family:'IBM Plex Serif','Georgia',serif;background:#fff;color:#1a1a1a;font-size:15px;}
  a{color:var(--accent2);}
  .doc-nav{background:var(--accent);color:white;padding:.6rem 0;
           font-family:system-ui,sans-serif;font-size:.85rem;}
  .doc-nav a{color:rgba(255,255,255,.75);text-decoration:none;}
  .doc-nav a:hover{color:white;}
  /* ── Hero: engineering data-sheet style, not SaaS landing ─────────── */
  .doc-hero{background:linear-gradient(160deg,#0a1628 0%,#0f2040 55%,#0a1628 100%);
            color:white;padding:2rem 2rem 1.75rem;border-radius:4px;margin-bottom:2rem;
            border-top:3px solid #2563eb;}
  .onto-eyebrow{font-family:'IBM Plex Mono','Courier New',monospace;font-size:.68rem;
                font-weight:600;letter-spacing:.18em;text-transform:uppercase;
                color:rgba(255,255,255,.4);margin-bottom:.5rem;}
  .onto-title{font-family:system-ui,sans-serif;font-size:2.8rem;font-weight:800;letter-spacing:-.04em;
              line-height:1;}
  .onto-subtitle{font-size:1rem;color:rgba(255,255,255,.55);font-weight:300;margin-top:.3rem;}
  .onto-iri{font-family:'IBM Plex Mono','Courier New',monospace;font-size:.88rem;
            color:rgba(255,255,255,.75);margin-top:1rem;letter-spacing:.01em;
            padding:.4rem .7rem;background:rgba(255,255,255,.07);border-radius:4px;
            display:inline-block;border-left:3px solid #2563eb;}
  .hero-meta-strip{display:flex;flex-wrap:wrap;gap:.5rem 1.5rem;margin-top:1rem;
                   font-family:'IBM Plex Mono','Courier New',monospace;
                   font-size:.72rem;color:rgba(255,255,255,.45);}
  .hero-meta-strip strong{color:rgba(255,255,255,.75);font-weight:600;}
  .hero-pill{display:inline-block;background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.18);
             border-radius:3px;font-size:.7rem;font-family:'IBM Plex Mono','Courier New',monospace;
             padding:.15rem .55rem;color:rgba(255,255,255,.65);}
  /* ── Language toggle: segmented EN/PT control ──────────────────────── */
  .lang-toggle{display:flex;align-items:center;gap:2px;background:rgba(255,255,255,.1);
               border-radius:5px;padding:2px;}
  .lang-seg{background:transparent;border:none;color:rgba(255,255,255,.5);
            padding:.15rem .55rem;font-family:system-ui,sans-serif;font-size:.72rem;
            font-weight:700;letter-spacing:.06em;border-radius:3px;cursor:pointer;
            transition:background .15s,color .15s;}
  .lang-seg.active{background:rgba(255,255,255,.2);color:white;}
  .lang-seg:hover:not(.active){color:rgba(255,255,255,.8);}
  .lang-toggle-label{font-family:system-ui,sans-serif;font-size:.65rem;font-weight:600;
                     text-transform:uppercase;letter-spacing:.1em;color:rgba(255,255,255,.35);
                     margin-right:.4rem;}
  .index-table th{font-family:system-ui,sans-serif;font-size:.72rem;font-weight:700;
                  text-transform:uppercase;letter-spacing:.07em;color:var(--muted);
                  background:var(--light);border-bottom:2px solid var(--border);}
  .index-table td{font-size:.875rem;vertical-align:middle;border-bottom:1px solid var(--border);}
  .class-link{font-family:system-ui,sans-serif;font-weight:600;color:var(--accent2);text-decoration:none;}
  .class-link:hover{text-decoration:underline;}
  .bfo-pill{font-size:.68rem;font-family:monospace;background:#eff6ff;border:1px solid #bfdbfe;
            border-radius:4px;padding:.1rem .4rem;color:#1d4ed8;}
  .mode-pill{font-size:.68rem;font-family:system-ui,sans-serif;font-weight:600;text-transform:uppercase;
             letter-spacing:.05em;border-radius:4px;padding:.1rem .45rem;}
  .mode-equivalent{background:#dcfce7;color:#166534;}
  .mode-necessary{background:#fef3c7;color:#92400e;}
  .mode-mixed{background:#f3e8ff;color:#6b21a8;}
  .bfo-section{margin-bottom:3rem;}
  .bfo-section-header{font-family:system-ui,sans-serif;font-size:.72rem;font-weight:700;
                      text-transform:uppercase;letter-spacing:.1em;color:var(--muted);
                      border-bottom:2px solid var(--border);padding-bottom:.5rem;margin-bottom:1.5rem;
                      display:flex;align-items:center;justify-content:space-between;}
  .count-badge{background:var(--light);border:1px solid var(--border);border-radius:20px;
               padding:.15rem .6rem;font-size:.68rem;font-weight:600;color:var(--muted);}
  .class-card{border:1px solid var(--border);border-radius:8px;margin-bottom:1.5rem;overflow:hidden;}
  .class-card-header{padding:.85rem 1.1rem .7rem;background:var(--light);border-bottom:1px solid var(--border);
                     display:flex;align-items:flex-start;justify-content:space-between;gap:1rem;}
  .class-card-name{font-family:system-ui,sans-serif;font-size:1.1rem;font-weight:700;color:var(--accent);}
  .class-card-name a{color:var(--accent);text-decoration:none;}
  .class-card-name a:hover{color:var(--accent2);text-decoration:underline;}
  .class-iri{font-family:monospace;font-size:.72rem;color:var(--muted);}
  .class-card-body{padding:.85rem 1.1rem;display:flex;gap:1.5rem;align-items:flex-start;}
  .class-def{font-size:.9rem;color:#374151;line-height:1.6;font-style:italic;margin-bottom:.6rem;}
  .class-meta{display:flex;flex-wrap:wrap;gap:.75rem;font-family:system-ui,sans-serif;font-size:.8rem;}
  .meta-item{color:var(--muted);}
  .meta-item strong{color:#374151;}
  .rel-card{border:1px solid var(--border);border-radius:6px;margin-bottom:.75rem;overflow:hidden;}
  .rel-card-header{padding:.6rem .9rem;background:var(--light);border-bottom:1px solid var(--border);
                   display:flex;align-items:center;gap:.75rem;}
  .rel-name{font-family:monospace;font-size:.95rem;font-weight:700;color:var(--accent);}
  .rel-type-pill{font-size:.65rem;font-family:system-ui,sans-serif;font-weight:700;text-transform:uppercase;
                 letter-spacing:.05em;border-radius:4px;padding:.1rem .45rem;background:#ede9fe;color:#5b21b6;}
  .rel-card-body{padding:.6rem .9rem;font-family:system-ui,sans-serif;font-size:.83rem;}
  .rel-meta{display:flex;flex-wrap:wrap;gap:1rem;color:var(--muted);}
  .rel-meta strong{color:#374151;}
  .toc-sticky{position:sticky;top:1rem;}
  .toc-link{display:block;font-family:system-ui,sans-serif;font-size:.82rem;color:var(--accent);
            text-decoration:none;padding:.2rem .5rem;border-left:2px solid var(--border);margin-bottom:.15rem;}
  .toc-link:hover{color:var(--accent2);border-left-color:var(--accent2);}
  .toc-header{font-family:system-ui,sans-serif;font-size:.65rem;font-weight:700;text-transform:uppercase;
              letter-spacing:.1em;color:var(--muted);margin-bottom:.5rem;}
  /* Per-class page */
  .ph-hero{border-bottom:3px solid var(--accent);padding:2rem 0 1.5rem;margin-bottom:2rem;}
  .ph-class-name{font-size:2.4rem;font-weight:700;letter-spacing:-.03em;
                 font-family:system-ui,sans-serif;color:var(--accent);}
  .ph-class-iri{font-family:monospace;font-size:.85rem;color:var(--muted);word-break:break-all;}
  .status-pill{font-size:.72rem;font-family:system-ui,sans-serif;font-weight:600;padding:.2rem .7rem;
               border-radius:20px;text-transform:uppercase;letter-spacing:.06em;}
  .status-validated{background:#dcfce7;color:#166534;}
  .status-exported{background:#f3e8ff;color:#6b21a8;}
  .status-reviewed{background:#dbeafe;color:#1e40af;}
  .status-proposed{background:#fef3c7;color:#92400e;}
  .doc-section{margin-bottom:2.5rem;}
  .doc-section-title{font-family:system-ui,sans-serif;font-size:.72rem;font-weight:700;text-transform:uppercase;
                     letter-spacing:.1em;color:var(--muted);border-bottom:1px solid var(--border);
                     padding-bottom:.4rem;margin-bottom:1rem;}
  .nl-def{font-size:1.08rem;font-style:italic;color:#1a1a1a;border-left:4px solid var(--accent2);
          padding:.6rem 1rem;margin-bottom:.75rem;background:#f8faff;}
  .nl-def .lang-tag{font-size:.7rem;font-family:monospace;font-style:normal;color:var(--muted);margin-bottom:.2rem;}
  .axiom-block{background:#f8f9fa;border:1px solid var(--border);border-radius:6px;
               padding:.9rem 1rem;margin-bottom:.75rem;font-size:.88rem;}
  .axiom-label{font-family:system-ui,sans-serif;font-size:.68rem;font-weight:700;text-transform:uppercase;
               letter-spacing:.08em;color:var(--muted);margin-bottom:.3rem;}
  .owl-block{background:#1e293b;color:#e2e8f0;border-radius:8px;padding:1rem 1.2rem;
             font-family:'JetBrains Mono','Fira Code','Courier New',monospace;font-size:.78rem;
             line-height:1.7;overflow-x:auto;white-space:pre;}
  .fol-line{font-family:monospace;font-size:.85rem;line-height:1.9;display:block;}
  .fol-label{font-family:system-ui,sans-serif;font-size:.68rem;font-weight:700;text-transform:uppercase;
             letter-spacing:.06em;color:var(--muted);margin-right:.5rem;}
  .step-block{border:1px solid var(--border);border-radius:8px;margin-bottom:1rem;overflow:hidden;}
  .step-block-header{display:flex;align-items:center;gap:.6rem;padding:.65rem 1rem;
                     font-family:system-ui,sans-serif;font-weight:600;font-size:.9rem;}
  .step-num{width:22px;height:22px;border-radius:50%;display:flex;align-items:center;
            justify-content:center;color:white;font-size:.7rem;font-weight:700;flex-shrink:0;}
  .step-1 .step-block-header{background:color-mix(in srgb,#2563eb 8%,white);border-bottom:2px solid #2563eb;}
  .step-1 .step-num{background:#2563eb;}
  .step-2 .step-block-header{background:color-mix(in srgb,#7c3aed 8%,white);border-bottom:2px solid #7c3aed;}
  .step-2 .step-num{background:#7c3aed;}
  .step-3 .step-block-header{background:color-mix(in srgb,#d97706 8%,white);border-bottom:2px solid #d97706;}
  .step-3 .step-num{background:#d97706;}
  .step-4 .step-block-header{background:color-mix(in srgb,#059669 8%,white);border-bottom:2px solid #059669;}
  .step-4 .step-num{background:#059669;}
  .step-body{padding:.9rem 1rem;}
  .decision-value{font-family:monospace;font-size:.9rem;background:#f1f5f9;padding:.15rem .5rem;
                  border-radius:4px;font-weight:600;}
  .rationale{margin-top:.6rem;font-size:.88rem;color:#374151;border-left:3px solid var(--border);padding-left:.75rem;}
  .disjoint-pill{display:inline-block;font-family:monospace;font-size:.8rem;padding:.2rem .6rem;
                 border-radius:4px;background:#fee2e2;color:#991b1b;margin:.15rem;}
  .parts-table{width:100%;font-size:.85rem;border-collapse:collapse;}
  .parts-table th{background:#f8f9fa;font-family:system-ui,sans-serif;font-size:.72rem;text-transform:uppercase;
                  letter-spacing:.05em;padding:.4rem .7rem;border:1px solid var(--border);font-weight:600;color:var(--muted);}
  .parts-table td{padding:.4rem .7rem;border:1px solid var(--border);font-family:monospace;}
  .sig-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:.75rem;}
  .sig-cell{border:1px solid var(--border);border-radius:6px;padding:.65rem .8rem;}
  .sig-cell-label{font-family:system-ui,sans-serif;font-size:.68rem;font-weight:700;text-transform:uppercase;
                  letter-spacing:.08em;color:var(--muted);margin-bottom:.3rem;}
  .bfo-badge{display:inline-block;font-family:monospace;font-size:.75rem;padding:.15rem .5rem;
             border-radius:4px;background:#eff6ff;color:#1d4ed8;border:1px solid #bfdbfe;}
  .meta-table{font-size:.8rem;font-family:system-ui,sans-serif;}
  .meta-table td:first-child{color:var(--muted);padding-right:1rem;white-space:nowrap;}
  .meta-table td{padding:.2rem 0;vertical-align:top;}
  /* Source definitions */
  .source-card{border:1px solid var(--border);border-radius:8px;margin-bottom:.75rem;overflow:hidden;}
  .source-card-header{display:flex;justify-content:space-between;align-items:center;padding:.5rem .9rem;
                      background:#f8f9fa;border-bottom:1px solid var(--border);font-family:system-ui,sans-serif;}
  .source-card-body{padding:.75rem .9rem;font-size:.88rem;}
  /* Layered-source provenance (tier / secondary_coverage / candidate_parts) */
  .tier-badge{display:inline-block;font-size:.68rem;font-weight:700;text-transform:uppercase;
              letter-spacing:.04em;padding:.1rem .5rem;border-radius:4px;color:#fff;}
  .tier-badge.tier-primary{background:#2563eb;}
  .tier-badge.tier-secondary{background:#64748b;}
  .tier-badge.tier-tertiary{background:#d97706;}
  .coverage-badge{display:inline-block;font-size:.68rem;padding:.1rem .5rem;border-radius:4px;color:#fff;}
  .coverage-badge.coverage-full{background:#16a34a;}
  .coverage-badge.coverage-partial{background:#d97706;}
  .coverage-badge.coverage-none{background:#94a3b8;}
  .provenance-row{font-size:.75rem;display:flex;gap:.4rem;align-items:baseline;flex-wrap:wrap;
                   margin-bottom:.35rem;}
  .provenance-quote{font-size:.78rem;color:#374151;margin:.15rem 0 .5rem 0;padding-left:.6rem;
                     border-left:2px solid var(--border);}
  .candidate-part-row{font-size:.78rem;margin-bottom:.3rem;}
  .conflict-banner{border-radius:8px;padding:.75rem 1rem;margin-bottom:1.25rem;font-size:.85rem;}
  .conflict-banner.has-conflict{background:#fef2f2;border:1px solid #fecaca;color:#b91c1c;}
  .conflict-banner.no-conflict{background:#f8fafc;border:1px dashed var(--border);color:var(--muted);}
  /* Click-to-reveal help icon — reusable anywhere a term needs a short explanation
     without cluttering the page by default. No JS: <details>/<summary>, same
     mechanism already used for "excluded definitions" elsewhere on this page. */
  .help-popover{display:inline-block;vertical-align:middle;margin-left:.3rem;}
  .help-popover summary{list-style:none;}
  .help-popover summary::-webkit-details-marker{display:none;}
  .help-icon{display:inline-flex;align-items:center;justify-content:center;width:1.05rem;height:1.05rem;
             border-radius:50%;background:var(--border);color:var(--muted);font-size:.68rem;
             font-weight:700;font-family:system-ui,sans-serif;cursor:pointer;user-select:none;}
  .help-icon:hover{background:#cbd5e1;color:#374151;}
  .help-popover[open] .help-icon{background:#64748b;color:#fff;}
  .help-content{display:block;font-size:.72rem;color:#374151;background:#f8fafc;
                border:1px solid var(--border);border-radius:6px;padding:.5rem .65rem;
                margin-top:.35rem;max-width:320px;line-height:1.45;font-family:system-ui,sans-serif;}
  @media (min-width:992px){.sidebar-sticky{position:sticky;top:1rem;}}
  @media print{.doc-nav,.no-print{display:none!important;}body{font-size:13px;}}
  /* Language toggle */
  html.lang-pt .t-en{display:none!important;}
  html:not(.lang-pt) .t-pt{display:none!important;}
  .scope-note{font-size:.88rem;color:#374151;border-left:4px solid #f59e0b;
              padding:.5rem .9rem;margin-bottom:.6rem;background:#fffbeb;border-radius:0 4px 4px 0;}
  /* ── Monospace upgrade: use IBM Plex Mono where JetBrains Mono was referenced */
  .owl-block{background:#0f1e35;color:#cfe2ff;border-radius:4px;padding:1rem 1.2rem;
             font-family:'IBM Plex Mono','JetBrains Mono','Fira Code','Courier New',monospace;
             font-size:.78rem;line-height:1.7;overflow-x:auto;white-space:pre;
             border-left:3px solid #2563eb;}
  /* ── Layer A: copi-core — navy ─────────────────────────────────────── */
  #copi-core-module .class-card{border-left:3px solid var(--layer-core);}
  #copi-core-module .rel-card{border-left:3px solid var(--layer-core);}
  #copi-core-module .bfo-section-header{border-bottom-color:var(--layer-core);color:var(--layer-core);}
  .toc-link[href="#copi-core-module"]{border-left-color:var(--layer-core);font-weight:600;}
  /* ── Layer B: copi-vocab — teal ────────────────────────────────────── */
  #copi-vocab-module .class-card{border-left:3px solid var(--layer-vocab);}
  #copi-vocab-module .rel-card{border-left:3px solid var(--layer-vocab);}
  #copi-vocab-module .bfo-section-header{border-bottom-color:var(--layer-vocab);color:var(--layer-vocab);}
  .toc-link[href="#copi-vocab-module"]{border-left-color:var(--layer-vocab);font-weight:600;}
  /* ── Layer C: leaf equipment — amber ───────────────────────────────── */
  #leaf-classes .class-card{border-left:3px solid var(--layer-leaf);}
  #leaf-classes .bfo-section-header{border-bottom-color:var(--layer-leaf);color:var(--layer-leaf);}
  .toc-link[href="#leaf-classes"]{border-left-color:var(--layer-leaf);font-weight:600;}
  /* ── Layer legend in TOC: coloured dot before each layer link ──────── */
  .toc-layer-dot{display:inline-block;width:7px;height:7px;border-radius:50%;
                 margin-right:.4rem;vertical-align:middle;flex-shrink:0;}
  /* ── Suggestion box: floating button opens a pre-filled GitHub issue ── */
  .suggest-fab{position:fixed;right:1.25rem;bottom:1.25rem;z-index:1000;
               background:var(--accent2);color:#fff;border:none;border-radius:999px;
               padding:.6rem 1.1rem;font-family:system-ui,sans-serif;font-size:.82rem;
               font-weight:600;box-shadow:0 4px 16px rgba(0,0,0,.25);cursor:pointer;
               display:flex;align-items:center;gap:.4rem;transition:transform .15s,box-shadow .15s;}
  .suggest-fab:hover{transform:translateY(-1px);box-shadow:0 6px 20px rgba(0,0,0,.3);}
  .suggest-modal-backdrop{display:none;position:fixed;inset:0;z-index:1001;
                          background:rgba(10,22,40,.55);align-items:center;justify-content:center;padding:1rem;}
  .suggest-modal{background:#fff;border-radius:8px;max-width:480px;width:100%;
                 padding:1.5rem 1.6rem;box-shadow:0 24px 60px rgba(0,0,0,.35);
                 font-family:system-ui,sans-serif;}
  .suggest-modal h3{font-family:system-ui,sans-serif;font-size:1.1rem;font-weight:700;margin-bottom:.3rem;}
  .suggest-modal-hint{font-size:.8rem;color:var(--muted);margin-bottom:1rem;}
  .suggest-modal label{display:block;font-size:.78rem;font-weight:600;color:#374151;
                       margin-bottom:.25rem;margin-top:.85rem;}
  .suggest-modal input,.suggest-modal textarea{width:100%;border:1px solid var(--border);
                       border-radius:5px;padding:.45rem .6rem;font-family:system-ui,sans-serif;
                       font-size:.85rem;resize:vertical;}
  .suggest-modal input:focus,.suggest-modal textarea:focus{outline:2px solid var(--accent2);
                       outline-offset:1px;}
  .suggest-modal-actions{display:flex;justify-content:flex-end;gap:.6rem;margin-top:1.25rem;}
  .suggest-btn-cancel{background:none;border:none;color:var(--muted);font-size:.82rem;
                      font-weight:600;cursor:pointer;padding:.5rem .7rem;}
  .suggest-btn-submit{background:var(--accent2);color:#fff;border:none;border-radius:5px;
                      font-size:.82rem;font-weight:600;cursor:pointer;padding:.5rem 1rem;}
  .suggest-btn-submit:hover{background:#1d4ed8;}
  @media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important;}}
</style>
"""

_SUGGESTION_BOX_HTML = """
<button id="suggestFab" class="suggest-fab no-print" onclick="openSuggestModal()"
        title="Suggest a change / Sugerir uma mudança">
  💬 <span class="t-en">Suggest a change</span><span class="t-pt">Sugerir mudança</span>
</button>
<div id="suggestBackdrop" class="suggest-modal-backdrop no-print"
     onclick="if(event.target===this)closeSuggestModal()">
  <div class="suggest-modal">
    <h3><span class="t-en">Suggest a change</span><span class="t-pt">Sugerir uma mudança</span></h3>
    <p class="suggest-modal-hint">
      <span class="t-en">Opens a pre-filled GitHub issue on the COPI repo — nothing is sent until you submit it there.</span>
      <span class="t-pt">Abre uma issue pré-preenchida no repositório do COPI — nada é enviado até você confirmar lá.</span>
    </p>
    <label for="suggestTitle"><span class="t-en">Title</span><span class="t-pt">Título</span></label>
    <input id="suggestTitle" type="text" maxlength="200"
           placeholder="e.g. Definition for X seems too narrow / p.ex. Definição de X parece restritiva demais">
    <label for="suggestBody"><span class="t-en">Description</span><span class="t-pt">Descrição</span></label>
    <textarea id="suggestBody" rows="5"
              placeholder="What would you change, and why? / O que você mudaria, e por quê?"></textarea>
    <div class="suggest-modal-actions">
      <button class="suggest-btn-cancel" onclick="closeSuggestModal()">
        <span class="t-en">Cancel</span><span class="t-pt">Cancelar</span>
      </button>
      <button class="suggest-btn-submit" onclick="submitSuggestion()">
        <span class="t-en">Open GitHub issue ↗</span><span class="t-pt">Abrir issue no GitHub ↗</span>
      </button>
    </div>
  </div>
</div>
<script>
function openSuggestModal(){
  document.getElementById('suggestBackdrop').style.display='flex';
  document.getElementById('suggestTitle').focus();
}
function closeSuggestModal(){
  document.getElementById('suggestBackdrop').style.display='none';
}
function submitSuggestion(){
  var titleEl=document.getElementById('suggestTitle');
  var bodyEl=document.getElementById('suggestBody');
  var title=titleEl.value.trim()||('Suggestion: '+document.title);
  var desc=bodyEl.value.trim();
  var body=(desc?desc+'\\n\\n':'')+'---\\nPage: '+window.location.href;
  var url='https://github.com/INF-UFRGS-Ontologies/COPI/issues/new'
    +'?title='+encodeURIComponent(title)
    +'&body='+encodeURIComponent(body)
    +'&labels='+encodeURIComponent('suggestion');
  window.open(url,'_blank','noopener');
  titleEl.value='';bodyEl.value='';
  closeSuggestModal();
}
document.addEventListener('keydown',function(e){
  if(e.key==='Escape'){var b=document.getElementById('suggestBackdrop');if(b&&b.style.display==='flex')closeSuggestModal();}
});
</script>
"""


def _static_page(title: str, nav_home: str, body: str,
                 title_en: str = "", title_pt: str = "") -> str:
    # Plain-text tab titles for <title> and for the JS language toggle
    _tab_en = title_en or title
    _tab_pt = title_pt or title_en or title
    # Inline SVG favicon — the hex badge in miniature
    _favicon_svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='14 8 80 92'>"
        "<polygon points='54,8 93.8,31 93.8,77 54,100 14.2,77 14.2,31' fill='%230a1628'/>"
        "<polygon points='54,8 93.8,31 93.8,77 54,100 14.2,77 14.2,31' fill='none' "
        "stroke='%232563eb' stroke-width='3'/>"
        "<circle cx='54' cy='54' r='11' fill='%2307101e' stroke='%232563eb' stroke-width='2'/>"
        "<path d='M54,44 C61,47.5 61,52 61,53.5 A7,7 0,0,1 47,53.5 C47,52 47,47.5 54,44Z' "
        "fill='%23f59e0b'/>"
        "</svg>"
    )
    _favicon_uri = f"data:image/svg+xml,{_favicon_svg}"
    return f"""<!DOCTYPE html>
<html lang="en" id="copi-root">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_h(_tab_en)}</title>
<link rel="icon" type="image/svg+xml" href="{_favicon_uri}">
{_STATIC_BOOTSTRAP}
{_STATIC_SHARED_CSS}
</head>
<body>
<nav class="doc-nav">
  <div class="container-fluid px-4 d-flex align-items-center gap-3">
    <a href="{nav_home}" style="display:flex;align-items:center;text-decoration:none;color:rgba(255,255,255,.85);">{_NAV_BADGE_SVG}<strong>COPI</strong></a>
    <span style="opacity:.3">·</span>
    <a href="{nav_home}">{_bi("Class Reference","Referência de Classes")}</a>
    <span style="opacity:.3">·</span>
    <a href="https://github.com/INF-UFRGS-Ontologies/copi" target="_blank" rel="noopener"
       style="color:rgba(255,255,255,.55);font-size:.8rem;">GitHub ↗</a>
    <div style="margin-left:auto;display:flex;align-items:center;gap:.5rem;">
      <span class="lang-toggle-label">Lang</span>
      <div class="lang-toggle" title="Switch language / Mudar idioma">
        <button class="lang-seg active" id="lang-btn-en">EN</button>
        <button class="lang-seg" id="lang-btn-pt">PT</button>
      </div>
    </div>
  </div>
</nav>
<div class="container-fluid px-4 py-4" style="max-width:1200px;">
{body}
</div>
<script>
(function(){{
  var root=document.getElementById('copi-root');
  var btnEn=document.getElementById('lang-btn-en');
  var btnPt=document.getElementById('lang-btn-pt');
  if(!btnEn||!btnPt)return;
  var titleEn={json.dumps(_tab_en)};
  var titlePt={json.dumps(_tab_pt)};
  function applyLang(pt){{
    if(pt){{
      root.classList.add('lang-pt');root.lang='pt-BR';document.title=titlePt;
      btnPt.classList.add('active');btnEn.classList.remove('active');
    }}else{{
      root.classList.remove('lang-pt');root.lang='en';document.title=titleEn;
      btnEn.classList.add('active');btnPt.classList.remove('active');
    }}
  }}
  try{{applyLang(localStorage.getItem('copi-lang')==='pt');}}catch(e){{}}
  btnEn.addEventListener('click',function(){{applyLang(false);try{{localStorage.setItem('copi-lang','en');}}catch(e){{}}}} );
  btnPt.addEventListener('click',function(){{applyLang(true); try{{localStorage.setItem('copi-lang','pt');}}catch(e){{}}}} );
}})();
// Fix: <base> tag causes #fragment links to resolve to a different path, breaking in-page scrolling.
document.addEventListener('click',function(e){{
  var a=e.target.closest('a[href]');
  if(!a)return;
  var h=a.getAttribute('href');
  if(h&&h.charAt(0)==='#'){{
    var el=document.getElementById(h.slice(1));
    if(el){{e.preventDefault();el.scrollIntoView({{behavior:'smooth',block:'start'}});}}
  }}
}});
</script>
{_SUGGESTION_BOX_HTML}
</body>
</html>"""


def _mode_pill_static(mode: str | None) -> str:
    if not mode:
        return ""
    return f'<span class="mode-pill mode-{_h(mode)}">{_h(mode)}</span>'


def _status_pill_static(status: str | None) -> str:
    if not status:
        return ""
    return f'<span class="status-pill status-{_h(status)}">{_h(status)}</span>'


def _class_href_static(cls: dict) -> str:
    cid = cls.get("copi_id")
    if not cid:
        return "#"
    return f"classes/{_copi_label(cid)}.html"


def _overview_page(
    classes: list[dict],
    grouped: list[tuple[str, list[dict]]],
    relations: list[dict],
    version_date: str,
    core_data: dict | None = None,
    vocab_data: dict | None = None,
) -> str:
    total = len(classes)
    relation_count = len(relations)

    # Include copi-core classes in the total class count
    _core_ops   = len((core_data or {}).get("operations", []))
    _core_equip = len((core_data or {}).get("equipment", []))
    _core_other = len((core_data or {}).get("other_processes", []))
    # Include copi-vocab classes
    _vocab_cls = sum(
        len((vocab_data or {}).get(k, []))
        for k in ("functions", "process_stubs", "fluid_types", "info_types", "qualities")
    )
    total_display = total + _core_ops + _core_equip + _core_other + _vocab_cls
    _vocab_ap = len((vocab_data or {}).get("ann_props", []))
    relation_count_display = relation_count + (1 if (core_data or {}).get("property") else 0) + _vocab_ap

    axiom_count = 0
    for cls in classes:
        axiom_count += 2
        if cls.get("differentia_expression"):
            axiom_count += 1
        try:
            parts = json.loads(cls.get("necessary_parts") or "[]")
        except Exception:
            parts = []
        axiom_count += len(parts if isinstance(parts, list) else [])
        try:
            sig = json.loads(cls.get("process_signature") or "{}")
        except Exception:
            sig = {}
        if sig.get("inputs") or sig.get("outputs"):
            axiom_count += 1

    index_rows = ""
    for cls in classes:
        href = _class_href_static(cls)
        cid_label = _copi_label(cls.get("copi_id"))
        name_cell = (
            f'<a href="{href}" class="class-link">{_h(cls["cluster_label"].title())}</a>'
            if href != "#" else _h(cls["cluster_label"].title())
        )
        if cid_label:
            name_cell += (
                f' <code style="font-size:.68rem;color:var(--muted);">{_h(cid_label)}</code>'
            )
        root_cell = (
            f'<span class="bfo-pill">{_h(cls["genus_bfo_root"])}</span>'
            if cls.get("genus_bfo_root") else "—"
        )
        index_rows += (
            f"<tr><td>{name_cell}</td>"
            f"<td style='font-family:monospace;font-size:.8rem;color:#374151;'>"
            f"{_h(cls.get('genus') or '—')}</td>"
            f"<td>{root_cell}</td>"
            f"<td>{_mode_pill_static(cls.get('axiom_mode'))}</td></tr>\n"
        )

    def _toc_dot(color: str) -> str:
        return f'<span class="toc-layer-dot" style="background:{color};"></span>'

    # TOC order: modules first, then leaf classes, then relations
    toc = ""
    if core_data and (core_data.get("operations") or core_data.get("equipment")):
        toc += (
            f'<a href="#copi-core-module" class="toc-link" style="display:flex;align-items:center;gap:.35rem;">'
            f'{_toc_dot("var(--layer-core)")}'
            f'{_bi("copi-core","copi-core")} '
            f'<span style="color:#94a3b8;font-size:.7rem;margin-left:auto;">'
            f'({_core_ops + _core_equip + _core_other})</span></a>\n'
        )
    if vocab_data and _vocab_cls:
        toc += (
            f'<a href="#copi-vocab-module" class="toc-link" style="display:flex;align-items:center;gap:.35rem;">'
            f'{_toc_dot("var(--layer-vocab)")}'
            f'{_bi("copi-vocab","copi-vocab")} '
            f'<span style="color:#94a3b8;font-size:.7rem;margin-left:auto;">({_vocab_cls})</span></a>\n'
        )
    if total:
        toc += (
            f'<a href="#leaf-classes" class="toc-link" style="display:flex;align-items:center;gap:.35rem;">'
            f'{_toc_dot("var(--layer-leaf)")}'
            f'{_bi("Leaf classes","Classes folha")} '
            f'<span style="color:#94a3b8;font-size:.7rem;margin-left:auto;">({total})</span></a>\n'
        )
        for root_name, root_classes in grouped:
            anchor = root_name.lower().replace(" ", "-")
            toc += (
                f'<a href="#bfo-{_h(anchor)}" class="toc-link" '
                f'style="padding-left:1.2rem;font-size:.78rem;">'
                f'{_h(root_name)} <span style="color:#94a3b8;font-size:.7rem;">({len(root_classes)})</span>'
                f'</a>\n'
            )
    if relations:
        toc += (
            f'<a href="#relations" class="toc-link">Relations '
            f'<span style="color:#94a3b8;font-size:.7rem;">({relation_count})</span></a>\n'
        )

    bfo_sections = ""
    for root_name, root_classes in grouped:
        anchor = root_name.lower().replace(" ", "-")
        count_s = "class" if len(root_classes) == 1 else "classes"
        cards = ""
        for cls in root_classes:
            href = _class_href_static(cls)
            cid_label = _copi_label(cls.get("copi_id"))
            try:
                djt_raw = json.loads(cls.get("disjoint_with") or "[]")
                djt_str = ", ".join(djt_raw) if isinstance(djt_raw, list) else ""
            except Exception:
                djt_str = str(cls.get("disjoint_with") or "")
            try:
                parts_raw = json.loads(cls.get("necessary_parts") or "[]")
                parts_names = (
                    [n for p in parts_raw
                     for n in [p.get("name") if isinstance(p, dict) else str(p)]
                     if n is not None]
                    if isinstance(parts_raw, list) else []
                )
            except Exception:
                parts_names = []

            full_doc_btn = (
                f'<a href="{href}" class="btn btn-sm btn-outline-secondary"'
                f' style="font-size:.72rem;padding:.2rem .6rem;">Full doc →</a>'
                if href != "#" else ""
            )

            meta_items = ""
            if cls.get("genus"):
                meta_items += f'<div class="meta-item"><strong>Genus:</strong> {_h(cls["genus"])}</div>'
            if cls.get("function_name"):
                meta_items += f'<div class="meta-item"><strong>Function:</strong> {_h(cls["function_name"])}</div>'
            if parts_names:
                meta_items += (
                    f'<div class="meta-item"><strong>Necessary parts:</strong> '
                    f'{_h(", ".join(parts_names))}</div>'
                )
            if djt_str:
                meta_items += (
                    f'<div class="meta-item"><strong>Disjoint with:</strong> '
                    f'<span style="font-family:monospace;font-size:.78rem;color:#475569;">'
                    f'{_h(djt_str)}</span></div>'
                )

            iri_local = (
                f'<span class="class-iri">'
                f'https://www.inf.ufrgs.br/ontologies/copi/{_h(cid_label)}</span>'
                if cid_label else
                f'<span class="class-iri">copi:{_h(cls["cluster_label"].replace(" ","").title())}</span>'
            )

            # Inline SVG thumbnail for the card (48px)
            card_symbol_html = ""
            _card_sym_path = cls.get("symbol_path") or ""
            if _card_sym_path:
                _card_sym_file = (
                    Path(__file__).parent.parent / "app" / "static" / "isa5_1" / _card_sym_path
                )
                if _card_sym_file.exists():
                    _card_content = _inline_symbol(_card_sym_file, max_px=40)
                    card_symbol_html = (
                        f'<div style="flex-shrink:0;background:#f8fafc;border:1px solid var(--border);'
                        f'border-radius:6px;padding:.35rem;width:52px;height:52px;display:flex;'
                        f'align-items:center;justify-content:center;overflow:hidden;">'
                        f'<div style="width:40px;height:40px;display:flex;align-items:center;'
                        f'justify-content:center;overflow:hidden;">{_card_content}</div></div>'
                    )

            cards += f"""
<div class="class-card" id="cls-{cls['id']}">
  <div class="class-card-header">
    <div class="d-flex align-items-center gap-2" style="min-width:0;">
      {card_symbol_html}
      <div style="min-width:0;">
        <div class="class-card-name">
          {'<a href="' + href + '">' if href != '#' else ''}{_h(cls['cluster_label'].title())}{'</a>' if href != '#' else ''}
        </div>
        {iri_local}
      </div>
    </div>
    <div class="d-flex gap-2 align-items-center flex-shrink-0">
      {_mode_pill_static(cls.get('axiom_mode'))}
      {full_doc_btn}
    </div>
  </div>
  <div class="class-card-body">
    <div style="flex:1;min-width:0;">
      {'<div class="class-def t-en">' + _h(cls["nl_definition_en"]) + '</div>' if cls.get("nl_definition_en") else ''}
      {'<div class="class-def t-pt" style="border-left-color:#059669;">' + _h(cls["nl_definition_pt"]) + '</div>' if cls.get("nl_definition_pt") else ''}
      <div class="class-meta">{meta_items}</div>
    </div>
  </div>
</div>"""

        _root_label_en = {
            "MaterialArtifact": "MaterialArtifact — atomic components",
            "Assembly":         "Assembly — multi-part assemblies",
            "EngineeredSystem": "EngineeredSystem",
            "ObjectAggregate":  "ObjectAggregate",
            "Object":           "Object",
            "ProcessBoundary":  "ProcessBoundary",
            "Process":          "Process",
            "Other":            "Other (root unspecified)",
        }.get(root_name, root_name)
        _root_label_pt = {
            "MaterialArtifact": "MaterialArtifact — componentes atômicos",
            "Assembly":         "Assembly — conjuntos multi-parte",
            "EngineeredSystem": "EngineeredSystem",
            "ObjectAggregate":  "ObjectAggregate",
            "Object":           "Object",
            "ProcessBoundary":  "ProcessBoundary",
            "Process":          "Process",
            "Other":            "Outros (raiz não especificada)",
        }.get(root_name, root_name)
        bfo_sections += f"""
<div id="bfo-{_h(anchor)}" class="bfo-section">
  <div class="bfo-section-header">
    <span>{_bi(_root_label_en, _root_label_pt)}</span>
    <span class="count-badge">{len(root_classes)} {count_s}</span>
  </div>
  {cards}
</div>"""

    rel_section = ""
    if relations:
        obj_rels  = [r for r in relations if r.get("prop_type") == "ObjectProperty"]
        data_rels = [r for r in relations if r.get("prop_type") == "DatatypeProperty"]
        rel_groups_html = ""
        for group_label, group in [("Object Properties", obj_rels), ("Datatype Properties", data_rels)]:
            if not group:
                continue
            group_cards = ""
            for rel in sorted(group, key=lambda r: r.get("name", "")):
                chars = rel.get("characteristics") or ""
                char_spans = ""
                if chars:
                    for ch in str(chars).split(","):
                        ch = ch.strip()
                        if ch:
                            char_spans += (
                                f'<span style="font-family:monospace;font-size:.75rem;background:#f1f5f9;'
                                f'border-radius:3px;padding:.1rem .3rem;">{_h(ch)}</span> '
                            )
                def_text = rel.get("definition_en") or rel.get("definition") or ""
                def_line = (
                    f'<div style="font-style:italic;color:#374151;margin-bottom:.5rem;">'
                    f'{_h(def_text)}</div>'
                    if def_text else ""
                )
                meta_r = ""
                if rel.get("parent_prop"):
                    meta_r += f'<div><strong>Sub-property of:</strong> <code style="font-size:.8rem;">{_h(rel["parent_prop"])}</code></div>'
                if rel.get("domain"):
                    meta_r += f'<div><strong>Domain:</strong> <code style="font-size:.8rem;">{_h(rel["domain"])}</code></div>'
                if rel.get("range_type"):
                    meta_r += f'<div><strong>Range:</strong> <code style="font-size:.8rem;">{_h(rel["range_type"])}</code></div>'
                if char_spans:
                    meta_r += f'<div><strong>Characteristics:</strong> {char_spans}</div>'

                group_cards += f"""
<div class="rel-card">
  <div class="rel-card-header">
    <span class="rel-name">copi:{_h(rel.get("name",""))}</span>
    <span class="rel-type-pill">{_h(rel.get("prop_type",""))}</span>
    <span class="badge text-bg-success ms-auto" style="font-size:.65rem;">{_h(rel.get("status",""))}</span>
  </div>
  <div class="rel-card-body">
    {def_line}
    <div class="rel-meta">{meta_r}</div>
  </div>
</div>"""

            rel_groups_html += (
                f'<h6 style="font-family:system-ui,sans-serif;font-size:.72rem;font-weight:700;'
                f'text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:.75rem;">'
                f'{_h(group_label)}</h6>{group_cards}<div style="margin-bottom:1.5rem;"></div>'
            )

        rel_section = f"""
<div id="relations" class="bfo-section mt-4">
  <div class="bfo-section-header">
    <span>Object &amp; Datatype Properties</span>
    <span class="count-badge">{relation_count} relation{'s' if relation_count != 1 else ''}</span>
  </div>
  {rel_groups_html}
</div>"""

    _has_core = bool(
        core_data and (
            core_data.get("operations") or core_data.get("equipment") or core_data.get("other_processes")
        )
    )
    _core_section  = _core_module_section_html(core_data) if _has_core else ""
    _has_vocab     = bool(vocab_data and _vocab_cls)
    _vocab_section = _vocab_module_section_html(vocab_data) if _has_vocab else ""

    empty_state = (
        '<div class="text-center py-5 text-muted">'
        '<div style="font-size:3rem;opacity:.2;">📄</div>'
        '<div class="mt-2">No validated leaf classes yet.</div></div>'
        if not total else ""
    )

    main_content = ""
    if total or _has_core or _has_vocab:
        # Three-column layer diagram — replaces the grey alert box
        _n_core = _core_ops + _core_equip + _core_other
        intro_html = f"""
<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:1rem;margin-bottom:2.5rem;">

  <div style="border-top:3px solid var(--layer-core);border-radius:0 0 6px 6px;
              border:1px solid #cbd5e1;border-top:3px solid var(--layer-core);
              padding:1rem 1.1rem;background:#fff;">
    <div style="font-family:'IBM Plex Mono','Courier New',monospace;font-size:.7rem;
                font-weight:600;letter-spacing:.1em;text-transform:uppercase;
                color:var(--layer-core);margin-bottom:.5rem;">
      {_bi("Layer 1 · copi-core","Camada 1 · copi-core")}
    </div>
    <div style="font-family:system-ui,sans-serif;font-size:.9rem;font-weight:700;
                color:#1a1a1a;margin-bottom:.4rem;">
      {_bi("Process &amp; Equipment Taxonomy","Taxonomia de Processos e Equipamentos")}
    </div>
    <div style="font-size:.82rem;color:#4b5563;line-height:1.55;">
      <div class="t-en">Top-level operation categories and equipment categories, each defined by the function they realise.</div>
      <div class="t-pt">Categorias de operações e categorias de equipamentos de alto nível, cada uma definida pela função que realiza.</div>
    </div>
    <div style="margin-top:.75rem;font-family:'IBM Plex Mono','Courier New',monospace;
                font-size:.72rem;color:var(--layer-core);">{_n_core} {_bi("classes","classes")} · copi-core.ttl</div>
  </div>

  <div style="border-top:3px solid var(--layer-vocab);border-radius:0 0 6px 6px;
              border:1px solid #cbd5e1;border-top:3px solid var(--layer-vocab);
              padding:1rem 1.1rem;background:#fff;">
    <div style="font-family:'IBM Plex Mono','Courier New',monospace;font-size:.7rem;
                font-weight:600;letter-spacing:.1em;text-transform:uppercase;
                color:var(--layer-vocab);margin-bottom:.5rem;">
      {_bi("Layer 2 · copi-vocab","Camada 2 · copi-vocab")}
    </div>
    <div style="font-family:system-ui,sans-serif;font-size:.9rem;font-weight:700;
                color:#1a1a1a;margin-bottom:.4rem;">
      {_bi("Supporting Vocabulary","Vocabulário de Suporte")}
    </div>
    <div style="font-size:.82rem;color:#4b5563;line-height:1.55;">
      <div class="t-en">Functions, process stubs, fluids, information entities, and qualities used to build participation signatures.</div>
      <div class="t-pt">Funções, esboços de processos, fluidos, entidades de informação e qualidades usados para construir assinaturas de participação.</div>
    </div>
    <div style="margin-top:.75rem;font-family:'IBM Plex Mono','Courier New',monospace;
                font-size:.72rem;color:var(--layer-vocab);">{_vocab_cls} {_bi("classes","classes")} · copi-vocab.ttl</div>
  </div>

  <div style="border-top:3px solid var(--layer-leaf);border-radius:0 0 6px 6px;
              border:1px solid #cbd5e1;border-top:3px solid var(--layer-leaf);
              padding:1rem 1.1rem;background:#fff;">
    <div style="font-family:'IBM Plex Mono','Courier New',monospace;font-size:.7rem;
                font-weight:600;letter-spacing:.1em;text-transform:uppercase;
                color:var(--layer-leaf);margin-bottom:.5rem;">
      {_bi("Layer 3 · leaf classes","Camada 3 · classes folha")}
    </div>
    <div style="font-family:system-ui,sans-serif;font-size:.9rem;font-weight:700;
                color:#1a1a1a;margin-bottom:.4rem;">
      {_bi("Axiomatized Equipment Classes","Classes de Equipamentos Axiomatizadas")}
    </div>
    <div style="font-size:.82rem;color:#4b5563;line-height:1.55;">
      <div class="t-en">Concrete equipment subtypes — each with a genus, necessary parts, and a process participation signature.</div>
      <div class="t-pt">Subtipos concretos de equipamentos — cada um com gênero, partes necessárias e assinatura de participação em processo.</div>
    </div>
    <div style="margin-top:.75rem;font-family:'IBM Plex Mono','Courier New',monospace;
                font-size:.72rem;color:var(--layer-leaf);">{total} {_bi("axiomatized classes","classes axiomatizadas")} · enrichment DB</div>
  </div>

</div>
<style>@media(max-width:640px){{#layer-diagram{{grid-template-columns:1fr!important;}}}}</style>"""

        leaf_section = ""
        if total:
            class_index = (
                f'<div id="class-index" class="mb-4">'
                f'<h5 style="font-family:system-ui,sans-serif;font-size:.72rem;font-weight:700;'
                f'text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin-bottom:1rem;">'
                f'{_bi("Quick Index","Índice Rápido")}</h5>'
                f'<table class="table index-table table-sm"><thead><tr>'
                f'<th>{_bi("Class","Classe")}</th><th>{_bi("Genus","Gênero")}</th>'
                f'<th>{_bi("BFO root","Raiz BFO")}</th><th>{_bi("Axiom mode","Modo")}</th>'
                f'</tr></thead><tbody>{index_rows}</tbody></table></div>'
            )
            _leaf_header = _module_section_header(
                _bi("enrichment DB", "BD de enriquecimento"),
                "Layer 3 · Leaf Equipment Classes",
                "Camada 3 · Classes Folha de Equipamento",
                f"{total} {_bi('axiomatized classes','classes axiomatizadas')}",
                layer_color="var(--layer-leaf)",
            )
            leaf_section = f"""
<div id="leaf-classes" style="margin-bottom:3rem;">
  {_leaf_header}
  {class_index}
  {bfo_sections}
</div>"""

        main_content = (
            f'<div style="padding-bottom:2rem;"><div class="row g-4">'
            f'<div class="col-lg-2 d-none d-lg-block"><div class="toc-sticky">'
            f'<div class="toc-header">Contents</div>{toc}</div></div>'
            f'<div class="col-lg-10">'
            f'{intro_html}{_core_section}{_vocab_section}{leaf_section}{rel_section}'
            f'</div></div></div>'
        )

    # Scope notes (from config if available)
    scope_notes_html = ""
    try:
        _scope = COPI_SCOPE_NOTES  # imported at module level from config.py
        for _note, _lang in _scope:
            _cls = "t-en" if _lang == "en" else "t-pt"
            scope_notes_html += f'<div class="scope-note {_cls}">{_h(_note)}</div>'
    except Exception:
        pass
    if scope_notes_html:
        scope_notes_html = (
            f'<div class="doc-section mt-4" style="margin-bottom:2rem;">'
            f'<div class="doc-section-title">{_bi("Scope","Escopo")}</div>'
            f'{scope_notes_html}</div>'
        )

    # Description, contributors, license and provenance — from module-level config constants
    _desc_en, _desc_pt = COPI_DESCRIPTION if len(COPI_DESCRIPTION) == 2 else ("", "")
    _contributors_html = ", ".join(COPI_CONTRIBUTORS) if COPI_CONTRIBUTORS else ""
    _license_en, _license_url = COPI_LICENSE if len(COPI_LICENSE) == 2 else ("CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/")

    def _meta_row(label_en: str, label_pt: str, value: str, last: bool = False) -> str:
        border = "" if last else "border-bottom:1px solid var(--border);"
        return (
            f'<tr style="{border}">'
            f'<td style="padding:.45rem .7rem .45rem 0;color:var(--muted);white-space:nowrap;width:150px;">'
            f'{_bi(label_en, label_pt)}</td>'
            f'<td style="padding:.45rem 0;">{value}</td>'
            f'</tr>'
        )

    _metadata_strip = (
        f'<div class="doc-section mt-4" style="margin-bottom:2rem;">'
        f'<div class="doc-section-title">{_bi("Ontology info","Informações da ontologia")}</div>'
        f'<table style="font-family:system-ui,sans-serif;font-size:.85rem;border-collapse:collapse;width:100%;">'
        + _meta_row("Author", "Autor", _h(COPI_AUTHOR))
        + _meta_row("Contributors", "Contribuidores", _h(_contributors_html))
        + _meta_row("Institution", "Instituição", _h(COPI_PUBLISHER))
        + _meta_row("Research group", "Grupo de pesquisa", _h(COPI_RESEARCH_GROUP + " (CNPq)"))
        + _meta_row("Research project", "Projeto de pesquisa", _h(COPI_PROJECT_FULL))
        + _meta_row("License", "Licença",
                    f'<a href="{_license_url}" target="_blank" rel="noopener">{_h(_license_en)}</a>',
                    last=True)
        + f'</table></div>'
    )

    body = f"""
<div class="d-flex justify-content-between align-items-center mb-3 no-print"
     style="font-size:.83rem;">
  <span class="text-muted" style="font-family:system-ui,sans-serif;">
    {_bi("Class Reference","Referência de Classes")} · {_bi("Version","Versão")} {_h(version_date)}
  </span>
</div>

<div class="doc-hero">
  <div style="display:flex;align-items:flex-start;gap:0;">

    <!-- Text block -->
    <div style="flex:1;min-width:0;padding-right:2rem;">
      <div class="onto-eyebrow">{_bi("OWL 2 DL Ontology · Class Reference","Ontologia OWL 2 DL · Referência de Classes")}</div>
      <div class="onto-title">COPI</div>
      <div class="onto-subtitle">{_bi("Core Ontology for Petroleum Installations","Ontologia Core de Instalações de Petróleo")}</div>
      <div class="onto-iri">https://www.inf.ufrgs.br/ontologies/copi</div>
      <div class="hero-meta-strip">
        <span><strong>{total_display}</strong> {_bi("classes","classes")}</span>
        <span><strong>{relation_count_display}</strong> {_bi("properties","propriedades")}</span>
        <span><strong>{axiom_count}</strong> {_bi("axioms","axiomas")}</span>
        <span>BFO 2020</span>
        <span>IOF-Core 202603</span>
        <span>{_h(_license_en)}</span>
        <span>{_h(version_date)}</span>
        <a href="https://github.com/INF-UFRGS-Ontologies/copi" target="_blank" rel="noopener"
           style="color:rgba(255,255,255,.45);text-decoration:none;">GitHub ↗</a>
      </div>

      <!-- Paper citation block -->
      <div style="margin-top:1.1rem;padding:.65rem .9rem;background:rgba(255,255,255,.06);
                  border-left:2px solid rgba(255,255,255,.25);border-radius:0 4px 4px 0;">
        <div style="font-family:'IBM Plex Mono','Courier New',monospace;font-size:.65rem;
                    font-weight:600;letter-spacing:.12em;text-transform:uppercase;
                    color:rgba(255,255,255,.35);margin-bottom:.35rem;">
          {_bi("Published at · FOIS 2026","Publicado em · FOIS 2026")}
        </div>
        <div style="font-family:'IBM Plex Serif','Georgia',serif;font-size:.82rem;
                    color:rgba(255,255,255,.75);line-height:1.45;font-style:italic;">
          {_bi(
            "Axiomatizing Industrial Reference Data: A BFO/IOF-Core Enrichment of ISO 15926-4 Equipment Classes",
            "Axiomatizando Dados de Referência Industrial: Um Enriquecimento BFO/IOF-Core das Classes de Equipamento da ISO 15926-4"
          )}
        </div>
        <div style="font-family:system-ui,sans-serif;font-size:.75rem;color:rgba(255,255,255,.4);
                    margin-top:.25rem;">
          Santos, Antunes, Abel &amp; Netto · UFRGS ·
          <span class="t-en">to appear, September 2026</span>
          <span class="t-pt">a aparecer, setembro 2026</span>
        </div>
      </div>

      <!-- Paper citation block — ODP for Functional Locations -->
      <div style="margin-top:.6rem;padding:.65rem .9rem;background:rgba(255,255,255,.06);
                  border-left:2px solid rgba(255,255,255,.25);border-radius:0 4px 4px 0;">
        <div style="font-family:'IBM Plex Mono','Courier New',monospace;font-size:.65rem;
                    font-weight:600;letter-spacing:.12em;text-transform:uppercase;
                    color:rgba(255,255,255,.35);margin-bottom:.35rem;">
          {_bi("Published at · FOIS 2026","Publicado em · FOIS 2026")}
        </div>
        <div style="font-family:'IBM Plex Serif','Georgia',serif;font-size:.82rem;
                    color:rgba(255,255,255,.75);line-height:1.45;font-style:italic;">
          {_bi(
            "An Ontology Design Pattern for Functional Locations in Industrial Asset Management",
            "Um Padrão de Design Ontológico para Locais de Instalação na Gestão de Ativos Industriais"
          )}
        </div>
        <div style="font-family:system-ui,sans-serif;font-size:.75rem;color:rgba(255,255,255,.4);
                    margin-top:.25rem;">
          Santos, Rojas, Antunes, Rodrigues, Romeu, Petry, Abel &amp; Netto · UFRGS/UB ·
          <span class="t-en">to appear, September 2026</span>
          <span class="t-pt">a aparecer, setembro 2026</span>
        </div>
      </div>

      <div class="mt-3 d-flex gap-2 flex-wrap align-items-center">
        <a href="https://www.inf.ufrgs.br/ontologies/copi/copi.owl" target="_blank" rel="noopener"
           style="display:inline-flex;align-items:center;gap:.35rem;background:rgba(255,255,255,.1);
                  border:1px solid rgba(255,255,255,.25);color:rgba(255,255,255,.85);border-radius:3px;
                  padding:.3rem .8rem;font-family:system-ui,sans-serif;font-size:.78rem;
                  font-weight:600;text-decoration:none;transition:background .15s;"
           onmouseover="this.style.background='rgba(255,255,255,.18)'"
           onmouseout="this.style.background='rgba(255,255,255,.1)'">
          ↓ {_bi("Download OWL","Baixar OWL")}
        </a>
        {(f'<span class="t-en" style="font-size:.82rem;color:rgba(255,255,255,.45);font-style:italic;">{_h(_desc_en)}</span>') if _desc_en else ''}
        {(f'<span class="t-pt" style="font-size:.82rem;color:rgba(255,255,255,.45);font-style:italic;">{_h(_desc_pt)}</span>') if _desc_pt else ''}
      </div>
    </div>

    <!-- Large logo, right column, desktop only -->
    <div class="d-none d-lg-flex" style="flex-shrink:0;align-items:flex-start;justify-content:flex-end;
                                          padding-left:.5rem;align-self:flex-start;">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="38 6 284 306" width="200" height="215"
           style="opacity:.85;filter:drop-shadow(0 4px 24px rgba(0,0,0,.6));">
        <defs>
          <linearGradient id="hexBg" x1="0.2" y1="0" x2="0.8" y2="1">
            <stop offset="0%" stop-color="#0e2040"/>
            <stop offset="100%" stop-color="#070e1c"/>
          </linearGradient>
          <linearGradient id="goldFill" x1="0.25" y1="0" x2="0.75" y2="1">
            <stop offset="0%"   stop-color="#fde68a"/>
            <stop offset="45%"  stop-color="#f59e0b"/>
            <stop offset="100%" stop-color="#92400e"/>
          </linearGradient>
          <linearGradient id="hexStroke" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%"   stop-color="#60a5fa"/>
            <stop offset="50%"  stop-color="#2563eb"/>
            <stop offset="100%" stop-color="#1e3a5f"/>
          </linearGradient>
          <radialGradient id="innerGlow" cx="50%" cy="38%" r="58%">
            <stop offset="0%"   stop-color="#1e3a5f" stop-opacity="0.55"/>
            <stop offset="100%" stop-color="#070e1c" stop-opacity="0"/>
          </radialGradient>
          <filter id="goldAura" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur in="SourceGraphic" stdDeviation="7" result="b"/>
            <feColorMatrix in="b" type="matrix"
              values="1.2 0.6 0 0 0  0.6 0.4 0 0 0  0 0 0 0 0  0 0 0 0.55 0" result="cb"/>
            <feMerge><feMergeNode in="cb"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
          <filter id="ng" x="-35%" y="-35%" width="170%" height="170%">
            <feGaussianBlur in="SourceGraphic" stdDeviation="2.2" result="b"/>
            <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
          <filter id="hexShadow" x="-12%" y="-8%" width="124%" height="124%">
            <feDropShadow dx="0" dy="7" stdDeviation="14" flood-color="#000" flood-opacity="0.55"/>
          </filter>
          <clipPath id="hc">
            <polygon points="180,30 300,99 300,237 180,306 60,237 60,99"/>
          </clipPath>
        </defs>
        <polygon points="180,30 300,99 300,237 180,306 60,237 60,99"
                 fill="#000" opacity="0.4" transform="translate(2,9)"
                 filter="url(#hexShadow)"/>
        <polygon points="180,30 300,99 300,237 180,306 60,237 60,99"
                 fill="url(#hexBg)"/>
        <polygon points="180,30 300,99 300,237 180,306 60,237 60,99"
                 fill="url(#innerGlow)"/>
        <g clip-path="url(#hc)" fill="none" stroke="#4a7bc8" stroke-opacity="0.07" stroke-width="1">
          <line x1="180" y1="168" x2="180" y2="30"/>
          <line x1="180" y1="168" x2="300" y2="99"/>
          <line x1="180" y1="168" x2="300" y2="237"/>
          <line x1="180" y1="168" x2="180" y2="306"/>
          <line x1="180" y1="168" x2="60" y2="237"/>
          <line x1="180" y1="168" x2="60" y2="99"/>
          <polygon points="180,113 132.4,140.5 132.4,195.5 180,223 227.6,195.5 227.6,140.5"/>
        </g>
        <g stroke="#1d4ed8" stroke-width="0.85" stroke-opacity="0.28" fill="none">
          <line x1="180" y1="86"  x2="251" y2="127"/>
          <line x1="251" y1="127" x2="251" y2="209"/>
          <line x1="251" y1="209" x2="180" y2="250"/>
          <line x1="180" y1="250" x2="109" y2="209"/>
          <line x1="109" y1="209" x2="109" y2="127"/>
          <line x1="109" y1="127" x2="180" y2="86"/>
        </g>
        <g stroke="#38bdf8" stroke-width="1.5" stroke-opacity="0.48" fill="none">
          <line x1="180" y1="86"  x2="180" y2="168"/>
          <line x1="251" y1="127" x2="180" y2="168"/>
          <line x1="251" y1="209" x2="180" y2="168"/>
          <line x1="180" y1="250" x2="180" y2="168"/>
          <line x1="109" y1="209" x2="180" y2="168"/>
          <line x1="109" y1="127" x2="180" y2="168"/>
        </g>
        <g transform="translate(180,86)" filter="url(#ng)">
          <circle r="18" fill="#091728" stroke="#38bdf8" stroke-width="1.7"/>
          <ellipse cx="0" cy="-7" rx="7.5" ry="3.2" fill="none" stroke="#38bdf8" stroke-width="1.3"/>
          <rect x="-7.5" y="-7" width="15" height="13" fill="none" stroke="#38bdf8" stroke-width="1.3"/>
          <ellipse cx="0" cy="6" rx="7.5" ry="3.2" fill="#091728" stroke="#38bdf8" stroke-width="1.3"/>
          <line x1="7.5" y1="0" x2="11.5" y2="0" stroke="#38bdf8" stroke-width="1.2"/>
          <line x1="-7.5" y1="0" x2="-11.5" y2="0" stroke="#38bdf8" stroke-width="1.2"/>
        </g>
        <g transform="translate(251,127)" filter="url(#ng)">
          <circle r="18" fill="#091728" stroke="#60a5fa" stroke-width="1.7"/>
          <circle r="9" fill="none" stroke="#60a5fa" stroke-width="1.3"/>
          <line x1="-5.5" y1="-5.5" x2="5.5" y2="5.5" stroke="#60a5fa" stroke-width="1.15" stroke-opacity="0.6"/>
          <line x1="5.5"  y1="-5.5" x2="-5.5" y2="5.5" stroke="#60a5fa" stroke-width="1.15" stroke-opacity="0.6"/>
          <line x1="0" y1="-9" x2="0" y2="-14" stroke="#60a5fa" stroke-width="1.35"/>
          <line x1="9" y1="0" x2="14" y2="0" stroke="#60a5fa" stroke-width="1.35"/>
        </g>
        <g transform="translate(251,209)" filter="url(#ng)">
          <circle r="18" fill="#091728" stroke="#60a5fa" stroke-width="1.7"/>
          <polygon points="-9.5,-7 0,0 -9.5,7" fill="none" stroke="#60a5fa" stroke-width="1.45"/>
          <polygon points="9.5,-7 0,0 9.5,7" fill="none" stroke="#60a5fa" stroke-width="1.45"/>
          <line x1="0" y1="-7" x2="0" y2="-13.5" stroke="#60a5fa" stroke-width="1.35"/>
          <line x1="-4" y1="-13.5" x2="4" y2="-13.5" stroke="#60a5fa" stroke-width="1.7"/>
        </g>
        <g transform="translate(180,250)" filter="url(#ng)">
          <circle r="18" fill="#091728" stroke="#38bdf8" stroke-width="1.7"/>
          <circle r="9" fill="none" stroke="#38bdf8" stroke-width="1.3"/>
          <polygon points="0,-5.8 5.5,2.9 -5.5,2.9" fill="none" stroke="#38bdf8" stroke-width="1.25" stroke-opacity="0.72"/>
          <line x1="-9" y1="0" x2="-14" y2="0" stroke="#38bdf8" stroke-width="1.35"/>
          <line x1="0"  y1="9" x2="0"  y2="14" stroke="#38bdf8" stroke-width="1.35"/>
        </g>
        <g transform="translate(109,209)" filter="url(#ng)">
          <circle r="18" fill="#091728" stroke="#38bdf8" stroke-width="1.7"/>
          <rect x="-11" y="-6.5" width="22" height="13" rx="6.5" fill="none" stroke="#38bdf8" stroke-width="1.3"/>
          <line x1="-5" y1="-3.8" x2="-5" y2="3.8" stroke="#38bdf8" stroke-width="0.95" stroke-opacity="0.55"/>
          <line x1="0"  y1="-3.8" x2="0"  y2="3.8" stroke="#38bdf8" stroke-width="0.95" stroke-opacity="0.55"/>
          <line x1="5"  y1="-3.8" x2="5"  y2="3.8" stroke="#38bdf8" stroke-width="0.95" stroke-opacity="0.55"/>
          <line x1="-11" y1="0" x2="-15" y2="0" stroke="#38bdf8" stroke-width="1.2"/>
          <line x1="11"  y1="0" x2="15"  y2="0" stroke="#38bdf8" stroke-width="1.2"/>
        </g>
        <g transform="translate(109,127)" filter="url(#ng)">
          <circle r="18" fill="#091728" stroke="#38bdf8" stroke-width="1.7"/>
          <line x1="-6.5" y1="-10" x2="-6.5" y2="9.5" stroke="#38bdf8" stroke-width="1.45"/>
          <line x1="6.5"  y1="-10" x2="6.5"  y2="9.5" stroke="#38bdf8" stroke-width="1.45"/>
          <line x1="0" y1="-5.5" x2="0" y2="9.5" stroke="#38bdf8" stroke-width="1.05" stroke-opacity="0.65"/>
          <line x1="-9" y1="-10" x2="9" y2="-10" stroke="#38bdf8" stroke-width="1.65"/>
          <line x1="-3.5" y1="9.5" x2="3.5" y2="9.5" stroke="#38bdf8" stroke-width="1" stroke-opacity="0.55"/>
        </g>
        <circle cx="180" cy="165" r="36" fill="none" stroke="#f59e0b" stroke-width="0.8" stroke-opacity="0.12"/>
        <circle cx="180" cy="165" r="30" fill="none" stroke="#f59e0b" stroke-width="0.9" stroke-opacity="0.22"/>
        <circle cx="180" cy="165" r="26" fill="#07101e" stroke="#2563eb" stroke-width="2.2"/>
        <circle cx="180" cy="165" r="22" fill="none" stroke="#f59e0b" stroke-width="0.7" stroke-opacity="0.3"/>
        <path d="M 180,142 C 193,148 194,160 194,163 A 14,14 0 0,1 166,163 C 166,160 167,148 180,142 Z"
              fill="url(#goldFill)" filter="url(#goldAura)"/>
        <ellipse cx="175.5" cy="150.5" rx="3.8" ry="5.8" fill="white" opacity="0.22"
                 transform="rotate(-22,175.5,150.5)"/>
        <circle cx="173.5" cy="146.5" r="1.4" fill="white" opacity="0.32"/>
        <polygon points="180,30 300,99 300,237 180,306 60,237 60,99"
                 fill="none" stroke="#2563eb" stroke-width="2.8" stroke-opacity="0.72"/>
        <polygon points="180,35 295.6,102.5 295.6,233.5 180,301 64.4,233.5 64.4,102.5"
                 fill="none" stroke="#60a5fa" stroke-width="0.55" stroke-opacity="0.2"/>
        <circle cx="172" cy="320" r="1.6" fill="#1e3a5f"/>
        <circle cx="180" cy="320" r="1.6" fill="#2563eb"/>
        <circle cx="188" cy="320" r="1.6" fill="#1e3a5f"/>
        <text x="180" y="363" text-anchor="middle"
              font-family="system-ui,-apple-system,'Helvetica Neue',sans-serif"
              font-size="50" font-weight="900" letter-spacing="-0.045em"
              fill="white">COPI</text>
        <line x1="120" y1="372" x2="240" y2="372" stroke="#f59e0b" stroke-width="0.9" stroke-opacity="0.45"/>
        <text x="180" y="386" text-anchor="middle"
              font-family="system-ui,-apple-system,sans-serif"
              font-size="8.5" font-weight="600" letter-spacing="0.22em"
              fill="#60a5fa">CORE ONTOLOGY OF</text>
        <text x="180" y="401" text-anchor="middle"
              font-family="system-ui,-apple-system,sans-serif"
              font-size="8.5" font-weight="400" letter-spacing="0.15em"
              fill="#475569">PETROLEUM INSTALLATIONS</text>
      </svg>
    </div>

  </div>
</div>

{_metadata_strip}
{scope_notes_html}
{empty_state}
{main_content}
"""
    return _static_page(
        _bi("COPI — Class Reference", "COPI — Referência de Classes"),
        "docs.html", body,
        title_en="COPI · Class Reference",
        title_pt="COPI · Referência de Classes",
    )


def _fol_html_static(fol_entries: list[dict]) -> str:
    if not fol_entries:
        return '<p class="text-muted fst-italic">No FOL theory generated.</p>'
    lines = ""
    for entry in fol_entries:
        label = entry.get("label") or entry.get("step") or ""
        fol   = entry.get("fol") or ""
        note  = entry.get("note") or ""
        note_span = (
            f' <span style="color:#9ca3af;font-size:.78rem;">— {_h(note)}</span>'
            if note else ""
        )
        lines += (
            f'<span class="fol-line">'
            f'<span class="fol-label">[{_h(label)}]</span>'
            f'{_h(fol)}{note_span}</span>\n'
        )
    return f'<div style="background:#f8f9fa;border-radius:6px;padding:.9rem 1rem;">{lines}</div>'


def _class_page(e: dict, turtle_src: str, version_date: str, *, public_export: bool = False) -> str:
    cls_label = e.get("cluster_label") or ""
    cls_title = cls_label.title()
    cid = e.get("copi_id")
    cid_label = _copi_label(cid)
    iri = (
        f"https://www.inf.ufrgs.br/ontologies/copi/{cid_label}"
        if cid_label else
        f"https://www.inf.ufrgs.br/ontologies/copi#{cls_label.replace(' ','').title()}"
    )

    try:
        fol_entries = generate_fol_theory(e)
    except Exception:
        fol_entries = []
    fol_block = _fol_html_static(fol_entries)

    nl_defs = ""
    if e.get("nl_definition_en"):
        nl_defs += (
            f'<div class="nl-def">'
            f'<div class="lang-tag">EN</div>{_h(e["nl_definition_en"])}</div>'
        )
    if e.get("nl_definition_pt"):
        nl_defs += (
            f'<div class="nl-def" style="border-color:#059669;">'
            f'<div class="lang-tag">PT-BR</div>{_h(e["nl_definition_pt"])}</div>'
        )
    if not nl_defs:
        nl_defs = '<p class="text-muted fst-italic">No natural language definition recorded.</p>'

    semiformal = ""
    if e.get("semiformal_axiom"):
        semiformal = (
            f'<div class="axiom-block">'
            f'<div class="axiom-label">{_bi("Semi-formal (Aristotelian)","Semi-formal (Aristotélico)")}</div>'
            f'{_h(e["semiformal_axiom"])}</div>'
        )

    if public_export:
        _turtle_lines = turtle_src.splitlines()
        turtle_src = "\n".join(
            line for line in _turtle_lines
            if not any(pfx in line for pfx in PUBLIC_STRIP_PREFIXES)
        )
    owl_block = (
        f'<div class="axiom-block" style="padding:0;">'
        f'<div class="axiom-label" style="padding:.6rem 1rem 0;">OWL 2 / Turtle</div>'
        f'<div class="owl-block">{_h(turtle_src)}</div></div>'
    )

    # Step 1: Identity-Giving Function
    fn_name   = e.get("function_name") or "—"
    fn_parent = e.get("function_parent") or "DesignedFunction"
    proc_name = e.get("process_name") or "—"
    proc_par  = e.get("process_parent") or "PlannedProcess"
    step1 = f"""
<div class="step-block step-1">
  <div class="step-block-header">
    <span class="step-num">1</span> {_bi("Identity-Giving Function","Função Identitária")}
  </div>
  <div class="step-body">
    <div class="row g-3 mb-2">
      <div class="col-sm-6">
        <div style="font-size:.72rem;font-family:system-ui;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin-bottom:.2rem;">Function class</div>
        <span class="decision-value">{_h(fn_name)}</span>
        <span class="text-muted" style="font-size:.8rem;"> ⊑ {_h(fn_parent)}</span>
      </div>
      <div class="col-sm-6">
        <div style="font-size:.72rem;font-family:system-ui;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin-bottom:.2rem;">Realized in</div>
        <span class="decision-value">{_h(proc_name)}</span>
        <span class="text-muted" style="font-size:.8rem;"> ⊑ {_h(proc_par)}</span>
      </div>
    </div>
    {'<div class="rationale">' + _h(e["function_rationale"]) + '</div>' if e.get("function_rationale") else ''}
  </div>
</div>"""

    # Step 2: Genus
    genus = e.get("genus") or "—"
    genus_root = e.get("genus_bfo_root") or ""
    bfo_note = ""
    if genus_root in ("Assembly", "MaterialArtifact"):
        bfo_note = '<span class="bfo-badge ms-2">bfo:Object (BFO_0000030)</span>'
    elif genus_root == "EngineeredSystem":
        bfo_note = '<span class="bfo-badge ms-2">bfo:ObjectAggregate (BFO_0000027)</span>'
    step2 = f"""
<div class="step-block step-2">
  <div class="step-block-header">
    <span class="step-num">2</span> {_bi("Genus Determination","Determinação do Gênero")}
  </div>
  <div class="step-body">
    <div class="mb-2">
      <span class="decision-value">{_h(genus)}</span>{bfo_note}
    </div>
    {'<div class="rationale">' + _h(e["genus_rationale"]) + '</div>' if e.get("genus_rationale") else ''}
  </div>
</div>"""

    # Step 3: Differentia
    diff_expr = e.get("differentia_expression") or ""
    diff_nl   = e.get("differentia_nl") or ""
    step3_body = ""
    if diff_expr:
        step3_body += f'<div class="mb-2"><code style="font-size:.9rem;">{_h(diff_expr)}</code></div>'
    if diff_nl:
        step3_body += f'<p style="font-size:.88rem;color:#374151;">{_h(diff_nl)}</p>'
    if e.get("differentia_rationale"):
        step3_body += f'<div class="rationale">{_h(e["differentia_rationale"])}</div>'
    if not step3_body:
        step3_body = '<p class="text-muted fst-italic" style="font-size:.88rem;">No differentia recorded.</p>'
    step3 = f"""
<div class="step-block step-3">
  <div class="step-block-header">
    <span class="step-num">3</span> {_bi("Differentia Specifica","Diferença Específica")}
  </div>
  <div class="step-body">{step3_body}</div>
</div>"""

    # Step 4: Necessary Parts
    try:
        parts_raw = json.loads(e.get("necessary_parts") or "[]")
        parts = parts_raw if isinstance(parts_raw, list) else []
    except Exception:
        parts = []
    if parts:
        rows_html = ""
        for p in parts:
            if isinstance(p, dict):
                pname = p.get("name", "")
                ppar  = p.get("parent", "")
                prel  = p.get("relation", "hasComponentPartAtAllTimes")
            else:
                pname = str(p)
                ppar  = ""
                prel  = "hasComponentPartAtAllTimes"
            rows_html += (
                f"<tr><td>{_h(pname)}</td><td>{_h(ppar)}</td><td>{_h(prel)}</td></tr>"
            )
        parts_block = (
            f'<table class="parts-table"><thead><tr>'
            f'<th>Part class</th><th>Parent</th><th>Relation</th>'
            f'</tr></thead><tbody>{rows_html}</tbody></table>'
        )
    else:
        parts_block = '<p class="text-muted fst-italic" style="font-size:.88rem;">No necessary parts recorded.</p>'
    if e.get("parts_rationale"):
        parts_block += f'<div class="rationale mt-2">{_h(e["parts_rationale"])}</div>'
    step4 = f"""
<div class="step-block step-4">
  <div class="step-block-header">
    <span class="step-num">4</span> {_bi("Necessary Parts","Partes Necessárias")}
  </div>
  <div class="step-body">{parts_block}</div>
</div>"""

    # Process Signature
    try:
        sig = json.loads(e.get("process_signature") or "{}")
        if not isinstance(sig, dict):
            sig = {}
    except Exception:
        sig = {}

    sig_html = ""
    if sig.get("inputs") or sig.get("outputs") or sig.get("transformation"):
        def sig_list(items):
            if not items:
                return '<span class="text-muted">—</span>'
            if isinstance(items, list):
                return ", ".join(_h(str(i)) for i in items)
            return _h(str(items))
        sig_html = f"""
<div class="doc-section">
  <div class="doc-section-title">{_bi("Process Participation Signature","Assinatura de Participação em Processo")}</div>
  <div class="sig-grid">
    <div class="sig-cell"><div class="sig-cell-label">{_bi("Inputs","Entradas")}</div><div style="font-size:.88rem;">{sig_list(sig.get("inputs"))}</div></div>
    <div class="sig-cell"><div class="sig-cell-label">{_bi("Outputs","Saídas")}</div><div style="font-size:.88rem;">{sig_list(sig.get("outputs"))}</div></div>
    <div class="sig-cell"><div class="sig-cell-label">{_bi("Transformation","Transformação")}</div><div style="font-size:.88rem;">{_h(sig.get("transformation",""))}</div></div>
  </div>
  {'<div class="rationale mt-2">' + _h(e.get("signature_rationale","")) + '</div>' if e.get("signature_rationale") else ''}
</div>"""

    # Disjointness
    try:
        djt_raw = json.loads(e.get("disjoint_with") or "[]")
        djt = djt_raw if isinstance(djt_raw, list) else []
    except Exception:
        djt = []
    djt_html = ""
    if djt:
        pills = " ".join(f'<span class="disjoint-pill">{_h(d)}</span>' for d in djt)
        djt_html = (
            f'<div class="doc-section">'
            f'<div class="doc-section-title">{_bi("Disjoint With","Disjunto com")}</div><div>{pills}</div>'
            + (f'<div class="rationale mt-2">{_h(e["disjointness_rationale"])}</div>'
               if e.get("disjointness_rationale") else "")
            + "</div>"
        )

    # Source definitions (from terms.db), filtered by user exclusions.
    # In public export, keep the source/term/link so the page can cite the
    # standard, but strip the reproduced definition text (copyrighted).
    try:
        definitions = _filter_excluded_definitions(
            get_cluster_definitions(cls_label), e.get("excluded_definition_ids")
        )
    except Exception:
        definitions = []
    if public_export:
        from app.jinja_setup import COPYRIGHTED_SOURCES as _COPYRIGHTED_SOURCES
        definitions = [
            {**d, "definition": "", "properties": {}} if d.get("source") in _COPYRIGHTED_SOURCES else d
            for d in definitions
        ]

    _SRC_LABELS = {
        "iso15926":    "ISO 15926-4",
        "posc_caesar": "POSC Caesar",
        "cfihos":      "CFIHOS",
        "dexpi":       "DEXPI",
        "slb_glossary": "SLB Glossary",
        "iso14224":    "ISO 14224",
    }
    _SRC_COLORS = {
        "iso15926":    "background:#dbeafe;color:#1e40af;",
        "posc_caesar": "background:#ede9fe;color:#5b21b6;",
        "cfihos":      "background:#dcfce7;color:#166534;",
        "dexpi":       "background:#fef3c7;color:#92400e;",
        "slb_glossary": "background:#fce7f3;color:#9d174d;",
        "iso14224":    "background:#e0f2fe;color:#075985;",
    }
    src_cards = ""
    for d in definitions:
        src = d.get("source", "unknown")
        label = _SRC_LABELS.get(src, src.upper())
        badge_style = _SRC_COLORS.get(src, "background:#f1f5f9;color:#374151;")
        props_html = ""
        if d.get("properties"):
            prop_parts = []
            for k, v in d["properties"].items():
                if v and k not in ("id", "term_id", "created_at"):
                    prop_parts.append(f"{_h(k)}: {_h(str(v))}")
            if prop_parts:
                props_html = (
                    f'<div style="margin-top:.5rem;font-size:.78rem;color:var(--muted);">'
                    + " · ".join(prop_parts) + "</div>"
                )
        source_uri = d.get("source_uri") or ""
        source_version = d.get("source_version") or ""
        if source_uri:
            version_label = f" {_h(source_version)}" if source_version else ""
            src_link_html = (
                f'<a href="{source_uri}" target="_blank" rel="noopener" '
                f'style="font-size:.75rem;color:var(--accent2);text-decoration:none;">'
                f'{_h(label)}{version_label} ↗</a>'
            )
        else:
            src_link_html = ""
        if d.get("definition"):
            def_html = f'<div style="color:#374151;font-size:.88rem;">{_h(d.get("definition",""))}</div>'
        else:
            def_html = (
                '<div style="color:#6b7280;font-size:.85rem;font-style:italic;">'
                + _bi(
                    "Definition text withheld (copyrighted standard) — follow the source link above.",
                    "Texto da definição omitido (norma protegida por direitos autorais) — acesse o link da fonte acima.",
                )
                + "</div>"
            )
        src_cards += f"""
<div class="source-card">
  <div class="source-card-header">
    <span class="source-badge" style="font-size:.7rem;font-weight:700;text-transform:uppercase;
          letter-spacing:.06em;padding:.2rem .6rem;border-radius:4px;{badge_style}">{_h(label)}</span>
    <span style="font-size:.75rem;color:var(--muted);font-family:monospace;">{_h(d.get("term",""))}</span>
  </div>
  <div class="source-card-body">
    {def_html}
    {props_html}
    {f'<div style="margin-top:.4rem;">{src_link_html}</div>' if src_link_html else ""}
  </div>
</div>"""

    src_count = len(definitions)
    src_count_label = f"{src_count} source{'s' if src_count != 1 else ''}"
    if not src_cards:
        src_cards = '<p class="text-muted fst-italic" style="font-size:.85rem;">No source definitions found in the aggregator database.</p>'
    source_defs_block = f"""
<div class="doc-section">
  <div class="doc-section-title">
    {_bi("Source Definitions","Definições nas Fontes")}
    <span style="float:right;font-variant-numeric:tabular-nums;font-weight:400;">{src_count_label}</span>
  </div>
  {src_cards}
</div>"""

    # Layered-source provenance (tier / source_type / citation_mode / quote) — see
    # CLAUDE.md Step 2b/2c. Mirrors enrichment_detail.html's sidebar section so the
    # static docs show the same evidence trail the review UI does, not just the
    # raw terms.db definitions above.
    try:
        _sdu_raw = e.get("source_definitions_used")
        _sdu = json.loads(_sdu_raw) if isinstance(_sdu_raw, str) else (_sdu_raw or [])
    except (json.JSONDecodeError, TypeError):
        _sdu = []
    _sdu_tiered = [p for p in _sdu if isinstance(p, dict) and p.get("tier")]
    if _sdu_tiered:
        _cov = e.get("secondary_coverage")
        _cov_explainer = _bi(
            "How much independent secondary research backs this term — not how correct it is. "
            '"Full" means a non-primary source was quoted directly and covered several distinct '
            'aspects of the concept, not just its function. "Partial" means secondary research '
            'happened but covered less. "None" means only the primary definition was used. A '
            '"full" term can still contain an error, and a "none" term can still be entirely '
            "correct — this tracks whether the research step ran, not the result.",
            "Quanto de pesquisa secundária independente sustenta este termo — não o quão correto "
            'ele é. "Full" significa que uma fonte não-primária foi citada literalmente e cobriu '
            'vários aspectos distintos do conceito, não apenas sua função. "Partial" significa '
            'que houve pesquisa secundária, mas com cobertura menor. "None" significa que só a '
            'definição primária foi usada. Um termo "full" ainda pode conter um erro, e um termo '
            '"none" ainda pode estar totalmente correto — isso rastreia se a etapa de pesquisa '
            "ocorreu, não o resultado.",
        )
        _cov_help = (
            f'<details class="help-popover">'
            f'<summary class="help-icon">?</summary>'
            f'<div class="help-content">{_cov_explainer}</div>'
            f'</details>'
        )
        _cov_badge = (
            f'<span class="coverage-badge coverage-{_h(_cov)}">secondary: {_h(_cov)}</span>{_cov_help}'
            if _cov else ""
        )
        _prov_rows = ""
        for p in _sdu_tiered:
            _tier = p.get("tier", "")
            _cats = p.get("categories_covered") or []
            _access = p.get("access")
            _prov_rows += (
                f'<div class="provenance-row">'
                f'<span class="tier-badge tier-{_h(_tier)}">{_h(_tier)}</span>'
                f'<span class="text-muted">{_h(p.get("source_type") or "")}</span>'
                f'<span class="fst-italic text-muted">{_h(p.get("citation_mode") or "")}</span>'
                f'<span class="fw-semibold">{_h(p.get("source") or "")}</span>'
                + (f'<span class="text-muted" style="font-size:.68rem;">({_h(_access)})</span>' if _access and _access != "raw_fetch" else "")
                + (f'<span class="text-muted" style="font-size:.68rem;">[{_h(", ".join(_cats))}]</span>' if _cats else "")
                + "</div>"
            )
            if p.get("quote"):
                _prov_rows += f'<div class="provenance-quote">{_h(p["quote"])}</div>'
            elif p.get("url"):
                _prov_rows += f'<div class="provenance-quote"><a href="{_h(p["url"])}" target="_blank" rel="noopener">{_h(p["url"])}</a></div>'
        provenance_block = f"""
<div class="doc-section">
  <div class="doc-section-title">{_bi("Provenance tiers","Camadas de proveniência")} {_cov_badge}</div>
  {_prov_rows}
</div>"""
    else:
        provenance_block = ""

    # Candidate parts: triangulated tertiary findings not yet vetted as genus-wide —
    # never fed to OWL generation until a reviewer promotes them (Step 2c).
    try:
        _cp_raw = e.get("candidate_parts")
        _cp = json.loads(_cp_raw) if isinstance(_cp_raw, str) else (_cp_raw or [])
    except (json.JSONDecodeError, TypeError):
        _cp = []
    if _cp:
        _cp_rows = "".join(
            f'<div class="candidate-part-row"><span class="fw-semibold">{_h(cp.get("name") if isinstance(cp, dict) else cp)}</span></div>'
            for cp in _cp
        )
        candidate_parts_block = f"""
<div class="doc-section">
  <div class="doc-section-title">{_bi("Candidate parts (unconfirmed)","Partes candidatas (não confirmadas)")}</div>
  {_cp_rows}
</div>"""
    else:
        candidate_parts_block = ""

    # Primary-definition conflict — evidence CONTRADICTS the ISO 15926-4 primary
    # definition, not just supplements it (CLAUDE.md Step 2b). Always visible, not
    # tucked inside a collapsible section — mirrors enrichment_detail.html.
    _conflict = e.get("primary_definition_conflict")
    conflict_banner = (
        f'<div class="conflict-banner has-conflict">'
        f'<strong>⚠ {_bi("Conflicts with ISO 15926-4 primary definition","Conflita com a definição primária da ISO 15926-4")}</strong>'
        f'<div class="mt-1">{_h(_conflict)}</div></div>'
        if _conflict else ""
    )

    # Metadata
    meta_rows = "".join(
        f"<tr><td>{k}</td><td>{_h(v)}</td></tr>"
        for k, v in [
            (_bi("COPI ID","COPI ID"),    cid_label or "—"),
            (_bi("IRI","IRI"),             iri),
            (_bi("Status","Status"),       e.get("status") or "—"),
            (_bi("Axiom mode","Modo"),     e.get("axiom_mode") or "—"),
            (_bi("Created","Criado"),      (e.get("created_at") or "")[:10]),
            (_bi("Updated","Atualizado"),  (e.get("updated_at") or "")[:10]),
            (_bi("LLM model","Modelo LLM"), e.get("llm_model") or "—"),
            (_bi("Version","Versão"),      version_date),
        ]
    )
    metadata_block = (
        f'<div class="doc-section">'
        f'<div class="doc-section-title">{_bi("Metadata","Metadados")}</div>'
        f'<table class="meta-table"><tbody>{meta_rows}</tbody></table></div>'
    )

    # ISA 5.1 symbol — inline SVG so the static page is self-contained
    symbol_html = ""
    hero_symbol_html = ""
    symbol_path = e.get("symbol_path") or ""
    if symbol_path:
        _sym_file = (
            Path(__file__).parent.parent / "app" / "static" / "isa5_1" / symbol_path
        )
        if _sym_file.exists():
            _sym_content = _inline_symbol(_sym_file, max_px=120)
            _sym_hero   = _inline_symbol(_sym_file, max_px=64)
            # Sidebar version: full card with caption
            symbol_html = (
                f'<div style="background:#fff;border:1px solid var(--border);border-radius:8px;'
                f'padding:1rem;text-align:center;margin-bottom:1rem;">'
                f'<div style="max-height:120px;max-width:200px;margin:0 auto;overflow:hidden;">'
                f'{_sym_content}</div>'
                f'<div style="font-size:.68rem;color:var(--muted);margin-top:.4rem;font-family:monospace;">'
                f'ISA 5.1-2022 — {_h(symbol_path)}</div></div>'
            )
            # Hero version: compact thumbnail
            hero_symbol_html = (
                f'<div style="flex-shrink:0;background:#fff;border:1px solid rgba(255,255,255,.3);'
                f'border-radius:8px;padding:.5rem;width:80px;height:80px;display:flex;'
                f'align-items:center;justify-content:center;overflow:hidden;">'
                f'<div style="width:64px;height:64px;display:flex;align-items:center;'
                f'justify-content:center;overflow:hidden;">{_sym_hero}</div></div>'
            )

    body = f"""
<div class="d-flex justify-content-between align-items-center mb-3 no-print"
     style="font-family:system-ui,sans-serif;font-size:.83rem;">
  <div class="d-flex gap-2 align-items-center text-muted">
    <a href="../docs.html" class="text-muted text-decoration-none">← {_bi("Class Reference","Referência de Classes")}</a>
  </div>
</div>

<div style="max-width:1100px;">
  <div class="row">
    <div class="col-lg-8">

      <div class="ph-hero">
        <div class="d-flex align-items-start gap-3">
          {hero_symbol_html}
          <div style="flex:1;">
            <div class="d-flex align-items-center gap-2 mb-1">
              {_status_pill_static(e.get("status"))}
              {_mode_pill_static(e.get("axiom_mode"))}
              {'<code style="font-size:.72rem;background:#f3e8ff;color:#6b21a8;border-radius:4px;padding:.2rem .5rem;">' + _h(cid_label) + '</code>' if cid_label else ''}
            </div>
            <div class="ph-class-name">{_h(cls_title)}</div>
            <div class="ph-class-iri mt-1"><strong>IRI:</strong> <code>{_h(iri)}</code></div>
            <div class="mt-2" style="font-family:system-ui,sans-serif;font-size:.82rem;color:var(--muted);">
              {_bi("Generated on","Gerado em")} {_h((e.get("created_at") or "")[:10])}
            </div>
          </div>
        </div>
      </div>

      {conflict_banner}

      <div class="doc-section">
        <div class="doc-section-title">{_bi("Natural Language Definition","Definição em Linguagem Natural")}</div>
        {nl_defs}
      </div>

      <div class="doc-section">
        <div class="doc-section-title">{_bi("Formal Axioms","Axiomas Formais")}</div>
        {semiformal}
        <div class="axiom-block">
          <div class="axiom-label">{_bi("First-Order Logic Theory","Teoria em Lógica de Primeira Ordem")}</div>
          {fol_block}
        </div>
        {owl_block}
      </div>

      <div class="doc-section">
        <div class="doc-section-title">{_bi("Axiomatization Decision Log","Registro de Decisões")}</div>
        {step1}{step2}{step3}{step4}
      </div>

      {sig_html}
      {djt_html}
      {metadata_block}

    </div>

    <div class="col-lg-4">
      <div class="sidebar-sticky mt-4 mt-lg-0">
        {symbol_html}
        <div class="card border-0 shadow-sm mb-3" style="border-radius:8px;">
          <div class="card-header" style="font-family:system-ui,sans-serif;font-size:.72rem;
               font-weight:700;text-transform:uppercase;letter-spacing:.06em;background:#f8fafc;">
            {_bi("Quick facts","Dados rápidos")}
          </div>
          <div class="card-body" style="font-family:system-ui,sans-serif;font-size:.85rem;">
            <table class="meta-table">
              <tr><td>{_bi("Genus","Gênero")}</td><td><strong>{_h(e.get("genus") or "—")}</strong></td></tr>
              <tr><td>{_bi("Root class","Classe raiz")}</td><td>{('<span class="bfo-pill">' + _h(e.get("genus_bfo_root","")) + '</span>') if e.get("genus_bfo_root") else "—"}</td></tr>
              <tr><td>{_bi("Axiom mode","Modo")}</td><td>{_mode_pill_static(e.get("axiom_mode"))}</td></tr>
              <tr><td>{_bi("Function","Função")}</td><td>{_h(e.get("function_name") or "—")}</td></tr>
              <tr><td>{_bi("Process","Processo")}</td><td>{_h(e.get("process_name") or "—")}</td></tr>
              <tr><td>{_bi("Parts","Partes")}</td><td>{len(parts)}</td></tr>
            </table>
          </div>
        </div>
        {source_defs_block}
        {provenance_block}
        {candidate_parts_block}
      </div>
    </div>
  </div>
</div>
"""
    return _static_page(
        f"{cls_title} — COPI", "../docs.html", body,
        title_en=f"COPI · {cls_title}",
        title_pt=f"COPI · {cls_title}",
    )


_COPI_CORE_TTL  = Path(__file__).parent / "ontologies" / "copi-context" / "copi-core.ttl"
_COPI_VOCAB_TTL = Path(__file__).parent / "ontologies" / "copi-context" / "copi-vocab.ttl"


def _parse_copi_module(ttl_path: Path) -> dict:
    """
    Parse any COPI module TTL file.

    Returns two dicts:
      classes  : uri → record with all rich annotation fields
      obj_props: uri → record for ObjectProperties
      ann_props: uri → record for AnnotationProperties
    """
    try:
        import rdflib
        from rdflib import OWL, RDF, RDFS, SKOS, URIRef, Literal, Namespace
    except ImportError:
        return {"classes": {}, "obj_props": {}, "ann_props": {}}

    if not ttl_path.exists():
        return {"classes": {}, "obj_props": {}, "ann_props": {}}

    IOF_AV  = Namespace("https://spec.industrialontologies.org/ontology/annotation/")
    DC      = Namespace("http://purl.org/dc/terms/")
    COPI_NS = "https://www.inf.ufrgs.br/ontologies/copi/"

    g = rdflib.Graph()
    g.parse(str(ttl_path), format="turtle")

    def _first_lang(subj, prop, lang: str) -> str:
        for obj in g.objects(subj, prop):
            if isinstance(obj, Literal) and obj.language == lang:
                return str(obj)
        return ""

    def _all_langs(subj, prop) -> dict[str, str]:
        result: dict[str, str] = {}
        for obj in g.objects(subj, prop):
            if isinstance(obj, Literal):
                lang = obj.language or ""
                result[lang] = str(obj)
        return result

    def _untagged(subj, prop) -> str:
        for obj in g.objects(subj, prop):
            if isinstance(obj, Literal) and not obj.language:
                return str(obj)
        # fallback: any value
        val = g.value(subj, prop)
        return str(val) if val is not None else ""

    def _all_untagged(subj, prop) -> list[str]:
        return [
            str(obj) for obj in g.objects(subj, prop)
            if isinstance(obj, Literal) and not obj.language
        ]

    def _build_record(subj: URIRef, has_equiv: bool = False) -> dict:
        uri = str(subj)
        iri_label = uri[len(COPI_NS):]
        parents   = [str(p) for p in g.objects(subj, RDFS.subClassOf) if isinstance(p, URIRef)]
        disjoints = [str(d) for d in g.objects(subj, OWL.disjointWith) if isinstance(d, URIRef)]
        is_prim   = str(g.value(subj, IOF_AV.isPrimitive) or "").lower() == "true"

        # Multi-lang fields
        nld     = _all_langs(subj, IOF_AV.naturalLanguageDefinition)
        sfnla   = _all_langs(subj, IOF_AV.semiFormalNaturalLanguageAxiom)
        sfnld   = _all_langs(subj, IOF_AV.semiFormalNaturalLanguageDefinition)
        prat    = _all_langs(subj, IOF_AV.primitiveRationale)
        enotes  = _all_langs(subj, IOF_AV.explanatoryNote)
        examples = _all_langs(subj, SKOS.example)
        labels  = _all_langs(subj, RDFS.label)
        comment = _all_langs(subj, RDFS.comment)

        # Untagged fields (FOL, adaptedFrom, source)
        fol_axiom  = _untagged(subj, IOF_AV.firstOrderLogicAxiom)
        fol_def    = _untagged(subj, IOF_AV.firstOrderLogicDefinition)
        adapted    = _untagged(subj, IOF_AV.adaptedFrom)
        sources    = _all_untagged(subj, DC.source)

        return {
            "iri":         uri,
            "iri_label":   iri_label,
            "label_en":    labels.get("en", ""),
            "label_pt":    labels.get("pt-br", ""),
            "definition_en": nld.get("en", ""),
            "definition_pt": nld.get("pt-br", ""),
            "fol_axiom":      fol_axiom,
            "fol_definition": fol_def,
            "semiformal_axiom_en": sfnla.get("en", ""),
            "semiformal_axiom_pt": sfnla.get("pt-br", ""),
            "semiformal_def_en":   sfnld.get("en", ""),
            "semiformal_def_pt":   sfnld.get("pt-br", ""),
            "primitive_rationale_en": prat.get("en", ""),
            "primitive_rationale_pt": prat.get("pt-br", ""),
            "explanatory_note_en": enotes.get("en", ""),
            "explanatory_note_pt": enotes.get("pt-br", ""),
            "example_en":    examples.get("en", ""),
            "example_pt":    examples.get("pt-br", ""),
            "comment_en":    comment.get("en", ""),
            "adapted_from":  adapted,
            "source_odrs":   sources,
            "is_primitive":  is_prim,
            "is_defined":    has_equiv,
            "parents":       parents,
            "disjoints":     disjoints,
            "depth":         0,
        }

    classes:   dict[str, dict] = {}
    obj_props: dict[str, dict] = {}
    ann_props: dict[str, dict] = {}

    for subj in g.subjects(RDF.type, OWL.Class):
        if not isinstance(subj, URIRef):
            continue
        uri = str(subj)
        if not uri.startswith(COPI_NS):
            continue
        has_equiv = any(True for _ in g.objects(subj, OWL.equivalentClass))
        classes[uri] = _build_record(subj, has_equiv)

    for subj in g.subjects(RDF.type, OWL.ObjectProperty):
        if not isinstance(subj, URIRef):
            continue
        uri = str(subj)
        if not uri.startswith(COPI_NS):
            continue
        rec = _build_record(subj)
        # Additional property fields
        labels = _all_langs(subj, RDFS.label)
        sub_of = [str(p) for p in g.objects(subj, RDFS.subPropertyOf) if isinstance(p, URIRef)]
        # Property chain: collect each node in the chain list
        chain_nodes = []
        chain_val = g.value(subj, OWL.propertyChainAxiom)
        if chain_val is not None:
            from rdflib.collection import Collection
            try:
                chain_nodes = [str(n) for n in Collection(g, chain_val)]
            except Exception:
                pass
        rec.update({
            "sub_property_of": sub_of,
            "property_chain":  chain_nodes,
        })
        obj_props[uri] = rec

    for subj in g.subjects(RDF.type, OWL.AnnotationProperty):
        if not isinstance(subj, URIRef):
            continue
        uri = str(subj)
        if not uri.startswith(COPI_NS):
            continue
        lbl = _all_langs(subj, RDFS.label)
        cmt = _all_langs(subj, RDFS.comment)
        ann_props[uri] = {
            "iri":       uri,
            "iri_label": uri[len(COPI_NS):],
            "label_en":  lbl.get("en", "") or lbl.get("", ""),
            "comment_en": cmt.get("en", "") or cmt.get("", ""),
        }

    return {"classes": classes, "obj_props": obj_props, "ann_props": ann_props}


def _dfs_ordered(root_iri: str, items: list[dict]) -> list[dict]:
    """Return items in DFS tree order from root, setting 'depth' on each."""
    ordered: list[dict] = []
    seen: set[str] = set()

    def visit(iri: str, depth: int) -> None:
        if iri in seen:
            return
        seen.add(iri)
        item = next((c for c in items if c["iri"] == iri), None)
        if item:
            item["depth"] = depth
            ordered.append(item)
            children = sorted(
                [c for c in items if iri in c["parents"]],
                key=lambda c: c["iri_label"],
            )
            for child in children:
                visit(child["iri"], depth + 1)

    visit(root_iri, 0)
    for item in items:
        if item["iri"] not in seen:
            item["depth"] = 0
            ordered.append(item)
    return ordered


def _parse_copi_core_classes() -> dict:
    """Parse copi-core.ttl and organise into operations / equipment / other / property."""
    from rdflib import Namespace as _NS
    IOF_CONSTR = _NS("https://spec.industrialontologies.org/ontology/construct/")
    COPI_NS    = "https://www.inf.ufrgs.br/ontologies/copi/"

    mod = _parse_copi_module(_COPI_CORE_TTL)
    raw = mod["classes"]

    OPERATION_IRI     = f"{COPI_NS}COPI_0000001"
    MATERIAL_ARTIFACT = str(IOF_CONSTR.MaterialArtifact)

    def _is_op_desc(uri: str, visited: set | None = None) -> bool:
        if visited is None:
            visited = set()
        if uri in visited:
            return False
        visited.add(uri)
        if uri == OPERATION_IRI:
            return True
        return any(_is_op_desc(p, visited) for p in raw.get(uri, {}).get("parents", []))

    operations:      list[dict] = []
    equipment:       list[dict] = []
    other_processes: list[dict] = []

    for uri, cls in raw.items():
        if _is_op_desc(uri):
            operations.append(cls)
        elif MATERIAL_ARTIFACT in cls["parents"]:
            equipment.append(cls)
        else:
            other_processes.append(cls)

    sorted_ops = _dfs_ordered(OPERATION_IRI, operations)
    equipment.sort(key=lambda c: c["iri_label"])
    for cls in other_processes:
        cls["depth"] = 0

    obj_props = mod["obj_props"]
    property_data = next(iter(obj_props.values()), None) if obj_props else None

    return {
        "operations":      sorted_ops,
        "equipment":       equipment,
        "other_processes": other_processes,
        "property":        property_data,
    }


def _parse_copi_vocab_classes() -> dict:
    """Parse copi-vocab.ttl and organise into functions / process_stubs / fluids / info / qualities / ann_props."""
    COPI_NS = "https://www.inf.ufrgs.br/ontologies/copi/"
    mod     = _parse_copi_module(_COPI_VOCAB_TTL)
    raw     = mod["classes"]

    def _iri_num(cls: dict) -> int:
        try:
            return int(cls["iri_label"].replace("COPI_", ""))
        except ValueError:
            return 9999

    functions:      list[dict] = []
    process_stubs:  list[dict] = []
    fluid_types:    list[dict] = []
    info_types:     list[dict] = []
    qualities:      list[dict] = []

    for uri, cls in raw.items():
        n = _iri_num(cls)
        if 25 <= n <= 32:
            functions.append(cls)
        elif 33 <= n <= 36:
            process_stubs.append(cls)
        elif 37 <= n <= 44:
            fluid_types.append(cls)
        elif 45 <= n <= 51:
            info_types.append(cls)
        elif 52 <= n <= 60:
            qualities.append(cls)

    # Sort function hierarchy from root-ish classes down
    COPI_FLOW_FN  = f"{COPI_NS}COPI_0000026"
    COPI_INST_FN  = f"{COPI_NS}COPI_0000029"
    functions_ordered = _dfs_ordered(COPI_FLOW_FN, functions)
    # Merge remaining (root-level functions not under flow control)
    seen_iris = {c["iri"] for c in functions_ordered}
    for cls in sorted(functions, key=lambda c: c["iri_label"]):
        if cls["iri"] not in seen_iris:
            cls["depth"] = 0
            functions_ordered.append(cls)
            seen_iris.add(cls["iri"])

    fluid_ordered = _dfs_ordered(f"{COPI_NS}COPI_0000037", fluid_types)
    seen_f = {c["iri"] for c in fluid_ordered}
    for cls in sorted(fluid_types, key=lambda c: c["iri_label"]):
        if cls["iri"] not in seen_f:
            cls["depth"] = 0
            fluid_ordered.append(cls)

    for group in (process_stubs, info_types, qualities):
        for cls in group:
            cls["depth"] = 0
        group.sort(key=_iri_num)

    return {
        "functions":     functions_ordered,
        "process_stubs": process_stubs,
        "fluid_types":   fluid_ordered,
        "info_types":    info_types,
        "qualities":     qualities,
        "ann_props":     list(mod["ann_props"].values()),
    }


# ---------------------------------------------------------------------------
# Shared rich class card renderer for core / vocab module sections
# ---------------------------------------------------------------------------

def _rich_cls_card(cls: dict) -> str:
    """Render a full-content class card for a copi-core / copi-vocab class."""
    indent = cls.get("depth", 0) * 20
    indent_style = f"margin-left:{indent}px;" if indent else ""

    # ── Primitive / defined badge ──────────────────────────────────────────
    if cls.get("is_defined"):
        prim_badge = '<span class="mode-pill mode-equivalent" style="font-size:.62rem;">defined</span>'
    elif cls.get("is_primitive"):
        prim_badge = (
            '<span style="font-size:.62rem;font-family:system-ui,sans-serif;font-weight:600;'
            'padding:.1rem .45rem;border-radius:4px;background:#f1f5f9;color:#475569;">primitive</span>'
        )
    else:
        prim_badge = ""

    # ── Natural-language definition ────────────────────────────────────────
    nl_def = ""
    if cls.get("definition_en"):
        nl_def += f'<div class="nl-def t-en"><div class="lang-tag">en</div>{_h(cls["definition_en"])}</div>'
    if cls.get("definition_pt"):
        nl_def += (
            f'<div class="nl-def t-pt" style="border-left-color:#059669;">'
            f'<div class="lang-tag">pt-br</div>{_h(cls["definition_pt"])}</div>'
        )

    # ── FOL axiom / definition ─────────────────────────────────────────────
    fol_html = ""
    fol_text = cls.get("fol_definition") or cls.get("fol_axiom") or ""
    fol_kind = "Definition (↔)" if cls.get("fol_definition") else ("Axiom (→)" if cls.get("fol_axiom") else "")
    if fol_text:
        fol_html = (
            f'<div class="doc-section" style="margin-bottom:.75rem;">'
            f'<div class="doc-section-title">'
            f'{_bi(f"FOL {fol_kind}", f"LPO {fol_kind}")}</div>'
            f'<div class="owl-block" style="font-size:.76rem;padding:.55rem .8rem;">'
            f'{_h(fol_text)}</div></div>'
        )

    # ── Semi-formal NL (axiom for primitives, definition for defined) ──────
    sf_html = ""
    sf_en = cls.get("semiformal_def_en") or cls.get("semiformal_axiom_en") or ""
    sf_pt = cls.get("semiformal_def_pt") or cls.get("semiformal_axiom_pt") or ""
    if sf_en or sf_pt:
        sf_kind = "Semi-formal definition" if cls.get("semiformal_def_en") else "Semi-formal axiom"
        sf_inner = ""
        if sf_en:
            sf_inner += (
                f'<div class="t-en" style="font-family:monospace;font-size:.82rem;'
                f'background:#f8f9fa;border-radius:4px;padding:.35rem .6rem;margin-bottom:.3rem;">'
                f'{_h(sf_en)}</div>'
            )
        if sf_pt:
            sf_inner += (
                f'<div class="t-pt" style="font-family:monospace;font-size:.82rem;'
                f'background:#f0faf4;border-radius:4px;padding:.35rem .6rem;">'
                f'{_h(sf_pt)}</div>'
            )
        sf_html = (
            f'<div class="doc-section" style="margin-bottom:.75rem;">'
            f'<div class="doc-section-title">{_bi(sf_kind, sf_kind)}</div>'
            f'{sf_inner}</div>'
        )

    # ── Primitive rationale ────────────────────────────────────────────────
    prat_html = ""
    prat_en = cls.get("primitive_rationale_en", "")
    prat_pt = cls.get("primitive_rationale_pt", "")
    if prat_en or prat_pt:
        prat_inner = ""
        if prat_en:
            prat_inner += (
                f'<div class="t-en" style="font-size:.82rem;color:#374151;font-style:italic;">'
                f'{_h(prat_en)}</div>'
            )
        if prat_pt:
            prat_inner += (
                f'<div class="t-pt" style="font-size:.82rem;color:#374151;font-style:italic;">'
                f'{_h(prat_pt)}</div>'
            )
        prat_html = (
            f'<div class="doc-section" style="margin-bottom:.75rem;">'
            f'<div class="doc-section-title">{_bi("Primitive rationale","Justificativa de primitividade")}</div>'
            f'{prat_inner}</div>'
        )

    # ── Explanatory notes ──────────────────────────────────────────────────
    enote_html = ""
    enote_en = cls.get("explanatory_note_en", "")
    enote_pt = cls.get("explanatory_note_pt", "")
    if enote_en or enote_pt:
        en_inner = ""
        if enote_en:
            en_inner += f'<div class="t-en" style="font-size:.82rem;color:#374151;">{_h(enote_en)}</div>'
        if enote_pt:
            en_inner += f'<div class="t-pt" style="font-size:.82rem;color:#374151;">{_h(enote_pt)}</div>'
        enote_html = (
            f'<div class="doc-section" style="margin-bottom:.75rem;">'
            f'<div class="doc-section-title">{_bi("Explanatory note","Nota explicativa")}</div>'
            f'{en_inner}</div>'
        )

    # ── Examples ──────────────────────────────────────────────────────────
    ex_html = ""
    ex_en = cls.get("example_en", "")
    ex_pt = cls.get("example_pt", "")
    if ex_en or ex_pt:
        ex_inner = ""
        if ex_en:
            ex_inner += (
                f'<div class="t-en" style="font-size:.8rem;color:#475569;font-style:italic;">'
                f'<strong>e.g.</strong> {_h(ex_en)}</div>'
            )
        if ex_pt:
            ex_inner += (
                f'<div class="t-pt" style="font-size:.8rem;color:#475569;font-style:italic;">'
                f'<strong>ex.</strong> {_h(ex_pt)}</div>'
            )
        ex_html = (
            f'<div class="doc-section" style="margin-bottom:.75rem;">'
            f'<div class="doc-section-title">{_bi("Examples","Exemplos")}</div>'
            f'{ex_inner}</div>'
        )

    # ── Metadata strip (adaptedFrom, source, disjoint-with) ───────────────
    meta_rows = ""
    if cls.get("adapted_from"):
        meta_rows += (
            f'<tr><td style="padding:.2rem .7rem .2rem 0;color:var(--muted);white-space:nowrap;">'
            f'{_bi("Adapted from","Adaptado de")}</td>'
            f'<td style="font-size:.8rem;">{_h(cls["adapted_from"])}</td></tr>'
        )
    if cls.get("source_odrs"):
        meta_rows += (
            f'<tr><td style="padding:.2rem .7rem .2rem 0;color:var(--muted);white-space:nowrap;">'
            f'{_bi("Source","Fonte")}</td>'
            f'<td style="font-family:monospace;font-size:.78rem;">'
            f'{_h(", ".join(cls["source_odrs"]))}</td></tr>'
        )
    if cls.get("disjoints"):
        short_labels = [d.rsplit("/", 1)[-1].rsplit("#", 1)[-1] for d in cls["disjoints"]]
        meta_rows += (
            f'<tr><td style="padding:.2rem .7rem .2rem 0;color:var(--muted);white-space:nowrap;">'
            f'{_bi("Disjoint with","Disjunto de")}</td>'
            f'<td style="font-family:monospace;font-size:.78rem;color:#991b1b;">'
            f'{_h(", ".join(short_labels))}</td></tr>'
        )
    meta_html = ""
    if meta_rows:
        meta_html = (
            f'<div class="doc-section" style="margin-bottom:.5rem;">'
            f'<table style="font-family:system-ui,sans-serif;border-collapse:collapse;">'
            f'{meta_rows}</table></div>'
        )

    body = nl_def + fol_html + sf_html + prat_html + enote_html + ex_html + meta_html

    lbl_en = cls.get("label_en", "") or cls["iri_label"]
    lbl_pt = cls.get("label_pt", "") or lbl_en

    return f"""
<div class="class-card" style="{_h(indent_style)}">
  <div class="class-card-header">
    <div style="min-width:0;">
      <div class="class-card-name">
        {_bi(_h(lbl_en.title()), _h(lbl_pt.title()))}
      </div>
      <div class="class-iri">{_h(cls["iri"])}</div>
    </div>
    <div class="d-flex gap-2 align-items-center flex-shrink-0">{prim_badge}</div>
  </div>
  <div class="class-card-body">
    <div style="flex:1;min-width:0;">{body}</div>
  </div>
</div>"""


def _module_section_header(
    module_file: str, label_en: str, label_pt: str, count_str: str,
    layer_color: str = "var(--accent)",
) -> str:
    return f"""
<div style="font-family:system-ui,sans-serif;font-size:.72rem;font-weight:700;
            text-transform:uppercase;letter-spacing:.12em;color:{layer_color};
            border-bottom:3px solid {layer_color};padding-bottom:.5rem;margin-bottom:1.5rem;
            display:flex;align-items:center;justify-content:space-between;">
  <span style="display:flex;align-items:center;gap:.5rem;">
    <span class="toc-layer-dot" style="background:{layer_color};"></span>
    {_bi(label_en, label_pt)}
    <span style="font-weight:400;letter-spacing:0;text-transform:none;font-size:.75rem;
                 font-family:'IBM Plex Mono','Courier New',monospace;color:#94a3b8;">{_h(module_file)}</span>
  </span>
  <span class="count-badge">{count_str}</span>
</div>"""


def _prop_card(prop: dict, prop_type: str = "ObjectProperty") -> str:
    """Render a single ObjectProperty card with full annotations."""
    lbl_en = prop.get("label_en", prop["iri_label"])
    lbl_pt = prop.get("label_pt", "")
    def_en = prop.get("definition_en", "")
    def_pt = prop.get("definition_pt", "")
    enote_en = prop.get("explanatory_note_en", "")
    enote_pt = prop.get("explanatory_note_pt", "")

    body_parts = []
    if def_en:
        body_parts.append(
            f'<div class="t-en" style="font-style:italic;color:#374151;margin-bottom:.4rem;">{_h(def_en)}</div>'
        )
    if def_pt:
        body_parts.append(
            f'<div class="t-pt" style="font-style:italic;color:#374151;margin-bottom:.4rem;">{_h(def_pt)}</div>'
        )
    if enote_en:
        body_parts.append(
            f'<div class="t-en" style="font-size:.82rem;color:#374151;border-left:3px solid var(--border);'
            f'padding-left:.6rem;margin-top:.4rem;">{_h(enote_en)}</div>'
        )
    if enote_pt:
        body_parts.append(
            f'<div class="t-pt" style="font-size:.82rem;color:#374151;border-left:3px solid #059669;'
            f'padding-left:.6rem;margin-top:.4rem;">{_h(enote_pt)}</div>'
        )
    # Sub-property-of / chain
    meta_rows = ""
    sub_of = prop.get("sub_property_of") or []
    if sub_of:
        shorts = [p.rsplit("/", 1)[-1].rsplit("#", 1)[-1] for p in sub_of]
        meta_rows += (
            f'<tr><td style="color:var(--muted);padding-right:.7rem;white-space:nowrap;font-size:.78rem;">'
            f'Sub-property of</td><td style="font-family:monospace;font-size:.78rem;">'
            f'{_h(", ".join(shorts))}</td></tr>'
        )
    chain = prop.get("property_chain") or []
    if chain:
        short_chain = [p.rsplit("/", 1)[-1].rsplit("#", 1)[-1] for p in chain]
        meta_rows += (
            f'<tr><td style="color:var(--muted);padding-right:.7rem;white-space:nowrap;font-size:.78rem;">'
            f'Property chain</td><td style="font-family:monospace;font-size:.78rem;">'
            f'{_h(" ∘ ".join(short_chain))}</td></tr>'
        )
    sources = prop.get("source_odrs") or []
    if sources:
        meta_rows += (
            f'<tr><td style="color:var(--muted);padding-right:.7rem;white-space:nowrap;font-size:.78rem;">'
            f'Source</td><td style="font-family:monospace;font-size:.78rem;">'
            f'{_h(", ".join(sources))}</td></tr>'
        )
    if meta_rows:
        body_parts.append(
            f'<table style="font-family:system-ui,sans-serif;border-collapse:collapse;'
            f'margin-top:.5rem;">{meta_rows}</table>'
        )

    return f"""
<div class="rel-card">
  <div class="rel-card-header">
    <span class="rel-name">{_bi(_h(lbl_en), _h(lbl_pt))}</span>
    <span class="rel-type-pill">{_h(prop_type)}</span>
    <code style="margin-left:auto;font-size:.72rem;color:var(--muted);">{_h(prop["iri_label"])}</code>
  </div>
  <div class="rel-card-body">{''.join(body_parts)}</div>
</div>"""


def _ann_prop_card(prop: dict) -> str:
    return f"""
<div class="rel-card">
  <div class="rel-card-header">
    <span class="rel-name">{_h(prop.get("label_en",""))}</span>
    <span class="rel-type-pill">AnnotationProperty</span>
    <code style="margin-left:auto;font-size:.72rem;color:var(--muted);">{_h(prop["iri_label"])}</code>
  </div>
  {'<div class="rel-card-body" style="font-size:.82rem;color:#374151;">' + _h(prop.get("comment_en","")) + '</div>' if prop.get("comment_en") else ''}
</div>"""


def _core_module_section_html(core_data: dict) -> str:
    """Render the COPI-Core module section (operations + equipment + property)."""
    operations    = core_data.get("operations") or []
    equipment     = core_data.get("equipment") or []
    other_procs   = core_data.get("other_processes") or []
    prop          = core_data.get("property")

    if not (operations or equipment or other_procs or prop):
        return ""

    n_ops   = len(operations) + len(other_procs)
    n_equip = len(equipment)

    header = _module_section_header(
        "copi-core.ttl",
        "Module: copi-core", "Módulo: copi-core",
        f"{n_ops} {_bi('processes','processos')} · {n_equip} {_bi('equipment categories','categorias de equipamento')}",
        layer_color="var(--layer-core)",
    )

    ops_cards   = "".join(_rich_cls_card(c) for c in operations)
    other_cards = "".join(_rich_cls_card(c) for c in other_procs)
    equip_cards = "".join(_rich_cls_card(c) for c in equipment)

    prop_section = ""
    if prop:
        prop_section = f"""
<div class="bfo-section" id="core-properties">
  <div class="bfo-section-header">
    <span>{_bi("Object Properties","Propriedades de Objeto")}</span>
    <span class="count-badge">1 property</span>
  </div>
  {_prop_card(prop, "ObjectProperty")}
</div>"""

    return f"""
<div id="copi-core-module" style="margin-bottom:3rem;">
  {header}
  <div class="bfo-section" id="core-processes">
    <div class="bfo-section-header">
      <span>{_bi("Processes","Processos")}</span>
      <span class="count-badge">{n_ops} class{'es' if n_ops != 1 else ''}</span>
    </div>
    {ops_cards}{other_cards}
  </div>
  <div class="bfo-section" id="core-equipment">
    <div class="bfo-section-header">
      <span>{_bi("Equipment Categories","Categorias de Equipamento")}</span>
      <span class="count-badge">{n_equip} class{'es' if n_equip != 1 else ''}</span>
    </div>
    {equip_cards}
  </div>
  {prop_section}
</div>"""


def _vocab_module_section_html(vocab_data: dict) -> str:
    """Render the COPI-Vocab module section (functions, process stubs, participants, qualities, ann_props)."""
    functions    = vocab_data.get("functions") or []
    proc_stubs   = vocab_data.get("process_stubs") or []
    fluid_types  = vocab_data.get("fluid_types") or []
    info_types   = vocab_data.get("info_types") or []
    qualities    = vocab_data.get("qualities") or []
    ann_props    = vocab_data.get("ann_props") or []

    n_cls = len(functions) + len(proc_stubs) + len(fluid_types) + len(info_types) + len(qualities)
    n_ap  = len(ann_props)

    if not (n_cls or n_ap):
        return ""

    header = _module_section_header(
        "copi-vocab.ttl",
        "Module: copi-vocab", "Módulo: copi-vocab",
        f"{n_cls} {_bi('classes','classes')} · {n_ap} {_bi('annotation properties','propriedades de anotação')}",
        layer_color="var(--layer-vocab)",
    )

    def _subsection(anchor: str, label_en: str, label_pt: str, items: list[dict]) -> str:
        if not items:
            return ""
        cards = "".join(_rich_cls_card(c) for c in items)
        n = len(items)
        return f"""
<div class="bfo-section" id="{_h(anchor)}">
  <div class="bfo-section-header">
    <span>{_bi(label_en, label_pt)}</span>
    <span class="count-badge">{n} class{'es' if n != 1 else ''}</span>
  </div>
  {cards}
</div>"""

    fn_sec  = _subsection("vocab-functions",     "Designed Functions",        "Funções Projetadas",        functions)
    ps_sec  = _subsection("vocab-process-stubs", "Process Stubs",             "Esboços de Processos",      proc_stubs)
    fl_sec  = _subsection("vocab-fluids",        "Fluid Participant Types",   "Tipos de Participantes Fluidos", fluid_types)
    inf_sec = _subsection("vocab-info",          "Information Content Types", "Tipos de Conteúdo Informacional", info_types)
    q_sec   = _subsection("vocab-qualities",     "Quality Types",             "Tipos de Qualidade",        qualities)

    ap_sec = ""
    if ann_props:
        ap_cards = "".join(_ann_prop_card(p) for p in sorted(ann_props, key=lambda p: p["iri_label"]))
        ap_sec = f"""
<div class="bfo-section" id="vocab-ann-props">
  <div class="bfo-section-header">
    <span>{_bi("Cross-reference Annotation Properties","Propriedades de Anotação de Referência Cruzada")}</span>
    <span class="count-badge">{n_ap} propert{'ies' if n_ap != 1 else 'y'}</span>
  </div>
  {ap_cards}
</div>"""

    vocab_note = f"""
<div style="font-family:system-ui,sans-serif;font-size:.85rem;line-height:1.65;color:#374151;
     padding:.75rem 1rem;background:#f8fafc;border-left:4px solid var(--accent2);
     border-radius:0 6px 6px 0;margin-bottom:2rem;">
  <div class="t-en">
    <strong>Role in the ontology.</strong>
    The <em>Designed Functions</em> here are the functions whose realisation in a typed process
    defines each copi-core equipment category (via <code>functionally participates in</code> ∘
    <code>hasFunction</code>). <em>Process Stubs</em> are the corresponding process types.
    <em>Fluid, Information, and Quality types</em> populate the process participation signatures
    that ground disjointness between leaf equipment classes. The <em>cross-reference annotation
    properties</em> at the bottom link COPI classes to their counterparts in CFIHOS, PCA RDL,
    ISO 15926, DEXPI, and ISO 14224.
  </div>
  <div class="t-pt">
    <strong>Papel na ontologia.</strong>
    As <em>Funções Projetadas</em> aqui são as funções cuja realização em um processo tipado
    define cada categoria de equipamento do copi-core (via <code>functionally participates in</code> ∘
    <code>hasFunction</code>). <em>Esboços de Processos</em> são os tipos de processo correspondentes.
    Os <em>tipos de Fluidos, Informação e Qualidades</em> populam as assinaturas de participação
    em processos que fundamentam a disjunção entre as classes folha de equipamentos. As
    <em>propriedades de anotação de referência cruzada</em> no final vinculam as classes COPI
    às suas contrapartes no CFIHOS, PCA RDL, ISO 15926, DEXPI e ISO 14224.
  </div>
</div>"""

    return f"""
<div id="copi-vocab-module" style="margin-bottom:3rem;">
  {header}
  {vocab_note}
  {fn_sec}{ps_sec}{fl_sec}{inf_sec}{q_sec}{ap_sec}
</div>"""


def generate_static_docs(version_date: str | None = None, *, public_export: bool = False) -> dict[str, str]:
    """
    Generate self-contained static HTML documentation for all validated/exported enrichments.

    Returns a dict mapping relative paths (relative to the docs/ root) to HTML content:
      {"docs.html": "...", "classes/COPI_0000001.html": "...", ...}

    Caller writes these to disk or commits them to GitHub.
    The index maps to https://www.inf.ufrgs.br/ontologies/copi/docs
    Per-class pages map to https://www.inf.ufrgs.br/ontologies/copi/docs/classes/COPI_XXXXXXX.html
    """
    from datetime import date as _date
    from collections import defaultdict

    vdate = version_date or _date.today().isoformat()

    # Assign COPI IDs before generating so all validated classes have stable IRIs
    assign_copi_ids()

    conn = get_enrichment_db()
    rows = conn.execute("""
        SELECT id, cluster_label, status, genus, genus_bfo_root, function_name,
               function_parent, process_name, process_parent,
               nl_definition_en, nl_definition_pt, symbol_path, axiom_mode,
               disjoint_with, necessary_parts, process_signature,
               differentia_expression, differentia_nl,
               semiformal_axiom, fol_axiom,
               function_rationale, genus_rationale, differentia_rationale,
               parts_rationale, signature_rationale, disjointness_rationale,
               primitive_rationale, expert_review, expert_reviewer,
               copi_id, updated_at, created_at, llm_model,
               source_definitions_used, secondary_coverage,
               primary_definition_conflict, candidate_parts
        FROM enrichment
        WHERE status IN ('validated', 'exported')
        ORDER BY LOWER(cluster_label)
    """).fetchall()
    conn.close()

    classes = [dict(r) for r in rows]

    try:
        relations = [r for r in list_relations() if r.get("status") in ("validated", "exported")]
    except Exception:
        relations = []

    by_root: dict[str, list] = defaultdict(list)
    for cls in classes:
        root = cls.get("genus_bfo_root") or "Other"
        by_root[root].append(cls)

    root_order = ["EngineeredSystem", "Object", "ObjectAggregate", "MaterialArtifact",
                  "ProcessBoundary", "Process", "Other"]
    grouped = [(r, by_root[r]) for r in root_order if r in by_root]
    grouped += [(r, by_root[r]) for r in sorted(by_root) if r not in root_order]

    try:
        core_data = _parse_copi_core_classes()
    except Exception as _exc:
        logger.warning("_parse_copi_core_classes() failed: %s", _exc)
        core_data = None

    try:
        vocab_data = _parse_copi_vocab_classes()
    except Exception as _exc:
        logger.warning("_parse_copi_vocab_classes() failed: %s", _exc)
        vocab_data = None

    output: dict[str, str] = {}
    output["docs.html"] = _overview_page(
        classes, grouped, relations, vdate,
        core_data=core_data, vocab_data=vocab_data,
    )

    for cls in classes:
        cid = cls.get("copi_id")
        if not cid:
            continue
        try:
            turtle_src = generate_turtle(cls["id"])
        except Exception as exc:
            turtle_src = f"# Error generating Turtle: {exc}"
        output[f"classes/{_copi_label(cid)}.html"] = _class_page(cls, turtle_src, vdate, public_export=public_export)

    return output


# ── Cross-Standard Divergence Detection ───────────────────────────────────────

_DIV_LABELS = {
    "T1": "Categorical Placement",
    "T2": "Granularity",
    "T3": "Identity Criteria",
    "T4": "Topological vs. Mereological",
    "T5": "Implicit Function",
}

_SRC_DISPLAY = {
    "iso15926":          "ISO 15926-4",
    "posc_caesar":       "POSC Caesar",
    "cfihos":            "CFIHOS",
    "dexpi":             "DEXPI",
    "slb_glossary":      "SLB Glossary",
    "iso14224":          "ISO 14224",
    "onepetro_glossary": "OnePetro",
    "isa5_1":            "ISA 5.1",
    "ppdm":              "PPDM",
}

# Literal prefixes that must not appear in public OWL or HTML docs.
# Derived from _SRC_DISPLAY — update _SRC_DISPLAY first when adding sources.
PUBLIC_STRIP_PREFIXES: frozenset[str] = frozenset(
    f"[{name}]" for name in _SRC_DISPLAY.values()
)

# Broad parent category groups for T1 detection
_CAT_EQUIPMENT = {
    "equipment", "physicalobject", "object", "artefact", "artifact",
    "materialartifact", "assembly", "item", "physicalitem", "device",
    "mechanicalequipment", "processequipment", "staticequipment",
    "rotatingequipment", "industrialequipment", "mechanicalitem",
    "engineeredsystem", "engineereditem",
}
_CAT_PIPING = {
    "pipingcomponent", "pipelinesegment", "piperun", "pipework", "piping",
    "pipingnetworksegment", "pipingsegment", "flowpath", "networkcomponent",
    "pipingnetwork", "connectedpipe",
}
_CAT_INSTRUMENT = {
    "instrument", "measuringdevice", "sensor", "detector", "transmitter",
    "instrumentcomponent", "processinstrument", "instrumentationcomponent",
    "instrumentsystem",
}
_CAT_ELECTRICAL = {
    "electricalequipment", "electricalcomponent", "electricaldevice",
}


def _norm(s: str) -> str:
    """Normalise a label for category comparison."""
    return s.lower().replace(" ", "").replace("-", "").replace("_", "")


def _categorize_parent(parent_label: str) -> str:
    n = _norm(parent_label)
    if any(n.startswith(k) or k in n for k in _CAT_PIPING):
        return "piping"
    if any(n.startswith(k) or k in n for k in _CAT_INSTRUMENT):
        return "instrument"
    if any(n.startswith(k) or k in n for k in _CAT_ELECTRICAL):
        return "electrical"
    if any(n.startswith(k) or k in n for k in _CAT_EQUIPMENT):
        return "equipment"
    return "other"


def _get_cluster_hierarchy_info(cluster_label: str) -> list[dict]:
    """Query terms.db for parent/child hierarchy of the cluster across all sources."""
    conn = get_terms_db()
    variants = _label_variants(cluster_label)
    ph = ",".join("?" * len(variants))

    parent_rows = conn.execute(f"""
        SELECT t.preferred_label AS term, t.source,
               p.preferred_label AS parent
        FROM terms t
        JOIN hierarchy h ON h.child_term_id = t.id
        JOIN terms p ON p.id = h.parent_term_id
        WHERE LOWER(t.preferred_label) IN ({ph})
    """, variants).fetchall()

    child_rows = conn.execute(f"""
        SELECT t.preferred_label AS term, t.source,
               COUNT(c.id) AS child_count,
               GROUP_CONCAT(c.preferred_label, '||') AS child_labels
        FROM terms t
        JOIN hierarchy h ON h.parent_term_id = t.id
        JOIN terms c ON c.id = h.child_term_id
        WHERE LOWER(t.preferred_label) IN ({ph})
        GROUP BY t.source, t.preferred_label
    """, variants).fetchall()

    conn.close()

    parents_by_src: dict[str, list[str]] = {}
    for row in parent_rows:
        parents_by_src.setdefault(row["source"], []).append(row["parent"])

    children_by_src: dict[str, dict] = {}
    for row in child_rows:
        children_by_src[row["source"]] = {
            "count": row["child_count"],
            "labels": [lb for lb in (row["child_labels"] or "").split("||") if lb],
        }

    all_srcs = set(list(parents_by_src.keys()) + list(children_by_src.keys()))
    result = []
    for src in all_srcs:
        result.append({
            "source": src,
            "parents": parents_by_src.get(src, []),
            "child_count": children_by_src.get(src, {}).get("count", 0),
            "child_labels": children_by_src.get(src, {}).get("labels", []),
        })
    return result


def _detect_t5(cluster_label: str, definitions: list[dict]) -> dict | None:
    """T5: No source formally axiomatizes the identity-giving function."""
    formal_fn_kw = {
        "bfo_0000034", "designedfunction", "DesignedFunction", "realizable",
        "bearer", "disposition", "process in which", "realized in",
    }
    formal_sources = []
    for d in definitions:
        text_lower = (d.get("definition") or "").lower()
        if any(kw.lower() in text_lower for kw in formal_fn_kw):
            formal_sources.append(_SRC_DISPLAY.get(d["source"], d["source"]))

    src_list = list({_SRC_DISPLAY.get(d["source"], d["source"]) for d in definitions})
    evidence_parts = []
    for d in definitions:
        src = _SRC_DISPLAY.get(d["source"], d["source"])
        snippet = (d.get("definition") or "")[:120].replace("\n", " ")
        evidence_parts.append(f"{src}: \"{snippet}\"")

    evidence = " | ".join(evidence_parts) if evidence_parts else "No definitions found."

    if not formal_sources:
        return {
            "type": "T5",
            "label": _DIV_LABELS["T5"],
            "step": 1,
            "source_a": "; ".join(src_list) if src_list else None,
            "source_b": None,
            "description": (
                f"No standard provides a formal axiom for the identity-giving function of "
                f"{cluster_label}. All {len(definitions)} source definition(s) describe the "
                f"equipment informally (what it does) rather than specifying a DesignedFunction "
                f"subtype that constitutes the bearer's identity. This is the universal gap "
                f"that the five-step method addresses."
            ),
            "evidence": evidence,
        }
    return None


def _detect_t1(cluster_label: str, definitions: list[dict],
               hierarchy_info: list[dict]) -> dict | None:
    """T1: Different standards place the equipment under incompatible parent categories."""
    if len(hierarchy_info) < 2:
        return None

    categories: dict[str, list[str]] = {}
    for info in hierarchy_info:
        src = _SRC_DISPLAY.get(info["source"], info["source"])
        if not info["parents"]:
            continue
        cat = _categorize_parent(info["parents"][0])
        categories.setdefault(cat, []).append(
            f"{src} (parent: {info['parents'][0]})"
        )

    distinct_cats = {c for c in categories if c != "other"}
    if len(distinct_cats) < 2:
        return None

    cat_list = sorted(distinct_cats)
    src_a_entries = categories.get(cat_list[0], [])
    src_b_entries = categories.get(cat_list[1], [])

    src_a = src_a_entries[0].split(" (")[0] if src_a_entries else None
    src_b = src_b_entries[0].split(" (")[0] if src_b_entries else None

    all_evidence = []
    for cat, entries in categories.items():
        for e in entries:
            all_evidence.append(f"[{cat.upper()}] {e}")

    return {
        "type": "T1",
        "label": _DIV_LABELS["T1"],
        "step": 2,
        "source_a": src_a,
        "source_b": src_b,
        "description": (
            f"Standards disagree on the categorical placement of {cluster_label}. "
            f"Sources in the '{cat_list[0]}' category: {'; '.join(src_a_entries)}. "
            f"Sources in the '{cat_list[1]}' category: {'; '.join(src_b_entries)}. "
            f"This surfaces at Step 2 (genus determination) when choosing the BFO root."
        ),
        "evidence": " | ".join(all_evidence),
    }


def _detect_t2(cluster_label: str, definitions: list[dict],
               hierarchy_info: list[dict]) -> dict | None:
    """T2: One standard treats the concept as atomic; another decomposes it."""
    if not hierarchy_info:
        return None

    sources_with_children = [
        info for info in hierarchy_info if info["child_count"] > 0
    ]
    sources_without_children = [
        info for info in hierarchy_info if info["child_count"] == 0 and info["source"]
    ]

    src_def_counts: dict[str, int] = {}
    for d in definitions:
        src_def_counts[d["source"]] = src_def_counts.get(d["source"], 0) + 1

    if not sources_with_children:
        return None
    if not sources_without_children and all(v <= 1 for v in src_def_counts.values()):
        return None

    decomposed = []
    for info in sources_with_children:
        src = _SRC_DISPLAY.get(info["source"], info["source"])
        children_preview = ", ".join(info["child_labels"][:3])
        if len(info["child_labels"]) > 3:
            children_preview += f" … (+{info['child_count'] - 3} more)"
        decomposed.append(f"{src}: {info['child_count']} sub-class(es) [{children_preview}]")

    atomic = [
        _SRC_DISPLAY.get(info["source"], info["source"])
        for info in sources_without_children
    ]

    src_a = decomposed[0].split(":")[0] if decomposed else None
    src_b = atomic[0] if atomic else None

    return {
        "type": "T2",
        "label": _DIV_LABELS["T2"],
        "step": 4,
        "source_a": src_a,
        "source_b": src_b,
        "description": (
            f"Standards disagree on granularity for {cluster_label}. "
            f"{''.join(decomposed)} decompose into sub-classes, while "
            f"{', '.join(atomic) if atomic else 'other sources'} treat it as an atomic concept. "
            f"This surfaces at Step 4 (necessary parts) when deciding whether to model "
            f"sub-components as separate ontology classes or as parts of the main class."
        ),
        "evidence": (
            "Decomposed: " + "; ".join(decomposed) +
            (" | Atomic: " + ", ".join(atomic) if atomic else "")
        ),
    }


def _detect_t3(cluster_label: str, definitions: list[dict]) -> dict | None:
    """T3: Standards use different identity criteria (function vs topology vs properties)."""
    _FN_KW  = {"function", "designed", "purpose", "transfers", "controls", "regulates",
                "measures", "separates", "compresses", "pumps", "heats", "cools",
                "processes", "treats", "converts", "generates", "drives"}
    _TOP_KW = {"connects", "segment", "path", "network", "schematic", "symbol",
               "p&id", "routing", "connection", "spans", "topology", "topological",
               "configuration", "arrangement"}
    _PROP_KW= {"pressure", "temperature", "material", "rating", "specification",
               "design", "capacity", "flow rate", "size", "diameter", "thickness"}

    src_criteria: dict[str, str] = {}
    src_evidence: dict[str, str] = {}

    for d in definitions:
        text = (d.get("definition") or "").lower()
        src = _SRC_DISPLAY.get(d["source"], d["source"])
        fn_score   = sum(1 for kw in _FN_KW   if kw in text)
        top_score  = sum(1 for kw in _TOP_KW  if kw in text)
        prop_score = sum(1 for kw in _PROP_KW if kw in text)

        total = fn_score + top_score + prop_score
        if total == 0:
            continue

        if fn_score >= top_score and fn_score >= prop_score:
            criterion = "function-based"
        elif top_score >= fn_score and top_score >= prop_score:
            criterion = "topology-based"
        else:
            criterion = "property-based"

        src_criteria[src] = criterion
        src_evidence[src] = (d.get("definition") or "")[:100]

    distinct_criteria = set(src_criteria.values())
    if len(distinct_criteria) < 2:
        return None

    by_criterion: dict[str, list[str]] = {}
    for src, crit in src_criteria.items():
        by_criterion.setdefault(crit, []).append(src)

    crit_list = sorted(by_criterion.keys())
    src_a = by_criterion[crit_list[0]][0] if by_criterion.get(crit_list[0]) else None
    src_b = by_criterion[crit_list[1]][0] if len(crit_list) > 1 and by_criterion.get(crit_list[1]) else None

    evidence_parts = [
        f"{src} [{crit}]: \"{src_evidence.get(src,'')[:80]}\""
        for src, crit in src_criteria.items()
    ]

    return {
        "type": "T3",
        "label": _DIV_LABELS["T3"],
        "step": 3,
        "source_a": src_a,
        "source_b": src_b,
        "description": (
            f"Standards use different identity criteria for {cluster_label}. "
            + "; ".join(f"{', '.join(srcs)}: {crit}" for crit, srcs in by_criterion.items())
            + ". This surfaces at Step 3 (differentia specifica): the correct differentia "
            f"depends on which identity criterion the ontology adopts."
        ),
        "evidence": " | ".join(evidence_parts),
    }


def _detect_t4(cluster_label: str, definitions: list[dict]) -> dict | None:
    """T4: One standard models material parts; another models topological segments."""
    _TOPO_KW = {"segment", "network", "path", "routing", "endpoint", "node",
                "span", "run", "topological", "piping network", "flow path",
                "connection", "link", "reach"}
    _MERO_KW = {"part", "component", "body", "casing", "fitting", "flange",
                "wall", "housing", "shell", "tube", "assembly", "piece",
                "element", "member", "section"}

    topo_srcs  = []
    mero_srcs  = []
    evidence_parts = []

    for d in definitions:
        text = (d.get("definition") or "").lower()
        src  = _SRC_DISPLAY.get(d["source"], d["source"])
        topo = sum(1 for kw in _TOPO_KW if kw in text)
        mero = sum(1 for kw in _MERO_KW if kw in text)
        if topo > 0 and topo > mero:
            topo_srcs.append(src)
            evidence_parts.append(f"{src} [topological]: \"{(d.get('definition',''))[:80]}\"")
        elif mero > 0 and mero > topo:
            mero_srcs.append(src)
            evidence_parts.append(f"{src} [mereological]: \"{(d.get('definition',''))[:80]}\"")

    if not topo_srcs or not mero_srcs:
        return None

    return {
        "type": "T4",
        "label": _DIV_LABELS["T4"],
        "step": 4,
        "source_a": mero_srcs[0],
        "source_b": topo_srcs[0],
        "description": (
            f"Standards use fundamentally different modeling primitives for {cluster_label}. "
            f"{''.join(mero_srcs)} models it as a material artifact with physical parts "
            f"(mereological approach). {''.join(topo_srcs)} models it as a topological "
            f"entity in a network (topological approach). "
            f"This surfaces at Step 4: the BFO genus is incompatible between the two views."
        ),
        "evidence": " | ".join(evidence_parts),
    }


def detect_divergences(enrichment_id: int) -> list[dict]:
    """
    Auto-detect cross-standard divergences for a given enrichment.
    Clears any previously auto-detected divergences before re-running.
    Returns list of inserted divergence row dicts.
    """
    conn_e = get_enrichment_db()
    row = conn_e.execute("SELECT * FROM enrichment WHERE id=?", (enrichment_id,)).fetchone()
    if not row:
        conn_e.close()
        raise ValueError(f"Enrichment {enrichment_id} not found")
    e = dict(row)
    cluster_label = e["cluster_label"]

    definitions    = get_cluster_definitions(cluster_label)
    hierarchy_info = _get_cluster_hierarchy_info(cluster_label)

    # Clear previous auto-detections
    conn_e.execute(
        "DELETE FROM divergence_log WHERE enrichment_id=? AND detected_by='auto'",
        (enrichment_id,)
    )

    detected = []
    for fn in [_detect_t5, _detect_t1, _detect_t2, _detect_t3, _detect_t4]:
        try:
            if fn in (_detect_t1, _detect_t2):
                result = fn(cluster_label, definitions, hierarchy_info)
            else:
                result = fn(cluster_label, definitions)
        except Exception as exc:
            logger.warning("Divergence detector %s failed for %s: %s", fn.__name__, cluster_label, exc)
            result = None
        if result:
            detected.append(result)

    inserted_ids = []
    for d in detected:
        cur = conn_e.execute("""
            INSERT INTO divergence_log
                (enrichment_id, cluster_label, divergence_type, divergence_label,
                 detected_at_step, source_a, source_b, description, evidence, detected_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'auto')
        """, (
            enrichment_id, cluster_label,
            d["type"], d["label"], d.get("step"),
            d.get("source_a"), d.get("source_b"),
            d["description"], d.get("evidence"),
        ))
        inserted_ids.append(cur.lastrowid)

    conn_e.commit()

    # Re-fetch using DB column names so callers always get divergence_type/divergence_label/etc.
    rows = []
    for rid in inserted_ids:
        row = conn_e.execute("SELECT * FROM divergence_log WHERE id=?", (rid,)).fetchone()
        if row:
            rows.append(dict(row))

    conn_e.close()
    return rows


async def llm_detect_divergences(enrichment_id: int, api_key: str) -> list[dict]:
    """
    Use Claude to detect divergences that heuristics may have missed.
    Clears previous LLM-detected divergences before re-running.
    Returns list of inserted divergence row dicts.
    """
    conn_e = get_enrichment_db()
    row = conn_e.execute("SELECT * FROM enrichment WHERE id=?", (enrichment_id,)).fetchone()
    if not row:
        conn_e.close()
        raise ValueError(f"Enrichment {enrichment_id} not found")
    cluster_label = dict(row)["cluster_label"]
    conn_e.close()

    definitions = get_cluster_definitions(cluster_label)
    if not definitions:
        return []

    defs_text = "\n\n".join(
        f"**{_SRC_DISPLAY.get(d['source'], d['source'])}** — {d['term']}\n{d['definition']}"
        for d in definitions
    )

    prompt = f"""You are an ontology engineer analysing cross-standard divergences in industrial reference data.

Given these definitions of **{cluster_label}** from multiple industrial standards:

{defs_text}

Identify which of the following divergence types are present. Only report divergences that are clearly supported by the definitions above.

Divergence typology:
- **T1 Categorical Placement**: Same equipment type placed under different parent categories (e.g., Equipment in one standard vs PipingComponent in another)
- **T2 Granularity**: One standard treats it as atomic; another decomposes it into sub-classes or sub-functions
- **T3 Identity Criteria**: Standards use different criteria for what constitutes the type (function-based vs topology-based vs property-based)
- **T4 Topological vs Mereological**: One standard models material parts (flanges, casing); another models topological segments (network path, endpoint)
- **T5 Implicit Function**: No standard formally axiomatizes the identity-giving function using BFO/IOF constructs

For each divergence found, respond in this exact JSON format:
```json
[
  {{
    "type": "T1",
    "source_a": "ISO 15926-4",
    "source_b": "DEXPI",
    "step": 2,
    "description": "One sentence description of the divergence",
    "evidence": "Quoted text or field values from the definitions that show the divergence"
  }}
]
```

Only return the JSON array. If no divergences are found, return an empty array [].
"""

    import httpx as _httpx
    async with _httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            },
        )

    if resp.status_code != 200:
        raise ValueError(f"LLM API error {resp.status_code}: {resp.text[:200]}")

    raw = resp.json()["content"][0]["text"].strip()
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()

    try:
        candidates = json.loads(raw)
        if not isinstance(candidates, list):
            candidates = []
    except json.JSONDecodeError:
        candidates = []

    valid_types = {"T1", "T2", "T3", "T4", "T5"}
    conn_e = get_enrichment_db()
    conn_e.execute(
        "DELETE FROM divergence_log WHERE enrichment_id=? AND detected_by='llm'",
        (enrichment_id,)
    )
    inserted_ids = []
    for c in candidates:
        dtype = (c.get("type") or "").upper()
        if dtype not in valid_types:
            continue
        cur = conn_e.execute("""
            INSERT INTO divergence_log
                (enrichment_id, cluster_label, divergence_type, divergence_label,
                 detected_at_step, source_a, source_b, description, evidence, detected_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'llm')
        """, (
            enrichment_id, cluster_label,
            dtype, _DIV_LABELS[dtype],
            c.get("step"),
            c.get("source_a"), c.get("source_b"),
            c.get("description", ""), c.get("evidence", ""),
        ))
        inserted_ids.append(cur.lastrowid)
    conn_e.commit()

    # Re-fetch using DB column names so callers always get divergence_type/divergence_label/etc.
    rows = []
    for rid in inserted_ids:
        row = conn_e.execute("SELECT * FROM divergence_log WHERE id=?", (rid,)).fetchone()
        if row:
            rows.append(dict(row))

    conn_e.close()
    return rows


def get_divergences(enrichment_id: int) -> list[dict]:
    """Return all divergences logged for an enrichment, ordered by type."""
    conn = get_enrichment_db()
    rows = conn.execute(
        "SELECT * FROM divergence_log WHERE enrichment_id=? ORDER BY divergence_type, detected_by",
        (enrichment_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_divergence_resolution(div_id: int, resolution: str) -> None:
    conn = get_enrichment_db()
    conn.execute("UPDATE divergence_log SET resolution=? WHERE id=?", (resolution, div_id))
    conn.commit()
    conn.close()


def get_divergence_matrix() -> dict:
    """
    Build a matrix {cluster_label: {T1: [rows], T2: [rows], ...}} for all enrichments
    that have at least one divergence logged, ordered by cluster_label.
    Also returns sorted list of cluster_labels and summary stats per type.
    """
    conn = get_enrichment_db()
    rows = conn.execute("""
        SELECT d.*, e.id as enrichment_id_ref
        FROM divergence_log d
        JOIN enrichment e ON e.id = d.enrichment_id
        ORDER BY d.cluster_label, d.divergence_type
    """).fetchall()
    enrichments = conn.execute(
        "SELECT id, cluster_label, status, copi_id FROM enrichment "
        "WHERE status IN ('validated','exported','reviewed','proposed') "
        "ORDER BY cluster_label"
    ).fetchall()
    conn.close()

    matrix: dict[str, dict] = {}
    enr_map: dict[str, dict] = {}

    for e in enrichments:
        cl = e["cluster_label"]
        enr_map[cl] = dict(e)
        matrix[cl] = {"T1": [], "T2": [], "T3": [], "T4": [], "T5": []}

    for row in rows:
        cl = row["cluster_label"]
        if cl not in matrix:
            matrix[cl] = {"T1": [], "T2": [], "T3": [], "T4": [], "T5": []}
        dtype = row["divergence_type"]
        if dtype in matrix[cl]:
            matrix[cl][dtype].append(dict(row))

    stats = {}
    total = len(matrix)
    for t in ("T1", "T2", "T3", "T4", "T5"):
        count = sum(1 for cl_data in matrix.values() if cl_data[t])
        stats[t] = {"count": count, "pct": round(100 * count / total) if total else 0}

    return {
        "matrix": matrix,
        "enr_map": enr_map,
        "clusters": sorted(matrix.keys()),
        "stats": stats,
        "labels": _DIV_LABELS,
    }


def export_divergence_latex(matrix_data: dict) -> str:
    """Generate LaTeX table code for the divergence matrix."""
    clusters = matrix_data["clusters"]
    matrix   = matrix_data["matrix"]
    types    = ["T1", "T2", "T3", "T4", "T5"]

    lines = [
        r"\begin{table}[h]",
        r"\centering",
        r"\small",
        r"\begin{tabular}{l" + "c" * len(types) + "}",
        r"\hline",
        r"\textbf{Equipment Type} & " +
        " & ".join(r"\textbf{" + t + "}" for t in types) + r" \\",
        r"\hline",
    ]
    for cl in clusters:
        row_data = matrix.get(cl, {})
        cells = [r"$\bullet$" if row_data.get(t) else "" for t in types]
        lines.append(r"\textit{" + cl.title() + "} & " + " & ".join(cells) + r" \\")
    lines += [
        r"\hline",
        r"\end{tabular}",
        r"\caption{Cross-standard divergences revealed by the five-step axiomatization method. "
        r"T1=Categorical Placement, T2=Granularity, T3=Identity Criteria, "
        r"T4=Topological vs.\ Mereological, T5=Implicit Function ($\bullet$ = detected).}",
        r"\label{tab:divergences}",
        r"\end{table}",
    ]
    return "\n".join(lines)
