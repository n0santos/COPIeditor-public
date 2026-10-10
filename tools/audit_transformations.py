#!/usr/bin/env python3
"""
Empirical audit of Step 5 transformations recorded in enrichment.db.

Reads all enrichment records, extracts the free-text transformation phrase
from step5_signature, clusters them by semantic core using lightweight
heuristics, and writes structured reports to /tmp/.

Usage:
    python tools/audit_transformations.py

Output:
    /tmp/transformation_audit.json   — machine-readable groups + ungrouped
    /tmp/transformation_audit.md     — human-readable Markdown with tables

Does NOT modify the database.
"""

import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "enrichment.db"
OUT_JSON = Path("/tmp/transformation_audit.json")
OUT_MD   = Path("/tmp/transformation_audit.md")


# ---------------------------------------------------------------------------
# Grouping rules — ordered by priority (first match wins).
# Each rule: (group_key, list_of_regex_patterns_on_lowercase_transformation)
# Patterns are matched against the full text, not just the opening.
# ---------------------------------------------------------------------------

RULES: list[tuple[str, list[str]]] = [
    # ── Energy addition to fluid (pumps, compressors, fans, ejectors) ──────
    ("mechanical_energy_to_fluid",
     [r"mechanical energy add",
      r"mechanical energy impart",
      r"mechanical energy transfer",
      r"energy added to fluid",
      r"energy imparted to fluid",
      r"\bpumping\b.*energy",
      r"positive displacement.*fluid",
      r"fluid.*mechanical energy",
      r"mechanical.*hydraulic energy",    # pumps described as M→hydraulic
      ]),

    # ── Compression of gas ─────────────────────────────────────────────────
    ("gas_compression",
     [r"mechanical energy added to gas",
      r"mechanical energy.*compress",
      r"gas.*compress",
      r"compress.*gas",
      r"compression.*pressure",
      r"pressure.*through compression",
      ]),

    # ── Complete flow shutoff / isolation (block valves, gate valves) ──────
    ("flow_isolation",
     [r"complete flow interruption",
      r"complete flow blockage",
      r"complete flow stoppage",
      r"full.*flow.*stop",
      r"emergency.*isolat",
      r"isolat.*pipeline",
      r"flow.*fully.*stop",
      ]),

    # ── Flow regulation / control (valves) ─────────────────────────────────
    ("flow_regulation",
     [r"flow.*regulat",
      r"flow.*control",
      r"flow.*modif",
      r"flow.*modulat",
      r"flow.*throttl",
      r"flow.*restrict",
      r"flow.*permit.*obstruct",
      r"permits.*obstruct.*regulat",
      r"regulate.*flow",
      r"control.*flow",
      r"modify.*flow",
      r"modulate.*flow",
      r"valve.*opening",
      r"disc.*rotation",
      r"gate.*position",
      r"orifice.*area",
      r"ball.*rotation",
      r"plug.*position",
      ]),

    # ── Directional / check-valve control ──────────────────────────────────
    ("directional_flow_control",
     [r"directional flow",
      r"backflow",
      r"reverse flow",
      r"unidirectional",
      r"prevent.*flow.*reversal",
      r"flow direction",
      r"automatic.*direction",
      r"conditional flow passage",        # check valves
      ]),

    # ── Pressure reduction / relief ────────────────────────────────────────
    ("pressure_reduction_relief",
     [r"pressure.*reduc",
      r"pressure.*relief",
      r"pressure.*discharg",
      r"pressure.*release",
      r"pressure.*drop",
      r"pressure.*dissipat",
      r"excess pressure",
      r"overpressure",
      r"back-pressure",
      r"back pressure",
      r"energy storage.*release",         # accumulators
      r"energy storage.*controlled",
      ]),

    # ── Heat / thermal transfer ────────────────────────────────────────────
    ("thermal_energy_transfer",
     [r"thermal energy",
      r"heat transfer",
      r"heat exchang",
      r"thermal.*exchang",
      r"cool",
      r"heat.*fluid",
      r"temperature.*change",
      r"condensat",
      r"evaporat",
      r"boil",
      r"latent heat",                     # condensers, reboilers
      r"flame arrest",                    # flame arrestors (thermal dissipation)
      ]),

    # ── Phase separation ───────────────────────────────────────────────────
    ("phase_separation",
     [r"phase separat",
      r"separat.*phase",
      r"liquid.*gas.*separat",
      r"gas.*liquid.*separat",
      r"solid.*liquid.*separat",
      r"density.*separat",
      r"gravity.*separat",
      r"centrifugal.*separat",
      r"gravitational.*separat",
      r"component.*fractionat",
      r"fractionat",
      r"demist",
      r"coalesce",
      r"centrifugal.*force",              # hydrocyclones: separation through centrifugal force
      r"vapor.*liquid.*equilib",          # flash/distillation separators
      r"thermal.*separat",                # thermal separation via VLE
      ]),

    # ── Mass transfer / scrubbing / absorption ─────────────────────────────
    ("mass_transfer_absorption",
     [r"mass transfer",
      r"absorption",
      r"scrubbing",
      r"washing",
      r"contaminant.*remov",
      r"gas.*liquid.*contact",
      r"chemical.*reaction",
      r"dehydrat",
      r"deaerat",
      r"degass",
      r"moisture.*remov",                 # dehumidifiers, dryers
      r"moisture.*extract",
      r"dissolved.*gas",                  # degasifiers
      r"water.*remov",
      ]),

    # ── Mechanical particle / solid separation (filtration, straining) ─────
    ("mechanical_filtration",
     [r"solid.*particle.*separat",
      r"solid.*remov",
      r"particulate.*remov",
      r"filtrat",
      r"screen",
      r"strainer",
      r"mesh",
      r"mechanical.*separat.*solid",
      r"\bfilter\b",                      # "filter medium" not caught by r"filtrat"
      r"particle.*fluid.*stream",
      r"physical separation.*particle",
      r"selective.*constituent",          # selective separation of unwanted components
      r"unwanted component",
      r"scraping",                        # scrapers / pigging tools
      ]),

    # ── Fluid spatial transport / routing / piping geometry ───────────────
    ("fluid_transport",
     [r"spatial displacement",
      r"fluid.*transport",
      r"transport.*fluid",
      r"fluid.*moved",
      r"convey.*fluid",
      r"fluid.*source.*destination",
      r"fluid.*elevation",
      r"vertical.*transport",
      r"horizontal.*transport",
      r"spatial.*transport",              # "spatial transport without chemical/phase change"
      r"spatial.*elevat",                 # risers, standpipes
      r"spatial.*redirect",              # elbows
      r"spatial.*relocat",               # flexible hoses
      r"directional change",              # elbows, bends
      r"geometric transition",            # reducers, expanders
      r"flow.*division",                  # tees
      r"flow.*redistribu",               # manifolds, headers
      r"stream.*splitting",
      r"stream.*combining",
      r"fluid.*stream.*split",
      r"routing.*multiple.*service",
      ]),

    # ── Signal / measurement / instrumentation ─────────────────────────────
    ("measurement_signal_transduction",
     [r"signal.*transduct",
      r"transduct.*signal",
      r"process variable.*signal",
      r"measur.*convert",
      r"measur.*transmit",
      r"sensor.*signal",
      r"analyt",
      r"measurement",
      r"sampling",
      r"detect.*concentrat",
      r"concentrat.*signal",              # "gas concentration to detection signal"
      r"chromatograph",
      r"pressure sensing",                # pressure gauges and transmitters
      r"pressure difference",             # DP transmitters
      r"temperature sensing",             # thermometers, RTDs
      r"sensing.*indicat",
      r"differential pressure",           # DP cells and indicators
      r"detect.*transdu",                 # "detection transduced"
      r"variable.*transdu",               # "variable states are transduced"
      r"signal.*generat",                 # signal generators, flow transmitters
      r"information.*extract",            # analytical instruments
      r"molecular.*detect",              # GC/MS
      r"information processing",          # controllers, PLCs
      r"signal processing",               # signal conditioners, isolators
      r"electromechanical",               # electromechanical transducers
      ]),

    # ── Electrical / power switching / conversion ──────────────────────────
    ("electrical_power_conversion",
     [r"electrical.*energy",
      r"electric.*energy",
      r"electrical.*power",
      r"mechanical.*electrical",
      r"electrical.*mechanical",
      r"motor",
      r"generator",
      r"electromagnetic",
      r"electrochemical",
      r"current interruption",            # circuit breakers, fuses
      r"electrical.*isolation",           # electrical isolators
      r"electrical.*signal.*analys",      # signal analysers
      ]),

    # ── Kinetic / pressure energy conversion (nozzles, ejectors, turbines) ─
    ("kinetic_pressure_conversion",
     [r"kinetic energy.*pressure",
      r"pressure.*kinetic",
      r"pressure energy.*kinetic",
      r"kinetic energy conv",
      r"velocity.*pressure",
      r"pressure.*velocity",
      r"hydraulic.*rotational",           # hydraulic turbines
      r"momentum transfer.*fluid",        # ejectors
      r"jet entrainment",
      r"motive fluid",
      r"energy dissipat.*dynamic",        # dampeners, snubbers
      r"energy dissipat.*suppress",
      ]),

    # ── Mechanical power transmission (gearboxes, actuators) ──────────────
    ("mechanical_power_transmission",
     [r"mechanical power transmission",
      r"gear.*ratio",
      r"torque.*conversion",
      r"speed.*torque",
      r"pneumatic.*rotational",           # air motors
      r"pneumatic.*mechanical",           # pneumatic actuators
      r"rotational.*mechanical energy",
      r"input.*form.*mechanical",
      r"input.*form.*kinetic",
      r"energy.*form.*conversion",
      r"elastic deformation",             # springs, flexible elements
      r"mechanical force.*redirect",
      r"mechanical.*vibrational",         # vibrators
      r"vibrational motion",
      ]),

    # ── Combustion / chemical energy conversion (engines, flares) ─────────
    ("combustion_chemical_energy",
     [r"combustion",
      r"chemical energy",
      r"chemical.*oxidat",
      r"oxidat.*waste",
      ]),

    # ── Structural / spatial containment and support ───────────────────────
    ("structural_containment_support",
     [r"contain",
      r"structural.*support",
      r"physical.*support",
      r"mechanical.*support",
      r"spatial.*bound",
      r"encloses",
      r"cable.*support",
      r"weight.*support",
      r"load.*transfer",
      r"structural.*integrit",
      r"spatial enclosure",               # vessels, cabinets
      r"pressure barrier",                # pressure-containing walls
      r"pressure isolation.*sensor",      # thermowells
      r"physical protection.*sensor",
      r"leak barrier",                    # gaskets, seals
      r"geometric deformation",           # gaskets filling surface irregularities
      r"mechanical joining",              # flanges, couplings
      r"spatial relationship",            # spacers, clamps
      r"controlled discharge.*solid",     # hoppers, feeders
      ]),

    # ── Drilling / subsurface access ───────────────────────────────────────
    ("drilling_subsurface",
     [r"drill",
      r"subsurface.*access",
      r"wellbore",
      r"downhole",
      r"borehole",
      r"subsurface.*extract",             # production operations
      r"subsurface.*inject",              # injection wells
      r"subsurface.*reservoir",
      r"surface.*subsurface",             # surface-to-reservoir injection
      r"spatial creation.*rock",          # wellbore creation through rock
      r"rock.*volume.*pathway",
      r"\bpig\b",                         # pig launchers, receivers, all pigging tools
      r"shear.*separat",                  # shear rams (BOP components)
      r"cut.*separat.*pipe",
      r"size reduction",                  # mills (downhole milling tools)
      ]),

    # ── Fluid mixing / blending / agitation ───────────────────────────────
    ("mixing_blending",
     [r"mix",
      r"blend",
      r"agitat",
      r"homogen",
      r"disperse",
      r"inject.*fluid",
      r"fluid.*inject",
      ]),
]


