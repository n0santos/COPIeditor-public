#!/usr/bin/env python3
"""
Audit of function-class disjointness in the COPI ontology.

Sources consulted:
  1. enrichment.db — function_name / function_parent columns (all enrichments)
  2. Generated Turtle from validated enrichments — parsed with rdflib to find
     any owl:disjointWith or owl:AllDisjointClasses declarations whose members
     are function classes (subclasses of iof-core:DesignedFunction).

Usage:
    python tools/audit_function_disjointness.py

Output:
    /tmp/function_disjointness_audit.json  — machine-readable
    /tmp/function_disjointness_audit.md    — human-readable Markdown

Does NOT modify the database or ontology.
"""

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import rdflib
from rdflib import OWL, RDF, RDFS, Namespace, URIRef
from rdflib.collection import Collection

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "enrichment"))

from enrichment_service import generate_turtle, get_enrichment_db  # noqa: E402

DB_PATH   = PROJECT_ROOT / "data" / "enrichment.db"
OUT_JSON  = Path("/tmp/function_disjointness_audit.json")
OUT_MD    = Path("/tmp/function_disjointness_audit.md")

COPI_NS = "https://www.inf.ufrgs.br/ontologies/copi#"
IOF_NS  = "https://spec.industrialontologies.org/ontology/"

# DesignedFunction IRI can appear in two forms depending on the IOF-Core version
DESIGNED_FUNCTION_IRIS: set[str] = {
    f"{IOF_NS}construct/DesignedFunction",
    f"{IOF_NS}core/Core/DesignedFunction",
    f"{IOF_NS}DesignedFunction",
    "https://spec.industrialontologies.org/ontology/construct/DesignedFunction",
}
# BFO Function IRI (BFO_0000034)
BFO_FUNCTION_IRI = "http://purl.obolibrary.org/obo/BFO_0000034"


# ---------------------------------------------------------------------------
# Step 1: Load function classes from the DB
# ---------------------------------------------------------------------------

def load_function_classes_from_db(conn: sqlite3.Connection) -> dict[str, dict]:
    """
    Return a dict: function_name -> {iri, label, parent, parent_iri,
    parent_enriched, sources (list of cluster_labels), status_max}

    Deduplication: for each function_name, prefer the entry from a validated
    enrichment with function_parent_enriched=true. Fall back to majority vote
    on parent when there are conflicts.
    """
    rows = conn.execute(
        "SELECT cluster_label, function_name, function_parent, status, "
        "       llm_raw_response "
        "FROM enrichment "
        "WHERE function_name IS NOT NULL AND function_name != '' "
        "ORDER BY "
        "  CASE status WHEN 'validated' THEN 0 WHEN 'proposed' THEN 1 ELSE 2 END, "
        "  cluster_label"
    ).fetchall()

    # Accumulate per function_name
    raw: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        fn = row["function_name"].strip()
        parent = (row["function_parent"] or "DesignedFunction").strip()
        try:
            p = json.loads(row["llm_raw_response"] or "{}")
        except Exception:
            p = {}
        s1 = p.get("step1_function") or {}
        parent_enriched = bool(s1.get("function_parent_enriched", False))
        raw[fn].append({
            "cluster_label":    row["cluster_label"],
            "parent":           parent,
            "parent_enriched":  parent_enriched,
            "status":           row["status"],
        })

    result: dict[str, dict] = {}
    for fn, entries in raw.items():
        # Best entry: validated + parent_enriched > validated > proposed
        def _priority(e):
            s = 0 if e["status"] == "validated" else 1
            pe = 0 if e["parent_enriched"] else 1
            return (s, pe)

        best = sorted(entries, key=_priority)[0]

        # Check for conflicting parents
        parents_seen = {e["parent"] for e in entries}
        conflict = len(parents_seen) > 1

        iri = f"{COPI_NS}{fn}"
        parent_name = best["parent"]
        # Resolve parent IRI
        if parent_name in ("DesignedFunction",):
            parent_iri = list(DESIGNED_FUNCTION_IRIS)[0]
        elif parent_name == "DesignedFunction" or "DesignedFunction" in parent_name:
            parent_iri = list(DESIGNED_FUNCTION_IRIS)[0]
        else:
            parent_iri = f"{COPI_NS}{parent_name}"

        result[fn] = {
            "iri":             iri,
            "label":           fn,
            "parent":          parent_name,
            "parent_iri":      parent_iri,
            "parent_enriched": best["parent_enriched"],
            "sources":         sorted({e["cluster_label"] for e in entries}),
            "conflict":        conflict,
            "conflict_parents": sorted(parents_seen) if conflict else [],
        }

    return result


