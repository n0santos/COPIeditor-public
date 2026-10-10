# IEC 81346-2:2019 as a coverage reference for COPI-Core

Date: 2026-09-14. Status: **finding, not a decision.** Updated the same day with Table 2 of the full standard.

## Question

COPI-Core has nine operation / equipment categories (8 subclasses of Operation `COPI_0000001`
plus measurement). The COPI-Core anchoring gate (`scripts/check_core_anchoring.py`) found 118
validated entries that either reach no operation (90) or disagree with their
`transformation_kind` (28). `core-expansion-literature-scoping.md` found no BFO/IOF-aligned
reference for the uncovered clusters (power generation; electrical; mechanical power
transmission and structural support). Is there a standard that enumerates *all* functions of the
objects in a plant, so COPI-Core's coverage can be checked against it?

## Source

IEC 81346-2:2019, *Industrial systems, installations and equipment and industrial products —
Structuring principles and reference designations — Part 2: Classification of objects and codes
for classes*, Edition 2.0 (2019-06). Free sample preview:
<https://cdn.standards.iteh.ai/samples/21908/1b996d119d0945b2b28359332ffa9b3f/IEC-81346-2-2019.pdf>
(access: `WebFetch` could not extract text; recovered with `pdftotext -layout`).

The preview contains clauses 1–5.2 in full and Table 2 only up to class C. **Table 2 (all two-level
sub-classes) was then read from the full standard** (a copy supplied by the author, an image scan:
OCR with `pdftoppm -r 300` + `tesseract --psm 4`, pages rotated 90°). Sub-class placements below
marked ✓ are confirmed by an example term listed in Table 2 itself; the rest stay at entry-class
level. Table 3 (third level) was not read.

## What the standard says (verbatim)

- 3.1 *inherent function*: "function of an object, independent of any application of the object"
- 3.3 *class of object*: "set of objects characterized by the same inherent function"
- 4.3: "The classification tables of this document are considered to be complete, and therefore
  no “miscellaneous” or “other” classes are present. If no appropriate class for an
  object-of-interest can be found on a sub or sub-sub level, objects shall be classified to the
  higher level i.e. to the sub-class or entry class."
- Clause 1 (scope): "The classification schemes are applicable for objects in all technical
  disciplines and all branches of industry." The foreword states it "has the status of a
  horizontal standard in accordance with IEC Guide 108".

**Table 1 – Entry classes**

| Code | Class definition | Class name |
|---|---|---|
| B | object for picking up information and providing a representation | sensing object |
| C | object for storing for subsequent retrieval | storing object |
| E | object for emitting | emitting object |
| F | object for protecting against the effects of dangerous or undesirable conditions | protecting object |
| G | object for providing a controllable flow | generating object |
| H | object for treating matter | matter processing object |
| K | object for treating input signals and providing an appropriate output | information processing object |
| M | object for providing mechanical movement or force | driving object |
| N | object for enclosing partly or fully another object | covering object |
| P | object for providing perceptible information | presenting object |
| Q | object for controlling access or flow | controlling object |
| R | object for restricting or stabilising | restricting object |
| S | object for detecting a human action and providing an appropriate response | human interaction object |
| T | object for transforming | transforming object |
| U | object for localising of other objects | holding object |
| W | object for leading from one place to another | guiding object |
| X | object for interfacing an object | interfacing object |

"The letters A, I and O shall not be used as a class code. The letters D, J, L, V, Y and Z are
reserved for future standardization."

Verified sub-class examples in the preview: CM "storing object for matters within a stationary
closed enclosure" (box, cabinet, cupboard, tank); CN "… within a moveable closed enclosure"
(container, drum, …, gas cylinder); BF flow sensing, BL level sensing, BP pressure sensing
(… manometer …), BT temperature sensing.

## Why it fits what COPI needs

1. **Same identity criterion.** "Inherent function, independent of any application" is COPI's
   identity-giving designed function (rigid, not a role) — the same reason a stake "is a stake no
   matter what individual is used to realize the occurrence" (4.1).
2. **Claims completeness** for all technical disciplines, with an explicit rule to classify at the
   entry level when no sub-class fits — exactly the "enumerate every function in a plant" property
   the core-expansion search was looking for.
3. **Horizontal standard** (IEC Guide 108), already cited in ODR-015 as an annotation reference.

## Correspondence with COPI-Core (sub-classes from Table 2)

