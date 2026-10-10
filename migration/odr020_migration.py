#!/usr/bin/env python3
"""
ODR-020 migration — complete the ODR-010 participant-anchoring migration for the
25 legacy `auto_signature` fillers (13 Process-typed, 12 Quality-typed).

REVIEWABLE DRAFT. Dry-run by default. Nothing is written unless you pass --commit.
No OWL is regenerated. No deployed files are touched. See:
  docs/ontology-decisions/ODR-020-legacy-filler-migration.md
  docs/ontology-decisions/ODR-020-appendix-A-disposition.md

What it does (in one transaction, snapshotting to enrichment_history first):
  1. Drops the 24 inadmissible participant fillers from every enrichment
     process_signature (all offenders EXCEPT `Flame`, which is retained).
  2. Retypes auxiliary_class:  ElectricalCurrent: Process -> Quality;
     Flame: Process -> MaterialEntity  (Flame's restriction stays, now valid).
  3. Adds `bearer_of some <Quality>` axioms (as custom_axioms turtle blocks) on
     the equipment rows whose signature encoded a power/force/load characteristic.
  4. Marks every touched entry `fol_stale` (via divergence_flags) so the stale
     FOL/semiformal text is regenerated/reviewed in a separate future pass.
  5. (Optional, --enable-merge) reparents the 13 truly-empty process classes to
     their ProcessKind (ODR-009). OFF by default: ProcessKind IRIs must be
     confirmed first, and ElectricalConductionProcess has a conflicting tk.
  6. Verifies: 0 remaining offender restrictions; reports the residual ODR-010
     gap (EnergyPortion family etc., out of scope); prints the reasoner check.

Idempotent: re-running makes no further changes once an entry is migrated.

Usage:
  python migration/odr020_migration.py                 # dry-run (default)
  python migration/odr020_migration.py --report        # dry-run + full per-process report
  python migration/odr020_migration.py --commit         # APPLY (requires human approval)
  python migration/odr020_migration.py --commit --enable-merge --optional-struct-qualities
"""
from __future__ import annotations
import argparse, json, re, sqlite3, sys, datetime
from pathlib import Path

DB_DEFAULT = str(Path(__file__).resolve().parent.parent / "data" / "enrichment.db")
STATUSES = ("validated", "exported")           # matches generate_combined_turtle()
TRIGGER = "odr020_migration"
BEARER_OF_IRI = "bfo:BFO_0000196"              # 'bearer of'

# ── The 25 offenders ─────────────────────────────────────────────────────────
PROC = ["DisturbanceSource","ElectricalCurrent","ElectricalCurrentFlow","ElectromagneticRadiation",
        "Flame","KineticMotion","MechanicalMotion","MechanicalMovement","MechanicalRotation",
        "MechanicalWork","PhysicalPhenomenon","RotationalMotion","SuppressedDisturbance"]
QUAL = ["ACElectricalPower","ElectricalPower","MechanicalDisplacement","MechanicalForce","MechanicalLoad",
        "MechanicalPower","PressureField","StructuralDisplacement","StructuralForce","Temperature",
        "WeightOnBit","WellborePressure"]
OFFENDERS = set(PROC + QUAL)

# ── Dispositions (from ODR-020 Appendix A, human-finalized 2026-07-10) ────────
# Flame retype is DEFERRED (ODR-020 debt-(g), human decision 2026-07-12): the target
# 'MaterialEntity' is not in the auxiliary_class.bfo_category CHECK enum, and the correct
# concrete BFO category for a flame is a contested ontological question. Flame emits 0
# restrictions today (ignitor is 'proposed'), so RETYPE is left empty (aux retypes: 0).
# Flame stays in RETAIN (kept/undropped on IgnitionProcess); resolve before ignitor promotion.
RETAIN = {"Flame"}                              # kept in signatures (undropped); retype deferred (debt-(g))
DROP = OFFENDERS - RETAIN                        # 24 fillers dropped from signatures
RETYPE: dict = {}                               # Flame retype DEFERRED (debt-(g)); aux retypes: 0

# Collision resolution (ODR-020 Task 2): these auxiliary_class stubs are SUPERSEDED by curated
# Quality classes now declared in copi-vocab (COPI_0000383/384/385). The stubs are DELETED so
# they cannot re-emit as separate readable-name classes; bearer_of references the vocab IRI.
DEACTIVATE_STUBS = {
    "ElectricalCurrent": "COPI_0000383",   # copi-vocab quality (was Process-typed stub)
    "MechanicalForce":   "COPI_0000384",   # copi-vocab quality (was Quality-typed stub)
    "MechanicalLoad":    "COPI_0000385",   # copi-vocab quality (was Quality-typed stub)
}

