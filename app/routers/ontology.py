"""
Routes for the COPI Editor home page, Requirements, and Literature.

  GET  /              — Ontology metadata home
  POST /ontology/update — Save editable metadata fields
  GET  /requirements  — Competency questions + scenarios list
  POST /requirements  — Add a new competency question
  POST /requirements/{id}/update — Update status / notes on a CQ
  POST /requirements/{id}/delete — Delete a CQ
  POST /requirements/scenarios — Add a scenario
  POST /requirements/scenarios/{id}/update — Update a scenario
  POST /requirements/scenarios/{id}/delete — Delete a scenario
  GET  /references    — Literature bibliography
  POST /references    — Add a paper
  POST /references/{id}/update — Update a paper
  POST /references/{id}/delete — Delete a paper
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jinja2 import FileSystemLoader
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.jinja_setup import make_templates
from app.models import Term

router = APIRouter()

_ROOT = Path(__file__).parent.parent.parent
_META_FILE = _ROOT / "data" / "copi_metadata.json"
_ENRICH_DB = _ROOT / "data" / "enrichment.db"
_ORSD_META_FILE = _ROOT / "data" / "orsd_metadata.json"

templates = make_templates(FileSystemLoader(str(_ROOT / "app" / "templates")))


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------

def _load_meta() -> dict:
    import sys
    sys.path.insert(0, str(_ROOT))
    from config import (
        COPI_IRI, COPI_NS, COPI_VERSION, COPI_GITHUB,
        COPI_AUTHOR, COPI_CREATED, COPI_IMPORTS,
        COPI_SCOPE_DEFAULT, COPI_PUBLISHER,
        COPI_CONTRIBUTORS, COPI_PROJECT_FULL, COPI_RESEARCH_GROUP,
    )
    defaults = {
        "iri":            COPI_IRI,
        "version":        COPI_VERSION,
        "github":         COPI_GITHUB,
        "author":         COPI_AUTHOR,
        "created":        COPI_CREATED,
        "publisher":      COPI_PUBLISHER,
        "scope":          COPI_SCOPE_DEFAULT,
        "imports":        COPI_IMPORTS,
        "status":         "draft",
        "contributors":   COPI_CONTRIBUTORS,
        "research_group": COPI_RESEARCH_GROUP,
        "research_project": COPI_PROJECT_FULL,
    }
    if _META_FILE.exists():
        saved = json.loads(_META_FILE.read_text())
        saved.pop("version", None)  # version is git-derived; never override from JSON
        defaults.update(saved)
    return defaults


def _save_meta(updates: dict):
    _META_FILE.parent.mkdir(parents=True, exist_ok=True)
    current = _load_meta()
    # Only persist the user-editable fields (not the config-derived ones)
    editable = ("iri", "github", "scope", "status")
    for k in editable:
        if k in updates:
            current[k] = updates[k]
    _META_FILE.write_text(json.dumps(current, indent=2, ensure_ascii=False))


def _load_orsd_meta() -> dict:
    import sys
    sys.path.insert(0, str(_ROOT))
    from config import COPI_FULL_NAME, COPI_DESCRIPTION, COPI_SCOPE_DEFAULT
    defaults: dict = {
        "ontology_name":         COPI_FULL_NAME,
        "purpose":               COPI_DESCRIPTION[0],
        "scope":                 COPI_SCOPE_DEFAULT,
        "implementation_language": "OWL 2 DL",
        "intended_users":        [],
        "intended_uses":         [],
    }
    if _ORSD_META_FILE.exists():
        saved = json.loads(_ORSD_META_FILE.read_text())
        defaults.update(saved)
    return defaults


def _save_orsd_meta(updates: dict):
    _ORSD_META_FILE.parent.mkdir(parents=True, exist_ok=True)
    current = _load_orsd_meta()
    for k in ("ontology_name", "purpose", "scope", "implementation_language"):
        if k in updates:
            current[k] = updates[k] or ""
    for k in ("intended_users", "intended_uses"):
        if k in updates:
            raw = updates[k] or ""
            current[k] = [v.strip() for v in raw.split(",") if v.strip()]
    _ORSD_META_FILE.write_text(json.dumps(current, indent=2, ensure_ascii=False))


def _enrich_stats() -> dict:
    if not _ENRICH_DB.exists():
        return {"total": 0, "validated": 0, "last_modified": None}
    conn = sqlite3.connect(str(_ENRICH_DB))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT COUNT(*) as total, "
        "SUM(CASE WHEN status IN ('validated','exported') THEN 1 ELSE 0 END) as validated, "
        "MAX(updated_at) as last_modified "
        "FROM enrichment"
    ).fetchone()
    conn.close()
    return dict(row) if row else {"total": 0, "validated": 0, "last_modified": None}


def _get_enrichment_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_ENRICH_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_cq_schema():
    if not _ENRICH_DB.exists():
        return
    conn = _get_enrichment_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS competency_questions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            text            TEXT NOT NULL,
            formal_expr     TEXT,
            status          TEXT DEFAULT 'open'
                            CHECK(status IN ('open', 'partial', 'answered')),
            linked_classes  TEXT DEFAULT '[]',
            notes           TEXT,
            scenario_id     INTEGER,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cq_status ON competency_questions(status)"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scenarios (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL,
            narrative   TEXT NOT NULL,
            actors      TEXT DEFAULT '[]',
            status      TEXT NOT NULL DEFAULT 'draft'
                        CHECK(status IN ('draft','active','deprecated')),
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_scenarios_status ON scenarios(status)"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS literature (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL,
            authors     TEXT,
            year        INTEGER,
            doi         TEXT,
            url         TEXT,
            notes       TEXT,
            category    TEXT NOT NULL DEFAULT 'related_work',
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS nfr (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            category    TEXT NOT NULL
                        CHECK(category IN ('language','license','methodology','modelling','documentation')),
            text        TEXT NOT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nfr_category ON nfr(category)")
    if conn.execute("SELECT COUNT(*) FROM nfr").fetchone()[0] == 0:
        conn.executemany("INSERT INTO nfr (category, text) VALUES (?,?)", [
            ("language",    "The ontology must be expressed in OWL 2 DL."),
            ("license",     "The ontology must be released under the MIT license."),
            ("methodology", "The ontology must be developed following the LOT methodology."),
        ])
    # Idempotent: add bilingual requirement if not yet present
    if not conn.execute(
        "SELECT 1 FROM nfr WHERE text LIKE '%Portuguese%' OR text LIKE '%bilingual%'"
    ).fetchone():
        conn.execute(
            "INSERT INTO nfr (category, text) VALUES (?,?)",
            ("language", "The ontology must provide labels and definitions in both English and Brazilian Portuguese."),
        )
    # Idempotent migrations
    try:
        conn.execute(
            "ALTER TABLE competency_questions ADD COLUMN scenario_id INTEGER"
        )
    except Exception:
        pass
    try:
        conn.execute(
            "ALTER TABLE literature ADD COLUMN category TEXT NOT NULL DEFAULT 'related_work'"
        )
    except Exception:
        pass
    conn.commit()
    conn.close()


_init_cq_schema()


# ---------------------------------------------------------------------------
# Home
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
def ontology_home(request: Request, db: Session = Depends(get_db)):
    meta = _load_meta()
    enrich = _enrich_stats()

    from app.routers.terms import EQUIPMENT_SOURCES, SOURCE_LABELS, SOURCE_VERSIONS
    by_source = db.query(Term.source, func.count(Term.id)).group_by(Term.source).all()
    term_total = db.query(func.count(Term.id)).scalar()

    # In-scope cluster count from enrichment.db (cluster_scope is the source of truth)
    inscope_total = 0
    oos_total = 0
    try:
        _econn = sqlite3.connect(str(_ENRICH_DB))
        row = _econn.execute(
            "SELECT "
            "  SUM(CASE WHEN out_of_scope = 0 THEN 1 ELSE 0 END) AS inscope, "
            "  SUM(CASE WHEN out_of_scope = 1 THEN 1 ELSE 0 END) AS oos "
            "FROM cluster_scope"
        ).fetchone()
        _econn.close()
        if row:
            inscope_total = row[0] or 0
            oos_total     = row[1] or 0
    except Exception:
        pass

    return templates.TemplateResponse(request, "home.html", {
        "meta": meta,
        "enrich": enrich,
        "by_source": by_source,
        "term_total": term_total,
        "equipment_total": inscope_total,
        "oos_total": oos_total,
        "source_labels": SOURCE_LABELS,
        "source_versions": SOURCE_VERSIONS,
    })


@router.post("/ontology/update")
async def update_ontology_meta(request: Request):
    form = await request.form()
    _save_meta(dict(form))
    return JSONResponse({"success": True})


# ---------------------------------------------------------------------------
# Requirements / Competency Questions
# ---------------------------------------------------------------------------

@router.get("/requirements", response_class=HTMLResponse)
def requirements(request: Request):
    conn = _get_enrichment_db()

    # Load scenarios
    sc_rows = conn.execute(
        "SELECT * FROM scenarios ORDER BY status, created_at"
    ).fetchall()
    scenarios = []
    sc_by_id = {}
    for sc in sc_rows:
        d = dict(sc)
        try:
            d["actors"] = json.loads(d.get("actors") or "[]")
        except Exception:
            d["actors"] = []
        scenarios.append(d)
        sc_by_id[d["id"]] = d["title"]

    # Load CQs
    cqs = conn.execute(
        "SELECT * FROM competency_questions ORDER BY status, created_at"
    ).fetchall()

    # Fetch enriched class names and their IDs
    enriched = []
    enriched_id_map: dict[str, int] = {}
    try:
        for r in conn.execute(
            "SELECT id, cluster_label FROM enrichment ORDER BY cluster_label"
        ).fetchall():
            enriched.append(r["cluster_label"])
            enriched_id_map[r["cluster_label"]] = r["id"]
    except Exception as exc:
        logger.warning("Could not load enriched classes for requirements dropdown: %s", exc)

    nfrs = [dict(r) for r in conn.execute(
        "SELECT * FROM nfr ORDER BY category, id"
    ).fetchall()]
    conn.close()

    orsd = _load_orsd_meta()

    rows = []
    for cq in cqs:
        d = dict(cq)
        try:
            names = json.loads(d.get("linked_classes") or "[]")
        except Exception:
            names = []
        # Resolve each class name to (name, enrichment_id) so the template can build correct links
        d["linked_class_names"] = names
        d["linked_classes"] = [(cls, enriched_id_map.get(cls)) for cls in names]
        d["scenario_title"] = sc_by_id.get(d.get("scenario_id"))
        rows.append(d)

    return templates.TemplateResponse(request, "requirements.html", {
        "cqs": rows,
        "scenarios": scenarios,
        "enriched_classes": enriched,
        "orsd": orsd,
        "nfrs": nfrs,
    })


@router.post("/requirements")
async def add_cq(request: Request):
    form = await request.form()
    text = (form.get("text") or "").strip()
    if not text:
        return RedirectResponse("/requirements", status_code=303)

    linked_raw = form.get("linked_classes") or ""
    linked = [c.strip() for c in linked_raw.split(",") if c.strip()]

    scenario_id_raw = (form.get("scenario_id") or "").strip()
    scenario_id = int(scenario_id_raw) if scenario_id_raw.isdigit() else None

    conn = _get_enrichment_db()
    conn.execute(
        "INSERT INTO competency_questions "
        "(text, formal_expr, linked_classes, notes, scenario_id) VALUES (?,?,?,?,?)",
        (
            text,
            form.get("formal_expr") or None,
            json.dumps(linked),
            form.get("notes") or None,
            scenario_id,
        ),
    )
    conn.commit()
    conn.close()
    return RedirectResponse("/requirements", status_code=303)


@router.post("/requirements/{cq_id}/update")
async def update_cq(cq_id: int, request: Request):
    form = await request.form()
    updates: dict = {"updated_at": datetime.now().isoformat()}
    for field in ("text", "formal_expr", "status", "notes"):
        if field in form:
            updates[field] = form[field] or None
    if "linked_classes" in form:
        linked = [c.strip() for c in (form["linked_classes"] or "").split(",") if c.strip()]
        updates["linked_classes"] = json.dumps(linked)

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    conn = _get_enrichment_db()
    conn.execute(f"UPDATE competency_questions SET {set_clause} WHERE id = ?",
                 list(updates.values()) + [cq_id])
    conn.commit()
    conn.close()
    return JSONResponse({"success": True})


@router.post("/requirements/{cq_id}/delete")
async def delete_cq(cq_id: int):
    conn = _get_enrichment_db()
    conn.execute("DELETE FROM competency_questions WHERE id = ?", (cq_id,))
    conn.commit()
    conn.close()
    return RedirectResponse("/requirements", status_code=303)


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

@router.post("/requirements/scenarios")
async def add_scenario(request: Request):
    form = await request.form()
    title = (form.get("title") or "").strip()
    if not title:
        return RedirectResponse("/requirements", status_code=303)
    narrative = (form.get("narrative") or "").strip()
    actors_raw = form.get("actors") or ""
    actors = [a.strip() for a in actors_raw.split(",") if a.strip()]
    status = form.get("status") or "draft"

    conn = _get_enrichment_db()
    conn.execute(
        "INSERT INTO scenarios (title, narrative, actors, status) VALUES (?,?,?,?)",
        (title, narrative, json.dumps(actors), status),
    )
    conn.commit()
    conn.close()
    return RedirectResponse("/requirements", status_code=303)


@router.post("/requirements/scenarios/{sc_id}/update")
async def update_scenario(sc_id: int, request: Request):
    form = await request.form()
    updates: dict = {"updated_at": datetime.now().isoformat()}
    for field in ("title", "narrative", "status"):
        if field in form:
            val = form[field] or None
            if field in ("title", "narrative") and not val:
                continue  # NOT NULL fields; ignore empty submissions
            updates[field] = val
    if "actors" in form:
        actors = [a.strip() for a in (form["actors"] or "").split(",") if a.strip()]
        updates["actors"] = json.dumps(actors)

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    conn = _get_enrichment_db()
    conn.execute(
        f"UPDATE scenarios SET {set_clause} WHERE id = ?",
        list(updates.values()) + [sc_id],
    )
    conn.commit()
    conn.close()
    return JSONResponse({"success": True})


@router.post("/requirements/scenarios/{sc_id}/delete")
async def delete_scenario(sc_id: int):
    conn = _get_enrichment_db()
    conn.execute(
        "UPDATE competency_questions SET scenario_id = NULL WHERE scenario_id = ?",
        (sc_id,),
    )
    conn.execute("DELETE FROM scenarios WHERE id = ?", (sc_id,))
    conn.commit()
    conn.close()
    return RedirectResponse("/requirements", status_code=303)


# ---------------------------------------------------------------------------
# ORSD metadata
# ---------------------------------------------------------------------------

@router.post("/requirements/orsd/update")
async def update_orsd(request: Request):
    if not request.state.user:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    form = await request.form()
    _save_orsd_meta(dict(form))
    return JSONResponse({"success": True})


# ---------------------------------------------------------------------------
# Non-Functional Requirements
# ---------------------------------------------------------------------------

_NFR_CATEGORIES = {"language", "license", "methodology", "modelling", "documentation"}


@router.post("/requirements/nfr")
async def add_nfr(request: Request):
    form = await request.form()
    text = (form.get("text") or "").strip()
    category = (form.get("category") or "").strip()
    if not text or category not in _NFR_CATEGORIES:
        return RedirectResponse("/requirements", status_code=303)
    conn = _get_enrichment_db()
    conn.execute("INSERT INTO nfr (category, text) VALUES (?,?)", (category, text))
    conn.commit()
    conn.close()
    return RedirectResponse("/requirements", status_code=303)


@router.post("/requirements/nfr/{nfr_id}/update")
async def update_nfr(nfr_id: int, request: Request):
    if not request.state.user:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    form = await request.form()
    updates: dict = {}
    if "text" in form and (form["text"] or "").strip():
        updates["text"] = form["text"].strip()
    if "category" in form and form["category"] in _NFR_CATEGORIES:
        updates["category"] = form["category"]
    if not updates:
        return JSONResponse({"success": True})
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    conn = _get_enrichment_db()
    conn.execute(f"UPDATE nfr SET {set_clause} WHERE id = ?",
                 list(updates.values()) + [nfr_id])
    conn.commit()
    conn.close()
    return JSONResponse({"success": True})


@router.post("/requirements/nfr/{nfr_id}/delete")
async def delete_nfr(nfr_id: int):
    conn = _get_enrichment_db()
    conn.execute("DELETE FROM nfr WHERE id = ?", (nfr_id,))
    conn.commit()
    conn.close()
    return RedirectResponse("/requirements", status_code=303)


# ---------------------------------------------------------------------------
# Literature
# ---------------------------------------------------------------------------

_LIT_CATEGORIES = [
    ("about_copi",      "About COPI"),
    ("methodology",     "Methodology"),
    ("source_standard", "Source standard"),
    ("related_work",    "Related work"),
]
_LIT_CAT_KEYS = {k for k, _ in _LIT_CATEGORIES}


@router.get("/references", response_class=HTMLResponse)
def references(request: Request):
    conn = _get_enrichment_db()
    rows = conn.execute(
        "SELECT * FROM literature ORDER BY year DESC, title ASC"
    ).fetchall()
    conn.close()

    buckets: dict[str, list] = {k: [] for k, _ in _LIT_CATEGORIES}
    for p in rows:
        d = dict(p)
        cat = d.get("category") or "related_work"
        if cat not in buckets:
            cat = "related_work"
        d["category"] = cat
        buckets[cat].append(d)

    sections = [
        {"key": k, "label": lbl, "papers": buckets[k]}
        for k, lbl in _LIT_CATEGORIES
        if buckets[k]
    ]
    return templates.TemplateResponse(request, "references.html", {
        "sections": sections,
        "total": sum(len(s["papers"]) for s in sections),
        "categories": _LIT_CATEGORIES,
    })


@router.post("/references")
async def add_paper(request: Request):
    form = await request.form()
    title = (form.get("title") or "").strip()
    if not title:
        return RedirectResponse("/references", status_code=303)
    year_raw = (form.get("year") or "").strip()
    year = int(year_raw) if year_raw.isdigit() else None

    category = form.get("category") or "related_work"
    if category not in _LIT_CAT_KEYS:
        category = "related_work"

    conn = _get_enrichment_db()
    conn.execute(
        "INSERT INTO literature (title, authors, year, doi, url, notes, category) VALUES (?,?,?,?,?,?,?)",
        (
            title,
            form.get("authors") or None,
            year,
            form.get("doi") or None,
            form.get("url") or None,
            form.get("notes") or None,
            category,
        ),
    )
    conn.commit()
    conn.close()
    return RedirectResponse("/references", status_code=303)


@router.post("/references/{paper_id}/update")
async def update_paper(paper_id: int, request: Request):
    form = await request.form()
    updates: dict = {}
    for field in ("title", "authors", "doi", "url", "notes"):
        if field in form:
            val = form[field] or None
            if field == "title" and not val:
                continue
            updates[field] = val
    if "category" in form:
        cat = form["category"] or "related_work"
        updates["category"] = cat if cat in _LIT_CAT_KEYS else "related_work"
    if "year" in form:
        year_raw = (form.get("year") or "").strip()
        updates["year"] = int(year_raw) if year_raw.isdigit() else None

    if not updates:
        return JSONResponse({"success": True})

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    conn = _get_enrichment_db()
    conn.execute(
        f"UPDATE literature SET {set_clause} WHERE id = ?",
        list(updates.values()) + [paper_id],
    )
    conn.commit()
    conn.close()
    return JSONResponse({"success": True})


@router.post("/references/{paper_id}/delete")
async def delete_paper(paper_id: int):
    conn = _get_enrichment_db()
    conn.execute("DELETE FROM literature WHERE id = ?", (paper_id,))
    conn.commit()
    conn.close()
    return RedirectResponse("/references", status_code=303)
