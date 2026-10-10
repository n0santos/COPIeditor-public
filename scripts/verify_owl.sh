#!/usr/bin/env bash
# scripts/verify_owl.sh
#
# Generates the COPI combined OWL (or Nível 1 enriched OWL), reasons it with HermiT
# via ROBOT, and verifies structural entailments mandated by the ODRs.
#
# Usage:
#   ./scripts/verify_owl.sh [--skip-assembly-check] [--nivel1] [--skip-oops]
#
#   --skip-assembly-check  Suppress exit code 3 for the ControlValve⊑Assembly
#                          check (use while serializer fix is pending; the check
#                          still runs and its result is printed).
#   --nivel1               Generate Nível 1 enriched OWL (4 clusters) instead of
#                          the full combined OWL; runs classification checks in
#                          place of the combined-OWL ODR guards.
#   --skip-oops            Skip the OOPS! pitfall scan (use when offline or the
#                          service is unreachable).
#
# Exit codes:
#   0  — all checks passed (or only the suppressed assembly check failed)
#   1  — prerequisite failure (Java absent, ROBOT download failed, TTL generation failed)
#   2  — inconsistent ontology (unsatisfiable class found by HermiT)
#   3  — missing entailment (expected subclass relation not found in reasoned graph)
#   4  — ODR-013 regression: Valve ⊑ iof:Assembly was inferred (forbidden)
#   6  — disjointness axiom count mismatch between pre-publication Turtle and the
#        published copi-enriched.owl on disk (#26/#27)
#   7  — duplicate definition: a numeric COPI_* IRI carries axiom-bearing triples
#        in more than one component file (copi-core.ttl / copi-vocab.ttl /
#        copi-enriched.owl)
#   8  — differentia coverage: a differentia conjunct absent from the generated OWL
#        and not in scripts/differentia-coverage-baseline.txt
#   9  — participant vocabulary: a validated entry names a participant type that is
#        not copi-core/copi-vocab vocabulary, a BFO/IOF-Core redirect, or a validated
#        equipment class, and is not in scripts/participant-vocabulary-baseline.txt
#  10  — COPI-Core anchoring: a validated process reaches no COPI-Core operation without
#        a core_operation_gap, or its transformation_kind disagrees with the anchor, and
#        the finding is not in scripts/core-anchoring-baseline.txt
#
# Requirements:
#   - Java 11+ on PATH
#   - Internet access for first run (ROBOT JAR download); or pre-place the JAR at
#     .robot/robot-${ROBOT_VERSION}.jar
#   - Python venv at .venv/ (project-standard; used to generate the OWL)

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────

readonly ROBOT_VERSION="1.9.5"

readonly E_OK=0
readonly E_PREREQ=1
readonly E_INCONSISTENT=2
readonly E_ENTAILMENT=3
readonly E_REGRESSION=4
readonly E_STUB_IRI=5
readonly E_DISJOINT_MISSING=6
readonly E_DUPLICATE_DEFINITION=7
readonly E_DIFFERENTIA_COVERAGE=8
readonly E_PARTICIPANT_VOCABULARY=9
readonly E_CORE_ANCHORING=10

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ROBOT_DIR="$REPO_ROOT/.robot"
ROBOT_JAR="$ROBOT_DIR/robot-${ROBOT_VERSION}.jar"
ROBOT_URL="https://github.com/ontodev/robot/releases/download/v${ROBOT_VERSION}/robot.jar"
ONTOLOGIES_DIR="$REPO_ROOT/enrichment/ontologies"
COPI_CONTEXT_DIR="$ONTOLOGIES_DIR/copi-context"
SPARQL_DIR="$SCRIPT_DIR/sparql"
PYTHON="$REPO_ROOT/.venv/bin/python"

SKIP_ASSEMBLY_CHECK=0
NIVEL1_MODE=0
SKIP_OOPS=0
SKIP_IRI_GATE=0
for arg in "$@"; do
  [[ "$arg" == "--skip-assembly-check" ]] && SKIP_ASSEMBLY_CHECK=1
  [[ "$arg" == "--nivel1" ]] && NIVEL1_MODE=1
  [[ "$arg" == "--skip-oops" ]] && SKIP_OOPS=1
  [[ "$arg" == "--skip-iri-gate" ]] && SKIP_IRI_GATE=1
done

IRI_BASELINE="$SCRIPT_DIR/stub-iri-baseline.txt"
IRI_MAP="$REPO_ROOT/enrichment/ontologies/copi-context/copi-iri-map.tsv"

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

# ── Helpers ───────────────────────────────────────────────────────────────────

log()  { echo "[verify_owl] $*"; }
pass() { echo "[verify_owl] PASS  $*"; }
fail() { echo "[verify_owl] FAIL  $*" >&2; }
warn() { echo "[verify_owl] WARN  $*"; }

robot() { java -jar "$ROBOT_JAR" "$@"; }

# ── Step 0: Prerequisites ─────────────────────────────────────────────────────

log "Checking prerequisites..."

if ! command -v java &>/dev/null; then
  fail "Java not found on PATH. Install Java 11+ and retry."
  exit $E_PREREQ
fi

JAVA_VER=$(java -version 2>&1 | awk -F '"' '/version/ {print $2}' | cut -d. -f1)
if [[ "$JAVA_VER" -lt 11 ]]; then
  fail "Java 11+ required; found version $JAVA_VER."
  exit $E_PREREQ