# filler -> bearer_of target as the NUMERIC vocab IRI local name. Referencing the numeric IRI
# directly means NO readable-name stub is created, so nothing duplicates into copi-enriched and
# NO regen strip-range change is required (COPI_0000383-385 are outside the 001-060 strip range).
BEARER = {
    "ElectricalPower":   "COPI_0000058",   # existing vocab quality
    "MechanicalPower":   "COPI_0000059",   # existing vocab quality
    "ACElectricalPower": "COPI_0000058",   # reuse 0058 (A.4 — no new class)
    "ElectricalCurrent": "COPI_0000383",   # new vocab quality (declared this prerequisite session)
    "MechanicalForce":   "COPI_0000384",   # new vocab quality
    "MechanicalLoad":    "COPI_0000385",   # new vocab quality
}
OPTIONAL_STRUCT = {"StructuralForce": "StructuralForce", "StructuralDisplacement": "StructuralDisplacement"}
# Dropped, NO bearer_of — measured via the sensor's MeasurementICE 'describes' pattern:
MEASURE = {"Temperature","PressureField","MechanicalDisplacement","WeightOnBit","WellborePressure"}

# 13 truly-empty process classes -> ProcessKind (transformation_kind).  UNCONFIRMED IRIs.
PROCESSKIND_MAP = {
    "PowerTransmissionProcess":            "mechanical_power_transmission",
    "ElectricalPowerTransformationProcess":"electrical_power_conversion",
    "CurrentInterruptionByFusing":         "electrical_power_conversion",
    "DampingProcess":                      "mechanical_power_transmission",
    "ElectricalCircuitControlProcess":     "flow_direction_control",
    "ElectricalConnectionProcess":         "electrical_power_conversion",
    "ElectricalCurrentInterruptionProcess":"flow_isolation",
    "ForceTransmissionProcess":            "mechanical_power_transmission",
    "MovementCompensationProcess":         "mechanical_energy_absorption",
    "RotationalEnergyTransferProcess":     "mechanical_power_transmission",
    "ThermalExpansionAccommodationProcess":"mechanical_force_accommodation",
    "UninterruptedPowerSupplyProcess":     "electrical_power_conversion",
    "ElectricalConductionProcess":         "electrical_power_transmission",  # Task 4c: conflict resolved
}
MERGE_CONFLICTS: set = set()   # ElectricalConductionProcess conflict resolved 2026-07-11 (Task 4c)

# Task 4c (human decision): 'electrical connection' was mislabeled transformation_kind
# 'electrical_power_conversion' though its own rationale says "conduction rather than conversion".
# Corrected to 'electrical_power_transmission' (matching its sibling 'switch contact'), so both
# equipment of ElectricalConductionProcess agree and the class can merge.
TK_FIX = {"electrical connection": "electrical_power_transmission"}

# ── helpers ──────────────────────────────────────────────────────────────────
def pc(s: str) -> str:
    if not s: return s
    if re.match(r"^[A-Z][A-Za-z0-9]+$", s): return s
    return "".join(w.capitalize() for w in re.split(r"[\s_\-]+", s.strip()))

def now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")

def bearer_turtle(quality_name: str) -> str:
    return (f"rdfs:subClassOf [ rdf:type owl:Restriction ; "
            f"owl:onProperty {BEARER_OF_IRI} ; owl:someValuesFrom :{quality_name} ]")

def load_json(v, default):
    if not v: return default
    try: return json.loads(v)
    except Exception: return default

