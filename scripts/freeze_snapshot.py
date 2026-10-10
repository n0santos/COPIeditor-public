#!/usr/bin/env python3
"""
Freeze a dated, read-only snapshot of the terminal (status='exported') enrichment
population plus the ontology artifacts derived from it, for the paper's numbers to
be pinned against. See docs/audit_issues.md #1 and docs/working_protocol.md.

Never edit an existing eval/frozen/<date>/ directory. If a number needs to be
recalculated, run this again with a new date and diff the two snapshots.

Run from the COPIeditor root:
    .venv/bin/python3 -m scripts.freeze_snapshot --date 2026-08-25
"""
import argparse
import csv
import hashlib
import json
import os
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

COPIEDITOR_ROOT = Path(__file__).resolve().parents[1]
COPI_REPO_ROOT = COPIEDITOR_ROOT.parent / "copi"
ENRICHMENT_DB = COPIEDITOR_ROOT / "data" / "enrichment.db"
PUBLISHED_OWL = COPI_REPO_ROOT / "src" / "ontology" / "components" / "copi-enriched.owl"

sys.path.insert(0, str(COPIEDITOR_ROOT))
sys.path.insert(0, str(COPIEDITOR_ROOT / "enrichment"))

TERMINAL_STATUS = "exported"

SATELLITE_TABLES = [
    "eval_axiom_snapshot",
    "eval_step_field_snapshot",
    "eval_step_modification_summary",
    "eval_genus_usage",
    "eval_verification_snapshot",
    "eval_interaction_event",
    "enrichment_history",
    "divergence_log",
]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_head(repo_root: Path) -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


def git_dirty(repo_root: Path) -> bool:
    out = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo_root, capture_output=True, text=True, check=True
    )
    return bool(out.stdout.strip())


