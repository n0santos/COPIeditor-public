from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from jinja2 import FileSystemLoader
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.jinja_setup import make_templates
from app.models import Hierarchy, Property, Synonym, Term

router = APIRouter()


def _depluralize(word: str) -> str:
    """Strip common English plural suffixes from a single word."""
    if len(word) <= 3:
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"          # activities → activity
    if word.endswith("ess"):
        return word                      # process, stress — keep as-is
    if (
        word.endswith("s")
        and not word.endswith("ss")
        and not word.endswith("us")
        and not word.endswith("is")
        and not word.endswith("as")
        and len(word) > 4
    ):
        return word[:-1]                 # pumps→pump, valves→valve, motors→motor
    return word


def _normalize_label(label: str) -> str:
    """Lowercase + depluralize the last word for cross-source clustering."""
    label = label.lower().strip()
    words = label.split()
    if words:
        words[-1] = _depluralize(words[-1])
    return " ".join(words)


def _escape_like(s: str) -> str:
    """Escape SQLite LIKE special characters so user input is treated literally."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


templates = make_templates(FileSystemLoader("app/templates"))

SOURCE_LABELS = {
    "iso15926": "ISO 15926-4",
    "posc_caesar": "POSC Caesar RDL",
    "cfihos": "CFIHOS",
    "dexpi": "DEXPI",
    "slb_glossary": "SLB Glossary",
    "iso14224": "ISO 14224",
    "isa5_1": "ISA 5.1",
    "onepetro_glossary": "Onepetro Glossary",
    "ppdm": "PPDM",
}

SOURCE_VERSIONS = {
    "iso15926":          "2019",
    "posc_caesar":       "",
    "cfihos":            "V2.0",
    "dexpi":             "",
    "slb_glossary":      "",
    "iso14224":          "2016",
    "isa5_1":            "2022",
    "onepetro_glossary": "",
    "ppdm":              "R-2.4",
}

SOURCE_COLORS = {
    "iso15926": "primary",
    "posc_caesar": "success",
    "cfihos": "warning",
    "dexpi": "danger",
    "slb_glossary": "info",
    "iso14224": "secondary",
    "isa5_1": "dark",
    "onepetro_glossary": "primary",
    "ppdm": "success",
}

SOURCE_SCOPE = {
    "iso15926": "equipment",
    "posc_caesar": "equipment",
    "cfihos": "equipment",
    "dexpi": "equipment",
    "iso14224": "equipment",
    "isa5_1": "equipment",
    "slb_glossary": "glossary",
    "onepetro_glossary": "glossary",
    "ppdm": "equipment",
}

EQUIPMENT_SOURCES = [k for k, v in SOURCE_SCOPE.items() if v == "equipment"]


@router.get("/search", response_class=HTMLResponse)
def search(
    request: Request,
    q: str = Query(""),
    source: str = Query(""),
    term_type: str = Query(""),
    scope: str = Query(""),
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
):
    per_page = 30
    query = db.query(Term)

    if q:
        q_esc = _escape_like(q)
        like = f"%{q_esc}%"
        query = query.filter(
            or_(
                Term.preferred_label.ilike(like, escape="\\"),
                Term.definition.ilike(like, escape="\\"),
            )
        )
    if source:
        query = query.filter(Term.source == source)
    elif scope == "equipment":
        query = query.filter(Term.source.in_(EQUIPMENT_SOURCES))
    if term_type:
        query = query.filter(Term.term_type == term_type)

    total = query.count()

    if q:
        rank = case(
            (Term.preferred_label.ilike(q_esc, escape="\\"), 0),
            (Term.preferred_label.ilike(f"{q_esc} %", escape="\\"), 1),
            (Term.preferred_label.ilike(f"{q_esc}%", escape="\\"), 1),
            (Term.preferred_label.ilike(f"%{q_esc}%", escape="\\"), 2),
            else_=3,
        )
        order = [rank, Term.preferred_label]
    else:
        order = [Term.preferred_label]

    terms = (
        query.order_by(*order)
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    total_pages = max(1, (total + per_page - 1) // per_page)

    # Group terms by normalised label so same-name terms across sources form clusters
    # _normalize_label lowercases and depluralize the last word so
    # "Pumps" and "pump" or "Compressors" and "compressor" cluster together.
    seen: dict[str, int] = {}
    groups: list[list] = []
    page_ids: set[int] = set()
    for t in terms:
        page_ids.add(t.id)
        key = _normalize_label(t.preferred_label)
        if key not in seen:
            seen[key] = len(groups)
            groups.append([t])
        else:
            groups[seen[key]].append(t)

    # Boost: fetch plural/singular variants that ranked outside the current page
    # window but share a normalized key with a term already on this page.
    # Only done when there's an active query to keep browse pages fast.
    if q and seen:
        # Build candidate surface forms for each unique normalized key on this page
        boost_filters = []
        for norm_key in seen:
            boost_filters.append(Term.preferred_label.ilike(norm_key))
            if not norm_key.endswith("s"):
                boost_filters.append(Term.preferred_label.ilike(norm_key + "s"))
                boost_filters.append(Term.preferred_label.ilike(norm_key + "es"))
            if norm_key.endswith("y") and len(norm_key) > 2:
                boost_filters.append(Term.preferred_label.ilike(norm_key[:-1] + "ies"))

        boost_base = db.query(Term).filter(or_(*boost_filters))
        if source:
            boost_base = boost_base.filter(Term.source == source)
        elif scope == "equipment":
            boost_base = boost_base.filter(Term.source.in_(EQUIPMENT_SOURCES))
        if term_type:
            boost_base = boost_base.filter(Term.term_type == term_type)

        for extra in boost_base.all():
            if extra.id in page_ids:
                continue
            key = _normalize_label(extra.preferred_label)
            if key in seen:
                groups[seen[key]].append(extra)
                page_ids.add(extra.id)

    # Available filters
    sources = [
        {"value": src, "label": SOURCE_LABELS.get(src, src)}
        for (src,) in db.query(Term.source).distinct().order_by(Term.source).all()
    ]
    types = [
        t for (t,) in
        db.query(Term.term_type).filter(Term.term_type.isnot(None)).distinct().order_by(Term.term_type).all()
    ]

    return templates.TemplateResponse(
        request, "search.html",
        {
            "terms": terms,
            "groups": groups,
            "q": q,
            "source": source,
            "term_type": term_type,
            "scope": scope,
            "page": page,
            "total": total,
            "total_pages": total_pages,
            "sources": sources,
            "types": types,
            "source_labels": SOURCE_LABELS,
            "source_colors": SOURCE_COLORS,
            "source_scope": SOURCE_SCOPE,
        },
    )


@router.get("/cluster", response_class=HTMLResponse)
def cluster(request: Request, name: str = Query(...), db: Session = Depends(get_db)):
    # Build candidate surface forms: original + normalized + common plural/singular variants
    norm = _normalize_label(name)
    candidates: set[str] = {name, norm}
    if not norm.endswith("s"):
        candidates.add(norm + "s")
        candidates.add(norm + "es")
    if norm.endswith("y") and len(norm) > 2:
        candidates.add(norm[:-1] + "ies")

    raw = (
        db.query(Term)
        .filter(or_(*[Term.preferred_label.ilike(c) for c in candidates]))
        .order_by(Term.source)
        .all()
    )
    # Post-filter: keep only terms whose normalised form matches
    terms = [t for t in raw if _normalize_label(t.preferred_label) == norm]

    if not terms:
        return HTMLResponse("<h1>No terms found</h1>", status_code=404)

    entries = []
    for term in terms:
        parents = (
            db.query(Term)
            .join(Hierarchy, Hierarchy.parent_term_id == Term.id)
            .filter(Hierarchy.child_term_id == term.id)
            .all()
        )
        children = (
            db.query(Term)
            .join(Hierarchy, Hierarchy.child_term_id == Term.id)
            .filter(Hierarchy.parent_term_id == term.id)
            .limit(30)
            .all()
        )
        entries.append({
            "term": term,
            "parents": parents,
            "children": children,
            "source_label": SOURCE_LABELS.get(term.source, term.source),
            "source_color": SOURCE_COLORS.get(term.source, "secondary"),
        })

    return templates.TemplateResponse(
        request, "cluster.html",
        {
            "name": terms[0].preferred_label,
            "entries": entries,
            "source_labels": SOURCE_LABELS,
            "source_colors": SOURCE_COLORS,
        },
    )


@router.get("/terms/{term_id}", response_class=HTMLResponse)
def term_detail(request: Request, term_id: int, db: Session = Depends(get_db)):
    term = db.query(Term).filter(Term.id == term_id).first()
    if term is None:
        return HTMLResponse("<h1>Term not found</h1>", status_code=404)

    parents = (
        db.query(Term)
        .join(Hierarchy, Hierarchy.parent_term_id == Term.id)
        .filter(Hierarchy.child_term_id == term_id)
        .all()
    )
    children = (
        db.query(Term)
        .join(Hierarchy, Hierarchy.child_term_id == Term.id)
        .filter(Hierarchy.parent_term_id == term_id)
        .all()
    )

    return templates.TemplateResponse(
        request, "term.html",
        {
            "term": term,
            "parents": parents,
            "children": children,
            "source_label": SOURCE_LABELS.get(term.source, term.source),
            "source_color": SOURCE_COLORS.get(term.source, "secondary"),
        },
    )