# ---------------------------------------------------------------------------
# Step 2: Build parent→children map for sibling detection
# ---------------------------------------------------------------------------

def build_hierarchy(functions: dict[str, dict]) -> dict[str, list[str]]:
    """parent_name → [child_fn, child_fn, ...]"""
    children: dict[str, list[str]] = defaultdict(list)
    for fn, info in functions.items():
        children[info["parent"]].append(fn)
    return dict(children)


def all_descendants(fn: str, children: dict[str, list[str]]) -> set[str]:
    """All (transitive) descendants of fn in the function hierarchy."""
    result: set[str] = set()
    queue = list(children.get(fn, []))
    while queue:
        c = queue.pop()
        if c not in result:
            result.add(c)
            queue.extend(children.get(c, []))
    return result


def is_function_class(iri: str, functions: dict[str, dict]) -> bool:
    """True if the IRI corresponds to a COPI function class or DesignedFunction/BFO_Function."""
    if iri in DESIGNED_FUNCTION_IRIS:
        return True
    if iri == BFO_FUNCTION_IRI:
        return True
    if iri.startswith(COPI_NS):
        local = iri[len(COPI_NS):]
        return local in functions
    return False


# ---------------------------------------------------------------------------
# Step 3: Parse generated Turtle for validated enrichments
# ---------------------------------------------------------------------------

def build_rdf_graph(conn: sqlite3.Connection) -> rdflib.Graph:
    """Generate and merge Turtle from all validated enrichments into one graph."""
    rows = conn.execute(
        "SELECT id FROM enrichment WHERE status IN ('validated', 'exported') "
        "ORDER BY cluster_label"
    ).fetchall()

    g = rdflib.Graph()
    errors = 0
    for row in rows:
        try:
            ttl = generate_turtle(row["id"])
            g.parse(data=ttl, format="turtle")
        except Exception as exc:
            print(f"  Warning: could not generate Turtle for id={row['id']}: {exc}")
            errors += 1

    print(f"  Parsed {len(rows) - errors}/{len(rows)} validated enrichments "
          f"({len(g)} triples total)")
    return g


def extract_disjointness(
    g: rdflib.Graph,
    functions: dict[str, dict],
) -> list[dict]:
    """
    Find all disjointness declarations in the graph where BOTH members
    are function classes (subclasses of DesignedFunction).
    Returns list of {f1, f2, source}.
    """
    declared: list[dict] = []
    seen: set[frozenset] = set()

    def _record(a: str, b: str, source: str) -> None:
        key = frozenset([a, b])
        if key not in seen:
            seen.add(key)
            declared.append({"f1": a, "f2": b, "source": source})

    # owl:disjointWith pairs
    for s, _, o in g.triples((None, OWL.disjointWith, None)):
        s_str, o_str = str(s), str(o)
        if is_function_class(s_str, functions) and is_function_class(o_str, functions):
            _record(s_str, o_str, "owl:disjointWith")

    # owl:AllDisjointClasses
    for node in g.subjects(RDF.type, OWL.AllDisjointClasses):
        members_list = list(g.objects(node, OWL.members))
        if not members_list:
            continue
        items = list(Collection(g, members_list[0]))
        fn_items = [str(i) for i in items if is_function_class(str(i), functions)]
        for i, a in enumerate(fn_items):
            for b in fn_items[i + 1:]:
                _record(a, b, "owl:AllDisjointClasses")

    return declared


# ---------------------------------------------------------------------------
# Step 4: Candidate disjunctions (siblings with no declared disjunction)
# ---------------------------------------------------------------------------

