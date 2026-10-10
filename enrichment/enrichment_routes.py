"""
FastAPI routes for the RDL Enrichment feature.

Mount these in the existing agregador-termos app, e.g.:
    from enrichment_routes import router as enrichment_router
    app.include_router(enrichment_router, prefix="/enrich")

Provides:
    GET  /enrich/                     — Enrichment dashboard
    POST /enrich/run                  — Trigger LLM enrichment for a cluster
    GET  /enrich/{id}                 — View enrichment detail
    POST /enrich/{id}/update          — Update/validate a proposal
    GET  /enrich/{id}/turtle          — Download OWL/Turtle export
    GET  /enrich/{id}/owl             — Download OWL/XML export
    GET  /enrich/api/clusters         — JSON list of available clusters
    GET  /enrich/api/enrichments      — JSON list of all enrichments
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from fastapi import APIRouter, Depends, HTTPException, Request, Form, Query
from enrichment.auth import get_current_user
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse, StreamingResponse, RedirectResponse
from jinja2 import ChoiceLoader, FileSystemLoader

from app.jinja_setup import make_templates, COPYRIGHTED_SOURCES

import evaluation_metrics as _em
from metrics_routes import router as metrics_router

from enrichment_service import (
    enrich_cluster,
    reenrich_proposal,
    validate_necessary_parts_quotes,
    validate_tertiary_triangulation,
    validate_part_universality,
    validate_participant_vocabulary,
    validate_core_anchoring,
    normalize_core_operation_gap,
    find_unvetted_participants,
    load_participant_vocabulary_baseline,
    assign_copi_ids,
    generate_turtle,
    remap_turtle_to_numeric_iris,
    generate_combined_turtle,
    get_cluster_definitions,
    get_cluster_properties,
    get_label_aggregation_info,
    get_enrichment,
    get_enrichment_db,
    init_enrichment_schema,
    list_enrichments,
    update_enrichment,
    get_db,
    _find_col,
    list_relations,
    get_relation,
    create_relation,
    update_relation,
    delete_relation,
    get_out_of_scope_clusters,
    set_cluster_scope,
    snapshot_enrichment,
    list_history,
    get_history_snapshot,
    restore_enrichment_snapshot,
    get_linked_cqs,
    generate_cqs_csv,
    queue_add,
    queue_list,
    queue_next_pending,
    queue_set_running,
    queue_set_done,
    queue_set_failed,
    queue_clear_done,
    batch_submit_pending,
    batch_poll_status,
    batch_import_results,
    list_batch_submissions,
    scope_batch_submit,
    scope_batch_poll,
    scope_batch_import,
    list_scope_batch_submissions,
    generate_fol_theory,
    build_consequence_graph,
    build_chowlk_neighborhood,
    build_qa_context,
    log_qa_usage,
    list_qa_log,
    list_annotations,
    create_annotation,
    resolve_annotation,
    delete_annotation,
    get_copi_class_names,
    generate_static_docs,
    detect_divergences,
    llm_detect_divergences,
    get_divergences,
    update_divergence_resolution,
    get_divergence_matrix,
    export_divergence_latex,
    detect_aliases,
    list_aliases,
    update_alias,
    create_alias,
    _to_pascal_case,
    _AUX_VALID_CATEGORIES,
    _AUX_BFO_IRI,
    TERMS_DB_PATH,
    ENRICHMENT_DB_PATH,
    PUBLIC_STRIP_PREFIXES,
)

router = APIRouter()
router.include_router(metrics_router, prefix="/metrics")

logger = logging.getLogger(__name__)


def _redact_copyrighted_definitions(definitions: list[dict]) -> list[dict]:
    """Strip copyrighted definition text/properties for anonymous viewers.

    The source, term, term_type and source_uri are kept so the page can still
    link out to the standard as a citation — only the reproduced definition
    prose (and any properties derived from it) is gated behind login.
    """
    out = []
    for d in definitions:
        if d.get("source") in COPYRIGHTED_SOURCES:
            d = {**d, "definition": "", "properties": {}}
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# Evaluation metrics helpers (fire-and-forget — never raise)
# ---------------------------------------------------------------------------

def _log_event_safe(enrichment_id: int, event_type: str, event_detail: dict | None = None) -> None:
    """Open own DB connection, log one event, close. Never raises."""
    try:
        conn = get_enrichment_db()
        _em.log_event(conn, enrichment_id, event_type, event_detail)
        conn.close()
    except Exception as exc:
        logger.warning("_log_event_safe(%s, %s) failed: %s", enrichment_id, event_type, exc)


def _extract_step_data(e: dict) -> dict:
    """Pull all 5-step fields (content + rationale) used for axiom diff and Pareto tracking."""
    return {
        # Step 1
        "function_name":          e.get("function_name"),
        "process_name":           e.get("process_name"),
        "function_rationale":     e.get("function_rationale"),
        # Step 2
        "genus":                  e.get("genus"),
        "genus_bfo_root":         e.get("genus_bfo_root"),
        "genus_rationale":        e.get("genus_rationale"),
        # Step 3 (axiom_mode captured separately in take_axiom_snapshot)
        "differentia_expression": e.get("differentia_expression"),
        "differentia_nl":         e.get("differentia_nl"),
        "differentia_rationale":  e.get("differentia_rationale"),
        # Step 4
        "necessary_parts":        e.get("necessary_parts"),
        "parts_rationale":        e.get("parts_rationale"),
        # Step 5
        "process_signature":      e.get("process_signature"),
        "signature_rationale":    e.get("signature_rationale"),
    }


# Templates — ChoiceLoader: enrichment templates first, then app templates (for base.html)
TEMPLATE_DIR = Path(__file__).parent / "templates"
TEMPLATE_DIR.mkdir(exist_ok=True)
_APP_TEMPLATE_DIR = Path(__file__).parent.parent / "app" / "templates"
templates = make_templates(ChoiceLoader([
    FileSystemLoader(str(TEMPLATE_DIR)),
    FileSystemLoader(str(_APP_TEMPLATE_DIR)),
]))

# Initialize schema on import
init_enrichment_schema()

# ---------------------------------------------------------------------------
# Validation constants
# ---------------------------------------------------------------------------
_VALID_ENRICHMENT_STATUSES = {"draft", "proposed", "validated", "reviewed", "exported"}
_VALID_AXIOM_MODES = {"functional", "constructive", "both", "necessary", "equivalent"}
_VALID_BFO_ROOTS = {"Assembly", "MaterialArtifact", "EngineeredSystem"}
_VALID_SECONDARY_COVERAGE = {"none", "partial", "full"}
_VALID_PROP_TYPES = {"ObjectProperty", "DatatypeProperty"}
_VALID_RELATION_STATUSES = {"proposed", "validated", "exported"}
_VALID_EXPERT_STATUSES = {"pending", "approved", "rejected", "needs_revision"}


def _check_enum(value: str, allowed: set, field: str) -> None:
    if value and value not in allowed:
        raise HTTPException(422, f"Invalid value '{value}' for {field}. Allowed: {sorted(allowed)}")


# ---------------------------------------------------------------------------
# Helper: get available clusters from the terms DB
# ---------------------------------------------------------------------------

def _invalidate_cluster_cache() -> None:
    global _cluster_cache_ts
    with _cluster_cache_lock:
        _cluster_cache_ts = 0.0


def _get_available_clusters() -> list[dict]:
    """Get distinct term clusters from the terms database (cached for 5 min)."""
    global _cluster_cache, _cluster_cache_ts
    with _cluster_cache_lock:
        now = time.time()
        if _cluster_cache and (now - _cluster_cache_ts) < _CLUSTER_CACHE_TTL:
            return _cluster_cache

        conn = get_db()
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row["name"] for row in cursor.fetchall()]

        terms_table = None
        for candidate in ["terms", "term", "entries", "glossary"]:
            if candidate in tables:
                terms_table = candidate
                break

        if not terms_table:
            conn.close()
            return []

        cursor = conn.execute(f"PRAGMA table_info({terms_table})")
        columns = [row["name"] for row in cursor.fetchall()]
        name_col = _find_col(columns, ["preferred_label", "term", "name", "label", "title", "concept"])
        source_col = _find_col(columns, ["source", "origin", "standard", "provider", "dataset"])

        if not name_col:
            conn.close()
            return []

        # Quote identifiers to prevent injection from PRAGMA output
        q_table  = f'"{terms_table}"'
        q_name   = f'"{name_col}"'
        q_source = f'"{source_col}"' if source_col else None

        # Get clusters with counts
        query = f"""
            SELECT LOWER({q_name}) as cluster_label,
                   COUNT(*) as source_count
            {',' + f'GROUP_CONCAT(DISTINCT {q_source})' if q_source else ''}
            FROM {q_table}
            WHERE {q_name} IS NOT NULL AND {q_name} != ''
            GROUP BY LOWER({q_name})
            HAVING COUNT(*) >= 1
            ORDER BY COUNT(*) DESC
        """
        rows = conn.execute(query).fetchall()
        conn.close()

        results = []
        for row in rows:
            d = dict(row)
            results.append({
                "label": d["cluster_label"],
                "source_count": d["source_count"],
                "sources": d.get(f"GROUP_CONCAT(DISTINCT {q_source})", "") if q_source else "",
            })
        _cluster_cache = results
        _cluster_cache_ts = time.time()
        return results


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

from app.routers.terms import EQUIPMENT_SOURCES as _EQUIPMENT_SOURCES_LIST
_EQUIPMENT_SOURCES = set(_EQUIPMENT_SOURCES_LIST)

# Cluster list cache (5-minute TTL)
_cluster_cache: list[dict] = []
_cluster_cache_ts: float = 0.0
_CLUSTER_CACHE_TTL = 300.0
_cluster_cache_lock = threading.Lock()


@router.get("/", response_class=HTMLResponse)
async def enrichment_dashboard(request: Request):
    """Main enrichment dashboard."""
    enrichments = list_enrichments(deduplicate=True)
    _aux_db = get_enrichment_db()
    aux_pending = _aux_db.execute(
        "SELECT COUNT(*) FROM auxiliary_class WHERE status='pending'"
    ).fetchone()[0]
    _aux_db.close()
    return templates.TemplateResponse(request, "enrichment_dashboard.html", {
        "enrichments": enrichments,
        "api_key_configured": bool(os.getenv("ANTHROPIC_API_KEY")),
        "aux_pending": aux_pending,
    })


# Simple in-process rate limiter: track last run time per IP
_last_run_time: dict[str, float] = {}
_RUN_COOLDOWN_SECS = 10


@router.post("/run")
async def run_enrichment(
    request: Request,
    cluster_label: str = Form(...),
):
    """Trigger LLM enrichment for a cluster."""
    # Rate limit: one request per IP per cooldown window
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    last = _last_run_time.get(client_ip, 0.0)
    if now - last < _RUN_COOLDOWN_SECS:
        wait = int(_RUN_COOLDOWN_SECS - (now - last)) + 1
        raise HTTPException(429, f"Too many requests. Wait {wait}s before running another enrichment.")
    _last_run_time[client_ip] = now

    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        raise HTTPException(400, "ANTHROPIC_API_KEY is not set in the server environment.")

    try:
        proposal = await enrich_cluster(cluster_label, api_key=key)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"LLM call failed: {e}")

    _invalidate_cluster_cache()
    new_id = proposal["id"]

    # Snapshot the LLM initial output for axiom diff tracking
    try:
        _ttl = generate_turtle(new_id)
        _conn = get_enrichment_db()
        _em.take_axiom_snapshot(
            _conn, new_id, "llm_initial", _ttl,
            _extract_step_data(proposal), proposal.get("axiom_mode", ""),
        )
        _conn.close()
    except Exception as _exc:
        logger.warning("llm_initial snapshot(%s) failed: %s", new_id, _exc)

    # Auto-detect divergences (non-blocking — errors are logged, not raised)
    try:
        detect_divergences(new_id)
    except Exception as _exc:
        logger.warning("detect_divergences(%s) failed: %s", new_id, _exc)
    return JSONResponse({"id": new_id, "redirect": f"/enrich/{new_id}"})


@router.post("/rerun/{enrichment_id}")
async def rerun_enrichment(
    enrichment_id: int,
    request: Request,
    current_user: str = Depends(get_current_user),
):
    """Re-run LLM enrichment for an existing proposal, injecting reviewer notes as context."""
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        raise HTTPException(400, "ANTHROPIC_API_KEY is not set in the server environment.")
    _log_event_safe(enrichment_id, "rerun_request")
    snapshot_enrichment(enrichment_id, trigger="rerun")
    try:
        proposal = await reenrich_proposal(enrichment_id, api_key=key)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"LLM call failed: {e}")

    new_id = proposal["id"]
    update_enrichment(new_id, {
        "last_edited_by": current_user,
        "last_edited_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        "expert_reviewer": current_user,
    })
    _log_event_safe(new_id, "rerun_complete", {
        "input_tokens":  proposal.get("input_tokens"),
        "output_tokens": proposal.get("output_tokens"),
    })
    try:
        _ttl = generate_turtle(new_id)
        _conn = get_enrichment_db()
        _em.take_axiom_snapshot(
            _conn, new_id, "llm_initial", _ttl,
            _extract_step_data(proposal), proposal.get("axiom_mode", ""),
        )
        _conn.close()
    except Exception as _exc:
        logger.warning("llm_initial snapshot(%s) failed: %s", new_id, _exc)

    return JSONResponse({"id": new_id, "redirect": f"/enrich/{new_id}"})


@router.get("/verify", response_class=HTMLResponse)
async def verification_page(request: Request):
    """Ontology verification dashboard (OOPS!, FOOPS!, HermiT, CQ coverage)."""
    from verify_service import get_cq_summary
    from enrichment_service import get_enrichment_db, generate_combined_turtle
    import sqlite3, sys
    from pathlib import Path
    from config import COPI_IRI

    db_path = str(Path(__file__).parent.parent / "data" / "enrichment.db")
    cq = get_cq_summary(db_path)
    ttl = generate_combined_turtle()
    ttl_size = len(ttl.encode())
    with sqlite3.connect(db_path) as _c:
        enrichment_count = _c.execute(
            "SELECT COUNT(*) FROM enrichment WHERE status IN ('validated','exported')"
        ).fetchone()[0]

    return templates.TemplateResponse(request, "verification.html", {
        "copi_iri": COPI_IRI,
        "cq": cq,
        "ttl_size": ttl_size,
        "enrichment_count": enrichment_count,
        "has_ontology": ttl_size > 100,
    })


@router.post("/verify/oops", response_class=JSONResponse)
async def verify_oops(request: Request):
    """Run OOPS! Ontology Pitfall Scanner against the merged ontology TTL."""
    from verify_service import run_oops_check
    from pathlib import Path

    merged_path = Path(__file__).parent / "output" / "copi-merged.ttl"
    if not merged_path.exists():
        return JSONResponse({"ok": False, "error": "copi-merged.ttl not found. Regenerate it from the three source modules first."})
    ttl = merged_path.read_text(encoding="utf-8")
    if len(ttl.strip()) < 100:
        return JSONResponse({"ok": False, "error": "copi-merged.ttl is empty."})

    result = run_oops_check(ttl)
    return JSONResponse({
        "ok": result.ok,
        "error": result.error,
        "elapsed": round(result.elapsed, 2),
        "counts": result.counts if result.ok else {},
        "pitfalls": [
            {
                "code": p.code,
                "name": p.name,
                "description": p.description,
                "importance": p.importance,
                "affected": p.affected,
            }
            for p in result.pitfalls
        ] if result.ok else [],
    })


@router.post("/verify/foops", response_class=JSONResponse)
async def verify_foops(request: Request):
    """Run FOOPS! FAIR evaluation against the published ontology IRI."""
    from verify_service import run_foops_check

    FOOPS_IRI = "https://www.inf.ufrgs.br/ontologies/copi/"

    result = run_foops_check(FOOPS_IRI)
    if not result.ok:
        return JSONResponse({"ok": False, "error": result.error, "elapsed": round(result.elapsed, 2),
                             "evaluated_iri": FOOPS_IRI})

    by_cat = result.checks_by_category()
    return JSONResponse({
        "ok": True,
        "evaluated_iri": FOOPS_IRI,
        "ontology_uri": result.ontology_uri,
        "ontology_title": result.ontology_title,
        "overall_score": result.overall_score,
        "elapsed": round(result.elapsed, 2),
        "categories": {
            cat: {
                "score": result.score_for_category(cat),
                "checks": [
                    {
                        "abbreviation": c.abbreviation,
                        "title": c.title,
                        "principle_id": c.principle_id,
                        "status": c.status,
                        "explanation": c.explanation,
                        "total_tests_run": c.total_tests_run,
                        "total_passed_tests": c.total_passed_tests,
                    }
                    for c in checks
                ],
            }
            for cat, checks in by_cat.items()
        },
    })


@router.post("/verify/consistency", response_class=JSONResponse)
async def verify_consistency(request: Request):
    """Run OWL 2 DL consistency check via HermiT reasoner."""
    from verify_service import run_consistency_check, merge_base_modules
    from enrichment_service import generate_combined_turtle

    ttl = generate_combined_turtle()
    if len(ttl.strip()) < 100:
        return JSONResponse({"ok": False, "error": "No validated enrichments to check."})

    # Merge copi-core/copi-vocab first -- without this, references to vocab-owned
    # classes (e.g. COPI_0000058/59, COPI_0000383-385) reason as if undeclared.
    # See merge_base_modules() docstring; matches push_to_github's preflight.
    try:
        ttl = merge_base_modules(ttl)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": f"Could not merge base modules: {exc}"})

    result = run_consistency_check(ttl)
    return JSONResponse({
        "ok": result.ok,
        "consistent": result.consistent,
        "inconsistent_classes": result.inconsistent_classes,
        "class_count": result.class_count,
        "elapsed": round(result.elapsed, 2),
        "error": result.error,
        "inferences": [
            {
                "cls_label":    i.cls_label,
                "cls_iri":      i.cls_iri,
                "kind":         i.kind,
                "target_label": i.target_label,
                "target_iri":   i.target_iri,
            }
            for i in result.inferences
        ],
    })


@router.post("/verify/apv", response_class=JSONResponse)
async def verify_apv(request: Request):
    """Run APV annotation property verification against the combined ontology TTL."""
    from verify_service import run_apv_check
    from enrichment_service import generate_combined_turtle

    ttl = generate_combined_turtle()
    if len(ttl.strip()) < 100:
        return JSONResponse({"error": "No validated enrichments to check."})

    result = run_apv_check(ttl)
    return JSONResponse(result)


@router.get("/quality/batch", response_class=JSONResponse)
async def quality_batch():
    """Run definition quality checks over all validated/reviewed enrichments with a COPI ID."""
    from verify_service import run_quality_checks_batch
    from enrichment_service import ENRICHMENT_DB_PATH

    results = run_quality_checks_batch(str(ENRICHMENT_DB_PATH))
    with_issues = sum(1 for r in results if r["issue_count"] > 0)
    return JSONResponse({"ok": True, "total": len(results), "with_issues": with_issues, "results": results})


@router.get("/docs", response_class=HTMLResponse)
async def ontology_docs(request: Request):
    """Full ontology documentation — rendered inside the editor shell so the nav stays visible."""
    return templates.TemplateResponse(request, "docs_preview.html", {})


# ---------------------------------------------------------------------------
# Relations (object/datatype properties)
# — must be registered BEFORE /{enrichment_id} or FastAPI matches "relations"
#   as an integer path parameter and raises a 422 validation error.
# ---------------------------------------------------------------------------

@router.get("/api/clusters", response_class=JSONResponse)
async def api_clusters():
    """JSON list of all clusters with enrichment and scope flags (cached)."""
    clusters = _get_available_clusters()
    enrichments = list_enrichments()
    enriched_map = {e["cluster_label"]: {"id": e["id"], "status": e["status"]} for e in enrichments}
    manual_oos = get_out_of_scope_clusters()
    jobs = queue_list()
    running_labels = {j["cluster_label"] for j in jobs if j["status"] == "running"}
    pending_labels = {j["cluster_label"] for j in jobs if j["status"] == "pending"}
    # Labels that have a proposed alias (potential duplicate)
    alias_rows = list_aliases(status="proposed")
    alias_sources = {a["source_label"] for a in alias_rows}
    result = []
    for c in clusters:
        src_set = set((c.get("sources") or "").split(","))
        has_equipment = bool(src_set & _EQUIPMENT_SOURCES)
        is_oos = (c["label"] in manual_oos) or not has_equipment
        enr = enriched_map.get(c["label"])
        result.append({
            "label": c["label"],
            "source_count": c["source_count"],
            "sources": c.get("sources", ""),
            "has_enrichment": enr is not None,
            "enrichment_id": enr["id"] if enr else None,
            "enrichment_status": enr["status"] if enr else None,
            "is_oos": is_oos,
            "oos_manual": c["label"] in manual_oos,
            "is_running": c["label"] in running_labels,
            "is_pending": c["label"] in pending_labels,
            "has_alias": c["label"] in alias_sources,
        })
    return JSONResponse(result)


@router.get("/relations", response_class=HTMLResponse)
async def relations_page(request: Request):
    """Manage OWL object/datatype properties defined in COPI."""
    rels = list_relations()
    return templates.TemplateResponse(request, "relations.html", {"relations": rels})


@router.post("/relations/create")
async def create_relation_route(request: Request):
    form = await request.form()
    data = {
        "name":          form.get("name", "").strip(),
        "label_en":      form.get("label_en", ""),
        "label_pt":      form.get("label_pt", ""),
        "prop_type":     form.get("prop_type", "ObjectProperty"),
        "domain":        form.get("domain", ""),
        "range_type":    form.get("range_type", ""),
        "parent_prop":   form.get("parent_prop", ""),
        "is_functional": 1 if form.get("is_functional") else 0,
        "is_symmetric":  1 if form.get("is_symmetric") else 0,
        "is_transitive": 1 if form.get("is_transitive") else 0,
        "inverse_of":    form.get("inverse_of", ""),
        "definition_en": form.get("definition_en", ""),
        "definition_pt": form.get("definition_pt", ""),
        "rationale":     form.get("rationale", ""),
        "status":        form.get("status", "proposed"),
    }
    if not data["name"]:
        raise HTTPException(400, "Property name is required")
    _check_enum(data.get("prop_type", ""), _VALID_PROP_TYPES, "prop_type")
    _check_enum(data.get("status", ""), _VALID_RELATION_STATUSES, "status")
    rel = create_relation(data)
    return JSONResponse({"id": rel["id"], "redirect": "/enrich/relations"})


@router.post("/relations/{relation_id}/update")
async def update_relation_route(relation_id: int, request: Request):
    form = await request.form()
    data = {k: form[k] for k in form.keys()}
    for bool_field in ("is_functional", "is_symmetric", "is_transitive"):
        data[bool_field] = 1 if form.get(bool_field) else 0
    _check_enum(data.get("prop_type", ""), _VALID_PROP_TYPES | {""}, "prop_type")
    _check_enum(data.get("status", ""), _VALID_RELATION_STATUSES | {""}, "status")
    update_relation(relation_id, data)
    return JSONResponse({"success": True})


@router.post("/relations/{relation_id}/delete")
async def delete_relation_route(relation_id: int):
    delete_relation(relation_id)
    return JSONResponse({"success": True, "redirect": "/enrich/relations"})


@router.get("/api/relations/{rel_id}/usage", response_class=JSONResponse)
async def relation_usage(rel_id: int):
    import sqlite3
    from enrichment_service import ENRICHMENT_DB_PATH
    rel = get_relation(rel_id)
    if not rel:
        raise HTTPException(status_code=404, detail="Relation not found")
    with sqlite3.connect(str(ENRICHMENT_DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, cluster_label, status FROM enrichment "
            "WHERE custom_axioms LIKE ? ORDER BY cluster_label",
            (f'%{rel["name"]}%',),
        ).fetchall()
    return JSONResponse([dict(r) for r in rows])


# Scope toggle
# — must be registered BEFORE /{enrichment_id} to avoid int-parsing 422

# ---------------------------------------------------------------------------
# Scope classifiers — BEFORE /{enrichment_id} and BEFORE {cluster_label:path}
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Term-type-based OOS rules — deterministic, always override LLM decisions
# ---------------------------------------------------------------------------

# ISO 15926 term_types that are never physical equipment in a petroleum plant
_OOS_ISO15926_TYPES = {
    # Activities / events / roles
    "ClassOfActivity", "ClassOfEvent", "Role",
    # Quantities, scales, properties — abstract concepts not physical artifacts
    "SinglePropertyDimension", "Scale", "ClassOfScale", "ClassOfQuantity",
    "ClassOfIndirectProperty", "Property", "PropertyRange", "PropertySpace",
    "MultidimensionalProperty", "MultidimensionalPropertySpace", "MultidimensionalScale",
    "ClassOfProperty", "ClassOfPropertySpace",
    # Information / documents / representations
    "ClassOfInformationObject", "ClassOfInformationPresentation",
    "ClassOfRepresentation", "ClassOfInformationRepresentation",
    "DocumentDefinition", "RepresentationForm", "ExpressString",
    # Spatial / geometric / shape
    "ClassOfSpatialLocation", "ClassOfFeature",
    "ClassOfShape", "ClassOfShapeDimension",
    # Organisation / person
    "ClassOfOrganization", "ClassOfPerson",
    # Logical / relational / abstract structure
    "ClassOfArrangement", "ClassOfArrangementOfIndividual",
    "ClassOfRelationship", "ClassOfComposition", "ClassOfFunctionalMapping",
    "ClassOfClassOfIndividual", "ClassOfPossibleIndividual", "ClassOfSpecification",
    "ClassOfRecognition", "ClassOfAbstractObject", "ClassOfMultidimensionalObject",
    "ClassOfInvolvementByReference", "ClassOfCauseOfBeginningOfClassOfIndividual",
    "ParticipatingRoleAndDomain", "ClassOfIndividualUsedInConnection",
    "ClassOfConnectionOfIndividual", "ClassOfIndirectConnection",
    "EnumeratedSetOfClass",
    # Status / phase / language — not physical objects
    "ClassOfStatus", "Status", "Phase", "Language",
    # Chemical compounds / materials — not equipment pieces
    "ClassOfCompound", "ClassOfCompositeMaterial",
}

# ISO 14224 terms that are terminology definitions, not equipment classes
_OOS_ISO14224_TYPES = {"Definition"}

# ISA source types that are coding schemes, not equipment classes
_OOS_ISA_TYPES = {
    "letter_code", "tag_abbreviation", "modifier", "prefix", "suffix",
}


def _run_type_based_scope_classify() -> dict:
    """
    Apply term-type-based OOS rules to cluster_scope.
    Type-based decisions are deterministic and always override LLM in-scope
    decisions (but never demote an already-OOS term to in-scope).
    Returns {"marked": N, "total_candidates": M}.
    """
    import sqlite3
    from enrichment_service import TERMS_DB_PATH, ENRICHMENT_DB_PATH

    if not TERMS_DB_PATH.exists():
        return {"marked": 0, "total_candidates": 0, "error": "terms.db not found"}

    tconn = sqlite3.connect(str(TERMS_DB_PATH))
    tconn.row_factory = sqlite3.Row
    rows = tconn.execute(
        "SELECT DISTINCT preferred_label, source, term_type FROM terms "
        "WHERE term_type IS NOT NULL AND term_type != ''"
    ).fetchall()
    tconn.close()

    oos_clusters: dict[str, str] = {}
    for row in rows:
        # Normalize to lowercase to match _get_available_clusters() which uses LOWER(preferred_label)
        label = (row["preferred_label"] or "").strip().lower()
        src   = row["source"] or ""
        ttype = row["term_type"] or ""

        if src == "iso15926" and ttype in _OOS_ISO15926_TYPES:
            oos_clusters[label] = f"ISO 15926 term_type={ttype}"
        elif src == "iso14224" and ttype in _OOS_ISO14224_TYPES:
            oos_clusters[label] = f"ISO 14224 term_type={ttype}"
        elif src == "isa5_1" and ttype.lower() in _OOS_ISA_TYPES:
            oos_clusters[label] = f"ISA 5.1 term_type={ttype} (coding scheme)"

    if not oos_clusters:
        return {"marked": 0, "total_candidates": 0}

    econn = sqlite3.connect(str(ENRICHMENT_DB_PATH))
    econn.execute("""
        CREATE TABLE IF NOT EXISTS cluster_scope (
            cluster_label TEXT PRIMARY KEY,
            out_of_scope  INTEGER DEFAULT 0,
            reason        TEXT,
            updated_at    TEXT DEFAULT (datetime('now'))
        )
    """)

    count = 0
    for label, reason in oos_clusters.items():
        # Always override in-scope (0) or unset decisions; never demote OOS (1)
        econn.execute("""
            INSERT INTO cluster_scope (cluster_label, out_of_scope, reason, updated_at)
            VALUES (?, 1, ?, datetime('now'))
            ON CONFLICT(cluster_label) DO UPDATE SET
                out_of_scope = 1,
                reason = excluded.reason,
                updated_at = excluded.updated_at
            WHERE out_of_scope = 0 OR out_of_scope IS NULL
        """, (label, reason))
        count += econn.execute("SELECT changes()").fetchone()[0]
    econn.commit()
    econn.close()

    return {"marked": count, "total_candidates": len(oos_clusters)}


@router.post("/scope/auto-classify")
async def auto_classify_scope():
    """
    Auto-mark clusters as out-of-scope based on term_type.
    Type-based rules are deterministic and override LLM in-scope decisions.
    """
    if not TERMS_DB_PATH.exists():
        raise HTTPException(404, "terms.db not found")
    result = _run_type_based_scope_classify()
    if "error" in result:
        raise HTTPException(404, result["error"])
    return JSONResponse(result)


@router.post("/scope/llm-classify")
async def llm_classify_scope(request: Request):
    """
    Use Claude Haiku to classify unscoped clusters against COPI scope.
    Processes up to `limit` clusters per call (default 50).
    """
    import sqlite3
    from enrichment_service import TERMS_DB_PATH, ENRICHMENT_DB_PATH, ANTHROPIC_API_URL, SCOPE_DEFINITION

    form = await request.form()
    limit = int(form.get("limit") or 50)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(400, "ANTHROPIC_API_KEY is not set in the server environment.")

    # Find clusters without a scope decision
    econn = sqlite3.connect(str(ENRICHMENT_DB_PATH))
    econn.row_factory = sqlite3.Row
    scoped = {r["cluster_label"] for r in econn.execute(
        "SELECT cluster_label FROM cluster_scope"
    ).fetchall()}
    econn.close()

    tconn = sqlite3.connect(str(TERMS_DB_PATH))
    tconn.row_factory = sqlite3.Row
    all_labels = {r["preferred_label"] for r in tconn.execute(
        "SELECT DISTINCT preferred_label FROM terms WHERE preferred_label IS NOT NULL"
    ).fetchall()}
    tconn.close()

    unclassified = sorted(all_labels - scoped)[:limit]
    if not unclassified:
        return JSONResponse({"classified": 0, "message": "All clusters already have a scope decision"})

    # Build batch prompt
    items_text = "\n".join(f"{i+1}. {lbl}" for i, lbl in enumerate(unclassified))
    prompt = (
        f"{SCOPE_DEFINITION}\n\n"
        "For each term below, reply with ONLY a JSON array where each element is "
        "{\"label\": \"...\", \"in_scope\": true/false, \"reason\": \"one sentence\"}.\n\n"
        f"{items_text}"
    )

    import httpx as _httpx
    async with _httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": prompt}],
            },
        )

    if resp.status_code != 200:
        raise HTTPException(502, f"LLM error {resp.status_code}: {resp.text[:200]}")

    try:
        raw = resp.json()["content"][0]["text"]
    except Exception as exc:
        raise HTTPException(502, f"Unexpected API response shape: {exc} — body: {resp.text[:200]}")

    import re
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        raise HTTPException(502, f"LLM did not return a JSON array: {raw[:300]}")

    try:
        results = json.loads(m.group())
    except json.JSONDecodeError as exc:
        raise HTTPException(502, f"Could not parse LLM JSON array: {exc} — raw: {raw[:300]}")

    econn = sqlite3.connect(str(ENRICHMENT_DB_PATH))
    econn.execute("""
        CREATE TABLE IF NOT EXISTS cluster_scope (
            cluster_label TEXT PRIMARY KEY,
            out_of_scope  INTEGER DEFAULT 0,
            reason        TEXT,
            updated_at    TEXT DEFAULT (datetime('now'))
        )
    """)

    classified = 0
    for item in results:
        label  = item.get("label", "").strip()
        in_scope = bool(item.get("in_scope", True))
        reason = item.get("reason", "LLM classifier")
        econn.execute("""
            INSERT INTO cluster_scope (cluster_label, out_of_scope, reason, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(cluster_label) DO UPDATE SET
                out_of_scope = excluded.out_of_scope,
                reason = excluded.reason,
                updated_at = excluded.updated_at
        """, (label, 0 if in_scope else 1, reason))
        classified += 1

    econn.commit()
    econn.close()

    oos_count = sum(1 for r in results if not r.get("in_scope", True))
    return JSONResponse({
        "classified": classified,
        "out_of_scope": oos_count,
        "in_scope": classified - oos_count,
    })


# ---------------------------------------------------------------------------
# Scope classification — Anthropic Message Batch routes
# (must come BEFORE the {cluster_label:path} catch-all below)
# ---------------------------------------------------------------------------

@router.post("/scope/batch-submit", response_class=JSONResponse)
async def scope_batch_submit_route(request: Request):
    """
    Submit all unclassified cluster labels to the Anthropic Message Batches API
    in chunks of 100 for COPI scope classification.
    50% cheaper than standard calls; results available in ~1 hour.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(400, "ANTHROPIC_API_KEY is not set")
    try:
        result = await scope_batch_submit(api_key)
    except Exception as exc:
        raise HTTPException(502, str(exc))
    return JSONResponse(result)


@router.get("/scope/batch/{anthropic_batch_id}/status", response_class=JSONResponse)
async def scope_batch_status_route(anthropic_batch_id: str):
    """Poll Anthropic for the status of a scope classification batch."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(400, "ANTHROPIC_API_KEY is not set")
    try:
        data = await scope_batch_poll(anthropic_batch_id, api_key)
    except Exception as exc:
        raise HTTPException(502, str(exc))
    return JSONResponse(data)


@router.post("/scope/batch/{anthropic_batch_id}/import", response_class=JSONResponse)
async def scope_batch_import_route(anthropic_batch_id: str):
    """Import results from a completed scope classification batch into cluster_scope."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(400, "ANTHROPIC_API_KEY is not set")
    try:
        result = await scope_batch_import(anthropic_batch_id, api_key)
    except Exception as exc:
        raise HTTPException(502, str(exc))
    return JSONResponse(result)


@router.get("/scope/batches", response_class=JSONResponse)
async def scope_batch_list_route():
    """List all scope classification batch submissions."""
    return JSONResponse(list_scope_batch_submissions())


# This route uses {cluster_label:path} and must come AFTER all specific /scope/* routes
@router.post("/scope/{cluster_label:path}")
async def toggle_cluster_scope(
    cluster_label: str,
    out_of_scope: bool = Form(...),
    reason: str = Form(default=""),
):
    set_cluster_scope(cluster_label, out_of_scope, reason)
    return JSONResponse({"ok": True, "out_of_scope": out_of_scope})


# ---------------------------------------------------------------------------
# Literal-path routes that must come BEFORE /{enrichment_id}
# ---------------------------------------------------------------------------

@router.get("/imported-ontologies", response_class=HTMLResponse)
async def ontology_browser_page(request: Request):
    """Two-panel browser for BFO 2020 and IOF-Core classes."""
    from ontology_service import get_class_list
    classes = get_class_list()
    return templates.TemplateResponse(request, "ontology_browser.html", {
        "classes": classes,
    })


@router.get("/api-usage", response_class=HTMLResponse)
async def api_usage_page(request: Request):
    """API usage dashboard — token consumption and cost by enrichment."""
    import sqlite3
    from enrichment_service import ENRICHMENT_DB_PATH
    conn = sqlite3.connect(str(ENRICHMENT_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        # Fetch cache token columns with COALESCE for older rows that predate the columns
        rows = conn.execute(
            "SELECT id, cluster_label, status, llm_model, input_tokens, output_tokens, "
            "estimated_cost_usd, created_at, "
            "COALESCE(cache_write_tokens, 0) AS cache_write_tokens, "
            "COALESCE(cache_read_tokens, 0) AS cache_read_tokens "
            "FROM enrichment WHERE input_tokens IS NOT NULL AND input_tokens > 0 "
            "ORDER BY created_at DESC"
        ).fetchall()
        total_axiomatizations = conn.execute(
            "SELECT COUNT(*) FROM enrichment"
        ).fetchone()[0]
    except Exception:
        # Fallback for databases that don't yet have the cache columns
        rows = conn.execute(
            "SELECT id, cluster_label, status, llm_model, input_tokens, output_tokens, "
            "estimated_cost_usd, created_at "
            "FROM enrichment WHERE input_tokens IS NOT NULL AND input_tokens > 0 "
            "ORDER BY created_at DESC"
        ).fetchall()
        total_axiomatizations = conn.execute(
            "SELECT COUNT(*) FROM enrichment"
        ).fetchone()[0]
    finally:
        conn.close()
    enrichments = [dict(r) for r in rows]
    for e in enrichments:
        e.setdefault("cache_write_tokens", 0)
        e.setdefault("cache_read_tokens", 0)
    total_in          = sum(e["input_tokens"]        or 0 for e in enrichments)
    total_out         = sum(e["output_tokens"]       or 0 for e in enrichments)
    total_cost        = sum(e["estimated_cost_usd"]  or 0 for e in enrichments)
    total_cache_write = sum(e["cache_write_tokens"]  or 0 for e in enrichments)
    total_cache_read  = sum(e["cache_read_tokens"]   or 0 for e in enrichments)
    api_key_set = bool(os.getenv("ANTHROPIC_API_KEY"))

    qa_rows = list_qa_log()
    qa_total_in   = sum(r["input_tokens"]  or 0 for r in qa_rows)
    qa_total_out  = sum(r["output_tokens"] or 0 for r in qa_rows)
    qa_total_cost = sum(r["estimated_cost_usd"] or 0 for r in qa_rows)

    return templates.TemplateResponse(request, "api_usage.html", {
        "enrichments": enrichments,
        "total_in": total_in,
        "total_out": total_out,
        "total_cost": total_cost,
        "total_cache_write": total_cache_write,
        "total_cache_read": total_cache_read,
        "api_key_set": api_key_set,
        "total_axiomatizations": total_axiomatizations,
        "qa_rows": qa_rows,
        "qa_total_in": qa_total_in,
        "qa_total_out": qa_total_out,
        "qa_total_cost": qa_total_cost,
    })


@router.get("/consequences", response_class=HTMLResponse)
async def consequences_page(request: Request):
    """Ontology consequence viewer — graph of all approved classes + individual inferences."""
    return templates.TemplateResponse(request, "consequences.html", {})


@router.get("/api/consequences", response_class=JSONResponse)
async def api_consequences():
    """Return the full consequence graph JSON for the frontend."""
    try:
        graph = build_consequence_graph()
        return JSONResponse(graph)
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/api/chowlk/{enrichment_id}", response_class=JSONResponse)
async def api_chowlk(enrichment_id: int):
    """Return Chowlk-notation neighborhood data for a single enriched class."""
    try:
        return JSONResponse(build_chowlk_neighborhood(enrichment_id))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# Validate: Q&A
# ---------------------------------------------------------------------------

@router.post("/api/validate/qa", response_class=JSONResponse)
async def validate_qa(request: Request):
    """Answer a natural-language question about the ontology using Claude."""
    body    = await request.json()
    question = (body.get("question") or "").strip()
    if not question:
        raise HTTPException(400, "question is required")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(503, "ANTHROPIC_API_KEY not configured")

    context = build_qa_context()
    history = body.get("history") or []

    system_prompt = (
        "You are an ontology expert assistant for COPI (Core Ontology of Petroleum "
        "Production Plants), a BFO 2020 / IOF-Core based OWL 2 DL ontology.\n\n"
        "Answer questions based ONLY on the provided class definitions and axioms. "
        "Be explicit about:\n"
        "- What is formally required (necessary conditions / owl:someValuesFrom restrictions)\n"
        "- What is NOT in the ontology (open-world assumption: absence ≠ negation)\n"
        "- Whether a class uses equivalent (≡) or subClassOf (⊑) axioms\n"
        "If a class is not yet modelled, say so clearly.\n"
        "Respond in the same language as the question (Portuguese or English). "
        "Be concise — 2-4 paragraphs max.\n\n"
        f"## Ontology context\n\n{context}"
    )

    # Build message list: prior history (up to last 10 turns) + current question
    messages = [
        {"role": m["role"], "content": m["content"]}
        for m in history[-10:]
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]
    messages.append({"role": "user", "content": question})

    try:
        async with httpx.AsyncClient(timeout=60) as client:
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
                    "system": system_prompt,
                    "messages": messages,
                },
            )
    except Exception as exc:
        raise HTTPException(502, f"API call failed: {exc}")

    if resp.status_code != 200:
        raise HTTPException(resp.status_code, resp.text[:300])

    payload = resp.json()
    answer = payload["content"][0]["text"]

    # Log token usage
    usage = payload.get("usage", {})
    in_tok  = usage.get("input_tokens", 0)
    out_tok = usage.get("output_tokens", 0)
    # Haiku pricing: $0.80/M input, $4.00/M output (as of 2025)
    cost = (in_tok * 0.80 + out_tok * 4.00) / 1_000_000
    log_qa_usage(question, in_tok, out_tok, cost, "claude-haiku-4-5-20251001")

    return JSONResponse({"answer": answer})



@router.get("/qa", response_class=HTMLResponse)
async def qa_page(request: Request):
    """Dedicated Q&A page for ontology questions."""
    return templates.TemplateResponse(request, "qa.html", {})


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------

@router.post("/api/translate", response_class=JSONResponse)
async def translate_texts(request: Request):
    """
    Translate a batch of text blocks to pt-BR using Claude Haiku.
    Body: {"texts": [{"id": "...", "text": "..."}, ...]}
    Returns: {"translations": {"id": "translated text", ...}}
    """
    body = await request.json()
    texts = body.get("texts") or []
    if not texts:
        return JSONResponse({"translations": {}})

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(503, "ANTHROPIC_API_KEY not configured")

    # Build a numbered list for the LLM
    numbered = "\n\n".join(
        f"[{i+1}] {item['text']}" for i, item in enumerate(texts)
    )

    system_prompt = (
        "You are a precise technical translator. Translate the following texts "
        "from English to Brazilian Portuguese (pt-BR).\n\n"
        "Rules:\n"
        "- Keep ALL technical terms, class names, property names, and OWL/BFO/IOF "
        "identifiers in English (e.g., MaterialArtifact, hasComponentPartAtAllTimes, BFO, IOF-Core).\n"
        "- Translate surrounding prose naturally.\n"
        "- Preserve the original meaning exactly — do not paraphrase or summarize.\n"
        "- Return ONLY the translations, numbered exactly as the input [1], [2], etc.\n"
        "- Do not add explanations or commentary."
    )

    user_msg = f"Translate these texts to pt-BR:\n\n{numbered}"

    try:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 4096,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_msg}],
                },
            )
    except Exception as exc:
        raise HTTPException(502, f"Translation API call failed: {exc}")

    if resp.status_code != 200:
        raise HTTPException(resp.status_code, resp.text[:300])

    payload = resp.json()
    raw = payload["content"][0]["text"]

    # Log token usage (cheap — count as a Q&A-style event)
    usage = payload.get("usage", {})
    in_tok  = usage.get("input_tokens", 0)
    out_tok = usage.get("output_tokens", 0)
    cost = (in_tok * 0.80 + out_tok * 4.00) / 1_000_000
    log_qa_usage(f"[translate batch {len(texts)} items]", in_tok, out_tok, cost, "claude-haiku-4-5-20251001")

    # Parse numbered output back to a dict keyed by original id
    import re
    translations = {}
    parts = re.split(r'\[(\d+)\]', raw)
    # parts = ['', '1', ' text1...', '2', ' text2...', ...]
    it = iter(parts[1:])  # skip leading empty string
    for num_str, content in zip(it, it):
        idx = int(num_str) - 1
        if 0 <= idx < len(texts):
            translations[texts[idx]["id"]] = content.strip()

    return JSONResponse({"translations": translations})


