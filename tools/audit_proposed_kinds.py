#!/usr/bin/env python3
"""
Audit of proposed (non-controlled) transformation_kind values in enrichment.db.

Lists all records whose step5_signature contains transformation_kind_status='proposed',
groups them by the proposed term, and prints a Markdown report with usage counts,
cluster labels, and rationale samples.

Usage:
    python tools/audit_proposed_kinds.py

Output:
    /tmp/proposed_kinds_audit.md  — human-readable Markdown report

Does NOT modify the database.

Review policy
-------------
Run periodically (e.g. every 500 new enrichments):
  - Promote: term used >= 3 times with consistent rationale → add to
    TRANSFORMATION_KINDS_CONTROLLED in enrichment_service.py + update system prompt.
  - Reject: term is a special case of an existing canonical term → update
    affected records to use the canonical term.
  - Keep: ambiguous cases → defer to next review cycle.
"""

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "enrichment.db"
OUT_MD  = Path("/tmp/proposed_kinds_audit.md")


def load_proposed(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT cluster_label, llm_raw_response FROM enrichment"
    ).fetchall()

    proposed = []
    for label, raw in rows:
        try:
            p = json.loads(raw or "{}")
        except Exception:
            continue
        sig = p.get("step5_signature") or {}
        if sig.get("transformation_kind_status") != "proposed":
            continue
        proposed.append({
            "cluster_label":         label,
            "transformation_kind":   sig.get("transformation_kind", ""),
            "proposed_kind_rationale": (sig.get("proposed_kind_rationale") or "").strip(),
            "transformation":        (sig.get("transformation") or "").strip(),
        })
    return proposed


def build_groups(records: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        groups[r["transformation_kind"]].append(r)
    return dict(sorted(groups.items(), key=lambda kv: -len(kv[1])))


def write_markdown(groups: dict[str, list[dict]], total_enrichments: int) -> str:
    total_proposed = sum(len(v) for v in groups.values())
    pct = round(100 * total_proposed / total_enrichments, 1) if total_enrichments else 0

    lines = [
        "# Proposed Transformation-Kind Audit",
        "",
        f"**Total enrichments in DB:** {total_enrichments}  ",
        f"**Records with status=proposed:** {total_proposed} ({pct} %)  ",
        f"**Distinct proposed terms:** {len(groups)}  ",
        "",
        "---",
        "",
        "## Summary",
        "",
        "| Proposed term | Count | Cluster labels (sample) |",
        "|---------------|-------|-------------------------|",
    ]
    for term, items in groups.items():
        labels = ", ".join(sorted({i["cluster_label"] for i in items})[:5])
        lines.append(f"| `{term}` | {len(items)} | {labels} |")

    lines += ["", "---", "", "## Details", ""]

    for term, items in groups.items():
        lines += [
            f"### `{term}` ({len(items)} record{'s' if len(items) != 1 else ''})",
            "",
        ]
        labels = sorted({i["cluster_label"] for i in items})
        lines.append(f"**Cluster labels:** {', '.join(labels)}")
        lines.append("")

        rationales = [i["proposed_kind_rationale"] for i in items if i["proposed_kind_rationale"]]
        if rationales:
            lines.append("**Sample rationale:**")
            lines.append(f"> {rationales[0][:400]}")
            lines.append("")

        transformations = [i["transformation"] for i in items if i["transformation"]]
        if transformations:
            lines.append("**Sample transformation descriptions:**")
            for t in transformations[:3]:
                lines.append(f"- {t[:120]}")
            lines.append("")

        lines.append(
            "**Review action:** [ ] promote to controlled  "
            "[ ] reject → map to canonical  [ ] keep as proposed"
        )
        lines.append("")

    return "\n".join(lines) + "\n"


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    total_enrichments = conn.execute("SELECT COUNT(*) FROM enrichment").fetchone()[0]
    records = load_proposed(conn)
    conn.close()

    groups = build_groups(records)
    md = write_markdown(groups, total_enrichments)
    OUT_MD.write_text(md)

    print(f"Total enrichments : {total_enrichments}")
    print(f"Proposed records  : {len(records)}")
    print(f"Distinct terms    : {len(groups)}")
    print()
    for term, items in groups.items():
        print(f"  {len(items):4d}  {term}")
    print()
    print(f"Wrote {OUT_MD}")


if __name__ == "__main__":
    main()
