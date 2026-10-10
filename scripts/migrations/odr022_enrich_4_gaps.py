#!/usr/bin/env python3
"""
ODR-022 §13 — enrich the 4 standard-term artifacts found by the coverage audit.

These are artifact universals that bear a DesignedFunction, are terms in a source standard,
and reached the ontology as numbered stubs without passing the 5-step method. They were not
caught by the earlier §O6 scan because that scan only looked at named `necessary_parts`;
two of these are referenced from `process_signature` and one is used as a *genus*.

  MeasuringElement  COPI_0000573  ISO 15926 + DEXPI   ClassOfFunctionalObject
  FluidPort         COPI_0000536  ISO 15926           ClassOfFunctionalObject
  DrillString       COPI_0000480  ISO 15926 + OnePetro + SLB
  ElectricalCable   COPI_0000489  ISO 15926

All four already hold numeric IRIs, so this does not change the IRI map — it supplies the
axiomatization those IRIs were missing.

Inserted with status='proposed'; expert review in /enrich/ is the next step.

Two collisions were avoided deliberately (see differentia_rationale on each):
  * ElectricalCable does NOT reuse ElectricalConductionFunction — `electrical connection` is
    already equivalent on it with the same genus, so sharing it would make cable and
    connection interdefinable.
  * MeasuringElement is equivalent on PropertyMeasurementFunction, which is free; its
    existing siblings (temperature/flow/differential-pressure measuring element) carry their
    own quantity-specific functions and are unaffected.

Usage:
    python scripts/migrations/odr022_enrich_4_gaps.py --dry-run
    python scripts/migrations/odr022_enrich_4_gaps.py --apply
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / "data" / "enrichment.db"
MODEL = "claude-opus-5"


def sig(inputs, outputs, transformation, kind, kind_status="controlled",
        kind_rationale=None, rationale=""):
    return json.dumps({
        "inputs": inputs, "outputs": outputs, "transformation": transformation,
        "transformation_kind": kind, "transformation_kind_status": kind_status,
        "proposed_kind_rationale": kind_rationale, "rationale": rationale,
    }, ensure_ascii=False)


def p(t, c, n=1):
    return {"type": t, "count": n, "constraints": c}


ENTRIES = [
    dict(
        cluster_label="measuring element",
        label_pt="elemento de medição",
        function_name="PropertyMeasurementFunction",
        process_name="PropertyMeasurementProcess",
        function_rationale="ISO 15926 and DEXPI agree on a purely functional definition — 'used "
            "for the measurement of a Property' / 'An artefact used for the measurement of a "
            "Property'. ISO adds the decisive qualification: it is defined independently from the "
            "measuring instrument that handles the result and may or may not house it. So the "
            "identity-giving function is sensing the property itself, not reporting it.",
        genus="MaterialArtifact", genus_bfo_root="MaterialArtifact",
        genus_rationale="DEXPI types it plainly as an artefact. ISO 15926 files it under PROCESS "
            "SIGNAL GENERATING FUNCTION, which is a function class rather than an artifact class "
            "and so is not usable as a genus here.",
        differentia_expression="∃bearerOf.PropertyMeasurementFunction",
        differentia_nl="A material artifact that bears a property measurement function, sensing a "
            "property of some entity independently of the instrument that handles the result.",
        differentia_rationale="Functional basis, stated identically by two standards, so "
            "equivalence is safe. PropertyMeasurementFunction is unused elsewhere: the existing "
            "temperature / flow / differential-pressure measuring elements each carry their own "
            "quantity-specific function, so none of them is disturbed by this axiom.",
        axiom_mode="equivalent",
        process_signature=sig(
            [p("PortionOfFluid", "the entity whose property is being sensed")],
            [p("MeasurementInformationContentEntity", "the sensed value of the property")],
            "transduction of a property of some entity into a measurement result",
            "measurement_transduction",
            rationale="Output is information content, not a material entity (ODR-010 §3). The "
                      "element senses; the instrument handles the result."),
        nl_definition_en="A material artifact that bears a property measurement function, used for "
            "the measurement of a property and defined independently from the measuring instrument "
            "that handles that measurement result.",
        nl_definition_pt="Um artefato material que possui uma função de medição de propriedade, "
            "usado para a medição de uma propriedade e definido independentemente do instrumento "
            "de medição que trata esse resultado.",
        source_definitions_used=[{"source": "iso15926", "term": "MEASURING ELEMENT"},
                                 {"source": "dexpi", "term": "MeasuringElement"}],
        note="Genus of 'gas detecting measuring element'. Until now a non-enriched genus was "
             "carrying an enriched entry.",
    ),
    dict(
        cluster_label="fluid port",
        label_pt="porta de fluido",
        function_name="FluidEntryExitFunction",
        process_name="FluidEntryExitProcess",
        function_rationale="ISO 15926 defines it by what it permits — 'allows for the entry or "
            "exit of substances that behave as fluids' — a functional specification with no "
            "structural constraint.",
        genus="Port", genus_bfo_root="MaterialArtifact",
        genus_rationale="ISO 15926 states the genus explicitly: a FLUID PORT is a PORT. COPI "
            "already enriches 'port' (MaterialArtifact, InterfacingFunction), so the genus is "
            "available and enriched.",
        differentia_expression="∃bearerOf.FluidEntryExitFunction",
        differentia_nl="A port that bears a fluid entry-exit function, admitting or discharging "
            "gases, liquids and fluidized solids.",
        differentia_rationale="Functional differentia over an enriched genus. Port is equivalent "
            "on InterfacingFunction; adding a distinct fluid-specific function keeps the subtype "
            "from collapsing into its genus while still permitting equivalence.",
        axiom_mode="equivalent",
        process_signature=sig(
            [p("PortionOfFluid", "fluid presented at the port boundary")],
            [p("PortionOfFluid", "same fluid admitted into or discharged from the enclosing artifact")],
            "admission or discharge of a fluid across the boundary of an artifact",
            "fluid_transport",
            rationale="The port does not transform the fluid; it is the boundary crossing itself. "
                      "ISO's 'gases, liquids and fluidized solids' is exactly PortionOfFluid."),
        nl_definition_en="A port that allows for the entry or exit of substances that behave as "
            "fluids, that is gases, liquids and fluidized solids.",
        nl_definition_pt="Uma porta que permite a entrada ou saída de substâncias que se comportam "
            "como fluidos, isto é, gases, líquidos e sólidos fluidizados.",
        source_definitions_used=[{"source": "iso15926", "term": "FLUID PORT"}],
        note="Referenced from necessary_parts of 'hydraulic pump' and 'pipe tee'; also the parent "
             "of SuctionPort / DischargePort / BranchPort.",
    ),
    dict(
        cluster_label="drill string",
        label_pt="coluna de perfuração",
        function_name="DrillingPowerTransmissionFunction",
        process_name="DrillingPowerTransmissionProcess",
        function_rationale="SLB gives the purpose directly: the combination of drillpipe, BHA and "
            "other tools 'used to make the drill bit turn at the bottom of the wellbore'. The "
            "identity-giving function is transmitting rotation and weight from surface to the bit.",
        genus="Assembly", genus_bfo_root="Assembly",
        genus_rationale="All three sources describe an assembly or combination of parts — ISO "
            "'an assembly of drill pipe with attached tool joints', OnePetro 'all the equipment in "
            "a drilling BHA plus the drill pipe'. iof-core:Assembly is the correct root.",
        differentia_expression="∃bearerOf.DrillingPowerTransmissionFunction ⊓ "
            "∃hasComponentPartAtAllTimes.DrillPipe ⊓ ∃hasComponentPartAtAllTimes.BottomHoleAssembly",
        differentia_nl="An assembly of drill pipe and a bottom hole assembly, connected by tool "
            "joints, that transmits rotation and weight from surface to the drill bit.",
        differentia_rationale="Constructive basis: every source enumerates the constituents "
            "(drill pipe, tool joints, BHA). Necessary-only — an enumeration of parts is not a "
            "sufficient condition under OWA.",
        axiom_mode="necessary",
        primitive_rationale="The three definitions differ on exactly which tools are included "
            "('any other tools', 'all the equipment in a drilling BHA'), so the part list is not "
            "closed and cannot be sufficient.",
        process_signature=sig(
            [], [],
            "transmission of rotation and axial load from surface equipment to the drill bit",
            "mechanical_power_transmission",
            rationale="No admissible participants: what the string transmits is mechanical power, "
                      "which under ODR-010 §5.1 is not a material entity and therefore not a "
                      "process participant. The load is a quality (bearer_of MechanicalLoad, "
                      "COPI_0000385) on the artifact."),
        nl_definition_en="An assembly of drill pipe with attached tool joints together with the "
            "bottom hole assembly, bearing a drilling power transmission function that makes the "
            "drill bit turn at the bottom of the wellbore.",
        nl_definition_pt="Uma montagem de tubos de perfuração com uniões acopladas, junto com o "
            "conjunto de fundo, possuindo uma função de transmissão de potência de perfuração que "
            "faz a broca girar no fundo do poço.",
        source_definitions_used=[{"source": "iso15926", "term": "DRILL STRING"},
                                 {"source": "onepetro_glossary", "term": "Drill string"},
                                 {"source": "slb_glossary", "term": "drillstring"}],
        qualities=["MechanicalLoad"],
        note="Referenced from process_signature of 'wellbore'.",
    ),
    dict(
        cluster_label="electrical cable",
        label_pt="cabo elétrico",
        function_name="ElectricalDistributionFunction",
        process_name="ElectricalDistributionProcess",
        function_rationale="ISO 15926 states the purpose — 'used to distribute electricity' — "
            "while constraining the construction: one or more cable connectors held together with "
            "an overall sheath.",
        genus="MaterialArtifact", genus_bfo_root="MaterialArtifact",
        genus_rationale="ISO 15926 types it as an ARTEFACT and an ELECTRICAL CONDUCTOR; "
            "MaterialArtifact is the corresponding IOF root.",
        differentia_expression="∃bearerOf.ElectricalDistributionFunction ⊓ "
            "∃hasComponentPartAtAllTimes.CableConnector ⊓ ∃hasComponentPartAtAllTimes.Sheath",
        differentia_nl="A material artifact consisting of one or more cable connectors held "
            "together with an overall sheath, used to distribute electricity.",
        differentia_rationale="Necessary-only, and deliberately NOT reusing "
            "ElectricalConductionFunction: the 'electrical connection' entry is already equivalent "
            "on that function with the same genus MaterialArtifact, so sharing it would let the "
            "reasoner infer that every electrical cable is an electrical connection and conversely. "
            "The sheath and connector conditions are structural, which independently rules out "
            "equivalence.",
        axiom_mode="necessary",
        primitive_rationale="The ISO differentia is constructive (sheath, connectors); under OWA "
            "structural conditions cannot be sufficient.",
        process_signature=sig(
            [], [],
            "distribution of electricity along a sheathed conductor assembly",
            "electrical_power_transmission", "proposed",
            "The controlled vocabulary has mechanical_power_transmission but no electrical "
            "counterpart; distribution along a conductor is neither conversion nor fluid transport. "
            "Same proposed term as 'cable bundle', which has the same gap.",
            rationale="No admissible participants: electrical power is not a material entity "
                      "(ODR-010 §5.1). The cable's electrical rating is a quality (bearer_of "
                      "ElectricalCurrent, COPI_0000383)."),
        nl_definition_en="A material artifact that consists of one or more cable connectors held "
            "together with an overall sheath, and is used to distribute electricity.",
        nl_definition_pt="Um artefato material que consiste em um ou mais conectores de cabo "
            "mantidos juntos por uma capa externa, e é usado para distribuir eletricidade.",
        source_definitions_used=[{"source": "iso15926", "term": "ELECTRICAL CABLE"}],
        qualities=["ElectricalCurrent"],
        note="Referenced from process_signature of 'cable tray' and differentia of 'cable bundle'.",
    ),
]


def build_row(e: dict) -> dict:
    return {
        "cluster_label": e["cluster_label"], "label_pt": e["label_pt"],
        "function_name": e["function_name"], "function_parent": "DesignedFunction",
        "process_name": e["process_name"], "process_parent": "PlannedProcess",
        "function_rationale": e["function_rationale"],
        "genus": e["genus"], "genus_bfo_root": e["genus_bfo_root"],
        "genus_rationale": e["genus_rationale"],
        "differentia_expression": e["differentia_expression"],
        "differentia_nl": e["differentia_nl"],
        "differentia_rationale": e["differentia_rationale"],
        "necessary_parts": "[]",
        "parts_rationale": (
            "Parts named in the differentia are not asserted as necessary_parts: "
            "validate_necessary_parts_quotes() requires each part to carry a verbatim "
            "source_quote, and these come from the definition of this entry itself rather than "
            "from a standard stating a component relationship. Left empty pending expert review."
        ),
        "process_signature": e["process_signature"],
        "axiom_mode": e["axiom_mode"],
        "primitive_rationale": e.get("primitive_rationale"),
        "nl_definition_en": e["nl_definition_en"], "nl_definition_pt": e["nl_definition_pt"],
        "source_definitions_used": json.dumps(e["source_definitions_used"], ensure_ascii=False),
        "qualities": json.dumps(e.get("qualities", []), ensure_ascii=False),
        "status": "proposed", "llm_model": MODEL,
        "reviewer_notes": (
            f"ODR-022 §13 coverage audit: standard term bearing a DesignedFunction that held a "
            f"numeric IRI without an axiomatization. {e['note']} Awaiting expert review."
        ),
    }


def main(apply: bool) -> int:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    existing = {r["cluster_label"] for r in con.execute("SELECT cluster_label FROM enrichment")}
    dupes = [e["cluster_label"] for e in ENTRIES if e["cluster_label"] in existing]
    if dupes:
        print("ERROR — already exist:", dupes)
        con.close()
        return 1
    for e in ENTRIES:
        row = build_row(e)
        print(f"  {row['cluster_label']:<20} genus={row['genus']:<16} "
              f"mode={row['axiom_mode']:<11} fn={row['function_name']}")
        if apply:
            cols = ", ".join(row)
            con.execute(f"INSERT INTO enrichment ({cols}) VALUES ({', '.join('?' for _ in row)})",
                        tuple(row.values()))
    if apply:
        con.commit()
    con.close()
    print(f"\n{len(ENTRIES)} entries — {'INSERTED (status=proposed)' if apply else 'DRY RUN'}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    sys.exit(main(apply=ap.parse_args().apply))