# ---------------------------------------------------------------------------
# Annotations
# ---------------------------------------------------------------------------

@router.get("/api/enrichments/{enrichment_id}/annotations", response_class=JSONResponse)
async def get_annotations(enrichment_id: int):
    return JSONResponse(list_annotations(enrichment_id))


@router.post("/api/enrichments/{enrichment_id}/annotations", response_class=JSONResponse)
async def post_annotation(enrichment_id: int, request: Request):
    body = await request.json()
    text = (body.get("body") or "").strip()
    if not text:
        raise HTTPException(400, "body is required")
    ann = create_annotation(
        enrichment_id=enrichment_id,
        field=body.get("field"),
        author=body.get("author") or "anonymous",
        body=text,
    )
    return JSONResponse(ann)


@router.patch("/api/annotations/{ann_id}/resolve", response_class=JSONResponse)
async def resolve_ann(ann_id: int, request: Request):
    body = await request.json()
    ann = resolve_annotation(ann_id, body.get("resolved_by") or "anonymous")
    return JSONResponse(ann)


@router.delete("/api/annotations/{ann_id}", response_class=JSONResponse)
async def delete_ann(ann_id: int):
    delete_annotation(ann_id)
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# COPI class names for datalists
# ---------------------------------------------------------------------------

@router.get("/api/class-names", response_class=JSONResponse)
async def class_names():
    return JSONResponse(get_copi_class_names())


