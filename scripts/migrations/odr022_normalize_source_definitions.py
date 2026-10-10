#!/usr/bin/env python3
"""
ODR-022 §18 — normalise legacy `source_definitions_used`, and exclude homonym sources.

Two separate problems, both found while checking whether every axiomatization is grounded
in standard definitions.

1. FORMAT. 10 entries store source_definitions_used as a list of strings
   ("iso15926:AERATOR — A FunctionalObject that ...") while the other 277 store a list of
   objects ({"source": "iso15926", "term": "AERATOR"}). Both carry the same information,
   but any tooling that reads the field has to handle both — and one that does not
   silently reports the 10 as ungrounded, which is exactly what happened. Normalised to
   the object form; the definition text is not lost, it lives in terms.db keyed by
   (source, term).

2. HOMONYMS. Citing a source definition that describes a DIFFERENT universal is worse
   than citing none: it looks like grounding while pointing at the wrong thing. The
   ingestion clusters by label, so a label meaning two things in two standards produces
   one entry citing both.

   `lubricator` is the clear case. The entry axiomatizes the wellhead sense — "a
   pressurised cylindrical vessel assembly installed above the wellhead ... that allows
   downhole tools to be introduced" — matching SLB and OnePetro. It also cites ISO 15926
   LUBRICATOR, "a FunctionalObject that has the capability of LUBRICATING", which is a
   lubricating device: a different universal that happens to share a name.

   Excluded via excluded_definition_ids, the mechanism the review UI already uses to drop
   a definition from an entry's evidence (enrichment_routes.py:1992).

Usage:
    python scripts/migrations/odr022_normalize_source_definitions.py --dry-run
    python scripts/migrations/odr022_normalize_source_definitions.py --apply
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "enrichment.db"
TERMS_DB = ROOT / "data" / "terms.db"

# cluster_label -> [(source, term-as-written-in-terms.db)] to drop from the evidence,
# because the standard defines a different universal under the same label.
HOMONYMS = {
    "stack": [
        ("cfihos", "stack",
         "CFIHOS stack is 'a support structure intended to support a flare or vent pipe' — "
         "the structure, not the duct. This entry axiomatizes the ISO 15926 sense, "
         "'capability of EXHAUSTING a flue gas'. The two come apart in a guyed or "
         "derrick-supported flare, where the supporting structure is not the conduit, so "
         "they are distinct universals sharing a label. The support sense stays available "
         "as an unenriched CFIHOS term."),
    ],
    "lubricator": [
        ("iso15926", "LUBRICATOR",
         "ISO 15926 LUBRICATOR is a lubricating device ('capability of LUBRICATING'). "
         "This entry axiomatizes the wellhead pressure vessel that admits tools into a "
         "live well, per SLB and OnePetro. Same label, different universal."),
    ],
}

_LEGACY = re.compile(r"^\s*([A-Za-z0-9_]+)\s*:\s*(.+?)\s+—\s", re.S)


def parse_legacy(item: str):
    """'iso15926:AERATOR — A FunctionalObject ...' -> ('iso15926', 'AERATOR')."""
    m = _LEGACY.match(item)
    return (m.group(1), m.group(2).strip()) if m else None


def main(apply: bool) -> int:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    terms = sqlite3.connect(TERMS_DB)

    # ── 1. normalise format ────────────────────────────────────────────────
    converted = 0
    unparsed = []
    for row in con.execute(
        "SELECT id, cluster_label, source_definitions_used FROM enrichment"
    ).fetchall():
        raw = row["source_definitions_used"]
        if not raw or raw.strip() in ("", "[]", "null"):
            continue
        try:
            items = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(items, list) or not any(isinstance(x, str) for x in items):
            continue

        out, ok = [], True
        for item in items:
            if isinstance(item, dict):
                out.append(item)
                continue
            parsed = parse_legacy(item)
            if not parsed:
                ok = False
                unparsed.append((row["cluster_label"], item[:70]))
                continue
            src, term = parsed
            # Confirm the (source, term) pair really resolves in terms.db, so the
            # normalised record points at a definition that exists. Case-insensitive:
            # the legacy strings lowercased some labels ("onepetro_glossary:lubricator"
            # for a term stored as "Lubricator"). Store the label as terms.db spells it,
            # so the object form is a usable key.
            hit = terms.execute(
                "SELECT preferred_label FROM terms WHERE source = ? "
                "AND LOWER(preferred_label) = LOWER(?) "
                "AND definition IS NOT NULL AND TRIM(definition) != ''", (src, term)
            ).fetchone()
            if not hit:
                ok = False
                unparsed.append((row["cluster_label"], f"{src}:{term} não resolve"))
                continue
            out.append({"source": src, "term": hit[0]})

        if not ok:
            continue
        converted += 1
        print(f"  [{row['cluster_label']}] {len(out)} fonte(s) -> formato objeto")
        for o in out:
            print(f"       {o['source']}:{o['term']}")
        if apply:
            con.execute(
                "INSERT INTO enrichment_history (enrichment_id, snapshot_at, trigger, snapshot_json) "
                "SELECT id, datetime('now'), 'odr022_normalize_sources', "
                "json_object('cluster_label',cluster_label,"
                "'source_definitions_used',source_definitions_used,'updated_at',updated_at) "
                "FROM enrichment WHERE id = ?", (row["id"],))
            con.execute(
                "UPDATE enrichment SET source_definitions_used = ?, "
                "updated_at = datetime('now') WHERE id = ?",
                (json.dumps(out, ensure_ascii=False), row["id"]))

    if unparsed:
        print("\n  NÃO convertidas (deixadas como estavam):")
        for lbl, why in unparsed:
            print(f"    [{lbl}] {why}")

    # ── 2. exclude homonym definitions ─────────────────────────────────────
    print()
    excluded_total = 0
    for label, drops in HOMONYMS.items():
        row = con.execute(
            "SELECT id, excluded_definition_ids FROM enrichment WHERE cluster_label = ?",
            (label,)).fetchone()
        if not row:
            print(f"  [{label}] entrada não encontrada — pulando")
            continue
        try:
            excluded = json.loads(row["excluded_definition_ids"] or "[]")
        except (TypeError, ValueError):
            excluded = []
        added = []
        for src, term, why in drops:
            hit = terms.execute(
                "SELECT id FROM terms WHERE source = ? AND preferred_label = ?",
                (src, term)).fetchone()
            if not hit:
                print(f"  [{label}] {src}:{term} não existe em terms.db — pulando")
                continue
            if hit[0] in excluded:
                continue
            excluded.append(hit[0])
            added.append((hit[0], src, term, why))
        if not added:
            continue
        excluded_total += len(added)
        for tid, src, term, why in added:
            print(f"  [{label}] excluindo id={tid} {src}:{term}")
            print(f"       {why}")
        if apply:
            con.execute(
                "INSERT INTO enrichment_history (enrichment_id, snapshot_at, trigger, snapshot_json) "
                "SELECT id, datetime('now'), 'odr022_exclude_homonym', "
                "json_object('cluster_label',cluster_label,"
                "'excluded_definition_ids',excluded_definition_ids,'updated_at',updated_at) "
                "FROM enrichment WHERE id = ?", (row["id"],))
            con.execute(
                "UPDATE enrichment SET excluded_definition_ids = ?, "
                "updated_at = datetime('now') WHERE id = ?",
                (json.dumps(excluded), row["id"]))

    if apply:
        con.commit()
    con.close()
    terms.close()
    print(f"\nformato normalizado: {converted}   homônimos excluídos: {excluded_total}")
    print("APPLIED" if apply else "DRY RUN — nada escrito")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    sys.exit(main(apply=ap.parse_args().apply))