def find_candidates(
    functions: dict[str, dict],
    children: dict[str, list[str]],
    declared: list[dict],
) -> list[dict]:
    """
    For each internal node in the function hierarchy that has ≥ 2 direct
    children, list sibling pairs that have no declared disjunction.
    """
    declared_pairs: set[frozenset] = {
        frozenset([d["f1"], d["f2"]]) for d in declared
    }
    # Normalise IRIs to local names for simpler matching
    declared_local: set[frozenset] = set()
    for d in declared:
        f1_local = d["f1"].split("#")[-1].split("/")[-1]
        f2_local = d["f2"].split("#")[-1].split("/")[-1]
        declared_local.add(frozenset([f1_local, f2_local]))

    candidates: list[dict] = []
    seen: set[frozenset] = set()

    for parent, kids in children.items():
        if len(kids) < 2:
            continue
        for i, a in enumerate(sorted(kids)):
            for b in sorted(kids)[i + 1:]:
                key = frozenset([a, b])
                if key in seen:
                    continue
                seen.add(key)
                # Check declared using both IRI and local name
                a_iri = functions[a]["iri"]
                b_iri = functions[b]["iri"]
                if (frozenset([a_iri, b_iri]) in declared_pairs
                        or frozenset([a, b]) in declared_local):
                    continue
                candidates.append({
                    "f1":            a,
                    "f2":            b,
                    "f1_iri":        a_iri,
                    "f2_iri":        b_iri,
                    "shared_parent": parent,
                    "rationale":     f"siblings under {parent}",
                })

    return sorted(candidates, key=lambda x: (x["shared_parent"], x["f1"]))


# ---------------------------------------------------------------------------
# Step 5: Report generation
# ---------------------------------------------------------------------------

def interpret(report: dict) -> str:
    n   = report["total_function_classes"]
    d   = len(report["declared_disjunctions"])
    c   = len(report["candidate_disjunctions_not_declared"])
    lines = []
    if n < 10:
        lines.append(
            f"Function hierarchy is small/flat ({n} classes). "
            "Disjointness reasoning (Leva 3.4 Case 2) will rarely trigger."
        )
    else:
        lines.append(f"Function hierarchy has {n} classes across multiple levels.")
    if d == 0:
        lines.append(
            "No function-level disjointness declared. "
            "Leva 3.4 Case 2 is DORMANT: implement the rule but document "
            "it as future work — disjunctions should be added after domain-expert review."
        )
    else:
        lines.append(
            f"{d} function disjunction(s) declared. "
            "Leva 3.4 Case 2 validator must load this set at initialisation."
        )
    if c > 10:
        lines.append(
            f"{c} candidate sibling pairs with no declared disjunction. "
            "Opportunity to strengthen the ontology — review with domain expert "
            "before adding axioms."
        )
    elif c > 0:
        lines.append(f"{c} candidate sibling pair(s) suggested for review.")
    return "  ".join(lines)


def write_json(report: dict) -> None:
    OUT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False))


