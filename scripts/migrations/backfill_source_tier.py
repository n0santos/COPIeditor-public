#!/usr/bin/env python3
"""
Backfill layered-source provenance metadata onto existing source_definitions_used
entries (see CLAUDE.md "Interactive enrichment pipeline" and ODR — layered-source
enrichment). Every entry in the current 287-row enrichment.db is a terms.db-resolved
{"source": ..., "term": ...} object (post odr022_normalize_source_definitions.py) with
no tier/source_type/citation_mode/quote — those keys are new.

Two things happen here, both additive (no key is removed):

1. TIER. There's no recorded "this was the anchor citation" flag on historical rows,
   so the rule is positional: for a row with exactly one entry, that entry is trivially
   primary. For a row with several, the first entry in the JSON array (insertion order
   from the original enrichment step) is tagged primary and the rest secondary. All get
   source_type='standard' and citation_mode='verbatim' (the text cited was the terms.db
   definition field itself, not a paraphrase).

2. QUOTE (bug fix, not just metadata). validate_necessary_parts_quotes() reads
   source_definitions_used RAW and does `str(d)` on every entry to build the text a
   necessary_parts source_quote must appear in. Since odr022 normalized entries to
   {"source", "term"} objects, str(d) on those produces a Python dict repr containing
   the source/term identifiers -- never the actual definition prose -- so any
   source_quote grounding check against a post-migration entry can never match real
   text. Adding a "quote" key (the definition text, resolved the same way
   odr022_normalize_source_definitions.py resolved it) fixes this going forward without
   touching validate_necessary_parts_quotes itself, which treats the JSON opaquely.

Usage:
    python scripts/migrations/backfill_source_tier.py --dry-run
    python scripts/migrations/backfill_source_tier.py --apply
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "enrichment.db"
TERMS_DB = ROOT / "data" / "terms.db"


def main(apply: bool) -> int:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    terms = sqlite3.connect(TERMS_DB)

    updated = 0
    skipped_no_term = []

    for row in con.execute(
        "SELECT id, cluster_label, source_definitions_used FROM enrichment"
    ).fetchall():
        raw = row["source_definitions_used"]
        if not raw or raw.strip() in ("", "[]", "null"):
            continue
        try:
            entries = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(entries, list) or not entries:
            continue
        # Only touch rows where every entry is still an un-tagged {source, term} object.
        if not all(isinstance(e, dict) and "tier" not in e for e in entries):
            continue

        out = []
        changed = False
        for i, entry in enumerate(entries):
            src = entry.get("source")
            term = entry.get("term")
            new_entry = dict(entry)
            new_entry["tier"] = "primary" if i == 0 else "secondary"
            new_entry["source_type"] = "standard"
            new_entry["citation_mode"] = "verbatim"

            if src and term:
                hit = terms.execute(
                    "SELECT definition FROM terms WHERE source = ? "
                    "AND LOWER(preferred_label) = LOWER(?)", (src, term)
                ).fetchone()
                if hit and hit[0]:
                    new_entry["quote"] = hit[0]
                else:
                    skipped_no_term.append((row["cluster_label"], f"{src}:{term}"))
            out.append(new_entry)
            changed = True

        if not changed:
            continue
        updated += 1
        print(f"  [{row['cluster_label']}] {len(out)} entrada(s) tageadas")
        if apply:
            con.execute(
                "INSERT INTO enrichment_history (enrichment_id, snapshot_at, trigger, snapshot_json) "
                "SELECT id, datetime('now'), 'backfill_source_tier', "
                "json_object('cluster_label',cluster_label,"
                "'source_definitions_used',source_definitions_used,'updated_at',updated_at) "
                "FROM enrichment WHERE id = ?", (row["id"],))
            con.execute(
                "UPDATE enrichment SET source_definitions_used = ?, "
                "updated_at = datetime('now') WHERE id = ?",
                (json.dumps(out, ensure_ascii=False), row["id"]))

    if skipped_no_term:
        print("\n  Sem texto de definição resolvido (quote omitido, tier ainda aplicado):")
        for lbl, ident in skipped_no_term:
            print(f"    [{lbl}] {ident}")

    if apply:
        con.commit()
    con.close()
    terms.close()
    print(f"\nlinhas atualizadas: {updated}")
    print("APPLIED" if apply else "DRY RUN — nada escrito")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    sys.exit(main(apply=ap.parse_args().apply))