fi

if [[ ! -f "$ROBOT_JAR" ]]; then
  log "ROBOT ${ROBOT_VERSION} not found; downloading from GitHub..."
  mkdir -p "$ROBOT_DIR"
  if ! curl -sSL "$ROBOT_URL" -o "$ROBOT_JAR"; then
    fail "Failed to download ROBOT from $ROBOT_URL."
    exit $E_PREREQ
  fi
  log "Downloaded ROBOT ${ROBOT_VERSION} to $ROBOT_JAR"
fi

# ── Step 1: Generate OWL/Turtle ───────────────────────────────────────────────

COPI_TTL="$WORK_DIR/copi.ttl"

if [[ "$NIVEL1_MODE" -eq 1 ]]; then
  log "Generating Nível 1 enriched Turtle from Design-B map..."
  if ! "$PYTHON" - "$COPI_TTL" <<'PYEOF'
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "enrichment"))
from enrichment_service import generate_nivel1_enriched
out_path = sys.argv[1]
ttl = generate_nivel1_enriched()
pathlib.Path(out_path).write_text(ttl, encoding="utf-8")
print(f"Generated {len(ttl):,} bytes → {out_path}")
PYEOF
  then
    fail "Nível 1 Turtle generation failed."
    exit $E_PREREQ
  fi
else
  log "Generating combined OWL from enrichment DB (mirroring full publish transform)..."
  if ! "$PYTHON" - "$COPI_TTL" "$REPO_ROOT" <<'PYEOF'
import sys, pathlib
out_path, repo_root = sys.argv[1], pathlib.Path(sys.argv[2])
sys.path.insert(0, str(repo_root / "enrichment"))
sys.path.insert(0, str(repo_root / "scripts"))
from enrichment_service import generate_combined_turtle
from regen_enriched_owl import (
    _load_iri_map, remap_graph,
    remove_protected_subject_triples, assert_no_information_bearing_artifact,
    assert_all_classes_anchored, assert_no_unintended_function_subsumption,
    remove_upstream_declarations,
)
from rdflib import Graph

ttl = generate_combined_turtle()
if not ttl.strip() or ttl.startswith("# No validated"):
    print("ERROR: No validated enrichments found.", file=sys.stderr)
    sys.exit(1)

# Reason the SAME closure that ships, so the entailment checks below (which target
# numeric COPI IRIs) are meaningful. This mirrors regen_enriched_owl.py's pipeline:
#   1. remap readable-name IRIs -> numeric COPI IRIs (copi-iri-map.tsv), so
#      copi:COPI_0000087 etc. exist for the SPARQL checks;
#   2. drop COPI_0000001-0000060 subject triples — these base classes are declared
#      in copi-core.ttl (merged in the reason step); re-declaring conflicts;
#   3. assert InformationBearingArtifact is absent (ODR-021, resolved 2026-08-08). The
#      former I/O strip is retired: every participant restriction now ships un-stripped.
g = Graph()
g.parse(data=ttl, format="turtle")
g = remap_graph(g, _load_iri_map())
g, _removed = remove_protected_subject_triples(g)
g = assert_all_classes_anchored(g)
g = assert_no_unintended_function_subsumption(g)
g, _up = remove_upstream_declarations(g)
g = assert_no_information_bearing_artifact(g)
g.serialize(destination=out_path, format="turtle")
print(f"Generated {len(g):,} triples (remapped + base-stripped) → {out_path}")
PYEOF
  then
    fail "OWL/Turtle generation failed."
    exit $E_PREREQ
  fi
fi

# ── Step 1b: Numeric IRI gate (ODR-022) ───────────────────────────────────────
#
# Policy: nothing deploys with a readable-name class IRI. Every class in the
# published artifact carries a numeric COPI_* IRI.
#
# Enforced as a ratchet, not a cliff: scripts/stub-iri-baseline.txt grandfathers
# the 427 stubs that shipped before this gate existed. Any readable-name class
# NOT in the baseline fails the build immediately, so the count can only go down.
# When the baseline is empty the gate enforces zero unconditionally.
#
# --skip-iri-gate is for local iteration only. CI and the publish path must not
# pass it.

if [[ "$SKIP_IRI_GATE" -eq 0 ]]; then
  log "Numeric IRI gate: scanning for readable-name class IRIs..."

  IRI_GATE_REPORT="$WORK_DIR/iri_gate.txt"
  if "$PYTHON" - "$COPI_TTL" "$IRI_BASELINE" "$IRI_GATE_REPORT" "$IRI_MAP" <<'PYEOF'
import re, sys, pathlib

ttl_path, baseline_path, report_path, map_path = sys.argv[1:5]
NS_ = "https://www.inf.ufrgs.br/ontologies/copi/"

# Parse the graph rather than pattern-matching the serialization. rdflib binds the copi
# namespace to the EMPTY prefix (":Chamber", not "copi:Chamber"), so a regex anchored on
# "copi:" silently reported zero stubs while 15 were present — a gate that passes when it
# should fail is worse than no gate. Parsing is prefix-agnostic by construction.
from rdflib import Graph, RDF, OWL, URIRef

_g = Graph()
_g.parse(ttl_path, format="turtle")
declared = {
    str(s_)[len(NS_):]
    for s_ in _g.subjects(RDF.type, OWL.Class)
    if isinstance(s_, URIRef) and str(s_).startswith(NS_)
}

