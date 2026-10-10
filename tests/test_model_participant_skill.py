# tests/test_model_participant_skill.py
"""
apply_signature.py (model-participant skill) against a throwaway enrichment DB:
refuses unvetted types, dry-runs by default, and on --commit writes an
enrichment_history snapshot before updating the row.
"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
_ENRICHMENT_DIR = str(ROOT / "enrichment")
if _ENRICHMENT_DIR not in sys.path:
    sys.path.insert(0, _ENRICHMENT_DIR)

import enrichment_service as svc  # noqa: E402


def _load_script():
    path = ROOT / ".claude" / "skills" / "model-participant" / "apply_signature.py"
    spec = importlib.util.spec_from_file_location("apply_signature", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _db_with_row(tmp_path, monkeypatch, sig) -> int:
    monkeypatch.setattr(svc, "ENRICHMENT_DB_PATH", tmp_path / "enr.db")
    svc.init_enrichment_schema()
    conn = svc.get_enrichment_db()
    conn.execute("INSERT INTO enrichment (cluster_label, status, process_signature) VALUES ('gauge', 'proposed', ?)",
                 (json.dumps(sig),))
    conn.commit()
    rid = conn.execute("SELECT id FROM enrichment").fetchone()[0]
    conn.close()
    return rid


def _run(mod, monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["apply_signature.py", *argv])
    return mod.main()


def _state(rid):
    conn = svc.get_enrichment_db()
    sig = json.loads(conn.execute("SELECT process_signature FROM enrichment WHERE id=?", (rid,)).fetchone()[0])
    hist = conn.execute("SELECT trigger, snapshot_json FROM enrichment_history WHERE enrichment_id=?", (rid,)).fetchall()
    conn.close()
    return sig, hist


def test_refuses_unvetted_dry_runs_then_commits_with_history(tmp_path, monkeypatch):
    old = {"inputs": [{"type": "PhysicalQuantityValue"}], "outputs": [{"type": "LocalIndication"}]}
    rid = _db_with_row(tmp_path, monkeypatch, old)
    mod = _load_script()

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"inputs": [{"type": "SteelPipe"}], "outputs": []}))
    assert _run(mod, monkeypatch, [str(rid), str(bad), "--commit"]) == 1
    assert _state(rid) == (old, [])

    good_sig = {"inputs": [{"type": "PortionOfFluid"}], "outputs": [{"type": "VisualIndication"}]}
    good = tmp_path / "good.json"
    good.write_text(json.dumps(good_sig))
    assert _run(mod, monkeypatch, [str(rid), str(good)]) == 0
    assert _state(rid) == (old, []), "dry run must not write"

    assert _run(mod, monkeypatch, [str(rid), str(good), "--commit"]) == 0
    sig, hist = _state(rid)
    assert sig == good_sig
    assert len(hist) == 1 and hist[0][0] == "model_participant_skill"
    assert "PhysicalQuantityValue" in hist[0][1], "snapshot must hold the previous signature"
