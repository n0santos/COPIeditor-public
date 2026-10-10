#!/usr/bin/env python3
"""
ODR-022 §O6 — enrich the standard-term components.

Each is a term in a source standard AND is stated by that standard to be a component of a
particular equipment (verbatim source_quote in the owning entry's necessary_parts), so
under ODR-022 §10.2 it enters through the 5-step method rather than by IRI allocation.

14 of the 15 are enriched here. The 15th, `Shell`, is NOT: the CFIHOS definition ("a layer
or surface surrounding a space, typically the cylindrical part of a vessel") is the same
concept as the already-exported `vessel shell` entry (COPI_0000374, "the outer
pressure-containing structural boundary of a vessel"). Enriching it would create exactly
the duplication ODR-022 exists to remove, so the part reference is repointed instead —
see odr022_repoint_shell.py.

Inserted with status='proposed' — expert review in /enrich/ is the next step, and only
'validated'/'exported' entries reach generate_combined_turtle(). Until they are reviewed
they stay readable-name stubs in the baseline, which is the intended gate.

necessary_parts is [] for all 14: none of the source definitions names a sub-component,
and validate_necessary_parts_quotes() requires a verbatim source_quote for every part.
Inventing parts here is exactly what the source-grounding rule exists to prevent.

Energy does not appear as a process participant (ODR-010 §5.1). For the electrical
components the demand is recorded as a quality (bearer_of ElectricalCurrent COPI_0000383)
rather than an input, and their signatures are correspondingly empty.

Usage:
    python scripts/migrations/odr022_enrich_15_components.py --dry-run
    python scripts/migrations/odr022_enrich_15_components.py --apply
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
        "inputs": inputs,
        "outputs": outputs,
        "transformation": transformation,
        "transformation_kind": kind,
        "transformation_kind_status": kind_status,
        "proposed_kind_rationale": kind_rationale,
        "rationale": rationale,
    }, ensure_ascii=False)


def p(t, c, n=1):
    return {"type": t, "count": n, "constraints": c}


ENTRIES = [
    # ── christmas tree components ────────────────────────────────────────────
    dict(
        cluster_label="master valve",
        label_pt="válvula mestra",
        function_name="PrimaryWellIsolationFunction",
        process_name="PrimaryWellIsolationProcess",
        function_rationale="SLB and OnePetro both define the master valve by what it governs — "
            "all flow from the wellbore — not by its construction. The identity-giving function "
            "is primary isolation of the entire well stream, which is what distinguishes it from "
            "every other valve on the tree.",
        genus="Valve", genus_bfo_root="MaterialArtifact",
        genus_rationale="A master valve is a valve; ISO 15926 VALVE is the nearest superclass "
            "already enriched in COPI (COPI_0000077).",
        differentia_expression="∃bearerOf.PrimaryWellIsolationFunction ⊓ ∃componentPartOf.ChristmasTree",
        differentia_nl="A valve that bears a primary well isolation function and is a component "
            "of a christmas tree, governing the whole wellbore stream rather than a branch of it.",
        differentia_rationale="Constructive subtype of Valve: the differentia combines a function "
            "with a positional condition (mounted on the tree, upstream of the wing valves). "
            "Position is not a sufficient condition, so the axiom is necessary-only.",
        axiom_mode="necessary",
        primitive_rationale="The definition is partly positional ('on the christmas tree', 'main "
            "shut-in valve on the well'); under OWA a positional differentia cannot be sufficient.",
        process_signature=sig(
            [p("FormationFluid", "full wellbore stream upstream of any branch")],
            [p("FormationFluid", "wellbore stream permitted downstream, or fully isolated")],
            "permitting or blocking the entire produced stream from the wellbore",
            "flow_isolation",
            rationale="The master valve is the primary shut-in point: its process either passes "
                      "or isolates the whole well stream."),
        nl_definition_en="A valve that bears a primary well isolation function and is a component "
            "of a christmas tree, controlling all flow from the wellbore.",
        nl_definition_pt="Uma válvula que possui uma função de isolamento primário do poço e é um "
            "componente de uma árvore de natal, controlando todo o fluxo do poço.",
        source_definitions_used=[{"source": "slb_glossary", "term": "master valve"},
                                 {"source": "onepetro_glossary", "term": "Master valve"}],
        component_of="christmas tree",
    ),
    dict(
        cluster_label="wing valve",
        label_pt="válvula lateral",
        function_name="FlowlineIsolationFunction",
        process_name="FlowlineIsolationProcess",
        function_rationale="Both glossaries place the wing valve on the lateral flow line, above "
            "the master valve. Its function is isolating that branch, so the well can be routed "
            "or shut in at the flowline without closing the master valve.",
        genus="Valve", genus_bfo_root="MaterialArtifact",
        genus_rationale="A wing valve is a valve; Valve (COPI_0000077) is the nearest enriched "
            "superclass.",
        differentia_expression="∃bearerOf.FlowlineIsolationFunction ⊓ ∃componentPartOf.ChristmasTree",
        differentia_nl="A valve that bears a flowline isolation function and is a component of a "
            "christmas tree, mounted laterally on the flow line downstream of the master valve.",
        differentia_rationale="Like the master valve this is a constructive subtype: the sources "
            "define it by location ('on the side', 'above the master valve, on the flow line').",
        axiom_mode="necessary",
        primitive_rationale="Definition is positional relative to the master valve and the flow "
            "line; not a sufficient condition under OWA.",
        process_signature=sig(
            [p("FormationFluid", "produced stream entering the lateral flow line")],
            [p("FormationFluid", "stream permitted into the flow line, or isolated")],
            "permitting or blocking flow through the lateral flow line of the tree",
            "flow_isolation",
            rationale="Isolates a branch of the tree rather than the whole wellbore, which is "
                      "what separates it from the master valve."),
        nl_definition_en="A valve that bears a flowline isolation function and is a component of a "
            "christmas tree, located on the flow line downstream of the master valve.",
        nl_definition_pt="Uma válvula que possui uma função de isolamento de linha de fluxo e é um "
            "componente de uma árvore de natal, localizada na linha de fluxo a jusante da válvula mestra.",
        source_definitions_used=[{"source": "slb_glossary", "term": "wing valve"},
                                 {"source": "onepetro_glossary", "term": "Wing valve"}],
        component_of="christmas tree",
    ),

    # ── drilling ────────────────────────────────────────────────────────────
    dict(
        cluster_label="drill bit",
        label_pt="broca",
        function_name="RockCuttingFunction",
        process_name="RockCuttingProcess",
        function_rationale="All three sources define the drill bit purely by what it does to rock "
            "— 'used to create cylindrical holes', 'rock cutting device', 'tool used to crush or "
            "cut rock'. None constrains its construction, so the function is identity-giving and "
            "sufficient.",
        genus="MaterialArtifact", genus_bfo_root="MaterialArtifact",
        genus_rationale="ISO 15926 types it as a CUTTING TOOL, which COPI does not declare; "
            "MaterialArtifact is the nearest available superclass.",
        differentia_expression="∃bearerOf.RockCuttingFunction",
        differentia_nl="A material artifact that bears a rock cutting function, comminuting "
            "formation rock to advance a borehole.",
        differentia_rationale="Purely functional basis — the three source definitions agree on "
            "function and say nothing about construction, so equivalence is safe and lets the "
            "reasoner classify bit subtypes automatically.",
        axiom_mode="equivalent",
        process_signature=sig(
            [p("PortionOfSolid", "in-situ formation rock at the bottom of the borehole")],
            [p("RockCuttings", "comminuted rock fragments released into the drilling fluid")],
            "mechanical comminution of formation rock to advance a borehole",
            "subsurface_access",
            rationale="Input is intact formation rock, output is cuttings; the transformation is "
                      "the defining act of the bit."),
        nl_definition_en="A material artifact that bears a rock cutting function, used to crush or "
            "cut formation rock in order to create a borehole.",
        nl_definition_pt="Um artefato material que possui uma função de corte de rocha, usado para "
            "triturar ou cortar rocha da formação a fim de criar um poço.",
        source_definitions_used=[{"source": "iso15926", "term": "DRILL BIT"},
                                 {"source": "onepetro_glossary", "term": "Drill bit"},
                                 {"source": "slb_glossary", "term": "drill bit"}],
        component_of="bottom hole assembly",
    ),

    # ── heat exchange ───────────────────────────────────────────────────────
    dict(
        cluster_label="finned tube",
        label_pt="tubo aletado",
        function_name="ExtendedSurfaceHeatTransferFunction",
        process_name="ExtendedSurfaceHeatTransferProcess",
        function_rationale="ISO 15926 defines the finned tube by the purpose of its fins — "
            "'to increase its outer surface area' — which is a heat transfer enhancement function.",
        genus="MaterialArtifact", genus_bfo_root="MaterialArtifact",
        genus_rationale="ISO 15926 types it as a TUBE, which COPI does not enrich separately; "
            "MaterialArtifact is the nearest available superclass.",
        differentia_expression="∃bearerOf.ExtendedSurfaceHeatTransferFunction ⊓ ∃hasComponentPartAtAllTimes.Fin",
        differentia_nl="A material artifact that bears an extended-surface heat transfer function "
            "by virtue of one or more fins that increase its outer surface area.",
        differentia_rationale="Constructive basis: the differentia is the presence of fins, a "
            "structural feature. Necessary-only — a tube without fins that happens to transfer "
            "heat well is not a finned tube.",
        axiom_mode="necessary",
        primitive_rationale="The differentia is structural (presence of fins), so under OWA it "
            "cannot be a sufficient condition.",
        process_signature=sig(
            [p("HeatTransferMedium", "fluid flowing over or through the finned surface")],
            [p("HeatTransferMedium", "same fluid at altered temperature")],
            "conductive and convective heat transfer across an extended outer surface",
            "thermal_energy_transfer",
            rationale="The fins alter the rate, not the kind, of transfer; participants are the "
                      "heat transfer medium on either side."),
        nl_definition_en="A material artifact that is a tube extended with one or more fins to "
            "increase its outer surface area, bearing an extended-surface heat transfer function.",
        nl_definition_pt="Um artefato material que é um tubo estendido com uma ou mais aletas para "
            "aumentar sua área de superfície externa, possuindo uma função de transferência de "
            "calor por superfície estendida.",
        source_definitions_used=[{"source": "iso15926", "term": "FINNED TUBE"}],
        component_of="finned tube heat exchanger",
    ),
    dict(
        cluster_label="tube bundle",
        label_pt="feixe tubular",
        function_name="MultipathFluidConveyanceFunction",
        process_name="MultipathFluidConveyanceProcess",
        function_rationale="ISO 15926 defines the tube bundle by what its assembly achieves — "
            "'allowing multiple flow paths from a single source' — which is a conveyance function "
            "distinguishing it from a single tube.",
        genus="Assembly", genus_bfo_root="Assembly",
        genus_rationale="ISO 15926 types it as a BUNDLE consisting of several tubes assembled "
            "together; a plurality of parts held as one makes iof-core:Assembly the correct root.",
        differentia_expression="∃bearerOf.MultipathFluidConveyanceFunction ⊓ ∃hasComponentPartAtAllTimes.Tube",
        differentia_nl="An assembly of several tubes held together so that a single source is "
            "divided among multiple parallel flow paths.",
        differentia_rationale="Constructive basis: 'several tubes assembled together' is a "
            "structural condition, so necessary-only.",
        axiom_mode="necessary",
        primitive_rationale="The differentia is the structural fact of several tubes assembled "
            "together; not sufficient under OWA.",
        process_signature=sig(
            [p("PortionOfFluid", "fluid stream entering from a single source")],
            [p("PortionOfFluid", "same fluid divided among parallel tube paths")],
            "division of a single fluid stream among multiple parallel tube paths",
            "fluid_transport",
            rationale="The bundle does not change the fluid, only the number of paths it takes."),
        nl_definition_en="An assembly of several tubes assembled together, bearing a multipath "
            "fluid conveyance function that allows multiple flow paths from a single source.",
        nl_definition_pt="Uma montagem de vários tubos reunidos, possuindo uma função de condução "
            "de fluido em múltiplos caminhos que permite vários percursos de fluxo a partir de "
            "uma única fonte.",
        source_definitions_used=[{"source": "iso15926", "term": "TUBE BUNDLE"}],
        component_of="shell and tube heat exchanger",
    ),
    # ── containment ─────────────────────────────────────────────────────────
    dict(
        cluster_label="chamber",
        label_pt="câmara",
        function_name="ContainmentFunction",
        process_name="ContainmentProcess",
        function_rationale="CFIHOS defines a chamber as 'an enclosed space' and ISO 15926 as an "
            "ENCLOSURE 'especially one inside an ARTEFACT'. The identity-giving function is "
            "containment, which COPI already declares as COPI_0000025.",
        genus="MaterialArtifact", genus_bfo_root="MaterialArtifact",
        genus_rationale="ISO 15926 types CHAMBER as an ARTEFACT and an ENCLOSURE; MaterialArtifact "
            "is the corresponding IOF root.",
        differentia_expression="∃bearerOf.ContainmentFunction ⊓ ∃componentPartOf.MaterialArtifact",
        differentia_nl="A material artifact that bears a containment function and is an enclosed "
            "space located within a larger artifact.",
        differentia_rationale="Necessary-only. ContainmentFunction is borne by many things that "
            "are not chambers (vessels, tanks, pipelines); making this equivalent would pull all "
            "of them in. The interiority condition is what narrows it.",
        axiom_mode="necessary",
        primitive_rationale="ContainmentFunction is shared with every containing artifact in COPI, "
            "so it cannot be sufficient. Interiority is a relational condition, not a sufficient one.",
        process_signature=sig(
            [p("PortionOfFluid", "fluid admitted into the enclosed space")],
            [p("PortionOfFluid", "same fluid, held within the enclosed space")],
            "holding a fluid within an enclosed interior space of an artifact",
            "containment",
            rationale="A chamber holds rather than transforms; input and output are the same "
                      "portion under containment."),
        nl_definition_en="A material artifact that is an enclosed space within a larger artifact, "
            "bearing a containment function.",
        nl_definition_pt="Um artefato material que é um espaço fechado dentro de um artefato maior, "
            "possuindo uma função de contenção.",
        source_definitions_used=[{"source": "cfihos", "term": "chamber"},
                                 {"source": "iso15926", "term": "CHAMBER"},
                                 {"source": "dexpi", "term": "Chamber"}],
        component_of="manifold",
    ),

    # ── electrical ──────────────────────────────────────────────────────────
    dict(
        cluster_label="electrical switch",
        label_pt="chave elétrica",
        function_name="ElectricalSwitchingFunction",
        process_name="ElectricalSwitchingProcess",
        function_rationale="CFIHOS and ISO 15926 give the same functional definition — 'turns "
            "electrical current on and/or off' — with no structural constraint, so the function "
            "is identity-giving and sufficient.",
        genus="MaterialArtifact", genus_bfo_root="MaterialArtifact",
        genus_rationale="ISO 15926 types it as an ARTEFACT and a SWITCHING DEVICE; MaterialArtifact "
            "is the corresponding IOF root.",
        differentia_expression="∃bearerOf.ElectricalSwitchingFunction",
        differentia_nl="A material artifact that bears an electrical switching function, "
            "establishing or interrupting the continuity of an electrical circuit.",
        differentia_rationale="Purely functional basis, stated identically by two independent "
            "standards, so equivalence is safe.",
        axiom_mode="equivalent",
        process_signature=sig(
            [p("ControlSignal", "command to open or close the circuit, manual or automatic")],
            [p("InformationContentEntity", "resulting circuit state")],
            "establishing or interrupting electrical circuit continuity on command",
            "electrical_circuit_switching", "proposed",
            "The controlled vocabulary has electrical_power_conversion but no term for switching, "
            "which changes circuit continuity rather than converting power. flow_isolation is the "
            "fluid analogue and would be a category error.",
            rationale="Energy is not a participant (ODR-010 §5.1): the switch's electrical demand "
                      "is a quality (bearer_of ElectricalCurrent), while the process participants "
                      "are the command and the resulting state."),
        nl_definition_en="A material artifact that bears an electrical switching function, turning "
            "electrical current on and/or off.",
        nl_definition_pt="Um artefato material que possui uma função de chaveamento elétrico, "
            "ligando e/ou desligando a corrente elétrica.",
        source_definitions_used=[{"source": "cfihos", "term": "electrical switch"},
                                 {"source": "iso15926", "term": "ELECTRICAL SWITCH"}],
        component_of="switchboard",
        qualities=["ElectricalCurrent"],
    ),
    dict(
        cluster_label="stator winding",
        label_pt="enrolamento do estator",
        function_name="ElectromagneticFieldGenerationFunction",
        process_name="ElectromagneticFieldGenerationProcess",
        function_rationale="ISO 15926 defines it as a WINDING on the stator — an assembly of "
            "interconnected turns 'intended for common operation'. In a machine that common "
            "operation is generating the stationary electromagnetic field.",
        genus="MaterialArtifact", genus_bfo_root="MaterialArtifact",
        genus_rationale="ISO 15926 types WINDING as an ARTEFACT and an ELECTRICAL CONDUCTOR; "
            "MaterialArtifact is the corresponding IOF root.",
        differentia_expression="∃bearerOf.ElectromagneticFieldGenerationFunction ⊓ ∃componentPartOf.Stator",
        differentia_nl="A material artifact that is an assembly of interconnected conductor turns "
            "mounted on the stator of a machine, bearing an electromagnetic field generation function.",
        differentia_rationale="Constructive and positional: 'a winding on the stator'. The same "
            "winding construction on a rotor is a rotor winding, so position is essential and the "
            "axiom is necessary-only.",
        axiom_mode="necessary",
        primitive_rationale="Differentia is positional (on the stator, not the rotor); positional "
            "conditions are not sufficient under OWA.",
        process_signature=sig(
            [], [],
            "conversion between electrical current and a stationary electromagnetic field",
            "electrical_power_conversion",
            rationale="No material or informational participants. Under ODR-010 §5.1 energy is "
                      "not a bfo:MaterialEntity and therefore not a process participant; the "
                      "winding's electrical demand is recorded as a quality (bearer_of "
                      "ElectricalCurrent, COPI_0000383) on the artifact instead."),
        nl_definition_en="A material artifact that is a winding on the stator of a machine, "
            "bearing an electromagnetic field generation function.",
        nl_definition_pt="Um artefato material que é um enrolamento no estator de uma máquina, "
            "possuindo uma função de geração de campo eletromagnético.",
        source_definitions_used=[{"source": "iso15926", "term": "STATOR WINDING"}],
        component_of="stator",
        qualities=["ElectricalCurrent"],
    ),
    dict(
        cluster_label="cable bundle",
        label_pt="feixe de cabos",
        function_name="GroupedConductorRoutingFunction",
        process_name="GroupedConductorRoutingProcess",
        function_rationale="POSC Caesar declares Cable Bundle under Artefact without a definition, "
            "so the grounding is the umbilical entry that names it: 'a flexible and easily "
            "disconnectable collection of cables and/or tubing for control, power, communication "
            "or chemical injection purposes'. The identity-giving function is routing several "
            "conductors together as one disconnectable unit.",
        genus="Assembly", genus_bfo_root="Assembly",
        genus_rationale="A collection of cables held together as one handleable unit is an "
            "iof-core:Assembly, matching the parent recorded in the umbilical's necessary_parts.",
        differentia_expression="∃bearerOf.GroupedConductorRoutingFunction ⊓ ∃hasComponentPartAtAllTimes.ElectricalCable",
        differentia_nl="An assembly of two or more electrical cables held together so that they "
            "are routed, installed and disconnected as a single unit.",
        differentia_rationale="Constructive basis: the differentia is the structural fact of "
            "several cables bound together. Necessary-only.",
        axiom_mode="necessary",
        primitive_rationale="POSC Caesar supplies no definition; the axiom rests on the umbilical's "
            "component quote alone, which is too thin to support a sufficient condition.",
        process_signature=sig(
            [p("InformationContentEntity", "control or communication signals carried by the "
                                           "constituent cables")],
            [p("InformationContentEntity", "the same signals delivered at the far end")],
            "conveyance of signals along several conductors routed as one unit",
            "electrical_power_transmission", "proposed",
            "The controlled vocabulary covers mechanical_power_transmission but has no electrical "
            "counterpart. Conveying power or signal along a conductor is neither conversion nor "
            "fluid transport.",
            rationale="Electrical power is not a participant (ODR-010 §5.1) and is recorded as a "
                      "quality; the informational payload is admissible as ICE."),
        nl_definition_en="An assembly of two or more electrical cables held together and routed as "
            "a single disconnectable unit, bearing a grouped conductor routing function.",
        nl_definition_pt="Uma montagem de dois ou mais cabos elétricos reunidos e roteados como uma "
            "única unidade desconectável, possuindo uma função de roteamento agrupado de condutores.",
        source_definitions_used=[{"source": "posc_caesar", "term": "Cable Bundle"}],
        component_of="umbilical",
        qualities=["ElectricalCurrent"],
    ),

    # ── instrumentation ─────────────────────────────────────────────────────
    dict(
        cluster_label="gas detecting measuring element",
        label_pt="elemento de medição de detecção de gás",
        function_name="GasDetectionFunction",
        process_name="GasDetectionProcess",
        function_rationale="ISO 15926 defines it as a MEASURING ELEMENT 'for the detection of the "
            "presence of a specified concentration of a gas' — a purely functional specification.",
        genus="MeasuringElement", genus_bfo_root="MaterialArtifact",
        genus_rationale="ISO 15926 states the genus explicitly: it is a MEASURING ELEMENT, "
            "defined independently of the instrument handling the measurement.",
        differentia_expression="∃bearerOf.GasDetectionFunction",
        differentia_nl="A measuring element that bears a gas detection function, sensing whether a "
            "specified concentration of a gas is present.",
        differentia_rationale="Necessary-only despite the functional definition. The existing "
            "'gas detector' entry is already equivalent on GasDetectionFunction with genus "
            "Detector; a measuring element is a component of such an instrument, not an instance "
            "of one. Asserting equivalence here would make the part and the whole "
            "interdefinable on the same function.",
        axiom_mode="necessary",
        primitive_rationale="GasDetectionFunction is already the sufficient condition for the "
            "'gas detector' instrument. A measuring element bears it as a component; parthood is "
            "not a sufficient condition.",
        process_signature=sig(
            [p("PortionOfGas", "sampled atmosphere or process gas whose composition is sensed")],
            [p("CompositionMeasurementResult", "indication of whether the specified gas "
                                               "concentration is present")],
            "transduction of gas concentration into a detectable indication",
            "measurement_transduction",
            rationale="Input is the gas being sensed, output is information content — the "
                      "measurement result, not a material entity (ODR-010 §3)."),
        nl_definition_en="A measuring element that bears a gas detection function, used for "
            "detecting the presence of a specified concentration of a gas.",
        nl_definition_pt="Um elemento de medição que possui uma função de detecção de gás, usado "
            "para detectar a presença de uma concentração especificada de um gás.",
        source_definitions_used=[{"source": "iso15926", "term": "GAS DETECTING MEASURING ELEMENT"}],
        component_of="gas detector",
    ),
    dict(
        cluster_label="panel",
        label_pt="painel",
        function_name="InstrumentMountingFunction",
        process_name="InstrumentMountingProcess",
        function_rationale="ISA 5.1 defines the panel by what it carries — 'groups of instrument "
            "hardware mounted on it, houses the operator-process interface' — and ISO 15926 as a "
            "SUPPORT that is a mount for displaying. The common function is mounting instrument "
            "hardware and presenting it to an operator.",
        genus="MaterialArtifact", genus_bfo_root="MaterialArtifact",
        genus_rationale="ISO 15926 types PANEL as an ARTEFACT and a SUPPORT; MaterialArtifact is "
            "the corresponding IOF root.",
        differentia_expression="∃bearerOf.InstrumentMountingFunction",
        differentia_nl="A material artifact that is a structure on which instrument hardware is "
            "mounted and through which an operator interacts with the process.",
        differentia_rationale="Necessary-only: ISA 5.1 leads with structure ('a freestanding or "
            "built-in structure consisting of one or more sections, cubicles, consoles, or desks'), "
            "so the definition is constructive as much as functional.",
        axiom_mode="necessary",
        primitive_rationale="The ISA definition is structure-led and enumerative (sections, "
            "cubicles, consoles, desks); no sufficient condition follows from it.",
        process_signature=sig(
            [p("InformationContentEntity", "process information arriving from mounted instruments")],
            [p("VisualIndication", "information presented at the operator-process interface")],
            "presentation of process information to an operator via mounted instrument hardware",
            "structural_support", "proposed",
            "The controlled vocabulary has no term for bearing or mounting other equipment. "
            "containment is the nearest but a panel supports rather than encloses.",
            rationale="A panel neither transforms matter nor measures; its participants are "
                      "informational."),
        nl_definition_en="A material artifact that is a structure on which groups of instrument "
            "hardware are mounted and which houses the operator-process interface.",
        nl_definition_pt="Um artefato material que é uma estrutura sobre a qual grupos de "
            "instrumentos são montados e que abriga a interface operador-processo.",
        source_definitions_used=[{"source": "isa5_1", "term": "panel"},
                                 {"source": "iso15926", "term": "PANEL"},
                                 {"source": "posc_caesar", "term": "Panel"}],
        component_of="switchboard",
    ),

    # ── mechanical ──────────────────────────────────────────────────────────
    dict(
        cluster_label="piston",
        label_pt="pistão",
        function_name="ReciprocatingDisplacementFunction",
        process_name="ReciprocatingDisplacementProcess",
        function_rationale="ISO 15926 states the purpose explicitly: it reciprocates within a "
            "hollow outer cylinder 'to change the internal volume of the outer cylinder in order "
            "to either discharge pressurized liquid or gas'.",
        genus="MaterialArtifact", genus_bfo_root="MaterialArtifact",
        genus_rationale="ISO 15926 types PISTON as an ENGINE COMPONENT and a DISPLACER; neither is "
            "declared in COPI, so MaterialArtifact is the nearest available superclass.",
        differentia_expression="∃bearerOf.ReciprocatingDisplacementFunction ⊓ ∃componentPartOf.Cylinder",
        differentia_nl="A material artifact of normally cylindrical shape with a closed end, "
            "reciprocating within a hollow outer cylinder so as to change its internal volume.",
        differentia_rationale="Constructive basis: the ISO definition constrains shape "
            "('normally of the cylindrical shape', 'provided with a closed end') as well as "
            "function. Necessary-only.",
        axiom_mode="necessary",
        primitive_rationale="Shape constraints in the source definition are constructive; under "
            "OWA they cannot be sufficient conditions.",
        process_signature=sig(
            [p("PortionOfFluid", "liquid or gas admitted into the cylinder volume")],
            [p("PortionOfFluid", "same fluid discharged at elevated pressure")],
            "cyclic change of a cylinder's internal volume to displace and pressurize a fluid",
            "mechanical_power_transmission",
            rationale="The piston converts reciprocating mechanical motion into fluid displacement; "
                      "the fluid is the participant, the mechanical work is not (ODR-010 §5.1)."),
        nl_definition_en="A material artifact, normally cylindrical and provided with a closed end, "
            "that reciprocates within a hollow outer cylinder to change its internal volume in "
            "order to discharge pressurized liquid or gas.",
        nl_definition_pt="Um artefato material, normalmente cilíndrico e provido de uma extremidade "
            "fechada, que se move alternadamente dentro de um cilindro externo oco para alterar seu "
            "volume interno a fim de descarregar líquido ou gás pressurizado.",
        source_definitions_used=[{"source": "iso15926", "term": "PISTON"}],
        component_of="diesel engine",
    ),

    # ── separation ──────────────────────────────────────────────────────────
    dict(
        cluster_label="filter medium",
        label_pt="meio filtrante",
        function_name="SelectivePermeabilityFunction",
        process_name="FiltrationProcess",
        function_rationale="SLB defines it as 'a permeable material ... through which filtrate "
            "passes and on which the filter cake is deposited'. Its identity-giving function is "
            "selective permeability — passing one phase while retaining another — which is "
            "narrower than the filtration function borne by a filter as a whole.",
        genus="MaterialArtifact", genus_bfo_root="MaterialArtifact",
        genus_rationale="SLB calls it a permeable material used in a filtration device; as an "
            "engineered barrier it is a MaterialArtifact.",
        differentia_expression="∃bearerOf.SelectivePermeabilityFunction ⊓ ∃componentPartOf.Filter",
        differentia_nl="A material artifact that is a permeable barrier within a filtration device, "
            "passing filtrate while retaining the deposited solids.",
        differentia_rationale="Necessary-only and deliberately given a function distinct from the "
            "Filter entry's FiltrationFunction. Filter is defined as equivalent on "
            "FiltrationFunction; reusing that function here would let the reasoner infer that the "
            "medium is the filter.",
        axiom_mode="necessary",
        primitive_rationale="The medium is a component of the filter, not a filter; the distinction "
            "rests on parthood, which is not a sufficient condition.",
        process_signature=sig(
            [p("FluidMixture", "unfiltered stream carrying suspended solids")],
            [p("PortionOfFluid", "filtrate passing through the medium"),
             p("RemovedMaterial", "filter cake deposited on the medium")],
            "separation of suspended solids from a fluid by selective passage through a "
            "permeable barrier",
            "mechanical_filtration",
            rationale="Two outputs, matching the SLB definition: the filtrate that passes and the "
                      "cake that is retained."),
        nl_definition_en="A material artifact that is a permeable material used in a filtration "
            "device, through which filtrate passes and on which the filter cake is deposited.",
        nl_definition_pt="Um artefato material que é um material permeável usado em um dispositivo "
            "de filtração, através do qual passa o filtrado e sobre o qual se deposita a torta "
            "de filtração.",
        source_definitions_used=[{"source": "slb_glossary", "term": "filter medium"}],
        component_of="filter press",
    ),

    # ── wellhead ────────────────────────────────────────────────────────────
    dict(
        cluster_label="tubing bowl",
        label_pt="alojamento da coluna de produção",
        function_name="TubingHangerSeatingFunction",
        process_name="TubingHangerSeatingProcess",
        function_rationale="OnePetro defines it entirely by what it receives: 'a section in a part "
            "of the wellhead that accommodates the tubing hanger'. Accommodating and seating the "
            "hanger is the identity-giving function.",
        genus="MaterialArtifact", genus_bfo_root="MaterialArtifact",
        genus_rationale="A machined seating profile within the tubing head; MaterialArtifact is "
            "the correct IOF root.",
        differentia_expression="∃bearerOf.TubingHangerSeatingFunction ⊓ ∃componentPartOf.TubingHead",
        differentia_nl="A material artifact that is the profiled section of a tubing head in which "
            "the tubing hanger sets and seals.",
        differentia_rationale="Necessary-only: the definition is positional ('a section in a part "
            "of the wellhead'), so the function alone is not sufficient.",
        axiom_mode="necessary",
        primitive_rationale="Definition locates it within the wellhead rather than characterising "
            "it independently; parthood is not a sufficient condition.",
        process_signature=sig(
            [], [],
            "seating and sealing of a tubing hanger within the wellhead",
            "structural_support", "proposed",
            "The controlled vocabulary has no term for bearing or seating another artifact.",
            rationale="No admissible participants: what the bowl receives is the tubing hanger, an "
                      "equipment part, and ODR-010 §5 excludes artifacts as hasInput/"
                      "hasSpecifiedOutput fillers."),
        nl_definition_en="A material artifact that is the section of a tubing head which "
            "accommodates the tubing hanger, where it sets and seals.",
        nl_definition_pt="Um artefato material que é a seção de uma cabeça de produção que acomoda "
            "o suspensor da coluna, onde este assenta e veda.",
        source_definitions_used=[{"source": "onepetro_glossary", "term": "Tubing bowl"}],
        component_of="tubing head",
    ),
]


def build_row(e: dict) -> dict:
    return {
        "cluster_label": e["cluster_label"],
        "label_pt": e["label_pt"],
        "function_name": e["function_name"],
        "function_parent": "DesignedFunction",
        "process_name": e["process_name"],
        "process_parent": "PlannedProcess",
        "function_rationale": e["function_rationale"],
        "genus": e["genus"],
        "genus_bfo_root": e["genus_bfo_root"],
        "genus_rationale": e["genus_rationale"],
        "differentia_expression": e["differentia_expression"],
        "differentia_nl": e["differentia_nl"],
        "differentia_rationale": e["differentia_rationale"],
        "necessary_parts": "[]",
        "parts_rationale": (
            "No sub-component is named in any source definition for this term. "
            "validate_necessary_parts_quotes() requires a verbatim source_quote for every part, "
            "and there is nothing to quote — so no parts are asserted (ODR-022 §10.2)."
        ),
        "process_signature": e["process_signature"],
        "axiom_mode": e["axiom_mode"],
        "primitive_rationale": e.get("primitive_rationale"),
        "nl_definition_en": e["nl_definition_en"],
        "nl_definition_pt": e["nl_definition_pt"],
        "source_definitions_used": json.dumps(e["source_definitions_used"], ensure_ascii=False),
        "qualities": json.dumps(e.get("qualities", []), ensure_ascii=False),
        "status": "proposed",
        "llm_model": MODEL,
        "reviewer_notes": (
            f"ODR-022 §O6: standard-term component of '{e['component_of']}'. Admitted to the "
            f"pipeline because it is a term in a source standard AND that standard states it is a "
            f"component of that equipment (verbatim source_quote in the owning entry). "
            f"Awaiting expert review."
        ),
    }


def main(apply: bool) -> int:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    existing = {r["cluster_label"] for r in con.execute("SELECT cluster_label FROM enrichment")}
    dupes = [e["cluster_label"] for e in ENTRIES if e["cluster_label"] in existing]
    if dupes:
        print("ERROR — these cluster_labels already exist:", dupes)
        con.close()
        return 1

    for e in ENTRIES:
        row = build_row(e)
        print(f"  {row['cluster_label']:<32} genus={row['genus']:<18} "
              f"mode={row['axiom_mode']:<10} fn={row['function_name']}")
        if apply:
            cols = ", ".join(row)
            ph = ", ".join("?" for _ in row)
            con.execute(f"INSERT INTO enrichment ({cols}) VALUES ({ph})", tuple(row.values()))

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
    a = ap.parse_args()
    sys.exit(main(apply=a.apply))