# ── core ─────────────────────────────────────────────────────────────────────
def plan(conn: sqlite3.Connection, include_struct: bool) -> dict:
    """Compute (but do not apply) all per-row changes. Returns a plan dict."""
    bearer = dict(BEARER)
    if include_struct:
        bearer.update(OPTIONAL_STRUCT)

    rows = conn.execute(
        "SELECT id, cluster_label, process_name, process_signature, custom_axioms, "
        "divergence_flags FROM enrichment "
        "WHERE status IN (?, ?) AND process_signature IS NOT NULL AND process_signature != ''",
        STATUSES,
    ).fetchall()

    entry_changes = []          # list of dicts describing each touched enrichment row
    dropped_total = 0
    for r in rows:
        sig = load_json(r["process_signature"], {})
        changed = False
        dropped_here = []
        for slot in ("inputs", "outputs"):
            kept = []
            for item in (sig.get(slot) or []):
                t = pc(item.get("type", ""))
                if t in DROP:
                    dropped_here.append((slot, t)); changed = True
                else:
                    kept.append(item)
            if slot in sig:
                sig[slot] = kept
        # Task 4c: correct mislabeled transformation_kind (ElectricalConductionProcess conflict)
        if r["cluster_label"] in TK_FIX and sig.get("transformation_kind") != TK_FIX[r["cluster_label"]]:
            sig["transformation_kind"] = TK_FIX[r["cluster_label"]]; changed = True
        # bearer_of additions for the power/force/load qualities dropped here
        cust = load_json(r["custom_axioms"], [])
        existing_turtle = {(c.get("turtle") or "").strip() for c in cust if isinstance(c, dict)}
        add_bearer = []
        for _slot, t in dropped_here:
            q = bearer.get(t)
            if q:
                tb = bearer_turtle(q)
                if tb not in existing_turtle and tb not in {a["turtle"] for a in add_bearer}:
                    add_bearer.append({"turtle": tb, "source": "odr020"})
        # fol_stale marker
        flags = load_json(r["divergence_flags"], [])
        has_stale = any(isinstance(f, dict) and f.get("type") == "fol_stale" for f in flags)
        needs_stale = changed and not has_stale

        if changed or add_bearer or needs_stale:
            dropped_total += len(dropped_here)
            entry_changes.append({
                "id": r["id"], "label": r["cluster_label"], "process": r["process_name"],
                "dropped": dropped_here, "new_signature": sig,
                "add_bearer": add_bearer, "needs_stale": needs_stale,
                "already_stale": has_stale,
            })

    # auxiliary_class retypes
    aux_changes = []
    for name, new_cat in RETYPE.items():
        row = conn.execute("SELECT bfo_category FROM auxiliary_class WHERE name = ?", (name,)).fetchone()
        if row and row["bfo_category"] != new_cat:
            aux_changes.append({"name": name, "old": row["bfo_category"], "new": new_cat})

    # superseded stubs to delete (replaced by curated copi-vocab classes)
    deactivate = []
    for name, iri in DEACTIVATE_STUBS.items():
        row = conn.execute("SELECT bfo_category FROM auxiliary_class WHERE name = ?", (name,)).fetchone()
        if row:
            deactivate.append({"name": name, "was": row["bfo_category"], "vocab_iri": iri})

    # merges (default off; still computed for reporting)
    merges, merge_skips = [], []
    for proc, tk in PROCESSKIND_MAP.items():
        merges.append({"process": proc, "transformation_kind": tk,
                       "target_processkind": pc(tk) + "Process"})   # UNCONFIRMED name
    for proc in MERGE_CONFLICTS:
        merge_skips.append({"process": proc, "reason": "conflicting transformation_kind"})

    return {"entries": entry_changes, "dropped_total": dropped_total,
            "aux": aux_changes, "deactivate": deactivate,
            "merges": merges, "merge_skips": merge_skips}


def snapshot(conn, enrichment_id, fields: dict):
    conn.execute(
        "INSERT INTO enrichment_history (enrichment_id, snapshot_at, trigger, snapshot_json) "
        "VALUES (?, ?, ?, ?)",
        (enrichment_id, now(), TRIGGER, json.dumps(fields)),
    )


def apply(conn, p: dict, enable_merge: bool):
    for e in p["entries"]:
        cur = conn.execute("SELECT process_signature, custom_axioms, divergence_flags "
                           "FROM enrichment WHERE id = ?", (e["id"],)).fetchone()
        snapshot(conn, e["id"], {
            "process_signature": cur["process_signature"],
            "custom_axioms": cur["custom_axioms"],
            "divergence_flags": cur["divergence_flags"],
            "note": "pre-odr020 participant migration",
        })
        cust = load_json(cur["custom_axioms"], []) + e["add_bearer"]
        flags = load_json(cur["divergence_flags"], [])
        if e["needs_stale"]:
            flags.append({"type": "fol_stale", "reason": "odr020 participant migration", "at": now()})
        conn.execute(
            "UPDATE enrichment SET process_signature = ?, custom_axioms = ?, "
            "divergence_flags = ?, updated_at = ? WHERE id = ?",
            (json.dumps(e["new_signature"]), json.dumps(cust), json.dumps(flags), now(), e["id"]),
        )
    for a in p["aux"]:
        conn.execute("UPDATE auxiliary_class SET bfo_category = ? WHERE name = ?", (a["new"], a["name"]))
    for d in p["deactivate"]:
        conn.execute("DELETE FROM auxiliary_class WHERE name = ?", (d["name"],))

    if enable_merge:
        raise SystemExit(
            "REFUSING to auto-merge: the per-transformation_kind ProcessKind classes DO NOT EXIST "
            "in copi-vocab/copi-core/copi-enriched (confirmed 2026-07-11). Only the 9 ODR-009 "
            "operation classes (COPI_0000001-024) exist, with no declared transformation_kind->class "
            "mapping. Merges are BLOCKED on ODR-009 ProcessKind implementation. See ODR-020 §4 / A.3.1."
        )