def _normalise(text: str) -> str:
    return re.sub(r"[.;,!?]+$", "", text.lower().strip())


def _assign_group(text: str) -> str | None:
    t = text.lower()
    for group_key, patterns in RULES:
        for pat in patterns:
            if re.search(pat, t):
                return group_key
    return None


def load_records() -> list[dict]:
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        "SELECT cluster_label, genus, llm_raw_response FROM enrichment"
    ).fetchall()
    conn.close()

    records = []
    for label, genus, raw in rows:
        try:
            p = json.loads(raw or "{}")
        except Exception:
            continue
        sig  = p.get("step5_signature") or {}
        conf = p.get("confidence") or {}
        t    = (sig.get("transformation") or "").strip()
        if not t:
            continue
        records.append({
            "cluster_label":  label,
            "genus":          genus or "",
            "transformation": t,
            "conf_step5":     conf.get("step5", ""),
        })
    return records


def build_report(records: list[dict]) -> dict:
    grouped: dict[str, list[dict]] = defaultdict(list)
    ungrouped: list[dict] = []

    for r in records:
        key = _assign_group(r["transformation"])
        if key:
            grouped[key].append(r)
        else:
            ungrouped.append(r)

    groups = []
    for key, items in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        label_counts = Counter(i["cluster_label"] for i in items)
        genus_counts  = Counter(i["genus"] for i in items if i["genus"])
        top_labels  = [l for l, _ in label_counts.most_common(5)]
        top_genera  = [g for g, _ in genus_counts.most_common(4)]
        samples = list({_normalise(i["transformation"]) for i in items})[:3]
        groups.append({
            "core":                  key,
            "count":                 len(items),
            "top_cluster_labels":    top_labels,
            "top_genera":            top_genera,
            "sample_transformations": samples,
        })

    return {
        "total_records_with_transformation": len(records),
        "total_grouped":   len(records) - len(ungrouped),
        "total_ungrouped": len(ungrouped),
        "coverage_pct":    round(100 * (len(records) - len(ungrouped)) / len(records), 1),
        "groups":          groups,
        "ungrouped": [
            {"cluster_label": r["cluster_label"], "transformation": r["transformation"]}
            for r in ungrouped
        ],
    }