| COPI-Core category | IEC 81346-2 sub-class(es) — example terms quoted from Table 2 |
|---|---|
| measurement instrument | B sensing — ✓ BF flow (flow sensor, flow transmitter), BL level, BP pressure (manometer), BT temperature; P presenting |
| containment device | C storing — ✓ CM (tank), CN (container, drum, gas cylinder) |
| flow-control device | Q controlling — ✓ QM (gas/liquid shutoff valve), QN (gas/liquid control valve); R restricting — ✓ RM (non-return valve), RN (orifice plate, fixed/adjustable nozzle, regulation valve) |
| momentum-transfer device | G generating — ✓ GP liquid flow (centrifugal pump, rotary gear pump, impeller), GQ gas flow (gas compressor, mechanical fan) |
| heat-transfer device | E emitting — ✓ EG thermal energy transfer (heat exchanger, heat pump), EM combustion heating (burner, combustion boiler), EP thermal heating (condenser, heating coil), EQ thermal cooling (chiller, cooler) |
| mechanical-separation device | H — ✓ HM force separating (centrifuge, cyclone, hydrocyclone, settling tank), HQ mechanical separating (filter) |
| mass-transfer device | H — ✓ HS chemical separating (absorber, adsorber), HP thermal separating (distillation column, evaporator) |
| chemical reactor | H — ✓ HX reacting (chemical reactor) |
| phase-change device | H — ✓ HP thermal separating (evaporator, dryer) |

**Sub-classes with no COPI-Core category** — verified placements of the 118 anchoring findings:

| Sub-class (Table 2) | Example terms in Table 2 | Findings it takes |
|---|---|---|
| WP guiding matter flow in closed enclosure | chimney, duct, hose, pipe | pipe, riser, flexible riser, flowline, hose |
| WQ guiding mechanical energy | axle, drive axle, gearwheel, wheel, drive belt | shaft, drive/input/output/pump shaft, gear wheel, sheave |
| WZ guiding multiple kinds of flows | umbilical, umbilical cable | umbilical |
| XM interfacing sealed material flow | pipe fitting, pipe flange, hose coupler, pipe coupler | pipe bend, elbow, tee, reducer, flange, quick connector |
| XN non-detachable coupling / XD LV connecting | flexible coupling; plug, socket, electric terminal | coupling; electrical connector |
| MA / MB / MM / ML / MS driving | electric motor; actuator, solenoid; hydraulic/pneumatic cylinder and motor; gas/water turbine; Diesel/Otto engine | motors, actuators, turbines, engines |
| TL transforming mechanical energy | gear, speed convertor, torque converter | gearbox |
| TA transforming electric energy | transformer, isolating transformer | power transformer, transformer |
| GA generating electric energy | AC/DC generator | electric generator |
| QA controlling electric current | circuit breaker, contactor, electronic power switch | circuit breaker, electrical switch |
| RB stabilising electric energy | uninterruptible power supply, UPS | UPS unit |
| RL restricting movements | brake, shock absorber | brake, damper |
| UB carrying / UP jointing / UQ fastening / UC enclosing / UL structural | cable tray, hanger, equipment support structure; bearing; expansion joint; sensor housing, electric panel; plate | cable tray, tubing hanger, skid; bearing; expansion joint; transmitter housing, housing, panel; thin plate |
| NA filling an opening | gasket, gland, sealing joint | gasket |
| FS local environment / FC overcurrents | cathodic protection; fuse | cathodic protection system; fuse |
| HU grinding and crushing | mill, crusher | mill |

66 of the 118 findings have a verified sub-class; the other 52 (casings, windings, stator, pig
launcher/receiver/trap, controller, relay, thermowell, chromatographs, …) are entry-class guesses.

**Observations the verification surfaced**

- **Pipe fittings are interfacing (XM), not guiding (W).** Only pipe and hose are WP; bends, tees,
  reducers and flanges join sections.
- **Shafts guide mechanical energy (WQ); only gears transform it (TL).** The "mechanical power
  transmission" cluster splits across W, T, X (couplings) and U (bearings).
- **Instrument housings and panels are holding objects (UC)**, not covering (N) — N is for closing
  or filling openings (NA gasket).
- **Orifice plate is RN "restricting a guided flow of matter"** by inherent function; COPI models it
  as a flow measuring element (genus FlowElement). The standard treats the measurement as an
  application. Worth an explicit decision.
- **Passive guiding of matter (WP) is the largest single gap** among the findings, and COPI's own
  scope note names "transport" — COPI-Core has no operation for it.
- Well and wellbore are not in the Table 2 object scheme at all (clause 7 covers infrastructure
  objects; not read).

## Caveats

- IEC 81346-2 classifies **objects**, not processes. COPI-Core pairs each equipment category with
  an operation; adopting a class means deciding its process counterpart (e.g. W → a guiding /
  conveying process) — the classification does not supply BFO process semantics.
- Not BFO/IOF-aligned; class definitions are one line. It is a coverage checklist and a naming
  source, not an importable ontology.
- The object-level classes mix component parts (winding, stem, casing) with equipment; COPI's
  component-part policy (ODR-022 §2) still decides admission.
- Sub-class codes above come from OCR of a scanned copy; each ✓ placement was checked against the
  quoted example term, but the OCR can garble codes (e.g. "Ww", "Tc"). Table 3 (third level) and
  clause 7 (infrastructure) were not read.

## Related

- `docs/findings/core-expansion-literature-scoping.md` — prior search, same gap clusters
- `docs/findings/drilling-equipment-scope-question.md` — drill bit, BHA, well, wellbore findings
- `enrichment/core_operations.py` — `KIND_TO_OPERATIONS`
- ISO 81346-10:2022 sample preview is also on iteh — not read yet