def verify(conn) -> dict:
    """Post-state check: remaining offender restrictions (via signatures) must be 0."""
    rows = conn.execute(
        "SELECT process_signature FROM enrichment WHERE status IN (?, ?) "
        "AND process_signature IS NOT NULL AND process_signature != ''", STATUSES).fetchall()
    remaining, residual = 0, 0
    RESID = {"EnergyPortion","ThermalEnergyPortion","MechanicalEnergyPortion","ElectricalEnergyPortion",
             "InformationBearingArtifact","ProcessVariable"}
    for r in rows:
        sig = load_json(r["process_signature"], {})
        for slot in ("inputs", "outputs"):
            for item in (sig.get(slot) or []):
                t = pc(item.get("type", ""))
                if t in DROP:  remaining += 1
                if t in RESID: residual += 1
    return {"remaining_offender_participants": remaining, "residual_odr010_gap": residual}


def main():
    ap = argparse.ArgumentParser(description="ODR-020 legacy-filler migration (dry-run by default)")
    ap.add_argument("--db", default=DB_DEFAULT)
    ap.add_argument("--commit", action="store_true", help="APPLY changes (default: dry-run)")
    ap.add_argument("--enable-merge", action="store_true", help="attempt empty-process merges (guarded/off)")
    ap.add_argument("--optional-struct-qualities", action="store_true",
                    help="also add bearer_of for StructuralForce/StructuralDisplacement (A.4 optional)")
    ap.add_argument("--report", action="store_true", help="print full per-entry plan")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    p = plan(conn, include_struct=args.optional_struct_qualities)
    print(f"ODR-020 migration plan ({'COMMIT' if args.commit else 'DRY-RUN'}) on {args.db}")
    print(f"  enrichment rows touched:      {len(p['entries'])}")
    print(f"  participant restrictions dropped: {p['dropped_total']}")
    print(f"  bearer_of axioms to add:      {sum(len(e['add_bearer']) for e in p['entries'])}")
    print(f"  fol_stale markers to set:     {sum(1 for e in p['entries'] if e['needs_stale'])}")
    print(f"  auxiliary_class retypes:      {[(a['name'], a['old']+'->'+a['new']) for a in p['aux']]}")
    print(f"  auxiliary_class stubs DELETED (superseded by vocab): {[(d['name'], d['was']+'->'+d['vocab_iri']) for d in p['deactivate']]}")
    print(f"  merge candidates (BLOCKED — ProcessKind classes absent): {len(p['merges'])}   skipped(conflict): {[m['process'] for m in p['merge_skips']]}")
    if args.report:
        for e in p["entries"]:
            print(f"    #{e['id']:>3} {e['label']:<32} drop={[t for _,t in e['dropped']]} "
                  f"bearer={[a['turtle'].split(':')[-1].rstrip(' ]') for a in e['add_bearer']]}")

    if args.commit:
        try:
            apply(conn, p, args.enable_merge)
            conn.commit()
            print("  COMMITTED.")
        except Exception as ex:
            conn.rollback()
            print(f"  ROLLED BACK: {ex}")
            sys.exit(1)
    else:
        print("  (dry-run — nothing written; re-run with --commit after human approval)")

    v = verify(conn)   # projected in dry-run reflects current DB; real after --commit
    print(f"VERIFY (current DB state): remaining offender participants = {v['remaining_offender_participants']} "
          f"(target 0 post-commit); residual ODR-010 gap (out of scope) = {v['residual_odr010_gap']}")
    conn.close()

    print("\nPOST-COMMIT REASONER CHECK (run after --commit):")
    print("  1) regenerate: python -c \"import sys; sys.path.insert(0,'enrichment'); "
          "from enrichment_service import generate_combined_turtle as g; open('/tmp/odr020.ttl','w').write(g())\"")
    print("  2) reason the UN-STRIPPED TTL (merge copi-core+copi-vocab) with HermiT/ELK; expect 0 unsatisfiable classes.")
    print("     (../copi guard-01-no-unsat must pass on the un-stripped output.)")
    print("  3) only then retire the strip step in scripts/regen_enriched_owl.py (ODR-020 Decision 6).")


if __name__ == "__main__":
    main()
