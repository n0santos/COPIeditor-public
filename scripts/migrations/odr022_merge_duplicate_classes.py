#!/usr/bin/env python3
"""
ODR-022 §15 — merge duplicate classes: repoint every reference to the canonical name.

Two entries turned out to be one universal named differently by two standards. Marking the
loser `deprecated_in_favor_of` is only half the job: every OTHER entry that referenced the
deprecated name by genus, differentia, part or participant must be repointed, or the
generator keeps emitting a stub for it and the ontology still carries two classes.

Columns repointed (semantic — these drive axioms):
    genus, differentia_expression, necessary_parts (name/parent), process_signature (type),
    disjoint_with, distinguishes_from, genus_already_provides, custom_axioms
Columns repointed (prose — stale explanations of a changed choice):
    genus_rationale, differentia_rationale, parts_rationale, disjointness_rationale,
    nl_definition_en, semiformal_axiom
NOT touched:
    llm_raw_response — provenance, must stay verbatim
    fol_axiom — regenerated from the fields above

Safety checks before writing:
  * refuses if a repoint would make a class disjoint with itself
  * refuses if a repoint would make a class its own genus
  * refuses if the canonical target does not exist or is itself deprecated

Usage:
    python scripts/migrations/odr022_merge_duplicate_classes.py --dry-run
    python scripts/migrations/odr022_merge_duplicate_classes.py --apply
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / "data" / "enrichment.db"

SEMANTIC_TEXT = ["genus", "differentia_expression"]
SEMANTIC_JSON = ["necessary_parts", "process_signature", "disjoint_with",
                 "distinguishes_from", "genus_already_provides", "custom_axioms"]
PROSE = ["genus_rationale", "differentia_rationale", "parts_rationale",
         "disjointness_rationale", "nl_definition_en", "semiformal_axiom"]


def pascal(label: str) -> str:
    return "".join(w[:1].upper() + w[1:] for w in re.split(r"[\s_-]+", label.strip()) if w)


def repoint_json(raw, old, new, log, where):
    """Rename `old` -> `new` anywhere it appears as a value or key in a JSON blob."""
    if not raw or raw in ("", "[]", "{}", "null"):
        return raw, False
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return raw, False

    changed = False

    def walk(node):
        nonlocal changed
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                nk = new if k == old else k
                if nk != k:
                    changed = True
                    log.append(f"{where}: key {old} -> {new}")
                out[nk] = walk(v)
            return out
        if isinstance(node, list):
            return [walk(x) for x in node]
        if node == old:
            changed = True
            log.append(f"{where}: value {old} -> {new}")
            return new
        return node

    data = walk(data)
    return (json.dumps(data, ensure_ascii=False), True) if changed else (raw, False)


def main(apply: bool) -> int:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    merges = con.execute(
        "SELECT cluster_label, deprecated_in_favor_of FROM enrichment "
        "WHERE deprecated_in_favor_of IS NOT NULL AND deprecated_in_favor_of != ''"
    ).fetchall()
    if not merges:
        print("No merges recorded (deprecated_in_favor_of is empty everywhere).")
        con.close()
        return 0

    labels = {r["cluster_label"] for r in con.execute("SELECT cluster_label FROM enrichment")}
    deprecated_labels = {r["cluster_label"] for r in merges}

    pairs = []
    for m in merges:
        tgt = m["deprecated_in_favor_of"]
        if tgt not in labels:
            print(f"ERROR — target '{tgt}' does not exist as an entry.")
            con.close()
            return 1
        if tgt in deprecated_labels:
            print(f"ERROR — target '{tgt}' is itself deprecated (chained merge).")
            con.close()
            return 1
        pairs.append((pascal(m["cluster_label"]), pascal(tgt), m["cluster_label"], tgt))

    print("merges:")
    for old, new, ol, nl in pairs:
        print(f"  {ol}  ->  {nl}      ({old} -> {new})")
    print()

    all_cols = ["id", "cluster_label"] + SEMANTIC_TEXT + SEMANTIC_JSON + PROSE
    rows = con.execute(f"SELECT {','.join(all_cols)} FROM enrichment").fetchall()

    updates, log, touched = {}, [], 0
    for row in rows:
        if row["cluster_label"] in deprecated_labels:
            continue                      # the deprecated entry keeps its own record
        upd = {}
        for old, new, ol, nl in pairs:
            for c in SEMANTIC_TEXT:
                v = upd.get(c, row[c])
                if v and re.search(rf"\b{re.escape(old)}\b", v):
                    upd[c] = re.sub(rf"\b{re.escape(old)}\b", new, v)
                    log.append(f"[{row['cluster_label']}] {c}: {old} -> {new}")
            for c in SEMANTIC_JSON:
                v, ch = repoint_json(upd.get(c, row[c]), old, new, log,
                                     f"[{row['cluster_label']}] {c}")
                if ch:
                    upd[c] = v
            for c in PROSE:
                v = upd.get(c, row[c])
                # PascalCase in prose is always a class reference — safe to repoint.
                if v and re.search(rf"\b{re.escape(old)}\b", v):
                    upd[c] = re.sub(rf"\b{re.escape(old)}\b", new, v)
                    log.append(f"[{row['cluster_label']}] {c} (prose): {old} -> {new}")
                # The spelled-out label is only safe when it is multi-word. A single-word
                # label like "seat" is ordinary English: repointing it rewrites "the seat
                # of the valve" into "the valve seat of the valve", and on the merge
                # target's own row it produces "valve valve seat". Skip both cases.
                if (v and len(ol.split()) >= 2
                        and row["cluster_label"] != nl
                        and re.search(rf"\b{re.escape(ol)}\b", v, re.I)):
                    upd[c] = re.sub(rf"\b{re.escape(ol)}\b", nl,
                                    upd.get(c, v), flags=re.I)
                    log.append(f"[{row['cluster_label']}] {c} (prose): '{ol}' -> '{nl}'")
        if upd:
            updates[row["id"]] = upd
            touched += 1

    for line in log:
        print("  " + line)
    print(f"\nentries touched: {touched}")

    # ── safety checks on the post-repoint state ─────────────────────────────
    problems = []
    for rid, upd in updates.items():
        row = con.execute("SELECT cluster_label, genus, disjoint_with FROM enrichment "
                          "WHERE id = ?", (rid,)).fetchone()
        me = pascal(row["cluster_label"])
        genus = upd.get("genus", row["genus"])
        if genus == me:
            problems.append(f"[{row['cluster_label']}] would become its own genus")
        try:
            dj = json.loads(upd.get("disjoint_with", row["disjoint_with"]) or "[]")
            if isinstance(dj, list) and me in dj:
                problems.append(f"[{row['cluster_label']}] would be disjoint with itself")
            if isinstance(dj, list) and len(dj) != len(set(dj)):
                problems.append(f"[{row['cluster_label']}] disjoint_with has duplicates "
                                f"after repoint: {dj}")
        except (TypeError, ValueError):
            pass
    if problems:
        print("\nREFUSING — repoint would create:")
        for p in problems:
            print("  " + p)
        con.close()
        return 1
    print("safety checks: OK (no self-genus, no self-disjointness)")

    if apply:
        for rid, upd in updates.items():
            con.execute(
                "INSERT INTO enrichment_history (enrichment_id, snapshot_at, trigger, snapshot_json) "
                "SELECT id, datetime('now'), 'odr022_merge_repoint', "
                "json_object('cluster_label',cluster_label,'genus',genus,"
                "'differentia_expression',differentia_expression,"
                "'necessary_parts',necessary_parts,'updated_at',updated_at) "
                "FROM enrichment WHERE id = ?", (rid,))
            sets = ", ".join(f"{c} = ?" for c in upd)
            con.execute(f"UPDATE enrichment SET {sets}, updated_at = datetime('now') "
                        f"WHERE id = ?", (*upd.values(), rid))
        con.commit()
    con.close()
    print("APPLIED" if apply else "DRY RUN — nothing written")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    sys.exit(main(apply=ap.parse_args().apply))
