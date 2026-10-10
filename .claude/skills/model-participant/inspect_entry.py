#!/usr/bin/env python3
"""
Show an enrichment entry's process participation signature with the participant
vocabulary gate's verdict for every participant type.

Usage:
    python .claude/skills/model-participant/inspect_entry.py <id | "cluster label">
    python .claude/skills/model-participant/inspect_entry.py --all-unvetted

Read-only.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "enrichment"))

import enrichment_service as svc  # noqa: E402
import participant_vocabulary as pv  # noqa: E402

NS = pv.COPI_NS


def verdict(name: str, cluster_label: str, iri_map, vocab_names, equipment, baseline) -> str:
    target = iri_map.get(NS + name, NS + name)
    if name in vocab_names:
        return "ok · copi-vocab"
    if not target.startswith(NS):
        return f"ok · redirect → {target}"
    if name in equipment:
        return "ok · validated equipment class"
    tag = "GRANDFATHERED (in baseline)" if f"{cluster_label}|{name}" in baseline else "UNVETTED — blocks validation"
    return tag


def show(row, iri_map, vocab_names, equipment, baseline, published) -> None:
    sig = json.loads(row["process_signature"] or "{}")
    print(f"id={row['id']}  [{row['status']}]  {row['cluster_label']}")
    print(f"  genus={row['genus']}  root={row['genus_bfo_root']}  function={row['function_name']}  process={row['process_name']}")
    print(f"  definition: {row['nl_definition_en'] or '—'}")
    for side in ("inputs", "outputs"):
        for item in sig.get(side) or []:
            if not isinstance(item, dict):
                continue
            name = svc._to_pascal_case((item.get("type") or "").strip())
            print(f"  {side[:-1]:<6} {name:<32} {verdict(name, row['cluster_label'], iri_map, vocab_names, equipment, baseline)}")
            if item.get("constraints"):
                print(f"         constraints: {item['constraints']}")
    print(f"  transformation: {sig.get('transformation')}  (kind: {sig.get('transformation_kind')})")
    for gap in sig.get("participant_vocabulary_gaps") or []:
        print(f"  gap: needed {gap.get('needed')!r}, used {gap.get('used_instead')!r} — {gap.get('why_no_listed_type_fits')}")

    for name in svc.find_unvetted_participants(sig):
        iri = iri_map.get(NS + name)
        if not iri:
            print(f"  >> {name}: never published (no copi-iri-map.tsv row)")
            continue
        info = published.get(iri, {})
        users = [r["cluster_label"] for r in ALL_ROWS if name in svc.participant_types(r["process_signature"])]
        print(f"  >> {name}: published as {iri.rsplit('/', 1)[-1]}  parent={info.get('parent', '?')}")
        print(f"     published definition: {info.get('definition', '—')}")
        print(f"     used by entries: {', '.join(users)}")
    print()


def load_published() -> dict:
    owl = ROOT.parent / "copi" / "src" / "ontology" / "components" / "copi-enriched.owl"
    if not owl.exists():
        return {}
    from rdflib import Graph, RDFS, SKOS, URIRef
    g = Graph()
    g.parse(owl)
    out = {}
    for s in set(g.subjects(RDFS.label, None)):
        if isinstance(s, URIRef) and str(s).startswith(NS):
            out[str(s)] = {
                "parent": ", ".join(str(o).rsplit("/", 1)[-1] for o in g.objects(s, RDFS.subClassOf) if isinstance(o, URIRef)),
                "definition": next((str(o) for o in g.objects(s, SKOS.definition)), "—"),
            }
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    conn = svc.get_enrichment_db()
    ALL_ROWS = conn.execute("SELECT * FROM enrichment").fetchall()
    conn.close()
    iri_map = svc._load_copi_iri_map()
    vocab_names = {t.name for t in pv.participant_types() if t.group != "upstream"}
    equipment = svc._validated_equipment_class_names()
    baseline = svc.load_participant_vocabulary_baseline()
    published = load_published()

    arg = sys.argv[1]
    if arg == "--all-unvetted":
        rows = [r for r in ALL_ROWS if svc.find_unvetted_participants(r["process_signature"])]
    elif arg.isdigit():
        rows = [r for r in ALL_ROWS if r["id"] == int(arg)]
    else:
        rows = [r for r in ALL_ROWS if r["cluster_label"].lower() == arg.lower()]
    if not rows:
        print(f"no enrichment entry matches {arg!r}")
        sys.exit(1)
    for row in rows:
        show(row, iri_map, vocab_names, equipment, baseline, published)