def dump_table_csv(conn: sqlite3.Connection, sql: str, params: tuple, out_path: Path) -> int:
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    n = 0
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(cols)
        for row in cur:
            writer.writerow(list(row))
            n += 1
    return n


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="YYYY-MM-DD, e.g. 2026-08-25")
    args = parser.parse_args()

    out_dir = COPIEDITOR_ROOT / "eval" / "frozen" / args.date
    if out_dir.exists():
        raise SystemExit(f"{out_dir} already exists — freeze dirs are never overwritten. Pick a new date.")
    out_dir.mkdir(parents=True)

    if not ENRICHMENT_DB.exists():
        raise SystemExit(f"{ENRICHMENT_DB} not found")

    conn = sqlite3.connect(f"file:{ENRICHMENT_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    sql_log = []
    counts = {}

    # enrichment.csv
    sql = "SELECT * FROM enrichment WHERE status = ? ORDER BY id"
    sql_log.append(("enrichment.csv", sql, (TERMINAL_STATUS,)))
    counts["enrichment"] = dump_table_csv(conn, sql, (TERMINAL_STATUS,), out_dir / "enrichment.csv")

    terminal_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM enrichment WHERE status = ? ORDER BY id", (TERMINAL_STATUS,)
    )]
    if not terminal_ids:
        raise SystemExit("no terminal (status='exported') rows found — refusing to freeze an empty cohort")
    placeholders = ",".join("?" for _ in terminal_ids)

    for table in SATELLITE_TABLES:
        sql = f"SELECT * FROM {table} WHERE enrichment_id IN ({placeholders}) ORDER BY enrichment_id"
        sql_log.append((f"{table}.csv", sql, tuple(terminal_ids)))
        counts[table] = dump_table_csv(conn, sql, tuple(terminal_ids), out_dir / f"{table}.csv")

    # disjoint_with.json — derived convenience view, named explicitly in the issue
    disjoint_rows = conn.execute(
        f"SELECT id, cluster_label, disjoint_with FROM enrichment "
        f"WHERE status = ? ORDER BY id", (TERMINAL_STATUS,)
    ).fetchall()
    disjoint_out = []
    for r in disjoint_rows:
        try:
            parsed = json.loads(r["disjoint_with"]) if r["disjoint_with"] else []
        except json.JSONDecodeError:
            parsed = None
        disjoint_out.append({
            "id": r["id"],
            "cluster_label": r["cluster_label"],
            "disjoint_with": parsed,
        })
    with open(out_dir / "disjoint_with.json", "w", encoding="utf-8") as f:
        json.dump(disjoint_out, f, ensure_ascii=False, indent=2)

    # frozen.sqlite — same terminal-filtered rows, queryable as SQL
    sqlite_path = out_dir / "frozen.sqlite"
    conn.execute(f"ATTACH DATABASE '{sqlite_path}' AS frozen")
    cur = conn.execute("SELECT sql FROM main.sqlite_master WHERE type='table' AND name='enrichment'")
    conn.execute(cur.fetchone()["sql"].replace("CREATE TABLE enrichment", "CREATE TABLE frozen.enrichment", 1))
    conn.execute(
        f"INSERT INTO frozen.enrichment SELECT * FROM main.enrichment WHERE status = ?",
        (TERMINAL_STATUS,),
    )
    for table in SATELLITE_TABLES:
        row = conn.execute(
            "SELECT sql FROM main.sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        create_sql = row["sql"].replace(f"CREATE TABLE {table}", f"CREATE TABLE frozen.{table}", 1)
        conn.execute(create_sql)
        conn.execute(
            f"INSERT INTO frozen.{table} SELECT * FROM main.{table} WHERE enrichment_id IN ({placeholders})",
            tuple(terminal_ids),
        )
    conn.commit()
    conn.execute("DETACH DATABASE frozen")
    conn.close()

    # combined-turtle-pre-publication.ttl
    from enrichment.enrichment_service import generate_combined_turtle
    combined_ttl = generate_combined_turtle()
    (out_dir / "combined-turtle-pre-publication.ttl").write_text(combined_ttl, encoding="utf-8")
    disjoint_block_count = combined_ttl.count("owl:AllDisjointClasses")

    # copi-enriched.owl — byte-for-byte copy of the published artifact, broken state preserved
    if not PUBLISHED_OWL.exists():
        raise SystemExit(f"{PUBLISHED_OWL} not found")
    published_bytes = PUBLISHED_OWL.read_bytes()
    (out_dir / "copi-enriched.owl").write_bytes(published_bytes)
    published_disjoint_count = published_bytes.decode("utf-8", errors="replace").lower().count("disjoint")

    copi_head = git_head(COPI_REPO_ROOT)
    copi_dirty = git_dirty(COPI_REPO_ROOT)
    copieditor_head = git_head(COPIEDITOR_ROOT)
    copieditor_dirty = git_dirty(COPIEDITOR_ROOT)

    # sha256 of every file written so far (before MANIFEST/README are added)
    frozen_files = sorted(p for p in out_dir.iterdir() if p.is_file())
    hashes = {p.name: sha256_of(p) for p in frozen_files}

    manifest_lines = []
    manifest_lines.append(f"# Frozen snapshot — {args.date}\n")
    manifest_lines.append(
        "Every number in the paper is, from this point on, derived from this directory — "
        "not from the live database or the live published artifact. See "
        "docs/working_protocol.md and docs/audit_issues.md #1.\n"
    )
    manifest_lines.append("## Provenance\n")
    manifest_lines.append(f"- COPIeditor HEAD: `{copieditor_head}`"
                           + (" (dirty working tree at freeze time)" if copieditor_dirty else "") + "\n")
    manifest_lines.append(f"- copi HEAD: `{copi_head}`"
                           + (" (dirty working tree at freeze time)" if copi_dirty else "") + "\n")
    manifest_lines.append(f"- terminal cohort: status='{TERMINAL_STATUS}', n={len(terminal_ids)}\n")
    manifest_lines.append(
        "\n**`copi-enriched.owl` is preserved in its broken state on purpose** — "
        f"`disjoint` occurs {published_disjoint_count} times in the published artifact "
        "(0 `owl:AllDisjointClasses` blocks survive publication; see issue #26). "
        "This is the evidence for the paper's F11 finding. Do not regenerate or "
        "'fix' this copy — a future correction to the live pipeline must produce a "
        "*new*, separately dated snapshot, never edit this one.\n"
    )
    manifest_lines.append(
        f"\nFor comparison, `combined-turtle-pre-publication.ttl` (the intermediate, "
        f"pre-IRI-remap Turtle) contains {disjoint_block_count} `owl:AllDisjointClasses` blocks — "
        "confirming the loss happens downstream of `generate_combined_turtle()`, in the "
        "publish path (`scripts/regen_enriched_owl.py`).\n"
    )
    manifest_lines.append("\n## Row counts\n")
    manifest_lines.append("| table | rows |\n|---|---|\n")
    manifest_lines.append(f"| enrichment | {counts['enrichment']} |\n")
    for table in SATELLITE_TABLES:
        manifest_lines.append(f"| {table} | {counts[table]} |\n")

    manifest_lines.append("\n## SQL exact per dump\n")
    for fname, sql, params in sql_log:
        shown_sql = sql
        if "IN (" in sql:
            shown_sql = sql.split(" WHERE ")[0] + f" WHERE enrichment_id IN (<{len(terminal_ids)} terminal ids>) ORDER BY enrichment_id"
        manifest_lines.append(f"- `{fname}`:\n  ```sql\n  {shown_sql}\n  ```\n")
    manifest_lines.append(
        "\nTerminal ids (status='exported'), used to filter every satellite table above:\n"
        f"```\n{terminal_ids}\n```\n"
    )
    manifest_lines.append(
        "\n`disjoint_with.json`: derived from `enrichment.disjoint_with` for the same "
        "terminal cohort, JSON-parsed for convenience — not an independent source.\n"
    )
    manifest_lines.append(
        "\n`frozen.sqlite`: same 9 tables (`enrichment` + the 8 satellites above), same "
        "terminal filter, as a queryable SQLite file mirroring the CSVs.\n"
    )
    manifest_lines.append(
        "\n`combined-turtle-pre-publication.ttl`: output of "
        "`enrichment_service.generate_combined_turtle()` at COPIeditor HEAD above — "
        "the pre-IRI-remap, pre-strip Turtle that issue #26's block/class counts are "
        "measured against.\n"
    )
    manifest_lines.append(
        f"\n`copi-enriched.owl`: byte-for-byte copy of "
        f"`{PUBLISHED_OWL.relative_to(COPIEDITOR_ROOT.parent)}` at copi HEAD `{copi_head}`.\n"
    )

    manifest_lines.append("\n## SHA-256\n")
    manifest_lines.append("```\n")
    for name, h in sorted(hashes.items()):
        manifest_lines.append(f"{h}  {name}\n")
    manifest_lines.append("```\n")
    manifest_lines.append(f"\nGenerated by `scripts/freeze_snapshot.py --date {args.date}`.\n")

    (out_dir / "MANIFEST.md").write_text("".join(manifest_lines), encoding="utf-8")

    readme = (
        f"# Frozen snapshot — {args.date}\n\n"
        "Read-only. Every number the paper reports is derived from this directory, "
        "not the live database or the live published artifact. See MANIFEST.md for "
        "provenance, row counts, exact SQL, and file hashes. Do not edit — if a number "
        "needs recalculating, run `scripts/freeze_snapshot.py` with a new `--date` and "
        "diff the two snapshots.\n"
    )
    (out_dir / "README.md").write_text(readme, encoding="utf-8")

    # Re-hash including MANIFEST.md and README.md themselves for the printed summary
    # (not recorded inside MANIFEST.md, which would be self-referential).
    all_files = sorted(p for p in out_dir.iterdir() if p.is_file())
    print(f"Wrote {len(all_files)} files to {out_dir}")
    for p in all_files:
        print(f"  {p.name}  ({p.stat().st_size} bytes)")

    # chmod last: files read-only for everyone, directory read+execute only (no write).
    # Shelling out to `chmod` rather than os.chmod(): os.chmod() on the directory was
    # observed to silently not stick in this environment (files chmod'd fine, the
    # directory came back 0o700 instead of the requested 0o555) — `chmod` via subprocess
    # verified reliable, so use it for both to keep the two code paths consistent.
    subprocess.run(["chmod", "444"] + [str(p) for p in all_files], check=True)
    subprocess.run(["chmod", "555", str(out_dir)], check=True)
    actual_mode = stat.S_IMODE(out_dir.stat().st_mode)
    if actual_mode != 0o555:
        raise SystemExit(f"chmod verification failed: {out_dir} is {oct(actual_mode)}, expected 0o555")
    print(f"chmod applied and verified: files 444, {out_dir.name}/ 555")


if __name__ == "__main__":
    main()