@router.get("/backup", dependencies=[Depends(get_current_user)])
async def backup_enrichment_db():
    """Download enrichment.db as a timestamped zip archive."""
    import io
    import zipfile
    from datetime import datetime
    from enrichment_service import ENRICHMENT_DB_PATH

    if not ENRICHMENT_DB_PATH.exists():
        raise HTTPException(404, "enrichment.db not found")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(str(ENRICHMENT_DB_PATH), "enrichment.db")
    buf.seek(0)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=enrichment_backup_{ts}.zip"},
    )


@router.get("/ontology.ttl", response_class=PlainTextResponse, dependencies=[Depends(get_current_user)])
async def combined_ontology():
    """Download merged OWL/Turtle for all validated/exported enrichments."""
    ttl = generate_combined_turtle()
    return PlainTextResponse(
        ttl,
        media_type="text/turtle",
        headers={"Content-Disposition": "attachment; filename=copi.ttl"},
    )


@router.get("/export/odk.owl", response_class=PlainTextResponse, dependencies=[Depends(get_current_user)])
async def export_owl_functional():
    """Download the same RDF/XML that push_to_github() would commit to
    src/ontology/components/copi-enriched.owl -- see generate_enriched_owl_rdfxml()
    docstring. Previously served a different, independently-generated OWL
    Functional Syntax file that had drifted out of sync with the real pipeline
    (unmapped readable-name IRIs, hasFunction instead of bearerOf, no
    copi-core/copi-vocab/copi-enriched import chain); fixed to match push_to_github."""
    from datetime import date
    import sys as _sys
    vdate = date.today().isoformat()
    _sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from regen_enriched_owl import generate_enriched_owl_rdfxml
    try:
        owl_content = generate_enriched_owl_rdfxml(verbose=False)
    except Exception as exc:
        raise HTTPException(400, str(exc))
    return PlainTextResponse(
        owl_content,
        media_type="application/rdf+xml",
        headers={"Content-Disposition": f"attachment; filename=copi-enriched-{vdate}.owl"},
    )


