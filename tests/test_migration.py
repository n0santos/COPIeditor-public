import sqlite3
import sys
import os
from pathlib import Path
import pytest

# enrichment_service.py uses bare `from prompts import ...` which resolves
# relative to the enrichment/ directory.  Add it to sys.path so the import
# works when pytest runs from the project root.
_ENRICHMENT_DIR = str(Path(__file__).parent.parent / "enrichment")
if _ENRICHMENT_DIR not in sys.path:
    sys.path.insert(0, _ENRICHMENT_DIR)


def test_attribution_columns_created(tmp_path, monkeypatch):
    db_path = tmp_path / "test_enrichment.db"

    # Re-import to get a clean module state
    import enrichment.enrichment_service as svc
    import importlib; importlib.reload(svc)

    # Redirect the module-level DB path to our temp database
    monkeypatch.setattr(svc, "ENRICHMENT_DB_PATH", db_path)

    svc.init_enrichment_schema()
    conn = sqlite3.connect(str(db_path))
    cols = {row[1] for row in conn.execute("PRAGMA table_info(enrichment)").fetchall()}
    conn.close()

    assert "last_edited_by" in cols
    assert "last_edited_at" in cols
    assert "second_reviewer" in cols
    assert "second_reviewer_notes" in cols