# copi-iri-map.tsv is the authoritative readable-name -> numeric registry. A readable
# name reaching the output means it has no row here, so read the map to report the next
# free number and emit paste-ready rows.
mapped, allocated = set(), set()
mp = pathlib.Path(map_path)
if mp.exists():
    for line in mp.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        cols = line.split("\t")
        if len(cols) < 2 or cols[0] == "old_iri":
            continue
        mapped.add(cols[0].rsplit("/", 1)[-1])
        m = re.search(r"COPI_(\d+)", cols[1])
        if m:
            allocated.add(int(m.group(1)))
next_free = (max(allocated) + 1) if allocated else 1

stubs = {n for n in declared if not re.fullmatch(r'COPI_\d+', n)}

baseline = set()
bp = pathlib.Path(baseline_path)
if bp.exists():
    baseline = {
        line.strip() for line in bp.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }

new = sorted(stubs - baseline)
retired = sorted(baseline - stubs)

lines = []
if new:
    lines.append(
        f"UNGRANDFATHERED readable-name classes ({len(new)}) — present in the "
        f"ontology but absent from the baseline.")
    lines.append(
        "  Either a new stub shipped, or the baseline was pruned before the stub")
    lines.append(
        "  was actually removed (remove from the ontology first, then prune).")
    lines.append("")
    lines.append(
        "  Allocate by adding rows to copi-iri-map.tsv — it is the authoritative")
    lines.append(
        f"  readable-name -> numeric registry. Next free: COPI_{next_free:07d}.")
    lines.append("  Ready to paste:")
    for i, n in enumerate(new):
        lines.append(f"\t{NS_}{n}\t{NS_}COPI_{next_free + i:07d}")
    lines.append("")
    lines.append("  Offending names:")
    lines += [f"    {n}" for n in new]
    already = sorted(set(new) & mapped)
    if already:
        lines.append(
            "  NOTE: these already have a copi-iri-map.tsv row but still reached the")
        lines.append(
            "  output — the remap step did not fire. Check the key matches the")
        lines.append("  emitted local-name exactly:")
        lines += [f"    {n}" for n in already]
if retired:
    lines.append(f"RETIRED since baseline ({len(retired)}) — remove from baseline file:")
    lines += [f"    {n}" for n in retired[:20]]
    if len(retired) > 20:
        lines.append(f"    ... and {len(retired) - 20} more")
lines.append(f"SUMMARY stubs={len(stubs)} baseline={len(baseline)} new={len(new)}")
pathlib.Path(report_path).write_text("\n".join(lines) + "\n", encoding="utf-8")

sys.exit(1 if new else 0)
PYEOF
  then
    IRI_STUBS=$(awk '/^SUMMARY/ {print $2}' "$IRI_GATE_REPORT" | cut -d= -f2)
    IRI_RETIRED=$(awk '/^RETIRED/ {print $3}' "$IRI_GATE_REPORT" | tr -d '()')
    if [[ "$IRI_STUBS" -eq 0 ]]; then
      pass "Numeric IRI gate — every class carries a numeric COPI_* IRI."
    else
      pass "Numeric IRI gate — no new stubs ($IRI_STUBS grandfathered, ODR-022 backlog)."
      if [[ -n "$IRI_RETIRED" && "$IRI_RETIRED" -gt 0 ]]; then
        warn "$IRI_RETIRED baseline entries retired — prune scripts/stub-iri-baseline.txt."
      fi
    fi
  else
    fail "Numeric IRI gate — readable-name class IRIs not covered by the baseline (ODR-022 §2)."
    cat "$IRI_GATE_REPORT" >&2
    fail "Every deployed class must carry a numeric COPI_* IRI."
    exit $E_STUB_IRI
  fi
fi

# ── Step 1c: Disjointness invariant (#26/#27) ──────────────────────────────────
#
# This script's own Step 1 reasoning graph above is generated by the SAME
# remove_protected_subject_triples() that caused copi-enriched.owl to ship zero
# AllDisjointClasses axioms (#26) — a check sharing a transformation step with the
# thing it verifies cannot catch a defect that step introduces (#44). This gate
# reads the PUBLISHED artifact from disk instead, independent of everything
# computed above in this script.
#
# No ratchet, no baseline file: publishing must not lose axioms, period. Assert
# equality between the count in the pre-publication combined Turtle (upstream,
# known correct) and the count parsed from the actually-published copi-enriched.owl.
# Cheap upstream-coverage check on this script's own $COPI_TTL is printed alongside
# for diagnostic signal, but the disk comparison below is the actual gate.

if [[ "$NIVEL1_MODE" -eq 0 ]]; then
  log "Disjointness invariant: pre-publication count vs published artifact on disk..."

  UPSTREAM_DISJOINT=$(grep -c "AllDisjointClasses" "$COPI_TTL" || true)
  log "  (upstream reasoning graph carries $UPSTREAM_DISJOINT AllDisjointClasses — diagnostic only)"

  DISJOINT_REPORT="$WORK_DIR/disjoint_gate.txt"
  if "$PYTHON" - "$REPO_ROOT" "$DISJOINT_REPORT" <<'PYEOF'
import sys, pathlib
repo_root, report_path = pathlib.Path(sys.argv[1]), sys.argv[2]
sys.path.insert(0, str(repo_root / "enrichment"))
from enrichment_service import generate_combined_turtle
from rdflib import Graph, RDF, OWL