_docs_preview_cache: dict[str, str] = {}
_docs_preview_cache_public: dict[str, str] = {}


def _get_docs_preview() -> dict[str, str]:
    """Generate (or return cached) static docs for the preview routes."""
    global _docs_preview_cache
    from datetime import date
    vdate = date.today().isoformat()
    _docs_preview_cache = generate_static_docs(version_date=vdate)
    return _docs_preview_cache


def _get_docs_preview_public() -> dict[str, str]:
    """Generate (or return cached) public static docs — copyrighted definitions stripped."""
    global _docs_preview_cache_public
    from datetime import date
    vdate = date.today().isoformat()
    _docs_preview_cache_public = generate_static_docs(version_date=vdate, public_export=True)
    return _docs_preview_cache_public


def _inject_base_tag(html: str, base_href: str) -> str:
    """Inject <base href="..."> right after <head> so relative links resolve correctly."""
    return html.replace("<head>", f'<head>\n<base href="{base_href}">', 1)


@router.get("/export/docs", response_class=HTMLResponse)
async def preview_static_docs(request: Request):
    """Preview the generated static docs index (same HTML that will be committed to GitHub)."""
    docs = _get_docs_preview() if request.state.user else _get_docs_preview_public()
    html = docs.get("docs.html", "<p>No validated classes to document.</p>")
    # Inject base so that relative links (classes/COPI_*.html) resolve to /enrich/export/docs/classes/...
    html = _inject_base_tag(html, "/enrich/export/docs/")
    return HTMLResponse(html)


@router.get("/export/docs/docs.html", response_class=RedirectResponse)
async def static_docs_index_redirect():
    """Redirect ../docs.html links from class pages back to the docs index."""
    return RedirectResponse("/enrich/export/docs", status_code=302)


@router.get("/export/docs/classes/{copi_filename}", response_class=HTMLResponse)
async def preview_static_docs_class(request: Request, copi_filename: str):
    """Serve a single class page from the static docs preview."""
    if request.state.user:
        docs = _docs_preview_cache if _docs_preview_cache else _get_docs_preview()
    else:
        docs = _docs_preview_cache_public if _docs_preview_cache_public else _get_docs_preview_public()
    key = f"classes/{copi_filename}"
    html = docs.get(key)
    if not html:
        raise HTTPException(404, f"Class page '{copi_filename}' not found in generated docs")
    # Use classes/ as base so ../docs.html resolves to /enrich/export/docs/docs.html → redirected to /enrich/export/docs
    html = _inject_base_tag(html, "/enrich/export/docs/classes/")
    return HTMLResponse(html)