def write_markdown(report: dict) -> None:
    n = report["total_function_classes"]
    d = len(report["declared_disjunctions"])
    candidates = report["candidate_disjunctions_not_declared"]
    c = len(candidates)

    # Split candidates: DesignedFunction siblings (flat, low value) vs deeper siblings
    deep_candidates   = [x for x in candidates if x["shared_parent"] != "DesignedFunction"]
    flat_candidates   = [x for x in candidates if x["shared_parent"] == "DesignedFunction"]

    lines = [
        "# Function Disjointness Audit — COPI Ontology",
        "",
        f"**Total function classes:** {n}  ",
        f"**Declared function disjunctions:** {d}  ",
        f"**Candidate sibling pairs (all levels):** {c}  ",
        f"  — deep (non-DesignedFunction parent): **{len(deep_candidates)}**  ",
        f"  — flat (direct DesignedFunction children): {len(flat_candidates)}  ",
        "",
        f"**Interpretation:** {report['interpretation']}",
        "",
        "---",
        "",
        "## Function Class Hierarchy",
        "",
        "| Function class | Parent | Sources (sample) |",
        "|----------------|--------|------------------|",
    ]
    for fc in sorted(report["function_classes"], key=lambda x: (x["parent"], x["label"])):
        sources = ", ".join(fc["sources"][:4])
        if len(fc["sources"]) > 4:
            sources += f" (+{len(fc['sources'])-4})"
        conflict = " ⚠ parent conflict" if fc.get("conflict") else ""
        lines.append(f"| `{fc['label']}` | `{fc['parent']}` | {sources}{conflict} |")

    lines += [
        "",
        "---",
        "",
        f"## Declared Function Disjunctions ({d})",
        "",
    ]
    if d == 0:
        lines.append(
            "_None declared. All disjointness in the current ontology is between "
            "equipment classes, not function classes._"
        )
    else:
        lines += [
            "| F1 | F2 | Source |",
            "|----|----|----|",
        ]
        for dj in report["declared_disjunctions"]:
            f1 = dj["f1"].split("#")[-1]
            f2 = dj["f2"].split("#")[-1]
            lines.append(f"| `{f1}` | `{f2}` | `{dj['source']}` |")

    lines += [
        "",
        "---",
        "",
        f"## Priority Candidates: Deep Sibling Pairs ({len(deep_candidates)})",
        "",
        "_Siblings under an enriched COPI function parent (not DesignedFunction directly). "
        "These are the highest-value candidates for disjointness axioms because their "
        "shared parent already carries shared context._",
        "",
    ]
    if not deep_candidates:
        lines.append(
            "_None. The hierarchy is currently too flat — almost all function classes "
            "are direct children of DesignedFunction._"
        )
    else:
        current_parent = None
        for cd in deep_candidates:
            if cd["shared_parent"] != current_parent:
                current_parent = cd["shared_parent"]
                lines += ["", f"### Siblings under `{current_parent}`", ""]
                lines += ["| F1 | F2 |", "|----|----|"]
            lines.append(f"| `{cd['f1']}` | `{cd['f2']}` |")

    lines += [
        "",
        "---",
        "",
        f"## Flat Candidates: Direct DesignedFunction Children ({len(flat_candidates)} pairs)",
        "",
        "_All direct children of DesignedFunction are technically siblings, giving "
        f"C({sum(1 for f in report['function_classes'] if f['parent']=='DesignedFunction')}, 2) "
        f"= {len(flat_candidates)} pairs. Most of these are NOT semantically disjoint "
        "(e.g. FlowControlFunction and FlowMeasurementFunction can co-occur on the same "
        "equipment). Declaring disjointness here requires careful domain review._",
        "",
        "_List omitted from this report due to size. See the JSON output for the full list._",
    ]

    lines += ["", "---", ""]
    if report.get("parent_conflicts"):
        lines += [
            "## ⚠ Parent Conflicts (same function_name, different parents in DB)",
            "",
            "| Function | Parents observed |",
            "|----------|-----------------|",
        ]
        for fc in report["function_classes"]:
            if fc.get("conflict"):
                parents = " / ".join(fc["conflict_parents"])
                lines.append(f"| `{fc['label']}` | {parents} |")
        lines.append("")

    OUT_MD.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")

    conn = get_enrichment_db()

    print("Loading function classes from DB...")
    functions = load_function_classes_from_db(conn)
    print(f"  {len(functions)} distinct function classes found")

    children = build_hierarchy(functions)

    print("Parsing generated Turtle from validated enrichments...")
    g = build_rdf_graph(conn)
    conn.close()

    print("Extracting disjointness declarations...")
    declared = extract_disjointness(g, functions)
    print(f"  {len(declared)} function disjunction(s) declared")

    print("Finding candidate sibling pairs...")
    candidates = find_candidates(functions, children, declared)
    print(f"  {len(candidates)} candidate pair(s) without declared disjunction")

    has_conflicts = any(f.get("conflict") for f in functions.values())

    report = {
        "total_function_classes": len(functions),
        "function_classes": [
            {
                "iri":             info["iri"],
                "label":           info["label"],
                "parent":          info["parent"],
                "parent_enriched": info["parent_enriched"],
                "sources":         info["sources"],
                "conflict":        info["conflict"],
                "conflict_parents": info["conflict_parents"],
            }
            for info in sorted(functions.values(), key=lambda x: x["label"])
        ],
        "declared_disjunctions":               declared,
        "candidate_disjunctions_not_declared": candidates,
        "parent_conflicts":                    has_conflicts,
    }
    report["interpretation"] = interpret(report)

    write_json(report)
    write_markdown(report)

    print(f"\nWrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print()
    print(f"Interpretation: {report['interpretation']}")

    # Quick hierarchy summary
    print("\nHierarchy summary (parent → children count):")
    for parent, kids in sorted(children.items(), key=lambda kv: -len(kv[1])):
        print(f"  {len(kids):3d} children  {parent}")


if __name__ == "__main__":
    main()
