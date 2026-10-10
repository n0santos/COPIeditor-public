#!/usr/bin/env python3
"""
Find existing classes a participant could be typed as, in the order the
model-participant skill consults them.

Usage:
    python .claude/skills/model-participant/lookup.py <words describing the participant...>
    e.g. lookup.py temperature sensing element
         lookup.py pipeline pig

Prints four sections:
  1. COPI participant vocabulary (copi-vocab + BFO/IOF-Core redirects) — use directly
  2. Enriched equipment classes (validated/exported)                   — use directly
     and proposed entries                                              — usable once validated
  3. ISO 15926-4 FunctionalObject terms not yet enriched               — admit via the pipeline
  4. IOF-Core / BFO classes by label                                   — classification hints only
     (a role, a fiat surface, a process), never a participant type unless listed in section 1

Read-only.
"""
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "enrichment"))

import enrichment_service as svc  # noqa: E402
import participant_vocabulary as pv  # noqa: E402

FUNCTIONAL_OBJECT_ROOT = 7870  # ISO 15926-4 FunctionalObject (see CLAUDE.md Step 1)
STOP = {"of", "the", "a", "an", "and", "or", "for", "in", "to", "with"}


def tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text or "").lower())
    return {w.rstrip("s") for w in words if w not in STOP and len(w) > 1}


def score(query: set[str], *fields: str, weights=(3, 1)) -> int:
    total = 0
    for field, weight in zip(fields, weights):
        total += weight * len(query & tokens(field))
    return total


def top(rows, n=8):
    return [r for r in sorted(rows, key=lambda r: -r[0]) if r[0] > 0][:n]


def main(words: list[str]) -> None:
    q = tokens(" ".join(words))
    if not q:
        print(__doc__)
        sys.exit(2)

    print("1. COPI participant vocabulary — use directly")
    hits = top([(score(q, f"{t.name} {t.label}", t.definition), t) for t in pv.participant_types()])
    for _, t in hits:
        print(f"   {t.name:<36} [{t.group}] {t.definition[:110] or t.label}")
    if not hits:
        print("   (no match)")

    conn = svc.get_enrichment_db()
    rows = conn.execute(
        "SELECT id, cluster_label, status, copi_id, genus, nl_definition_en FROM enrichment "
        "WHERE deprecated_in_favor_of IS NULL OR deprecated_in_favor_of = ''"
    ).fetchall()
    conn.close()
    print("\n2. Enriched equipment classes")
    hits = top([(score(q, r["cluster_label"], r["nl_definition_en"] or ""), r) for r in rows], n=10)
    for _, r in hits:
        usable = "use directly" if r["status"] in ("validated", "exported") else "usable once validated"
        iri = f"COPI_{r['copi_id']:07d}" if r["copi_id"] else "no IRI yet"
        print(f"   {svc._to_pascal_case(r['cluster_label']):<36} id={r['id']:<5} {r['status']:<9} {iri:<13} genus={r['genus']} — {usable}")
    if not hits:
        print("   (no match)")

    enriched = {r["cluster_label"].lower() for r in rows}
    tdb = sqlite3.connect(ROOT / "data" / "terms.db")
    fo = tdb.execute(
        """WITH RECURSIVE fo(id) AS (
               SELECT ? UNION ALL
               SELECT h.child_term_id FROM hierarchy h JOIN fo ON fo.id = h.parent_term_id)
           SELECT DISTINCT t.preferred_label, t.definition FROM terms t JOIN fo ON fo.id = t.id
           WHERE t.source = 'iso15926'""",
        (FUNCTIONAL_OBJECT_ROOT,),
    ).fetchall()
    tdb.close()
    print("\n3. ISO 15926-4 FunctionalObject terms not yet enriched — admit via the 5-step pipeline")
    hits = top([(score(q, label, definition or "", weights=(3, 0)), label, definition)
                for label, definition in fo if label.lower() not in enriched])
    for _, label, definition in hits:
        print(f"   {label:<36} {(definition or '')[:110]}")
    if not hits:
        print("   (no match)")

    from rdflib import Graph, OWL, RDF, RDFS, SKOS, URIRef
    g = Graph()
    for path in pv.UPSTREAM_PATHS:
        g.parse(path)
    candidates = []
    for c in set(g.subjects(RDF.type, OWL.Class)):
        if not isinstance(c, URIRef):
            continue
        labels = [str(l) for p in (RDFS.label, SKOS.prefLabel) for l in g.objects(c, p)]
        label = labels[0] if labels else str(c).rsplit("/", 1)[-1]
        candidates.append((score(q, label, "", weights=(3, 0)), label, str(c)))
    print("\n4. IOF-Core / BFO classes — classification hints, not participant types unless in section 1")
    hits = top(candidates, n=6)
    for _, label, iri in hits:
        print(f"   {label:<36} {iri.replace(pv.IOF, 'iof-core:').replace(pv.BFO, 'bfo:')}")
    if not hits:
        print("   (no match)")


if __name__ == "__main__":
    main(sys.argv[1:])