@router.post("/export/github", response_class=JSONResponse)
async def push_to_github(request: Request):
    """
    Push copi-enriched.owl and static docs/ to INF-UFRGS-Ontologies/copi on GitHub
    as a new branch and open a pull request against master.

    The PR-based flow means anyone can trigger the push, but only the
    ontology maintainer can merge to master (where ODK CI runs QC).

    Expects form fields:
      github_token  — GitHub PAT with repo:write + pull_request:write scope
      commit_msg    — optional commit message / PR description override
    """
    import base64
    import subprocess
    import sys as _sys
    from datetime import date, datetime as _dt

    form = await request.form()
    token = (form.get("github_token") or "").strip()
    if not token:
        raise HTTPException(400, "github_token is required")

    vdate = date.today().isoformat()
    timestamp = _dt.now().strftime("%Y%m%d-%H%M%S")
    branch = f"enrichment/{timestamp}"

    validated = [e for e in list_enrichments() if e.get("status") in ("validated", "exported")]
    n = len(validated)
    if n == 0:
        raise HTTPException(400, "No validated enrichments to push.")

    user_msg = (form.get("commit_msg") or "").strip()
    commit_msg = user_msg or f"Update COPI ontology [{vdate}] — {n} validated class{'es' if n != 1 else ''}"
    pr_title   = user_msg or f"COPI ontology update [{vdate}] — {n} class{'es' if n != 1 else ''}"

    _copieditor_root = Path(__file__).parent.parent
    _copi_repo_root = _copieditor_root.parent / "copi"

    # ── Generate the real ontology content ──────────────────────────────────
    # Reuses scripts/regen_enriched_owl.py's pipeline directly. This flow used to
    # call a second, independent generator (generate_owl_functional()) that had
    # silently drifted out of sync with the maintained pipeline: it never
    # remapped readable-name IRIs through copi-iri-map.tsv, emitted hasFunction
    # instead of bearerOf on object-level axioms, and dropped the
    # copi-core/copi-vocab/copi-enriched import chain entirely (see PR #17,
    # closed unmerged 2026-09-03). Never reintroduce a second generator here —
    # everything this route ships must come from generate_enriched_owl_rdfxml().
    _sys.path.insert(0, str(_copieditor_root / "scripts"))
    from regen_enriched_owl import generate_enriched_owl_rdfxml, OUTPUT_PATH as _ENRICHED_OWL_PATH

    try:
        owl_content = generate_enriched_owl_rdfxml(verbose=False)
    except Exception as exc:
        raise HTTPException(400, {
            "error": "preflight_failed", "check": "generate_enriched_owl",
            "message": f"Could not generate copi-enriched.owl: {exc}",
        })

    # ── Pre-flight quality gate ─────────────────────────────────────────────
    # Run all checks before touching GitHub. Hard blocks prevent a broken
    # ontology from ever reaching the repository. verify_owl.sh is the
    # authoritative, already-tested gate (numeric IRI gate, disjointness
    # invariant, duplicate-definition gate, HermiT unsatisfiability, all
    # documented entailment/regression guards) -- run it for real instead of
    # re-deriving a subset of its checks in Python a second time. It reads
    # copi-enriched.owl from disk (its #26/#27 disjointness-invariant gate
    # specifically), so write the freshly-generated content there first, then
    # restore whatever was already committed once we're done with it -- this
    # route pushes via the GitHub API to a new branch, never by committing
    # locally, so the local clone must come out of this exactly as it went in.
    from verify_service import run_oops_check, merge_base_modules

    _original_owl = _ENRICHED_OWL_PATH.read_text(encoding="utf-8") if _ENRICHED_OWL_PATH.exists() else None
    _ENRICHED_OWL_PATH.write_text(owl_content, encoding="utf-8")
    try:
        _verify = subprocess.run(
            ["bash", str(_copieditor_root / "scripts" / "verify_owl.sh"), "--skip-oops"],
            cwd=str(_copieditor_root), capture_output=True, text=True, timeout=600,
        )
    finally:
        if _original_owl is not None:
            _ENRICHED_OWL_PATH.write_text(_original_owl, encoding="utf-8")
        else:
            _ENRICHED_OWL_PATH.unlink(missing_ok=True)
        subprocess.run(["git", "checkout", "--", "src/ontology/components/copi-enriched.owl"],
                        cwd=str(_copi_repo_root), capture_output=True, text=True)

    if _verify.returncode != 0:
        raise HTTPException(400, {
            "error": "preflight_failed", "check": "verify_owl",
            "message": f"verify_owl.sh failed (exit {_verify.returncode}).",
            "details": (_verify.stdout + _verify.stderr)[-4000:],
        })

    # OOPS Critical pitfalls — remote (BFO/IOF-Core AND copi-core/copi-vocab
    # merged in, so P34/P05/P29-style false positives on those don't fire; see
    # verify_service._parse_oops_xml's external-namespace filter). Not part of
    # verify_owl.sh's own exit code (there it's diagnostic-only) -- kept as an
    # extra layer here since this route pushes to GitHub unattended, unlike a
    # local verify_owl.sh run a human is watching.
    try:
        _preflight_ttl = merge_base_modules(owl_content, fmt="xml")
    except Exception as exc:
        raise HTTPException(400, {
            "error": "preflight_failed", "check": "merge_base_modules",
            "message": f"Could not merge copi-core.ttl/copi-vocab.ttl for the OOPS check: {exc}",
        })

    #    Timeout treated as hard block: a broken ontology must not slip through silently.
    _oops = run_oops_check(_preflight_ttl, timeout=90)
    if not _oops.ok:
        raise HTTPException(400, {
            "error": "preflight_failed", "check": "oops",
            "message": (
                f"OOPS verification unavailable: {_oops.error}. "
                "The service may be temporarily down — try again in a few minutes."
            ),
        })
    _critical = [p for p in _oops.pitfalls if p.importance == "Critical"]
    if _critical:
        raise HTTPException(400, {
            "error": "preflight_failed", "check": "oops_critical",
            "message": f"{len(_critical)} Critical OOPS pitfall(s) must be resolved before pushing.",
            "details": [
                {"code": p.code, "name": p.name, "affected_count": len(p.affected),
                 "affected_sample": p.affected[:3]}
                for p in _critical
            ],
        })

    # Tertiary-source triangulation gate. Mirrors the check enforced at save time
    # in update_enrichment_route() — re-checked here because a row can reach
    # 'validated'/'exported' status without that route ever re-running (e.g. bulk
    # status changes, or source_definitions_used edited through another path).
    _tri_conn = get_enrichment_db()
    _tri_failures = []
    for _v in validated:
        _tri_row = _tri_conn.execute(
            "SELECT source_definitions_used FROM enrichment WHERE id = ?", (_v["id"],)
        ).fetchone()
        _tri_err = validate_tertiary_triangulation(
            _tri_row["source_definitions_used"] if _tri_row else None
        )
        if _tri_err:
            _tri_failures.append({
                "cluster_label": _v["cluster_label"], "id": _v["id"], "error": _tri_err,
            })
    _tri_conn.close()
    if _tri_failures:
        raise HTTPException(400, {
            "error": "preflight_failed", "check": "tertiary_triangulation",
            "message": f"{len(_tri_failures)} entry(ies) have an uncorroborated tertiary source.",
            "details": _tri_failures[:10],
        })

    # Part-universality gate. Same rationale as the triangulation gate above: a
    # row can reach 'validated'/'exported' without update_enrichment_route() ever
    # re-running the hedge check on necessary_parts.
    _univ_conn = get_enrichment_db()
    _univ_failures = []
    for _v in validated:
        _univ_row = _univ_conn.execute(
            "SELECT necessary_parts FROM enrichment WHERE id = ?", (_v["id"],)
        ).fetchone()
        try:
            _parts = json.loads(_univ_row["necessary_parts"]) if _univ_row and _univ_row["necessary_parts"] else []
        except (json.JSONDecodeError, TypeError):
            _parts = []
        _univ_err = validate_part_universality(_parts) if isinstance(_parts, list) else None
        if _univ_err:
            _univ_failures.append({
                "cluster_label": _v["cluster_label"], "id": _v["id"], "error": _univ_err,
            })
    _univ_conn.close()
    if _univ_failures:
        raise HTTPException(400, {
            "error": "preflight_failed", "check": "part_universality",
            "message": f"{len(_univ_failures)} entry(ies) have a hedged necessary_part.",
            "details": _univ_failures[:10],
        })

    # Participant vocabulary gate. Same rationale: a row can reach 'validated'
    # without update_enrichment_route() re-checking its process_signature.
    _pv_conn = get_enrichment_db()
    _pv_failures = []
    for _v in validated:
        _pv_row = _pv_conn.execute(
            "SELECT cluster_label, process_signature FROM enrichment WHERE id = ?", (_v["id"],)
        ).fetchone()
        _pv_err = validate_participant_vocabulary(
            _pv_row["cluster_label"], _pv_row["process_signature"]
        ) if _pv_row else None
        if _pv_err:
            _pv_failures.append({
                "cluster_label": _v["cluster_label"], "id": _v["id"], "error": _pv_err,
            })
    _pv_conn.close()
    if _pv_failures:
        raise HTTPException(400, {
            "error": "preflight_failed", "check": "participant_vocabulary",
            "message": f"{len(_pv_failures)} entry(ies) name a participant type that is not COPI vocabulary.",
            "details": _pv_failures[:10],
        })

    # COPI-Core anchoring gate. Same rationale as the gates above.
    _ca_conn = get_enrichment_db()
    _ca_failures = []
    for _v in validated:
        _ca_row = _ca_conn.execute(
            "SELECT cluster_label, process_name, process_parent, process_signature, core_operation_gap "
            "FROM enrichment WHERE id = ?", (_v["id"],)
        ).fetchone()
        _ca_err = validate_core_anchoring(
            _ca_row["cluster_label"], _ca_row["process_name"], _ca_row["process_parent"],
            _ca_row["process_signature"], _ca_row["core_operation_gap"],
        ) if _ca_row else None
        if _ca_err:
            _ca_failures.append({"cluster_label": _v["cluster_label"], "id": _v["id"], "error": _ca_err})
    _ca_conn.close()
    if _ca_failures:
        raise HTTPException(400, {
            "error": "preflight_failed", "check": "core_anchoring",
            "message": f"{len(_ca_failures)} entry(ies) are not anchored in COPI-Core consistently.",
            "details": _ca_failures[:10],
        })

    # Collect informative results (Important/Minor) to include in the PR response
    _oops_informative = [
        {"code": p.code, "name": p.name, "importance": p.importance,
         "affected_count": len(p.affected)}
        for p in _oops.pitfalls if p.importance != "Critical"
    ]
    # ── End pre-flight ──────────────────────────────────────────────────────

    # Generate static docs (assigns COPI IDs as a side-effect)
    try:
        static_docs = generate_static_docs(version_date=vdate, public_export=True)
    except Exception as exc:
        logger.warning("generate_static_docs() failed: %s", exc)
        static_docs = {}

    encoded = base64.b64encode(owl_content.encode("utf-8")).decode("ascii")

    repo      = "INF-UFRGS-Ontologies/copi"
    file_path = "src/ontology/components/copi-enriched.owl"
    base_branch = "main"
    gh_headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=60) as client:

        # 1. Get SHA of main HEAD (needed to create the new branch)
        ref_resp = await client.get(
            f"https://api.github.com/repos/{repo}/git/ref/heads/{base_branch}",
            headers=gh_headers,
        )
        if ref_resp.status_code != 200:
            raise HTTPException(502, f"Cannot read {base_branch} ref: {ref_resp.status_code} {ref_resp.text[:200]}")
        master_sha = ref_resp.json()["object"]["sha"]

        # 2. Create the new branch
        create_ref_resp = await client.post(
            f"https://api.github.com/repos/{repo}/git/refs",
            headers=gh_headers,
            json={"ref": f"refs/heads/{branch}", "sha": master_sha},
        )
        if create_ref_resp.status_code not in (200, 201):
            raise HTTPException(502, f"Cannot create branch: {create_ref_resp.status_code} {create_ref_resp.text[:200]}")

        # 3. Get current file SHA on the new branch (so we can overwrite it)
        file_resp = await client.get(
            f"https://api.github.com/repos/{repo}/contents/{file_path}",
            headers=gh_headers,
            params={"ref": branch},
        )
        file_sha = file_resp.json().get("sha") if file_resp.status_code == 200 else None

        # 4. Push copi-edit.owl
        put_payload: dict = {
            "message": commit_msg,
            "content": encoded,
            "branch":  branch,
        }
        if file_sha:
            put_payload["sha"] = file_sha

        put_resp = await client.put(
            f"https://api.github.com/repos/{repo}/contents/{file_path}",
            headers=gh_headers,
            json=put_payload,
        )
        if put_resp.status_code not in (200, 201):
            raise HTTPException(502, f"GitHub push failed: {put_resp.status_code} {put_resp.text[:300]}")

        # 5. Push static docs/ files (docs/docs.html, docs/classes/*.html)
        docs_pushed = 0
        for rel_path, html_content in static_docs.items():
            gh_path = f"docs/{rel_path}"
            doc_enc = base64.b64encode(html_content.encode("utf-8")).decode("ascii")

            # Check if file already exists on branch (to get SHA for overwrite)
            existing = await client.get(
                f"https://api.github.com/repos/{repo}/contents/{gh_path}",
                headers=gh_headers,
                params={"ref": branch},
            )
            existing_sha = existing.json().get("sha") if existing.status_code == 200 else None

            doc_payload: dict = {
                "message": f"docs: update {rel_path} [{vdate}]",
                "content": doc_enc,
                "branch":  branch,
            }
            if existing_sha:
                doc_payload["sha"] = existing_sha

            doc_resp = await client.put(
                f"https://api.github.com/repos/{repo}/contents/{gh_path}",
                headers=gh_headers,
                json=doc_payload,
            )
            if doc_resp.status_code in (200, 201):
                docs_pushed += 1
            else:
                logger.warning(
                    "docs push failed for %s: %s %s",
                    gh_path, doc_resp.status_code, doc_resp.text[:200],
                )

        # 5b. Prune orphaned per-class doc pages: a class that leaves the
        # validated/exported set (e.g. retired as redundant, like
        # ElectricalConnection on 2026-09-04) otherwise leaves its
        # docs/classes/COPI_*.html behind forever, since step 5 above only
        # ever PUTs files and never diffs against what already exists.
        docs_pruned = 0
        try:
            live_class_files = {
                rel_path.split("/", 1)[1]
                for rel_path in static_docs
                if rel_path.startswith("classes/")
            }
            listing = await client.get(
                f"https://api.github.com/repos/{repo}/contents/docs/classes",
                headers=gh_headers,
                params={"ref": branch},
            )
            if listing.status_code == 200:
                for entry in listing.json():
                    if entry.get("type") != "file" or entry["name"] in live_class_files:
                        continue
                    del_resp = await client.request(
                        "DELETE",
                        f"https://api.github.com/repos/{repo}/contents/docs/classes/{entry['name']}",
                        headers=gh_headers,
                        json={
                            "message": f"docs: prune orphaned classes/{entry['name']} [{vdate}]",
                            "sha": entry["sha"],
                            "branch": branch,
                        },
                    )
                    if del_resp.status_code in (200, 204):
                        docs_pruned += 1
                    else:
                        logger.warning(
                            "docs prune failed for %s: %s %s",
                            entry["name"], del_resp.status_code, del_resp.text[:200],
                        )
        except Exception as exc:
            logger.warning("orphaned docs prune step failed: %s", exc)

        # 6. Push requirements/cqs.csv
        cqs_csv = generate_cqs_csv()
        cqs_enc = base64.b64encode(cqs_csv.encode("utf-8")).decode("ascii")
        cqs_path = "requirements/cqs.csv"
        existing_cqs = await client.get(
            f"https://api.github.com/repos/{repo}/contents/{cqs_path}",
            headers=gh_headers,
            params={"ref": branch},
        )
        cqs_payload: dict = {
            "message": f"requirements: update cqs.csv [{vdate}]",
            "content": cqs_enc,
            "branch":  branch,
        }
        if existing_cqs.status_code == 200:
            cqs_payload["sha"] = existing_cqs.json().get("sha")
        await client.put(
            f"https://api.github.com/repos/{repo}/contents/{cqs_path}",
            headers=gh_headers,
            json=cqs_payload,
        )

        # 7. Open the pull request
        class_list = ", ".join(e["cluster_label"] for e in validated[:10])
        if len(validated) > 10:
            class_list += f" … (+{len(validated)-10} more)"
        pr_body = (
            f"## COPI ontology update\n\n"
            f"Generated by COPI Editor on {vdate}.\n\n"
            f"**Classes included ({n}):** {class_list}\n\n"
            f"**Static docs:** {docs_pushed} file(s) committed to `docs/`"
            + (f", {docs_pruned} orphaned page(s) pruned" if docs_pruned else "")
            + f" (hosted at https://www.inf.ufrgs.br/ontologies/copi/docs after merge).\n\n"
            f"ODK QC will run automatically on this PR. "
            f"Review the diff and merge when QC passes.\n"
        )
        pr_resp = await client.post(
            f"https://api.github.com/repos/{repo}/pulls",
            headers=gh_headers,
            json={
                "title": pr_title,
                "body":  pr_body,
                "head":  branch,
                "base":  base_branch,
            },
        )
        if pr_resp.status_code not in (200, 201):
            raise HTTPException(502, f"PR creation failed: {pr_resp.status_code} {pr_resp.text[:300]}")

        pr_url = pr_resp.json().get("html_url", "")

    # 7. Mark all included enrichments as exported
    from enrichment_service import update_enrichment as _upd
    for e in validated:
        if e.get("status") == "validated":
            _upd(e["id"], {"status": "exported"})

    return JSONResponse({
        "ok":           True,
        "pr_url":       pr_url,
        "branch":       branch,
        "file":         file_path,
        "classes":      n,
        "docs_files":   docs_pushed,
        "docs_pruned":  docs_pruned,
        "version_date": vdate,
        "preflight": {
            "undeclared_classes": "ok",
            "consistency":        "ok",
            "oops_critical":      "ok",
            "oops_warnings":      _oops_informative,
        },
    })


