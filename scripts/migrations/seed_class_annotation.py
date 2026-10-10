#!/usr/bin/env python3
"""
Seed class_annotation from annotation text that already exists but never reached
the generated OWL in a form APV accepts.

For every non-equipment COPI class the combined Turtle emits (identity-giving
functions, their processes, parent stubs, part stubs) pick ONE English and, where
available, ONE Portuguese definition:

  1. function_nl_definition_en/_pt columns (reviewer-editable), from the entry
     that defines the function;
  2. the stored llm_raw_response step1 definition of the defining entry;
  3. data/stub-definitions.json (English only; until now injected by
     regen_enriched_owl only as skos:definition, which APV does not read).

The "defining entry" of a function/process is the one whose genus does not bear
the same function (e.g. `valve` for FlowControlFunction, not `ball valve`);
ties break on lowest id. Existing rows are never overwritten.

Classes outside COPI's own namespace after remap (redirects to BFO / IOF-Core)
and the frozen/base range COPI_0000001-0000060 are skipped: their annotations
live upstream or in copi-core / copi-vocab.

Usage:
    python -m scripts.migrations.seed_class_annotation            # dry run
    python -m scripts.migrations.seed_class_annotation --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "enrichment"))

import enrichment_service as svc  # noqa: E402

IRI_MAP = ROOT / "enrichment" / "ontologies" / "copi-context" / "copi-iri-map.tsv"
STUB_DEFS = ROOT / "data" / "stub-definitions.json"


def _load_iri_map() -> dict[str, str]:
    out = {}
    for line in IRI_MAP.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) == 2:
            out[parts[0].rsplit("/", 1)[-1]] = parts[1]
    return out


def _in_scope(name: str, iri_map: dict[str, str]) -> bool:
    target = iri_map.get(name)
    if target is None:
        return True  # not yet allocated: will get a COPI IRI
    if "/ontologies/copi/COPI_" not in target:
        return False  # redirected upstream
    return int(target.rsplit("_", 1)[-1]) > 60


def _raw_step1(e: dict) -> dict:
    try:
        raw = json.loads(e.get("llm_raw_response") or "{}") or {}
    except (json.JSONDecodeError, TypeError):
        return {}
    step1 = raw.get("step1_function") if isinstance(raw, dict) else None
    return step1 if isinstance(step1, dict) else {}


def collect() -> dict[str, dict]:
    conn = svc.get_enrichment_db()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM enrichment WHERE status IN ('validated','exported') ORDER BY id")]
    conn.close()
    by_label = {svc._to_pascal_case(r["cluster_label"]): r for r in rows}
    equipment = set(by_label)
    iri_map = _load_iri_map()
    stub_defs = json.loads(STUB_DEFS.read_text(encoding="utf-8")) if STUB_DEFS.exists() else {}

    def defining_first(entries):
        def key(r):
            genus = by_label.get(r["genus"] or "")
            reused = bool(genus and genus["function_name"] == r["function_name"])
            return (reused, r["id"])
        return sorted(entries, key=key)

    rows_out: dict[str, dict] = {}

    def add(name, kind, en=None, en_origin=None, pt=None, pt_origin=None):
        if not name or name in equipment or not _in_scope(name, iri_map):
            return
        rec = rows_out.setdefault(name, {"class_name": name, "kind": kind,
                                         "definition_en": None, "origin_en": None,
                                         "definition_pt": None, "origin_pt": None})
        if en and not rec["definition_en"]:
            rec["definition_en"], rec["origin_en"] = en.strip(), en_origin
        if pt and not rec["definition_pt"]:
            rec["definition_pt"], rec["origin_pt"] = pt.strip(), pt_origin

    by_function: dict[str, list] = {}
    by_process: dict[str, list] = {}
    for r in rows:
        by_function.setdefault(r["function_name"], []).append(r)
        by_process.setdefault(r["process_name"], []).append(r)

    for fname, entries in by_function.items():
        for r in defining_first(entries):
            add(fname, "function", r.get("function_nl_definition_en"), f"function_column:{r['id']}",
                r.get("function_nl_definition_pt"), f"function_column:{r['id']}")
        for r in defining_first(entries):
            add(fname, "function", _raw_step1(r).get("function_nl_definition"), f"llm_raw_response:{r['id']}")
    for pname, entries in by_process.items():
        for r in defining_first(entries):
            add(pname, "process", _raw_step1(r).get("process_nl_definition"), f"llm_raw_response:{r['id']}")

    for r in rows:
        fp = svc._to_pascal_case(r.get("function_parent") or "")
        if fp and fp != "DesignedFunction":
            add(fp, "function")
        pp = svc._to_pascal_case(r.get("process_parent") or "")
        if pp and pp != "PlannedProcess":
            add(pp, "process")
        for p in json.loads(r.get("necessary_parts") or "[]"):
            if p.get("name") and p.get("source_quote"):
                add(svc._to_pascal_case(p["name"]), "part")

    for name, rec in rows_out.items():
        if not rec["definition_en"] and stub_defs.get(name):
            rec["definition_en"], rec["origin_en"] = stub_defs[name], "stub_definitions_json"
    return rows_out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    svc.init_enrichment_schema()
    recs = collect()
    conn = svc.get_enrichment_db(actor="seed_class_annotation")
    existing = {r[0] for r in conn.execute("SELECT class_name FROM class_annotation")}
    new = [r for n, r in sorted(recs.items()) if n not in existing]

    kinds = {}
    for r in new:
        k = kinds.setdefault(r["kind"], {"rows": 0, "en": 0, "pt": 0})
        k["rows"] += 1
        k["en"] += bool(r["definition_en"])
        k["pt"] += bool(r["definition_pt"])
    print(f"{len(new)} new rows ({len(existing)} already present):")
    for k, v in sorted(kinds.items()):
        print(f"  {k:9} rows={v['rows']:3}  with EN={v['en']:3}  with PT={v['pt']:3}")

    if not args.apply:
        print("dry run -- pass --apply to write")
        return
    conn.executemany(
        "INSERT INTO class_annotation (class_name, kind, definition_en, origin_en, definition_pt, origin_pt) "
        "VALUES (:class_name, :kind, :definition_en, :origin_en, :definition_pt, :origin_pt)",
        new,
    )
    conn.commit()
    conn.close()
    print("written")


if __name__ == "__main__":
    main()
