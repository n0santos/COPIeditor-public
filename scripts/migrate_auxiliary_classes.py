"""
One-time migration: populate auxiliary_class from existing process_signature JSONs.
Run once from the project root with .venv active:
    python -m scripts.migrate_auxiliary_classes
"""
import json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "enrichment"))
from enrichment_service import get_enrichment_db, init_enrichment_schema, _to_pascal_case

def _extract_participant_names(sig: dict) -> list[str]:
    names = []
    for item in sig.get("inputs", []) + sig.get("outputs", []):
        raw = item.get("type", "").strip()
        if raw:
            names.append(_to_pascal_case(raw))
    return [n for n in names if n and n != "Unknown"]

def main():
    init_enrichment_schema()
    conn = get_enrichment_db()
    rows = conn.execute(
        "SELECT process_signature FROM enrichment WHERE process_signature IS NOT NULL AND process_signature != '{}'"
    ).fetchall()

    inserted = 0
    skipped = 0
    for row in rows:
        try:
            sig = json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            continue
        for name in _extract_participant_names(sig):
            cur = conn.execute(
                "INSERT OR IGNORE INTO auxiliary_class (name, source) VALUES (?, 'auto_signature')",
                (name,)
            )
            if cur.rowcount:
                inserted += 1
            else:
                skipped += 1

    conn.commit()
    conn.close()
    print(f"Done. {inserted} new entries inserted, {skipped} already existed.")

if __name__ == "__main__":
    main()