# ---------------------------------------------------------------------------
# Divergence detection and matrix
# ---------------------------------------------------------------------------

@router.get("/divergences", response_class=HTMLResponse)
async def divergence_matrix_page(request: Request):
    """Cross-standard divergence matrix dashboard."""
    data = get_divergence_matrix()
    return templates.TemplateResponse(request, "divergence_matrix.html", {
        "matrix": data["matrix"],
        "enr_map": data["enr_map"],
        "clusters": data["clusters"],
        "stats": data["stats"],
        "labels": data["labels"],
        "types": ["T1", "T2", "T3", "T4", "T5"],
    })


@router.get("/divergences/export-latex", response_class=PlainTextResponse)
async def export_latex():
    """Download LaTeX table code for the divergence matrix."""
    data = get_divergence_matrix()
    latex = export_divergence_latex(data)
    return PlainTextResponse(
        latex,
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=divergence_table.tex"},
    )


@router.get("/queue", response_class=HTMLResponse)
async def queue_dashboard(request: Request):
    """Batch enrichment queue dashboard."""
    jobs = queue_list()
    clusters = _get_available_clusters()
    enriched_labels = {e["cluster_label"] for e in list_enrichments()}
    batch_submissions = list_batch_submissions()
    manual_oos = get_out_of_scope_clusters()
    running_labels = {j["cluster_label"] for j in jobs if j["status"] == "running"}
    pending_labels = {j["cluster_label"] for j in jobs if j["status"] == "pending"}
    for c in clusters:
        c["has_enrichment"] = c["label"] in enriched_labels
        c["is_running"] = c["label"] in running_labels
        c["is_pending"] = c["label"] in pending_labels
        src_set = set((c.get("sources") or "").split(","))
        c["is_oos"] = (c["label"] in manual_oos) or not bool(src_set & _EQUIPMENT_SOURCES)
    return templates.TemplateResponse(request, "enrichment_queue.html", {
        "jobs": jobs,
        "clusters": clusters,
        "batch_submissions": batch_submissions,
    })


@router.post("/queue/add")
async def queue_add_route(request: Request):
    """Add one or more clusters to the batch queue."""
    form = await request.form()
    raw = form.get("cluster_labels", "")
    labels = [l.strip() for l in raw.split("\n") if l.strip()]
    if not labels:
        raise HTTPException(400, "No cluster labels provided")
    added = queue_add(labels)
    return JSONResponse({"added": len(added), "redirect": "/enrich/queue"})


@router.post("/queue/{job_id}/run")
async def queue_run_job(job_id: int):
    """Run a single pending job from the queue."""
    jobs = queue_list()
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] != "pending":
        raise HTTPException(409, f"Job is already in status '{job['status']}'")

    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        raise HTTPException(400, "ANTHROPIC_API_KEY is not set in the server environment.")

    queue_set_running(job_id)
    try:
        proposal = await enrich_cluster(job["cluster_label"], api_key=key)
        new_id = proposal["id"]
        queue_set_done(job_id, new_id)
        _invalidate_cluster_cache()

        # Metrics: snapshot LLM initial output
        try:
            _ttl = generate_turtle(new_id)
            _conn = get_enrichment_db()
            _em.take_axiom_snapshot(
                _conn, new_id, "llm_initial", _ttl,
                _extract_step_data(proposal), proposal.get("axiom_mode", ""),
            )
            _conn.close()
        except Exception as _exc:
            logger.warning("queue llm_initial snapshot(%s) failed: %s", new_id, _exc)

        # Divergence detection (heuristic)
        try:
            detect_divergences(new_id)
        except Exception as _exc:
            logger.warning("queue detect_divergences(%s) failed: %s", new_id, _exc)

        return JSONResponse({"status": "done", "enrichment_id": new_id})
    except Exception as e:
        queue_set_failed(job_id, str(e))
        return JSONResponse({"status": "failed", "error": str(e)}, status_code=500)


@router.post("/queue/clear")
async def queue_clear_route():
    """Delete all completed/failed jobs from the queue."""
    count = queue_clear_done()
    return JSONResponse({"deleted": count, "redirect": "/enrich/queue"})


@router.post("/queue/batch-submit")
async def queue_batch_submit_route(request: Request):
    """Submit all pending queue jobs as one Anthropic Message Batch (50% cost savings)."""
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise HTTPException(400, "ANTHROPIC_API_KEY is not set in the server environment.")
    try:
        result = await batch_submit_pending(api_key=key)
    except Exception as exc:
        raise HTTPException(500, str(exc))
    if "error" in result:
        raise HTTPException(400, result["error"])
    return JSONResponse(result)


@router.get("/queue/batch/{anthropic_batch_id}/status")
async def queue_batch_status_route(anthropic_batch_id: str):
    """Poll the processing status of a submitted Anthropic batch."""
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise HTTPException(400, "ANTHROPIC_API_KEY is not set in the server environment.")
    try:
        data = await batch_poll_status(anthropic_batch_id, api_key=key)
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return JSONResponse(data)


@router.post("/queue/batch/{anthropic_batch_id}/import")
async def queue_batch_import_route(anthropic_batch_id: str):
    """Download and import results from a completed Anthropic batch."""
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise HTTPException(400, "ANTHROPIC_API_KEY is not set in the server environment.")
    try:
        result = await batch_import_results(anthropic_batch_id, api_key=key)
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return JSONResponse(result)