def write_markdown(report: dict) -> str:
    lines = [
        "# Transformation Audit — COPI Enrichment Database",
        "",
        f"**Total records with transformation:** {report['total_records_with_transformation']}  ",
        f"**Grouped:** {report['total_grouped']} ({report['coverage_pct']} %)  ",
        f"**Ungrouped:** {report['total_ungrouped']}  ",
        "",
        "---",
        "",
        "## Groups",
        "",
        "| Core | Count | Top cluster labels | Top genera |",
        "|------|-------|--------------------|------------|",
    ]
    for g in report["groups"]:
        labels = ", ".join(g["top_cluster_labels"])
        genera = ", ".join(g["top_genera"])
        lines.append(f"| `{g['core']}` | {g['count']} | {labels} | {genera} |")

    lines += [
        "",
        "---",
        "",
        "## Group Details",
        "",
    ]
    for g in report["groups"]:
        lines += [
            f"### `{g['core']}` ({g['count']} records)",
            "",
            "**Sample transformations:**",
        ]
        for s in g["sample_transformations"]:
            lines.append(f"- {s}")
        lines.append("")

    lines += [
        "---",
        "",
        f"## Ungrouped ({report['total_ungrouped']} records)",
        "",
        "| cluster_label | transformation |",
        "|---------------|----------------|",
    ]
    for u in report["ungrouped"]:
        t = u["transformation"].replace("|", "｜")[:120]
        lines.append(f"| {u['cluster_label']} | {t} |")

    return "\n".join(lines) + "\n"


def check_quality(report: dict) -> None:
    n = report["total_records_with_transformation"]
    print("Quality checks:")
    for g in report["groups"]:
        pct = 100 * g["count"] / n
        if pct > 50:
            print(f"  ⚠  group '{g['core']}' covers {pct:.0f}% — may be too broad")
    ung_pct = 100 * report["total_ungrouped"] / n
    if ung_pct > 20:
        print(f"  ⚠  ungrouped at {ung_pct:.0f}% — may need more rules")
    else:
        print(f"  ✓  ungrouped: {ung_pct:.1f}%")
    print(f"  ✓  coverage: {report['coverage_pct']}%  groups: {len(report['groups'])}")


def main() -> None:
    print(f"Loading records from {DB_PATH} ...")
    records = load_records()
    print(f"  {len(records)} records with transformation")

    report = build_report(records)

    OUT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    OUT_MD.write_text(write_markdown(report))

    print(f"\nWrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print()
    check_quality(report)

    print("\nGroup summary:")
    for g in report["groups"]:
        print(f"  {g['count']:4d}  {g['core']}")
    print(f"  {report['total_ungrouped']:4d}  (ungrouped)")


if __name__ == "__main__":
    main()