pre_pub_ttl = generate_combined_turtle()
pre_g = Graph()
pre_g.parse(data=pre_pub_ttl, format="turtle")
pre_count = len(set(pre_g.subjects(RDF.type, OWL.AllDisjointClasses)))

published_path = repo_root.parent / "copi" / "src" / "ontology" / "components" / "copi-enriched.owl"
lines = []
if not published_path.exists():
    lines.append(f"MISSING published artifact: {published_path}")
    lines.append(f"SUMMARY pre={pre_count} published=0 match=False")
    pathlib.Path(report_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    sys.exit(1)

pub_g = Graph()
pub_g.parse(str(published_path), format="xml")
pub_count = len(set(pub_g.subjects(RDF.type, OWL.AllDisjointClasses)))

match = pre_count == pub_count
lines.append(f"pre-publication combined Turtle: {pre_count} AllDisjointClasses blocks")
lines.append(f"published copi-enriched.owl:      {pub_count} AllDisjointClasses blocks ({published_path})")
lines.append(f"SUMMARY pre={pre_count} published={pub_count} match={match}")
pathlib.Path(report_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
sys.exit(0 if match else 1)
PYEOF
  then
    pass "Disjointness invariant — published artifact matches pre-publication count."
    grep "^pre-publication\|^published" "$DISJOINT_REPORT" || true
  else
    fail "Disjointness invariant — published copi-enriched.owl does not match the pre-publication count (#26/#27)."
    cat "$DISJOINT_REPORT" >&2
    exit $E_DISJOINT_MISSING
  fi
fi

# ── Step 1d: Duplicate-definition gate ──────────────────────────────────────────
#
# A numeric COPI_* IRI must carry its axioms in exactly one component file. The
# published import chain is copi-enriched -> copi-vocab -> copi-core, so if the
# same IRI is axiomatized (anything beyond a bare `rdf:type owl:Class`) in more
# than one of the three, the reasoner loads two competing definitions for it —
# this happened once already for PressureVessel/HeatExchanger (COPI_0000090/92,
# fixed in commit b42a398) and recurred, missed, for Instrument (COPI_0000091).
# This gate makes that class of bug fail the build instead of shipping silently
# (it need not be logically inconsistent to be wrong — see CLAUDE.md).

if [[ "$NIVEL1_MODE" -eq 0 ]]; then
  log "Duplicate-definition gate: scanning component files for competing definitions..."

  DUPDEF_REPORT="$WORK_DIR/dupdef_gate.txt"
  if "$PYTHON" - "$REPO_ROOT" "$DUPDEF_REPORT" <<'PYEOF'
import sys, pathlib
from collections import defaultdict
from rdflib import Graph, RDF, OWL

repo_root, report_path = pathlib.Path(sys.argv[1]), sys.argv[2]
NS = "https://www.inf.ufrgs.br/ontologies/copi/"

files = {
    "copi-core.ttl": repo_root / "enrichment" / "ontologies" / "copi-context" / "copi-core.ttl",
    "copi-vocab.ttl": repo_root / "enrichment" / "ontologies" / "copi-context" / "copi-vocab.ttl",
    "copi-enriched.owl": repo_root.parent / "copi" / "src" / "ontology" / "components" / "copi-enriched.owl",
}

subj_extra_triples = {}
for name, path in files.items():
    if not path.exists():
        subj_extra_triples[name] = {}
        continue
    g = Graph()
    g.parse(str(path), format="xml" if path.suffix == ".owl" else "turtle")
    counts = defaultdict(int)
    for s, p, o in g:
        s_str = str(s)
        if not s_str.startswith(NS + "COPI_"):
            continue
        if p == RDF.type and o == OWL.Class:
            continue  # bare declaration is not a competing axiomatization
        counts[s_str] += 1
    subj_extra_triples[name] = counts

all_iris = set()
for counts in subj_extra_triples.values():
    all_iris |= set(counts.keys())

overlaps = []
for iri in sorted(all_iris):
    present = [name for name, counts in subj_extra_triples.items() if counts.get(iri, 0) > 0]
    if len(present) > 1:
        overlaps.append((iri, present))

lines = []
if overlaps:
    lines.append(
        f"DUPLICATE DEFINITIONS ({len(overlaps)}) — numeric COPI IRIs carrying "
        f"axiom-bearing triples in more than one component file.")
    lines.append(
        "The reasoner merges the full import chain (copi-enriched -> copi-vocab ->")
    lines.append(
        "copi-core), so both definitions load together for each IRI below:")
    lines.append("")
    for iri, present in overlaps:
        lines.append(f"  {iri[len(NS):]}: declared in {', '.join(present)}")
pathlib.Path(report_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
sys.exit(1 if overlaps else 0)
PYEOF
  then
    pass "Duplicate-definition gate — every numeric IRI axiomatized in exactly one component."
  else
    fail "Duplicate-definition gate — numeric IRI(s) carry axioms in more than one component file."
    cat "$DUPDEF_REPORT" >&2
    exit $E_DUPLICATE_DEFINITION
  fi
fi

# ── Step 1e: Differentia coverage gate ────────────────────────────────────────
#
# Step 3 writes differentia_expression as free text, but only the structured
# fields drive OWL generation. A conjunct naming a class that never reaches the
# artifact is shown on the published class page yet absent from the ontology —
# in the worst case the class collapses to a bare `genus + function` axiom that
# is logically indistinguishable from its siblings.
#
# None of the checkers below detects this: HermiT sees a consistent ontology,
# APV sees complete annotations, OOPS!/FOOPS! see no pitfall. Nothing is wrong,
# something is missing — which is exactly the class of defect a gate has to
# carry, because no reasoner will raise it.
#
# Ratchet, like Step 1b: scripts/differentia-coverage-baseline.txt grandfathers
# the conjuncts unrendered when the gate was introduced; anything not in the
# baseline fails. The count can only go down. Do NOT add entries to the baseline
# to get past this gate — ground the conjunct into necessary_parts/qualities, or
# trim the differentia text to match what the artifact actually asserts.

log "Differentia coverage gate: comparing differentia_expression against generated OWL..."

DIFF_COV_REPORT="$WORK_DIR/differentia_coverage.txt"
if "$PYTHON" "$SCRIPT_DIR/check_differentia_coverage.py" > "$DIFF_COV_REPORT" 2>&1; then
  pass "$(tail -n 1 "$DIFF_COV_REPORT")"
else
  fail "Differentia coverage gate — conjunct(s) not covered by the baseline."
  cat "$DIFF_COV_REPORT" >&2
  exit $E_DIFFERENTIA_COVERAGE
fi

# ── Participant vocabulary gate ───────────────────────────────────────────────
# Participant types (process_signature inputs/outputs) are hand-authored copi-vocab
# vocabulary (ODR-022 §2). An LLM-invented type reaches the artifact silently: the
# generator emits `someValuesFrom :<Type>` and allocate_missing_iris() mints it a
# COPI IRI. No reasoner or pitfall scanner flags a class that simply should not
# exist, so this gate does.
#
# Ratchet: scripts/participant-vocabulary-baseline.txt grandfathers the types already
# published when the gate was introduced. Do NOT add lines to get past it — use a real
# copi-vocab type, redirect to BFO / IOF-Core in copi-iri-map.tsv, or add the type to
# copi-vocab.ttl first.

log "Participant vocabulary gate: checking process_signature types against copi-vocab..."

PARTICIPANT_REPORT="$WORK_DIR/participant_vocabulary.txt"
if "$PYTHON" "$SCRIPT_DIR/check_participant_vocabulary.py" > "$PARTICIPANT_REPORT" 2>&1; then
  pass "$(tail -n 1 "$PARTICIPANT_REPORT")"
else
  fail "Participant vocabulary gate — participant type(s) not covered by the baseline."
  cat "$PARTICIPANT_REPORT" >&2
  exit $E_PARTICIPANT_VOCABULARY
fi

# ── COPI-Core anchoring gate ──────────────────────────────────────────────────
# Every equipment process must reach a COPI-Core operation or record why not
# (core_operation_gap), and its transformation_kind must agree with the anchor
# (enrichment/core_operations.py). An unanchored process reasons fine as
# ⊑ PlannedProcess, so no reasoner flags it — it just falls out of COPI-Core's
# category classification. Ratchet over scripts/core-anchoring-baseline.txt.

log "COPI-Core anchoring gate: checking process anchors and transformation_kind agreement..."

ANCHOR_REPORT="$WORK_DIR/core_anchoring.txt"
if "$PYTHON" "$SCRIPT_DIR/check_core_anchoring.py" > "$ANCHOR_REPORT" 2>&1; then
  pass "$(tail -n 1 "$ANCHOR_REPORT")"
else
  fail "COPI-Core anchoring gate — finding(s) not covered by the baseline."
  cat "$ANCHOR_REPORT" >&2
  exit $E_CORE_ANCHORING
fi

# ── Step 2: Write import catalog (maps remote IRIs to local files) ─────────────

log "Writing import catalog..."

cp "$ONTOLOGIES_DIR/IOF-Core.rdf" "$WORK_DIR/IOF-Core.rdf"
cp "$ONTOLOGIES_DIR/bfo-2020.ttl" "$WORK_DIR/bfo-2020.ttl"
cp "$COPI_CONTEXT_DIR/copi-core.ttl" "$WORK_DIR/copi-core.ttl"
cp "$COPI_CONTEXT_DIR/copi-vocab.ttl" "$WORK_DIR/copi-vocab.ttl"

# Map the copi-core / copi-vocab import IRIs so owl:imports resolve to local copies.
COPI_CORE_CATALOG_ENTRY='  <uri name="https://www.inf.ufrgs.br/ontologies/copi/copi-core" uri="copi-core.ttl"/>
  <uri name="https://www.inf.ufrgs.br/ontologies/copi/copi-vocab" uri="copi-vocab.ttl"/>'

CORE_MERGE_INPUT=""
if [[ "$NIVEL1_MODE" -eq 0 ]]; then
  # The combined turtle does not import the base modules, so merge them explicitly.
  # These reproduce the published import chain (copi-enriched -> copi-vocab -> copi-core):
  #   copi-core  declares COPI_0000001-0000024 (operation & equipment categories);
  #   copi-vocab declares the function hierarchy, process stubs, and participant
  #              types (COPI_0000025-0000060) that regen strips from copi-enriched.
  CORE_MERGE_INPUT="--input $WORK_DIR/copi-core.ttl --input $WORK_DIR/copi-vocab.ttl"
fi

cat > "$WORK_DIR/catalog-v001.xml" <<XML
<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<catalog prefer="public" xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">
  <!-- Maps the import IRIs in copi.ttl to local files in this directory -->
  <uri name="https://spec.industrialontologies.org/ontology/core/Core/"
       uri="IOF-Core.rdf"/>
  <uri name="http://purl.obolibrary.org/obo/bfo/2020/bfo.owl"
       uri="bfo-2020.ttl"/>
${COPI_CORE_CATALOG_ENTRY}
</catalog>
XML

# ── Step 3: Reason with HermiT ───────────────────────────────────────────────

REASONED_OWL="$WORK_DIR/reasoned.owl"
log "Running HermiT reasoner (this may take ~30 s)..."

if ! robot merge \
       --catalog "$WORK_DIR/catalog-v001.xml" \
       --input "$COPI_TTL" \
       $CORE_MERGE_INPUT \
       reason \
       --reasoner HermiT \
       --include-indirect true \
       --output "$REASONED_OWL" \
       2>"$WORK_DIR/reason.log"; then
  fail "robot reason failed. Log:"
  cat "$WORK_DIR/reason.log" >&2
  if grep -qi "inconsisten\|unsatisfiable" "$WORK_DIR/reason.log"; then
    exit $E_INCONSISTENT
  fi
  exit $E_PREREQ
fi

# ── Step 4: Explicit unsatisfiable-class check (belt-and-suspenders) ─────────

log "Checking for unsatisfiable classes..."

UNSAT_RESULTS="$WORK_DIR/unsat.csv"
robot query \
  --input "$REASONED_OWL" \
  --query "$SPARQL_DIR/check_unsatisfiable.sparql" "$UNSAT_RESULTS" \
  2>>"$WORK_DIR/reason.log"

UNSAT_ROWS=$(( $(wc -l < "$UNSAT_RESULTS") - 1 ))
if [[ "$UNSAT_ROWS" -gt 0 ]]; then
  fail "Unsatisfiable classes detected:"
  tail -n +2 "$UNSAT_RESULTS" >&2
  exit $E_INCONSISTENT
fi
pass "No unsatisfiable classes."

# ── Entailment helper ─────────────────────────────────────────────────────────

run_entailment_check() {
  local label="$1"
  local sparql="$2"
  local out="$WORK_DIR/$(basename "$sparql" .sparql).csv"

  robot query \
    --input "$REASONED_OWL" \
    --query "$sparql" "$out" \
    2>>"$WORK_DIR/reason.log"

  local rows=$(( $(wc -l < "$out") - 1 ))
  if [[ "$rows" -gt 0 ]]; then
    return 1
  fi
  return 0
}

ENTAILMENT_FAILED=0

if [[ "$NIVEL1_MODE" -eq 0 ]]; then

  # ── Step 5: Entailment checks (combined OWL only) ───────────────────────────

  log "Checking: ControlValve ⊑ Valve..."
  if run_entailment_check "ControlValve⊑Valve" "$SPARQL_DIR/check_cv_subclass_valve.sparql"; then
    pass "ControlValve ⊑ Valve"
  else
    fail "ControlValve ⊑ Valve — entailment absent."
    ENTAILMENT_FAILED=1
  fi

  log "Checking: Valve ⊑ iof:MaterialArtifact..."
  if run_entailment_check "Valve⊑MaterialArtifact" "$SPARQL_DIR/check_valve_subclass_material_artifact.sparql"; then
    pass "Valve ⊑ iof:MaterialArtifact"
  else
    fail "Valve ⊑ iof:MaterialArtifact — entailment absent. Check enrichment DB: Valve genus should be MaterialArtifact (ODR-013)."
    ENTAILMENT_FAILED=1
  fi

  log "Checking: ControlValve ⊑ iof:Assembly..."
  if run_entailment_check "ControlValve⊑Assembly" "$SPARQL_DIR/check_cv_subclass_assembly.sparql"; then
    pass "ControlValve ⊑ iof:Assembly"
  else
    if [[ "$SKIP_ASSEMBLY_CHECK" -eq 1 ]]; then
      warn "ControlValve ⊑ iof:Assembly — entailment absent (suppressed via --skip-assembly-check)."
    else
      fail "ControlValve ⊑ iof:Assembly — entailment absent."
      fail "  Check: 'control valve' must have a row in additional_parents with"
      fail "  parent_iri='https://spec.industrialontologies.org/ontology/construct/Assembly' (ODR-013)."
      ENTAILMENT_FAILED=1
    fi
  fi

  # ── Step 6: ODR-013 regression guard ─────────────────────────────────────────

  log "Regression guard: Valve ⊄ iof:Assembly..."
  GUARD_RESULTS="$WORK_DIR/guard_valve_not_assembly.csv"
  robot query \
    --input "$REASONED_OWL" \
    --query "$SPARQL_DIR/guard_valve_not_assembly.sparql" "$GUARD_RESULTS" \
    2>>"$WORK_DIR/reason.log"

  GUARD_ROWS=$(( $(wc -l < "$GUARD_RESULTS") - 1 ))
  if [[ "$GUARD_ROWS" -gt 0 ]]; then
    fail "ODR-013 REGRESSION: Valve is inferred as iof:Assembly."
    fail "  Valve genus must be MaterialArtifact in enrichment DB. Check ODR-013."
    tail -n +2 "$GUARD_RESULTS" >&2
    exit $E_REGRESSION
  fi
  pass "Valve ⊄ iof:Assembly  (ODR-013 guard OK)"

  # ── Step 7: ODR-008 checks ────────────────────────────────────────────────────

  log "Checking: ProcessControlledFlowFunction ⊑ FlowControlFunction..."
  if run_entailment_check "PCCF⊑FCF" "$SPARQL_DIR/check_pccf_subclass_fcf.sparql"; then
    pass "ProcessControlledFlowFunction ⊑ FlowControlFunction"
  else
    fail "ProcessControlledFlowFunction ⊑ FlowControlFunction — entailment absent."
    fail "  Check: control valve enrichment must have function_parent='FlowControlFunction' (ODR-008 §4)."
    ENTAILMENT_FAILED=1
  fi

  log "Promotion guard: IsolationValve ⊄ ControlValve..."
  GUARD_IV_RESULTS="$WORK_DIR/guard_isolation_not_control_valve.csv"
  robot query \
    --input "$REASONED_OWL" \
    --query "$SPARQL_DIR/guard_isolation_not_control_valve.sparql" "$GUARD_IV_RESULTS" \
    2>>"$WORK_DIR/reason.log"

  GUARD_IV_ROWS=$(( $(wc -l < "$GUARD_IV_RESULTS") - 1 ))
  if [[ "$GUARD_IV_ROWS" -gt 0 ]]; then
    fail "ODR-008 PROMOTION BLOCKED: IsolationValve ⊑ ControlValve detected."
    fail "  Resolve before promoting ControlValve to axiom_mode='equivalent'."
    tail -n +2 "$GUARD_IV_RESULTS" >&2
    exit $E_REGRESSION
  fi
  pass "IsolationValve ⊄ ControlValve  (ODR-008 promotion guard OK)"

  # ── Step 8: ODR-009 guards (combined OWL only) ───────────────────────────────

  log "Checking: LossOfContainment ⊑ bfo:Process  (ODR-009)..."
  if run_entailment_check "LoC⊑Process" "$SPARQL_DIR/check_loc_subclass_process.sparql"; then
    pass "LossOfContainment ⊑ bfo:Process"
  else
    fail "LossOfContainment ⊑ bfo:Process — entailment absent. Check process_parent in enrichment DB (ODR-009)."
    ENTAILMENT_FAILED=1
  fi

  log "Regression guard: LossOfContainment ⊄ PlannedProcess  (ODR-009)..."
  GUARD_LOC_RESULTS="$WORK_DIR/guard_loc_not_planned_process.csv"
  robot query \
    --input "$REASONED_OWL" \
    --query "$SPARQL_DIR/guard_loc_not_planned_process.sparql" "$GUARD_LOC_RESULTS" \
    2>>"$WORK_DIR/reason.log"

  GUARD_LOC_ROWS=$(( $(wc -l < "$GUARD_LOC_RESULTS") - 1 ))
  if [[ "$GUARD_LOC_ROWS" -gt 0 ]]; then
    fail "ODR-009 REGRESSION: LossOfContainment is inferred as PlannedProcess (forbidden)."
    tail -n +2 "$GUARD_LOC_RESULTS" >&2
    exit $E_REGRESSION
  fi
  pass "LossOfContainment ⊄ PlannedProcess  (ODR-009 guard OK)"

  log "Checking: SignalTransmissionProcess ⊑ PlannedProcess  (ODR-009)..."
  if run_entailment_check "STP⊑PlannedProcess" "$SPARQL_DIR/check_signal_trans_subclass_planned.sparql"; then
    pass "SignalTransmissionProcess ⊑ PlannedProcess"
  else
    fail "SignalTransmissionProcess ⊑ PlannedProcess — entailment absent. Check process_parent in enrichment DB (ODR-009)."
    ENTAILMENT_FAILED=1
  fi

else

  # ── Step 8 (--nivel1): Classification checks ─────────────────────────────────

  log "Nível 1 classification: Pump ⊑ MomentumTransferDevice..."
  if run_entailment_check "Pump⊑MTD" "$SPARQL_DIR/check_pump_subclass_mtd.sparql"; then
    pass "Pump ⊑ MomentumTransferDevice"
  else
    fail "Pump ⊑ MomentumTransferDevice — entailment absent. Check Design-B axioms."
    ENTAILMENT_FAILED=1
  fi

  log "Nível 1 classification: Compressor ⊑ MomentumTransferDevice..."
  if run_entailment_check "Compressor⊑MTD" "$SPARQL_DIR/check_compressor_subclass_mtd.sparql"; then
    pass "Compressor ⊑ MomentumTransferDevice"
  else
    fail "Compressor ⊑ MomentumTransferDevice — entailment absent."
    ENTAILMENT_FAILED=1
  fi

  log "Nível 1 classification: GasAbsorber ⊑ MassTransferDevice..."
  if run_entailment_check "Absorber⊑MassTD" "$SPARQL_DIR/check_absorber_subclass_masstd.sparql"; then
    pass "GasAbsorber ⊑ MassTransferDevice"
  else
    fail "GasAbsorber ⊑ MassTransferDevice — entailment absent."
    ENTAILMENT_FAILED=1
  fi

  log "Nível 1 classification: TemperatureSensor ⊑ MeasurementInstrument..."
  if run_entailment_check "TempSensor⊑MeasInstr" "$SPARQL_DIR/check_tsensor_subclass_mesinstr.sparql"; then
    pass "TemperatureSensor ⊑ MeasurementInstrument"
  else
    fail "TemperatureSensor ⊑ MeasurementInstrument — entailment absent."
    ENTAILMENT_FAILED=1
  fi

fi

# ── Step 9: OOPS! pitfall scan ───────────────────────────────────────────────

if [[ "$SKIP_OOPS" -eq 0 ]]; then
  log "Running OOPS! pitfall scan (https://oops.linkeddata.es)..."

  OOPS_REQUEST="$WORK_DIR/oops_request.xml"
  OOPS_RESPONSE="$WORK_DIR/oops_response.xml"
  OOPS_OWL="$WORK_DIR/oops_merged.owl"

  # OOPS! cannot resolve owl:imports from its server, so merge imports inline
  # before sending.  Fall back to the source TTL if merge fails.
  log "Merging imports for OOPS! scan..."
  if robot merge \
       --catalog "$WORK_DIR/catalog-v001.xml" \
       --input "$COPI_TTL" \
       --collapse-import-closure true \
       --output "$OOPS_OWL" \
       2>>"$WORK_DIR/reason.log"; then
    log "Merge OK — sending merged OWL to OOPS!"
  else
    warn "Import merge failed — sending source TTL to OOPS! (results may be incomplete)."
    OOPS_OWL="$COPI_TTL"
  fi

  "$PYTHON" - "$OOPS_OWL" "$OOPS_REQUEST" <<'PYEOF'
import sys, pathlib
content = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
envelope = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<OOPSRequest>\n'
    '  <OntologyURI></OntologyURI>\n'
    '  <OntologyContent><![CDATA[' + content + ']]></OntologyContent>\n'
    '  <Pitfalls></Pitfalls>\n'
    '  <OutputFormat>RDF/XML</OutputFormat>\n'
    '</OOPSRequest>\n'
)
pathlib.Path(sys.argv[2]).write_text(envelope, encoding='utf-8')
PYEOF

  if curl -sSf -X POST \
       -H "Content-Type: application/xml" \
       -d @"$OOPS_REQUEST" \
       -o "$OOPS_RESPONSE" \
       --max-time 180 \
       "https://oops.linkeddata.es/rest" 2>/dev/null; then

    "$PYTHON" - "$OOPS_RESPONSE" <<'PYEOF'
import sys, xml.etree.ElementTree as ET

raw = open(sys.argv[1], encoding='utf-8').read()
# Current OOPS! REST API namespace (changed from oeg-upm.net)
NS  = 'http://oops.linkeddata.es/def#'
RDF = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
COPI = 'https://www.inf.ufrgs.br/ontologies/copi/'

try:
    root = ET.fromstring(raw)
except ET.ParseError as exc:
    print(f"[verify_owl] OOPS!  parse error: {exc}", file=sys.stderr)
    sys.exit(0)

# Check for service error response
for desc in root.findall(f'{{{RDF}}}Description'):
    about = desc.get(f'{{{RDF}}}about', '')
    if 'unexpected_error' in about or 'error' in about.lower():
        msg = desc.findtext(f'{{{NS}}}hasMessage') or ''
        print(f"[verify_owl] OOPS!  service error: {msg}")
        sys.exit(0)

nodes = {d.get(f'{{{RDF}}}about', ''): d for d in root.findall(f'{{{RDF}}}Description')}
counts = {'Critical': 0, 'Important': 0, 'Minor': 0}
details = []

for node in nodes.values():
    code = (node.findtext(f'{{{NS}}}hasCode') or '').strip()
    name = (node.findtext(f'{{{NS}}}hasName') or '').strip()
    sev  = (node.findtext(f'{{{NS}}}hasImportanceLevel') or '').strip()
    n_el = node.find(f'{{{NS}}}hasNumberAffectedElements')
    count = n_el.text.strip() if n_el is not None else '?'
    if not code:
        continue
    if sev in counts:
        counts[sev] += 1
    affects = [
        (ae.text or ae.get(f'{{{RDF}}}resource', '')).strip()
        for ae in node.findall(f'{{{NS}}}hasAffectedElement')
    ]
    local = [a.replace(COPI, 'copi:') for a in affects if COPI in a]
    details.append((sev, code, name, count, local))

print(f"[verify_owl] OOPS!  Critical={counts['Critical']}  Important={counts['Important']}  Minor={counts['Minor']}")
order = {'Critical': 0, 'Important': 1, 'Minor': 2}
details.sort(key=lambda x: order.get(x[0], 9))
for sev, code, name, count, local in details:
    print(f"[verify_owl]        {sev:<10s}  {code}  {name}  (affected:{count})")
    for el in local[:5]:
        print(f"[verify_owl]              ↳ {el}")
    if len(local) > 5:
        print(f"[verify_owl]              ↳ … and {len(local)-5} more COPI elements")
PYEOF

  else
    warn "OOPS! service unreachable — skipping pitfall scan (pass --skip-oops to suppress)."
  fi
fi

# ── Summary ───────────────────────────────────────────────────────────────────

if [[ "$ENTAILMENT_FAILED" -eq 1 ]]; then
  fail "One or more entailment checks failed. See messages above."
  exit $E_ENTAILMENT
fi

log "All checks passed."
exit $E_OK