@router.post("/{enrichment_id}/detect-divergences", response_class=JSONResponse)
async def run_detect_divergences(enrichment_id: int):
    """Auto-detect cross-standard divergences for an enrichment."""
    try:
        found = detect_divergences(enrichment_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return JSONResponse({"ok": True, "count": len(found), "divergences": found})


@router.post("/{enrichment_id}/llm-detect-divergences", response_class=JSONResponse)
async def run_llm_detect_divergences(enrichment_id: int, request: Request):
    """LLM-assisted divergence detection."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(503, "ANTHROPIC_API_KEY not configured")
    try:
        found = await llm_detect_divergences(enrichment_id, api_key)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"ok": True, "count": len(found), "divergences": found})


# ---------------------------------------------------------------------------
# Auxiliary classes — must be registered before /{enrichment_id} wildcard routes
# ---------------------------------------------------------------------------

@router.get("/auxiliary", response_class=HTMLResponse)
async def auxiliary_classes_page(
    request: Request,
    status_filter: str = Query("all"),
    category_filter: str = Query("all"),
):
    conn = get_enrichment_db()
    query = "SELECT * FROM auxiliary_class"
    params: list = []
    conditions = []
    if status_filter != "all":
        conditions.append("status = ?"); params.append(status_filter)
    if category_filter != "all":
        conditions.append("bfo_category = ?"); params.append(category_filter)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY status, name"
    rows = [dict(r) for r in conn.execute(query, params).fetchall()]
    pending_count = conn.execute(
        "SELECT COUNT(*) FROM auxiliary_class WHERE status='pending'"
    ).fetchone()[0]

    # Build "used_in" map: name → list of cluster_labels referencing it
    all_sigs = conn.execute(
        "SELECT cluster_label, process_signature FROM enrichment "
        "WHERE process_signature IS NOT NULL AND process_signature != '{}'"
    ).fetchall()
    conn.close()
    used_in: dict[str, list[str]] = {}
    for sig_row in all_sigs:
        try:
            sig = json.loads(sig_row["process_signature"])
        except Exception:
            continue
        for item in sig.get("inputs", []) + sig.get("outputs", []):
            pname = _to_pascal_case((item.get("type") or "").strip())
            if pname:
                used_in.setdefault(pname, [])
                if sig_row["cluster_label"] not in used_in[pname]:
                    used_in[pname].append(sig_row["cluster_label"])

    return templates.TemplateResponse(request, "auxiliary_classes.html", {
        "rows": rows,
        "pending_count": pending_count,
        "status_filter": status_filter,
        "category_filter": category_filter,
        "valid_categories": sorted(_AUX_VALID_CATEGORIES),
        "used_in": used_in,
    })


@router.post("/auxiliary/{name}", response_class=JSONResponse)
async def validate_auxiliary_class(
    request: Request,
    name: str,
    current_user: str = Depends(get_current_user),
):
    if not current_user:
        raise HTTPException(status_code=401)
    form = await request.form()
    bfo_category = form.get("bfo_category", "").strip()
    if bfo_category and bfo_category not in _AUX_VALID_CATEGORIES:
        raise HTTPException(status_code=422, detail=f"Invalid bfo_category: {bfo_category!r}")
    updates = {
        "bfo_category":  bfo_category or None,
        "label_en":      form.get("label_en", "").strip() or None,
        "label_pt":      form.get("label_pt", "").strip() or None,
        "definition_en": form.get("definition_en", "").strip() or None,
        "status":        "validated",
        "updated_at":    datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
    }
    conn = get_enrichment_db()
    existing = conn.execute("SELECT id FROM auxiliary_class WHERE name=?", (name,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail=f"auxiliary_class '{name}' not found")
    set_clause = ", ".join(f"{k}=?" for k in updates)
    conn.execute(
        f"UPDATE auxiliary_class SET {set_clause} WHERE name=?",
        list(updates.values()) + [name]
    )
    conn.commit()
    conn.close()
    return {"ok": True, "name": name}


@router.get("/{enrichment_id}/fol")
async def get_fol_theory(enrichment_id: int):
    """Return the mechanically generated FOL theory for an enrichment."""
    enrichment = get_enrichment(enrichment_id)
    if not enrichment:
        raise HTTPException(404, "Enrichment not found")
    return JSONResponse(generate_fol_theory(enrichment))


@router.get("/{enrichment_id}", response_class=HTMLResponse)
async def enrichment_detail(request: Request, enrichment_id: int):
    """View a single enrichment proposal with editing controls."""
    enrichment = get_enrichment(enrichment_id)
    if not enrichment:
        raise HTTPException(404, "Enrichment not found")

    _log_event_safe(enrichment_id, "open")

    # Get the original definitions and CFIHOS/DEXPI properties for context
    all_definitions = get_cluster_definitions(enrichment["cluster_label"])
    excluded_ids: list = enrichment.get("excluded_definition_ids") or []
    if not isinstance(excluded_ids, list):
        excluded_ids = []
    definitions = [d for d in all_definitions if d.get("id") not in excluded_ids]
    excluded_definitions = [d for d in all_definitions if d.get("id") in excluded_ids]

    if not request.state.user:
        definitions = _redact_copyrighted_definitions(definitions)
        excluded_definitions = _redact_copyrighted_definitions(excluded_definitions)

    cfihos_properties = get_cluster_properties(enrichment["cluster_label"])
    linked_cqs = get_linked_cqs(enrichment["cluster_label"])
    aggregation_info = get_label_aggregation_info(enrichment["cluster_label"])
    out_of_scope = enrichment["cluster_label"] in get_out_of_scope_clusters()
    try:
        _pv_baseline = load_participant_vocabulary_baseline()
        unvetted_participants = [
            {"name": t, "grandfathered": f"{enrichment['cluster_label']}|{t}" in _pv_baseline}
            for t in find_unvetted_participants(enrichment.get("process_signature"))
        ]
    except Exception as exc:  # advisory display only — never block the page
        logger.warning("participant vocabulary check failed for %s: %s", enrichment_id, exc)
        unvetted_participants = []
    try:
        from core_operations import anchor_for_entry
        _pp_conn = get_enrichment_db()
        _process_parents = {
            r["process_name"]: r["process_parent"]
            for r in _pp_conn.execute(
                "SELECT process_name, process_parent FROM enrichment WHERE process_name IS NOT NULL"
            ).fetchall()
        }
        _pp_conn.close()
        core_anchor = anchor_for_entry(enrichment.get("process_name"), enrichment.get("process_parent"), _process_parents)
    except Exception as exc:  # advisory display only
        logger.warning("core anchoring check failed for %s: %s", enrichment_id, exc)
        core_anchor = None
    try:
        from core_operations import operations as _core_operations
        core_operation_options = [(op.name, op.depth) for op in _core_operations()]
    except Exception:
        core_operation_options = []

    # Compute prev/next for navigation (deduplicated list, most recent per label)
    all_enr = list_enrichments(deduplicate=True)
    all_ids = [e["id"] for e in all_enr]
    pos = 0
    prev_id = next_id = None
    try:
        pos = all_ids.index(enrichment_id)
        prev_id = all_ids[pos - 1] if pos > 0 else None
        next_id = all_ids[pos + 1] if pos < len(all_ids) - 1 else None
    except ValueError:
        pass

    return templates.TemplateResponse(request, "enrichment_detail.html", {
        "e": enrichment,
        "definitions": definitions,
        "excluded_definitions": excluded_definitions,
        "cfihos_properties": cfihos_properties,
        "linked_cqs": linked_cqs,
        "included_variants": aggregation_info["included_variants"],
        "near_match_labels": aggregation_info["near_matches"],
        "out_of_scope": out_of_scope,
        "unvetted_participants": unvetted_participants,
        "core_anchor": core_anchor,
        "core_operation_options": core_operation_options,
        "loaded_at": enrichment.get("updated_at", ""),
        "prev_id": prev_id,
        "next_id": next_id,
        "nav_pos": pos + 1 if all_ids else 1,
        "nav_total": len(all_ids),
    })


@router.post("/{enrichment_id}/update")
async def update_enrichment_route(
    enrichment_id: int,
    request: Request,
    current_user: str = Depends(get_current_user),
):
    """Update an enrichment proposal from the validation form."""
    form = await request.form()
    updates = {}

    # Map form fields to DB columns
    field_map = {
        "function_name": "function_name",
        "process_name": "process_name",
        "process_parent": "process_parent",
        "genus": "genus",
        "genus_bfo_root": "genus_bfo_root",
        "axiom_mode": "axiom_mode",
        "primitive_rationale": "primitive_rationale",
        "label_pt":         "label_pt",
        "nl_definition_en": "nl_definition_en",
        "nl_definition_pt": "nl_definition_pt",
        "semiformal_axiom": "semiformal_axiom",
        "fol_axiom": "fol_axiom",
        "differentia_expression": "differentia_expression",
        "differentia_nl": "differentia_nl",
        "differentia_rationale": "differentia_rationale",
        "reviewer_notes": "reviewer_notes",
        "second_reviewer_notes": "second_reviewer_notes",
        "status": "status",
        # "expert_reviewer" is now auto-set from Keycloak — removed from field_map
        "symbol_path": "symbol_path",
        "alt_labels": "alt_labels",
        "secondary_coverage": "secondary_coverage",
        "primary_definition_conflict": "primary_definition_conflict",
    }

    # Validate enum fields before applying updates
    _check_enum(form.get("status", ""), _VALID_ENRICHMENT_STATUSES, "status")
    _check_enum(form.get("axiom_mode", ""), _VALID_AXIOM_MODES, "axiom_mode")
    if form.get("secondary_coverage"):
        _check_enum(form["secondary_coverage"], _VALID_SECONDARY_COVERAGE, "secondary_coverage")
    _check_enum(form.get("genus_bfo_root", ""), _VALID_BFO_ROOTS | {""}, "genus_bfo_root")

    for form_field, db_field in field_map.items():
        if form_field in form:
            updates[db_field] = form[form_field]

    # Handle JSON fields
    if "necessary_parts" in form:
        try:
            updates["necessary_parts"] = json.loads(form["necessary_parts"])
        except json.JSONDecodeError:
            pass

    # Validate source_quote grounding for every named part, and that any
    # tertiary-tier source_definitions_used entry is triangulated.
    if "necessary_parts" in updates:
        _parts_to_validate = updates["necessary_parts"]
        _src_conn = get_enrichment_db()
        _src_row = _src_conn.execute(
            "SELECT source_definitions_used FROM enrichment WHERE id = ?",
            (enrichment_id,)
        ).fetchone()
        _src_conn.close()
        _src_defs_json = _src_row["source_definitions_used"] if _src_row else None

        _tri_err = validate_tertiary_triangulation(_src_defs_json)
        if _tri_err:
            return JSONResponse(status_code=422, content={"detail": _tri_err})

        if isinstance(_parts_to_validate, list) and _parts_to_validate:
            _part_err = validate_necessary_parts_quotes(_parts_to_validate, _src_defs_json)
            if _part_err:
                return JSONResponse(
                    status_code=422,
                    content={"detail": _part_err},
                )
            _univ_err = validate_part_universality(_parts_to_validate)
            if _univ_err:
                return JSONResponse(
                    status_code=422,
                    content={"detail": _univ_err},
                )

    if "disjoint_with" in form:
        try:
            updates["disjoint_with"] = json.loads(form["disjoint_with"])
        except json.JSONDecodeError:
            # Handle comma-separated list
            updates["disjoint_with"] = [
                s.strip() for s in form["disjoint_with"].split(",") if s.strip()
            ]

    if "process_signature" in form:
        try:
            updates["process_signature"] = json.loads(form["process_signature"])
        except json.JSONDecodeError:
            pass
        # Auto-register any new participant types as pending auxiliary_class entries
        sig = updates.get("process_signature") or {}
        if isinstance(sig, dict):
            _aux_db = get_enrichment_db()
            for _item in sig.get("inputs", []) + sig.get("outputs", []):
                _pname = _to_pascal_case((_item.get("type") or "").strip())
                if _pname and _pname != "Unknown":
                    _aux_db.execute(
                        "INSERT OR IGNORE INTO auxiliary_class (name, source) VALUES (?, 'auto_signature')",
                        (_pname,)
                    )
            _aux_db.commit()
            _aux_db.close()

    if "core_operation_gap" in form:
        _gap = normalize_core_operation_gap(form["core_operation_gap"])
        updates["core_operation_gap"] = json.dumps(_gap) if _gap else None

    # Save-time gates on validated entries. Errors are collected so the reviewer sees every
    # problem in one 422 instead of fixing them one round-trip at a time.
    _gate_errors: list[str] = []

    # COPI-Core anchoring gate: checked against the effective values, like the participant gate.
    if {"status", "process_parent", "process_signature", "core_operation_gap"} & set(updates):
        _ca_conn = get_enrichment_db()
        _ca_row = _ca_conn.execute(
            "SELECT cluster_label, status, process_name, process_parent, process_signature, core_operation_gap "
            "FROM enrichment WHERE id = ?", (enrichment_id,),
        ).fetchone()
        _ca_conn.close()
        if _ca_row and (updates.get("status") or _ca_row["status"]) in ("validated", "exported"):
            _ca_err = validate_core_anchoring(
                _ca_row["cluster_label"],
                updates.get("process_name", _ca_row["process_name"]),
                updates.get("process_parent", _ca_row["process_parent"]),
                updates.get("process_signature", _ca_row["process_signature"]),
                updates["core_operation_gap"] if "core_operation_gap" in updates else _ca_row["core_operation_gap"],
            )
            if _ca_err:
                _gate_errors.append(_ca_err)

    # Participant vocabulary gate: a validated entry may only name hand-authored
    # participant types. Checked against the effective status/signature, so both
    # "validate this entry" and "edit the signature of a validated entry" are caught.
    if "status" in updates or "process_signature" in updates:
        _pv_conn = get_enrichment_db()
        _pv_row = _pv_conn.execute(
            "SELECT cluster_label, status, process_signature FROM enrichment WHERE id = ?",
            (enrichment_id,),
        ).fetchone()
        _pv_conn.close()
        if _pv_row:
            _pv_status = updates.get("status") or _pv_row["status"]
            _pv_sig = updates.get("process_signature", _pv_row["process_signature"])
            if _pv_status in ("validated", "exported"):
                _pv_err = validate_participant_vocabulary(_pv_row["cluster_label"], _pv_sig)
                if _pv_err:
                    _gate_errors.append(_pv_err)

    if _gate_errors:
        return JSONResponse(status_code=422, content={"detail": "\n\n".join(_gate_errors)})

    if "qualities" in form:
        try:
            updates["qualities"] = json.loads(form["qualities"])
        except json.JSONDecodeError:
            pass

    if "custom_axioms" in form:
        try:
            updates["custom_axioms"] = json.loads(form["custom_axioms"])
        except json.JSONDecodeError:
            pass

    # alt_labels: comma-separated string → JSON array
    if "alt_labels" in form:
        raw = form["alt_labels"]
        try:
            parsed = json.loads(raw)
            updates["alt_labels"] = parsed
        except json.JSONDecodeError:
            updates["alt_labels"] = [s.strip() for s in raw.split(",") if s.strip()]

    # Rebuild expert_review JSON from per-step form fields
    steps = ["step1", "step2", "step3", "step4", "step5", "axiom_mode"]
    expert_review = {}
    for step in steps:
        status_key = f"expert_{step}_status"
        note_key   = f"expert_{step}_note"
        if status_key in form or note_key in form:
            expert_status = form.get(status_key, "pending")
            _check_enum(expert_status, _VALID_EXPERT_STATUSES, f"expert_{step}_status")
            expert_review[step] = {
                "status": expert_status,
                "note":   form.get(note_key, ""),
            }
    if expert_review:
        updates["expert_review"] = expert_review

    # Structural disjointness filter: strip catalogue-absent pairs BEFORE writing.
    # Applied whenever disjoint_with is being updated, regardless of status.
    # Design choice: auto-filter (not reject with 400) — see code-audit.md §6.2.
    # Uses normalised (case-insensitive, CamelCase-aware) lookup so that candidates
    # like "CheckValve" match cluster_label "check valve" correctly.
    if "disjoint_with" in updates and updates.get("disjoint_with"):
        try:
            from enrichment.disjointness_validator import normalise_label
            _filt_db = get_enrichment_db()
            _all_labels = {
                normalise_label(r[0])
                for r in _filt_db.execute(
                    "SELECT DISTINCT cluster_label FROM enrichment"
                ).fetchall()
            }
            _filt_db.close()

            _original = list(updates["disjoint_with"])
            _kept = [c for c in _original if normalise_label(str(c)) in _all_labels]
            _removed = [c for c in _original if normalise_label(str(c)) not in _all_labels]

            if _removed:
                updates["disjoint_with"] = _kept
                _current_rat = (
                    updates.get("disjointness_rationale")
                    or (get_enrichment(enrichment_id) or {}).get("disjointness_rationale", "")
                    or ""
                )
                _note = f"\n[Structural validator removed catalogue-absent pairs: {sorted(set(_removed))}]"
                updates["disjointness_rationale"] = _current_rat + _note
                logger.info(
                    "Disjointness filter(%s): removed %d catalogue-absent pair(s): %s",
                    enrichment_id, len(_removed), _removed,
                )
        except Exception as _df_exc:
            logger.warning("Disjointness filter(%s) failed (non-blocking): %s", enrichment_id, _df_exc)

    # Stale-write detection: reject if the page was loaded before the last save
    loaded_at = form.get("loaded_at", "")
    if loaded_at and loaded_at != "__force__":
        conn = get_enrichment_db()
        current = conn.execute(
            "SELECT updated_at, last_edited_by, last_edited_at FROM enrichment WHERE id = ?",
            (enrichment_id,)
        ).fetchone()
        conn.close()
        if current and current["updated_at"] and current["updated_at"] != loaded_at:
            return JSONResponse(
                status_code=409,
                content={
                    "conflict": True,
                    "last_edited_by": current["last_edited_by"] or "unknown",
                    "last_edited_at": current["last_edited_at"] or current["updated_at"],
                },
            )

    if updates.get("second_reviewer_notes"):
        updates["second_reviewer"] = current_user

    # Snapshot before mutation so history and undo work
    snapshot_enrichment(enrichment_id, trigger="save")
    _before = get_enrichment(enrichment_id)
    saved_at = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    updates["last_edited_by"] = current_user
    updates["last_edited_at"] = saved_at
    updates["expert_reviewer"] = current_user
    updates["updated_at"] = saved_at
    update_enrichment(enrichment_id, updates)

    # --- Evaluation metrics instrumentation (fire-and-forget) ---
    try:
        new_status   = updates.get("status")
        new_axmode   = updates.get("axiom_mode")
        expert_steps = updates.get("expert_review", {})

        if new_status in ("validated", "exported"):
            _log_event_safe(enrichment_id, "export_mark", {"status": new_status})
            # Take final_export snapshot
            try:
                _after = get_enrichment(enrichment_id)
                _ttl   = generate_turtle(enrichment_id)
                _conn  = get_enrichment_db()
                _em.take_axiom_snapshot(
                    _conn, enrichment_id, "final_export", _ttl,
                    _extract_step_data(_after), _after.get("axiom_mode", ""),
                )
                # Annotation-completeness flags for the verification snapshot
                _af = {
                    "has_nl_definition":       bool(_after.get("nl_definition_en")),
                    "has_semiformal_def":       bool(_after.get("semiformal_axiom")),
                    "has_fol_axiom":            bool(_after.get("fol_axiom")),
                    "has_primitive_rationale":  bool(_after.get("primitive_rationale")),
                    "has_label_en":             True,   # cluster_label is always present
                    "has_label_pt":             bool(_after.get("nl_definition_pt")),
                }
                # Run per-class HermiT consistency check (fast: ~1 s per class).
                # OOPS!/FOOPS!/APV are aggregate checks; they run on the combined
                # export via the /enrich/verify route and are not per-class here.
                try:
                    from verify_service import run_consistency_check as _hcheck
                    _hr = _hcheck(_ttl)
                    _hermit = {
                        "consistent": bool(_hr.consistent),
                        "inferred":   [vars(i) for i in _hr.inferences],
                        "error":      _hr.error,
                    }
                except Exception as _he:
                    logger.warning("HermiT check(%s) failed: %s", enrichment_id, _he)
                    _hermit = None
                _em.take_verification_snapshot(_conn, enrichment_id, _hermit, None, _af)
                _conn.close()
            except Exception as _exc:
                logger.warning("final_export snapshot(%s) failed: %s", enrichment_id, _exc)

        elif expert_steps:
            for _step, _sv in expert_steps.items():
                _log_event_safe(enrichment_id, "step_review", {
                    "step": _step, "status": _sv.get("status"),
                })

        elif new_axmode and _before and new_axmode != _before.get("axiom_mode"):
            _log_event_safe(enrichment_id, "axiom_mode_change", {
                "old": _before.get("axiom_mode"), "new": new_axmode,
            })

        else:
            _changed = list(updates.keys())
            if _changed:
                _log_event_safe(enrichment_id, "save", {"changed_fields": _changed})
    except Exception as _exc:
        logger.warning("update metrics instrumentation(%s) failed: %s", enrichment_id, _exc)

    # Return saved_at directly (captured before the update call) so the client can
    # refresh the loaded_at hidden field, preventing a false-positive stale-write 409
    # on the next save in the same session.  Avoids a racy get_enrichment() read.
    return JSONResponse({"success": True, "redirect": f"/enrich/{enrichment_id}", "updated_at": saved_at})


_VALID_CLIENT_EVENTS = frozenset({
    "open", "save", "step_review", "rerun_request", "rerun_complete",
    "axiom_mode_change", "export_mark", "restore_version",
    "cq_link", "turtle_preview", "fol_preview", "step_focus",
})


@router.post("/{enrichment_id}/exclude-definition", response_class=JSONResponse)
async def exclude_definition(enrichment_id: int, request: Request):
    """Toggle exclusion of a source definition for this enrichment.

    Body JSON: {definition_id: int, exclude: bool}
    """
    body = await request.json()
    def_id = body.get("definition_id")
    exclude = bool(body.get("exclude", True))
    if def_id is None:
        raise HTTPException(400, "definition_id required")

    enrichment = get_enrichment(enrichment_id)
    if not enrichment:
        raise HTTPException(404, "Enrichment not found")

    excluded: list = enrichment.get("excluded_definition_ids") or []
    if not isinstance(excluded, list):
        excluded = []

    if exclude and def_id not in excluded:
        excluded.append(def_id)
    elif not exclude and def_id in excluded:
        excluded.remove(def_id)

    update_enrichment(enrichment_id, {"excluded_definition_ids": json.dumps(excluded)})
    return {"ok": True, "excluded_definition_ids": excluded}


@router.post("/{enrichment_id}/event", response_class=JSONResponse)
async def log_client_event(enrichment_id: int, request: Request):
    """
    Log a frontend interaction event for evaluation metrics.

    Body JSON: {event_type: str, event_detail?: object}

    Currently useful for step_focus events emitted when the ontologist expands
    a step accordion card — enables compute_time_per_step() segmentation.
    Example: {event_type: "step_focus", event_detail: {step_number: 3}}
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    event_type = body.get("event_type")
    if event_type not in _VALID_CLIENT_EVENTS:
        raise HTTPException(400, f"Unknown event_type: {event_type!r}")
    _log_event_safe(enrichment_id, event_type, body.get("event_detail"))
    return JSONResponse({"ok": True})


@router.get("/{enrichment_id}/history", response_class=HTMLResponse)
async def enrichment_history_page(request: Request, enrichment_id: int):
    """Version history for an enrichment proposal."""
    enrichment = get_enrichment(enrichment_id)
    if not enrichment:
        raise HTTPException(404, "Enrichment not found")
    history = list_history(enrichment_id)
    return templates.TemplateResponse(request, "enrichment_history.html", {
        "e": enrichment,
        "history": history,
    })


@router.get("/{enrichment_id}/history/{history_id}", response_class=HTMLResponse)
async def enrichment_history_detail(request: Request, enrichment_id: int, history_id: int):
    """View a specific snapshot from the history."""
    enrichment = get_enrichment(enrichment_id)
    if not enrichment:
        raise HTTPException(404, "Enrichment not found")
    snap = get_history_snapshot(history_id)
    if not snap or snap["enrichment_id"] != enrichment_id:
        raise HTTPException(404, "Snapshot not found")
    return templates.TemplateResponse(request, "enrichment_history.html", {
        "e": enrichment,
        "history": list_history(enrichment_id),
        "selected": snap,
    })


@router.post("/{enrichment_id}/undo")
async def undo_enrichment(enrichment_id: int):
    """Restore the most recent history snapshot for an enrichment row."""
    enrichment = get_enrichment(enrichment_id)
    if not enrichment:
        raise HTTPException(404, "Enrichment not found")
    restored = restore_enrichment_snapshot(enrichment_id)
    if not restored:
        raise HTTPException(404, "No history to undo")
    return RedirectResponse(f"/enrich/{enrichment_id}", status_code=303)


# ── Alias / Deduplication endpoints ────────────────────────────────────────

@router.get("/api/aliases", response_class=JSONResponse)
async def api_list_aliases():
    """Return all proposed cluster alias rows with target enrichment snippet."""
    from enrichment_service import get_enrichment_db
    conn = get_enrichment_db()
    rows = conn.execute("""
        SELECT a.*, e.nl_definition_en AS target_definition
        FROM cluster_alias a
        LEFT JOIN enrichment e ON e.cluster_label = a.target_label
            AND e.id = (SELECT MIN(id) FROM enrichment WHERE cluster_label = a.target_label)
        WHERE a.status = 'proposed'
        ORDER BY a.confidence DESC
    """).fetchall()
    conn.close()
    return JSONResponse([dict(r) for r in rows])


@router.post("/api/aliases/detect", response_class=JSONResponse)
async def api_detect_aliases():
    """Run label-similarity alias detection and return new proposals count."""
    new_aliases = detect_aliases()
    return JSONResponse({"detected": len(new_aliases)})


@router.post("/api/aliases/{alias_id}/accept", response_class=JSONResponse)
async def api_accept_alias(alias_id: int, request: Request):
    from enrichment_service import get_enrichment_db
    form = await request.form()
    notes = form.get("notes")
    rel = (form.get("relation_type") or "").strip()
    ok = update_alias(alias_id, "accepted", notes)
    if rel and ok:
        conn = get_enrichment_db()
        conn.execute("UPDATE cluster_alias SET relation_type=? WHERE id=?", (rel, alias_id))
        conn.commit()
        conn.close()
    return JSONResponse({"ok": ok})


@router.post("/api/aliases/{alias_id}/reject", response_class=JSONResponse)
async def api_reject_alias(alias_id: int, request: Request):
    form = await request.form()
    notes = form.get("notes")
    ok = update_alias(alias_id, "rejected", notes)
    return JSONResponse({"ok": ok})


@router.post("/api/aliases", response_class=JSONResponse)
async def api_create_alias(request: Request):
    form = await request.form()
    source = (form.get("source_label") or "").strip()
    target = (form.get("target_label") or "").strip()
    if not source or not target:
        raise HTTPException(400, "source_label and target_label are required")
    rel = form.get("relation_type", "exactMatch")
    notes = form.get("notes")
    alias_id = create_alias(source, target, rel, notes)
    return JSONResponse({"id": alias_id})


@router.get("/{enrichment_id}/doc", response_class=HTMLResponse)
async def enrichment_doc(request: Request, enrichment_id: int):
    """Human-readable documentation page for a validated enrichment."""
    enrichment = get_enrichment(enrichment_id)
    if not enrichment:
        raise HTTPException(404, "Enrichment not found")

    definitions = get_cluster_definitions(enrichment["cluster_label"])
    if not request.state.user:
        definitions = _redact_copyrighted_definitions(definitions)

    try:
        turtle_src = remap_turtle_to_numeric_iris(generate_turtle(enrichment_id))
    except Exception as exc:
        logger.warning("generate_turtle(%s) failed: %s", enrichment_id, exc)
        turtle_src = f"# Error generating Turtle: {exc}"

    return templates.TemplateResponse(request, "enrichment_doc.html", {
        "e": enrichment,
        "definitions": definitions,
        "turtle_src": turtle_src,
    })


@router.get("/{enrichment_id}/turtle", response_class=PlainTextResponse)
async def download_turtle(request: Request, enrichment_id: int):
    """Export enrichment as OWL/Turtle."""
    _log_event_safe(enrichment_id, "turtle_preview")
    try:
        # Display/download copy only — numeric COPI_* IRIs as published, comments kept.
        ttl = remap_turtle_to_numeric_iris(generate_turtle(enrichment_id))
    except ValueError as e:
        raise HTTPException(404, str(e))

    if not request.state.user:
        lines = [ln for ln in ttl.splitlines() if not any(pfx in ln for pfx in PUBLIC_STRIP_PREFIXES)]
        ttl = "\n".join(lines)

    return PlainTextResponse(
        ttl,
        media_type="text/turtle",
        headers={"Content-Disposition": f"attachment; filename=enrichment_{enrichment_id}.ttl"},
    )


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# JSON API endpoints
# ---------------------------------------------------------------------------

@router.get("/api/clusters", response_class=JSONResponse)
async def api_clusters():
    """List available clusters."""
    return _get_available_clusters()


@router.get("/api/enrichments", response_class=JSONResponse)
async def api_enrichments(status: str = Query(default=None)):
    """List enrichment proposals."""
    return list_enrichments(status)


# ---------------------------------------------------------------------------
# Imported Ontology Browser — JSON API (must come BEFORE /api/{enrichment_id})
# ---------------------------------------------------------------------------

@router.get("/api/ontology-class", response_class=JSONResponse)
async def api_ontology_class(uri: str = Query(...)):
    """Return full annotations for one class by URI."""
    from ontology_service import get_class
    rec = get_class(uri)
    if rec is None:
        raise HTTPException(404, f"Class not found: {uri}")
    return JSONResponse(rec)


@router.get("/api/ontology-search", response_class=JSONResponse)
async def api_ontology_search(q: str = Query(default="")):
    """Substring search on class labels and definitions."""
    from ontology_service import search_classes, get_class_list
    if not q.strip():
        return JSONResponse(get_class_list())
    return JSONResponse(search_classes(q.strip()))


@router.get("/api/ontology-properties", response_class=JSONResponse)
async def api_ontology_properties():
    """Return all OWL properties from imported ontologies (BFO + IOF-Core)."""
    from ontology_service import get_property_list
    return JSONResponse(get_property_list())


@router.get("/api/{enrichment_id}/divergences", response_class=JSONResponse)
async def api_get_divergences(enrichment_id: int):
    """Return all divergences for an enrichment as JSON."""
    return JSONResponse(get_divergences(enrichment_id))


@router.patch("/api/divergences/{div_id}/resolution", response_class=JSONResponse)
async def patch_divergence_resolution(div_id: int, request: Request):
    body = await request.json()
    resolution = (body.get("resolution") or "").strip()
    update_divergence_resolution(div_id, resolution)
    return JSONResponse({"ok": True})


@router.get("/api/{enrichment_id}", response_class=JSONResponse)
async def api_enrichment_detail(enrichment_id: int):
    """Get enrichment detail as JSON."""
    enrichment = get_enrichment(enrichment_id)
    if not enrichment:
        raise HTTPException(404, "Enrichment not found")
    return enrichment
