"""
Validates each (X, C) disjointness pair in an enrichment proposal
against the 5-case disjointness decision tree.

Does NOT modify the proposal — only reports.
"""

import json
import logging
import re
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

_ENRICHMENT_DB = Path(__file__).resolve().parent.parent / "data" / "enrichment.db"

# Heuristic tokens that indicate operational/regulatory context (Case 5)
_OPERATIONAL_TOKENS = frozenset({
    "subsea", "topside", "onshore", "offshore",
    "deepwater", "shallow", "highpressure", "lowpressure",
    "highpressure", "lowpressure", "hp", "lp",
})

# Case identifier regex — matches C1: through C5: anywhere in the string
_CASE_ID_RE = re.compile(r'\bC[12345]:', re.IGNORECASE)


def _get_enrichment_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_ENRICHMENT_DB))
    conn.row_factory = sqlite3.Row
    return conn


def _load_candidate_row(label: str) -> dict | None:
    """Look up the most recent enrichment record for a cluster label."""
    conn = _get_enrichment_db()
    conn.create_function("_norm", 1, _norm_genus)
    # Prefer validated; fall back to any status. Match format-insensitively so a
    # PascalCase class ref ('HeatExchanger') resolves to its label ('heat exchanger').
    row = conn.execute(
        """
        SELECT cluster_label, function_name, genus, llm_raw_response, status
          FROM enrichment
         WHERE _norm(cluster_label) = _norm(?)
         ORDER BY CASE WHEN status='validated' THEN 0 ELSE 1 END, id DESC
         LIMIT 1
        """,
        (label,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    d = dict(row)
    # Extract classification_basis from llm_raw_response
    raw = d.get("llm_raw_response") or "{}"
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {}
    else:
        parsed = raw
    d["classification_basis"] = parsed.get("classification_basis") or ""
    return d


def _step5_of(row: dict) -> dict:
    """Extract step5_signature from a DB row's llm_raw_response."""
    raw = row.get("llm_raw_response") or ""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return {}
    return raw.get("step5_signature") or {}


def _has_operational_marker(label: str) -> bool:
    """Heuristic: label contains a token suggesting operational/regulatory context."""
    normalised = re.sub(r'[\s\-_]', '', label.lower())
    return any(normalised.startswith(t) or normalised.endswith(t)
               for t in _OPERATIONAL_TOKENS)


def _norm_genus(g: str) -> str:
    """Case/format-insensitive key for comparing genus values, so a PascalCase
    curated genus ('PressureElement') and its lowercase-spaced form
    ('pressure element') are recognised as the same class."""
    return re.sub(r'[^a-z0-9]', '', (g or '').lower())


def validate_disjointness(
    proposal: dict,
    ontology_state: dict | None = None,
) -> dict:
    """
    Validate each (X, C) disjointness pair in proposal against the 5-case tree.

    Parameters
    ----------
    proposal :
        The LLM-generated enrichment proposal (parsed JSON dict).
    ontology_state :
        Optional pre-built lookup {cluster_label: row_dict} for batch use.
        If None, each candidate is fetched from the DB individually.

    Returns
    -------
    dict with:
        'preserved'          list[(candidate, case_id, note)]   — passes tree
        'rejected'           list[(candidate, case_id, reason)] — fails tree
        'rationale_invalid'  list[(candidate, reason)]          — unverifiable / malformed
        'asymmetry_warnings' list[str]                          — symmetric-assertion warnings
    """
    disjoint_with = proposal.get("disjoint_with") or []
    rationale = proposal.get("disjointness_rationale") or ""
    x_label = proposal.get("cluster_label", "?")
    x_basis = proposal.get("classification_basis") or ""
    # Resolve rows by cluster_label format-insensitively: disjoint_with entries
    # and genus refs are frequently PascalCase class names ('HeatExchanger')
    # while cluster_labels are lowercase-spaced ('heat exchanger').
    _os_norm = ({_norm_genus(k): v for k, v in ontology_state.items()}
                if ontology_state is not None else None)

    def _lookup(label: str) -> dict | None:
        if _os_norm is not None:
            hit = _os_norm.get(_norm_genus(label))
            if hit is not None:
                return hit
        return _load_candidate_row(label)

    # Genus of record = the curated `genus` column (the same source used for
    # candidates below), NOT the frozen LLM step2_genus, which drifts stale once
    # a cluster is curated. Fall back to step2_genus only when the cluster is not
    # yet in the ontology (e.g. a brand-new proposal not in the DB/ontology_state).
    _x_row = _lookup(x_label)
    x_genus = (
        (_x_row.get("genus") if _x_row else "")
        or (proposal.get("step2_genus") or {}).get("genus_name")
        or ""
    )
    step5_x = proposal.get("step5_signature") or {}
    x_kind = step5_x.get("transformation_kind") or ""
    x_kind_status = step5_x.get("transformation_kind_status") or ""

    preserved: list = []
    rejected: list = []
    rationale_invalid: list = []

    for candidate in disjoint_with:
        # --- Rationale format check ---
        if not _CASE_ID_RE.search(rationale):
            rationale_invalid.append((
                candidate,
                "disjointness_rationale lacks a case identifier (C1:/C2:/C3:/C4:/C5:)",
            ))

        # --- Look up candidate record (format-insensitive) ---
        c_row: dict | None = _lookup(candidate)

        if c_row is None:
            rationale_invalid.append((
                candidate,
                f"'{candidate}' not found in DB — cannot validate decision tree",
            ))
            continue

        c_basis = c_row.get("classification_basis") or ""
        c_genus = c_row.get("genus") or ""
        step5_c = _step5_of(c_row)
        c_kind = step5_c.get("transformation_kind") or ""
        c_kind_status = step5_c.get("transformation_kind_status") or ""

        same_genus = bool(x_genus and c_genus and _norm_genus(x_genus) == _norm_genus(c_genus))

        # ---- Case 5: operational/regulatory context — NEVER disjoint -----------
        if _has_operational_marker(x_label) or _has_operational_marker(candidate):
            rejected.append((
                candidate, "C5",
                "operational/regulatory context marker present; Case 5 — never disjoint",
            ))
            continue

        if same_genus:
            both_functional = (x_basis == "functional" and c_basis == "functional")
            both_constructive = (x_basis == "constructive" and c_basis == "constructive")
            mixed = (
                x_basis in ("functional", "constructive") and
                c_basis in ("functional", "constructive") and
                x_basis != c_basis
            )

            if mixed:
                # ---- Case 3: mixed bases — NEVER disjoint -----------------------
                rejected.append((
                    candidate, "C3",
                    f"same genus '{x_genus}'; bases are orthogonal "
                    f"({x_basis} vs {c_basis}); Case 3 — never disjoint",
                ))

            elif both_functional:
                # ---- Case 2: functional — DORMANT (no function disjunctions) ----
                rejected.append((
                    candidate, "C2",
                    f"same genus '{x_genus}'; both functional; "
                    "no declared function disjunctions in current ontology; Case 2 dormant",
                ))

            elif both_constructive:
                # ---- Case 1: constructive — preserved only with structural evidence
                structural_kws = (
                    "part", "closure", "mechanism", "structure", "configuration",
                    "quality", "hascomponentpart", "geometry", "seal", "body",
                )
                if any(kw in rationale.lower() for kw in structural_kws):
                    preserved.append((
                        candidate, "C1",
                        f"same genus '{x_genus}'; both constructive; "
                        "rationale cites structural evidence",
                    ))
                else:
                    rejected.append((
                        candidate, "C1",
                        f"same genus '{x_genus}'; both constructive but "
                        "disjointness_rationale does not cite structural parts/qualities",
                    ))

            else:
                # One or both are 'both' basis — apply Case 1 leniently
                preserved.append((
                    candidate, "C1",
                    f"same genus '{x_genus}'; at least one side is 'both' basis — "
                    "applying Case 1 rules permissively",
                ))

        else:
            # ---- Case 4: different genus ----------------------------------------
            both_controlled = (
                x_kind_status == "controlled" and c_kind_status == "controlled"
            )
            if both_controlled and x_kind and c_kind and x_kind != c_kind:
                preserved.append((
                    candidate, "C4",
                    f"different genus ('{x_genus}' vs '{c_genus}'); "
                    f"transformation_kind incompatible: {x_kind!r} vs {c_kind!r}",
                ))
            elif not both_controlled:
                rejected.append((
                    candidate, "C4",
                    f"different genus but transformation_kind evidence insufficient: "
                    f"X_status={x_kind_status!r}, C_status={c_kind_status!r}; "
                    "treating kind as unknown under OWA — not disjoint",
                ))
            else:
                # Both controlled but same kind — signatures not provably incompatible
                rationale_invalid.append((
                    candidate,
                    f"different genus ('{x_genus}' vs '{c_genus}'); "
                    f"same transformation_kind '{x_kind}'; "
                    "cannot confirm Case 4 disjointness from kind alone",
                ))

    asymmetry_warnings = _check_asymmetry(x_label, disjoint_with)

    return {
        "preserved": preserved,
        "rejected": rejected,
        "rationale_invalid": rationale_invalid,
        "asymmetry_warnings": asymmetry_warnings,
    }


def _check_asymmetry(x_label: str, disjoint_with: list) -> list:
    """
    For each C in disjoint_with, warn if C's record does not declare X as disjoint.
    Asymmetric disjointness is an inconsistency flag — it does not block insertion.
    """
    warnings = []
    conn = _get_enrichment_db()
    conn.create_function("_norm", 1, _norm_genus)
    for candidate in disjoint_with:
        row = conn.execute(
            "SELECT llm_raw_response FROM enrichment "
            "WHERE _norm(cluster_label) = _norm(?) ORDER BY id DESC LIMIT 1",
            (candidate,),
        ).fetchone()
        if row is None:
            continue
        raw = row["llm_raw_response"]
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                continue
        c_disjoint = raw.get("disjoint_with") or []
        if _norm_genus(x_label) not in {_norm_genus(d) for d in c_disjoint}:
            warnings.append(
                f"asymmetric: '{x_label}' declares disjoint with '{candidate}' "
                f"but '{candidate}' does not declare disjoint with '{x_label}'"
            )
    conn.close()
    return warnings


# ---------------------------------------------------------------------------
# Name normalisation (CamelCase → lowercase with spaces)
# ---------------------------------------------------------------------------

def _camel_to_spaces(name: str) -> str:
    """'BallValve' → 'ball valve', 'HeatExchanger' → 'heat exchanger'."""
    s = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', name)
    s = re.sub(r'([A-Z]{2,})([A-Z][a-z])', r'\1 \2', s)
    return s.lower().strip()


def normalise_label(name: str) -> str:
    """Normalise a class name or cluster label for case-insensitive lookup.

    Handles: CamelCase, hyphen, underscore, mixed case.
    'BallValve' == 'ball valve' == 'Ball Valve' == 'ball-valve'
    """
    s = _camel_to_spaces(name)
    s = re.sub(r'[-_]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def build_normalised_index(ontology_state: dict) -> dict:
    """Return {normalised_label → cluster_label} for approximate lookup."""
    index: dict = {}
    for label in ontology_state:
        key = normalise_label(label)
        if key not in index:
            index[key] = label
    return index


# ---------------------------------------------------------------------------
# Structural-only pair validation (ignores rationale text)
# ---------------------------------------------------------------------------

def validate_pair_structural(
    x_label: str, x_basis: str, x_genus: str, x_kind: str, x_kind_status: str,
    c_label: str, c_basis: str, c_genus: str, c_kind: str, c_kind_status: str,
) -> tuple[str, str, str]:
    """Apply the 5-case tree using structural fields only (no rationale text check).

    Returns (classification, case_id, reason) where classification is:
        'preserved_by_structure'  — tree is consistent with disjointness
        'rejected_by_structure'   — tree definitively excludes disjointness
        'unverifiable'            — required structural field absent in X or C
    """
    # Case 5: operational/regulatory context — never disjoint
    if _has_operational_marker(x_label) or _has_operational_marker(c_label):
        return (
            "rejected_by_structure", "C5",
            "operational/regulatory context marker detected",
        )

    same_genus = bool(
        x_genus and c_genus and x_genus.strip().lower() == c_genus.strip().lower()
    )

    if same_genus:
        if not x_basis or not c_basis:
            return (
                "unverifiable", "?",
                f"classification_basis missing — X={x_basis!r}, C={c_basis!r}",
            )

        mixed = (
            x_basis in ("functional", "constructive") and
            c_basis in ("functional", "constructive") and
            x_basis != c_basis
        )
        both_functional = x_basis == "functional" and c_basis == "functional"
        both_constructive = x_basis == "constructive" and c_basis == "constructive"

        if mixed:
            return (
                "rejected_by_structure", "C3",
                f"same genus '{x_genus}'; orthogonal bases ({x_basis} vs {c_basis})",
            )
        elif both_functional:
            return (
                "rejected_by_structure", "C2",
                f"same genus '{x_genus}'; both functional; Case 2 dormant",
            )
        elif both_constructive:
            return (
                "preserved_by_structure", "C1",
                f"same genus '{x_genus}'; both constructive; "
                "structural preconditions met (mutual exclusivity requires domain review)",
            )
        else:
            # At least one side is 'both' — apply Case 1 permissively
            return (
                "preserved_by_structure", "C1",
                f"same genus '{x_genus}'; 'both' basis present; "
                "applying Case 1 permissively",
            )

    else:
        # Different genus — Case 4
        if not x_genus or not c_genus:
            return (
                "unverifiable", "C4",
                f"genus missing — X={x_genus!r}, C={c_genus!r}",
            )
        both_controlled = (
            x_kind_status == "controlled" and c_kind_status == "controlled"
        )
        if both_controlled and x_kind and c_kind:
            if x_kind != c_kind:
                return (
                    "preserved_by_structure", "C4",
                    f"different genus ('{x_genus}' vs '{c_genus}'); "
                    f"transformation_kind incompatible: {x_kind!r} vs {c_kind!r}",
                )
            else:
                return (
                    "unverifiable", "C4",
                    f"different genus but same transformation_kind '{x_kind}'; "
                    "cannot confirm incompatibility from kind alone",
                )
        else:
            return (
                "unverifiable", "C4",
                f"different genus ('{x_genus}' vs '{c_genus}'); "
                f"kind evidence insufficient — X_status={x_kind_status!r}, "
                f"C_status={c_kind_status!r}",
            )


def build_ontology_state() -> dict:
    """
    Load all enrichment records into a lookup dict keyed by cluster_label.
    Use this for batch validation to avoid N DB queries.
    classification_basis is extracted from llm_raw_response.
    """
    conn = _get_enrichment_db()
    rows = conn.execute(
        """
        SELECT cluster_label, function_name, genus, llm_raw_response, status
          FROM enrichment
         ORDER BY CASE WHEN status='validated' THEN 0 ELSE 1 END, id DESC
        """
    ).fetchall()
    conn.close()

    state: dict = {}
    for row in rows:
        label = row["cluster_label"]
        if label in state:
            continue  # keep first (validated-preferred by ORDER BY)
        d = dict(row)
        raw = d.get("llm_raw_response") or "{}"
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = {}
        else:
            parsed = raw
        d["classification_basis"] = parsed.get("classification_basis") or ""
        state[label] = d
    return state
