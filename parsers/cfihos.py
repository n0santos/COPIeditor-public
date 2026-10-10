"""
CFIHOS Reference Data Library parser.

Supports the two known CFIHOS file formats:
  - C-ST-001-Extended-Reference-Data-Library-*.xlsx   (Extended RDL)
  - CORE-CFIHOS-V*.xlsx                               (Core)

Both files share the same CFIHOS unique codes. The Extended RDL is processed
first as the primary source; the Core file supplements missing definitions.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd

from config import DATA_DIR
from parsers.base import BaseParser, ParsedProperty, ParsedTerm

logger = logging.getLogger(__name__)

# CFIHOS has no stable per-term deep links, so every term points to the
# official standard homepage (IOGP JIP36) as a citation for the definition.
_BASE_URI = "https://www.jip36-cfihos.org/"


def _df(xl: pd.ExcelFile, sheet: str) -> pd.DataFrame | None:
    if sheet not in xl.sheet_names:
        return None
    return xl.parse(sheet, dtype=str).fillna("")


def _val(row: pd.Series, col: str) -> str:
    v = row.get(col, "")
    return str(v).strip() if v else ""


class CFIHOSParser(BaseParser):
    source_name = "cfihos"

    def parse(self) -> list[ParsedTerm]:
        raw_dir = DATA_DIR / "cfihos"
        xlsx_files = sorted(raw_dir.glob("*.xlsx")) + sorted(raw_dir.glob("*.xls"))

        if not xlsx_files:
            logger.warning("CFIHOS: no Excel files found in data/raw/cfihos/")
            return []

        # Classify files
        extended_files = [
            f for f in xlsx_files if "C-ST-001" in f.name or "extended" in f.name.lower()
        ]
        core_files = [
            f for f in xlsx_files
            if f not in extended_files and ("CORE" in f.name.upper() or "CFIHOS" in f.name.upper())
        ]
        remaining = [f for f in xlsx_files if f not in extended_files and f not in core_files]
        # Process Extended RDL first, then Core, then anything else
        ordered = extended_files + core_files + remaining

        terms: dict[str, ParsedTerm] = {}
        prop_defs: dict[str, ParsedProperty] = {}  # property name → base definition

        for filepath in ordered:
            logger.info("CFIHOS: reading %s", filepath.name)
            try:
                xl = pd.ExcelFile(filepath)
            except Exception as exc:
                logger.error("  Cannot open: %s", exc)
                continue

            sheets = xl.sheet_names
            is_extended = "tag or equipment class" in sheets
            is_core = "tag class" in sheets or "equipment class" in sheets

            if is_extended:
                self._parse_extended(xl, terms, prop_defs)
            elif is_core:
                self._parse_core(xl, terms, prop_defs)
            else:
                logger.warning("  Unrecognised CFIHOS format in %s, skipping", filepath.name)

        logger.info("CFIHOS: %d terms total", len(terms))
        return list(terms.values())

    # ------------------------------------------------------------------
    # Extended RDL  (C-ST-001)
    # ------------------------------------------------------------------

    def _parse_extended(
        self,
        xl: pd.ExcelFile,
        terms: dict[str, ParsedTerm],
        prop_defs: dict[str, ParsedProperty],
    ) -> None:
        # 1 — property definitions
        prop_sheet = _df(xl, "property")
        if prop_sheet is not None:
            for _, row in prop_sheet.iterrows():
                status = _val(row, "status")
                if status == "TERMINATED":
                    continue
                name = _val(row, "property name")
                if not name:
                    continue
                prop_defs[name.lower()] = ParsedProperty(
                    name=name,
                    definition=_val(row, "property definition") or None,
                    datatype=_val(row, "property data type") or None,
                    unit=_val(row, "unit of measure dimension code") or None,
                )

        # 2 — class definitions
        class_sheet = _df(xl, "tag or equipment class")
        if class_sheet is None:
            logger.warning("  Sheet 'tag or equipment class' not found")
            return

        name_to_id: dict[str, str] = {}

        for _, row in class_sheet.iterrows():
            status = _val(row, "status")
            if status == "TERMINATED":
                continue

            source_id = _val(row, "CFIHOS unique code")
            # "tag or equipment class name.1" is the clean label (no index suffix)
            label = _val(row, "tag or equipment class name.1") or _val(row, "tag or equipment class name")
            if not source_id or not label:
                continue

            definition = _val(row, "tag or equipment class definition") or None

            tc = _val(row, "tag class indicator").lower() == "yes"
            ec = _val(row, "equipment class indicator").lower() == "yes"
            abstract = _val(row, "abstract class indicator").lower() == "yes"
            if tc and ec:
                term_type = "TagAndEquipmentClass"
            elif tc:
                term_type = "TagClass"
            elif ec:
                term_type = "EquipmentClass"
            else:
                term_type = "Class"
            if abstract:
                term_type = "Abstract" + term_type

            parent_name = _val(row, "parent tag or equipment class name") or None

            if source_id not in terms:
                terms[source_id] = ParsedTerm(
                    preferred_label=label,
                    source=self.source_name,
                    source_id=source_id,
                    definition=definition,
                    term_type=term_type,
                    source_uri=_BASE_URI,
                )
            else:
                # Supplement missing fields
                t = terms[source_id]
                if not t.definition and definition:
                    t.definition = definition

            name_to_id[label.lower()] = source_id

            if parent_name:
                # Store temporarily; resolve after all rows processed
                terms[source_id]._parent_name = parent_name  # type: ignore[attr-defined]

        # 3 — resolve parent names to IDs
        for term in terms.values():
            pname = getattr(term, "_parent_name", None)
            if pname:
                parent_id = name_to_id.get(pname.lower())
                if parent_id and parent_id not in term.parent_source_ids:
                    term.parent_source_ids.append(parent_id)
                del term._parent_name  # type: ignore[attr-defined]

        # 4 — synonyms
        syn_sheet = _df(xl, "tag or equipment synonym")
        if syn_sheet is not None:
            for _, row in syn_sheet.iterrows():
                status = _val(row, "status")
                if status == "TERMINATED":
                    continue
                class_name = _val(row, "tag or equipment class name")
                raw_syns = _val(row, "tag or equipment class synonym name")
                if not class_name or not raw_syns:
                    continue
                source_id = name_to_id.get(class_name.lower())
                if not source_id or source_id not in terms:
                    continue
                for syn in raw_syns.split(";"):
                    syn = syn.strip()
                    if syn and syn not in terms[source_id].synonyms:
                        terms[source_id].synonyms.append(syn)

        # 5 — properties per class
        for sheet_name, id_col in [
            ("tag class property", "tag class CFIHOS unique code"),
            ("equipment class property", "equipment class CFIHOS unique code"),
        ]:
            prop_sheet_cls = _df(xl, sheet_name)
            if prop_sheet_cls is None:
                continue

            # Build a mapping: class_id → [(prop_name, unit)]
            for _, row in prop_sheet_cls.iterrows():
                status = _val(row, "status")
                if status == "TERMINATED":
                    continue
                class_id = _val(row, id_col)
                prop_name = _val(row, "property name")
                if not class_id or not prop_name or class_id not in terms:
                    continue

                unit = _val(row, "SI unit of measure name") or None
                base = prop_defs.get(prop_name.lower())

                # Avoid duplicate property names per class
                existing = {p.name.lower() for p in terms[class_id].properties}
                if prop_name.lower() in existing:
                    continue

                terms[class_id].properties.append(
                    ParsedProperty(
                        name=prop_name,
                        definition=base.definition if base else None,
                        datatype=base.datatype if base else None,
                        unit=unit or (base.unit if base else None),
                    )
                )

    # ------------------------------------------------------------------
    # Core V2  (CORE-CFIHOS-V2.0)
    # ------------------------------------------------------------------

    def _parse_core(
        self,
        xl: pd.ExcelFile,
        terms: dict[str, ParsedTerm],
        prop_defs: dict[str, ParsedProperty],
    ) -> None:
        # property definitions
        prop_sheet = _df(xl, "property")
        if prop_sheet is not None:
            for _, row in prop_sheet.iterrows():
                name = _val(row, "property name")
                if not name or name.lower() in prop_defs:
                    continue
                prop_defs[name.lower()] = ParsedProperty(
                    name=name,
                    definition=_val(row, "property definition") or None,
                    datatype=_val(row, "property data type") or None,
                    unit=_val(row, "unit of measure dimension code") or None,
                )

        name_to_id: dict[str, str] = {}

        # Process tag class + equipment class sheets (may overlap on codes)
        for sheet_name, id_col, label_col, def_col, parent_col, syn_col in [
            (
                "tag class",
                "CFIHOS unique code",
                "tag class name",
                "tag class definition",
                "parent tag class name",
                "tag class synonym",
            ),
            (
                "equipment class",
                "equipment class CFIHOS unique code",
                "equipment class name",
                "equipment class definition",
                "parent equipment class name",
                "equipment class synonym name",
            ),
        ]:
            sheet = _df(xl, sheet_name)
            if sheet is None:
                continue

            for _, row in sheet.iterrows():
                source_id = _val(row, id_col)
                label = _val(row, label_col)
                if not source_id or not label:
                    continue

                definition = _val(row, def_col) or None
                parent_name = _val(row, parent_col) or None
                abstract = _val(row, "abstract class indicator").lower() == "yes"
                term_type = ("Abstract" if abstract else "") + (
                    "TagClass" if "tag" in sheet_name else "EquipmentClass"
                )

                if source_id not in terms:
                    terms[source_id] = ParsedTerm(
                        preferred_label=label,
                        source=self.source_name,
                        source_id=source_id,
                        definition=definition,
                        term_type=term_type,
                        source_uri=_BASE_URI,
                    )
                else:
                    t = terms[source_id]
                    if not t.definition and definition:
                        t.definition = definition

                name_to_id[label.lower()] = source_id

                # Synonyms from inline column (Core V2 style)
                raw_syns = _val(row, syn_col)
                if raw_syns:
                    for syn in re.split(r'[;,]', raw_syns):
                        syn = syn.strip()
                        if syn and syn != label and syn not in terms[source_id].synonyms:
                            terms[source_id].synonyms.append(syn)

                if parent_name:
                    terms[source_id]._parent_name_core = parent_name  # type: ignore[attr-defined]

        # Resolve parent names
        for term in terms.values():
            pname = getattr(term, "_parent_name_core", None)
            if pname:
                parent_id = name_to_id.get(pname.lower())
                if parent_id and parent_id not in term.parent_source_ids:
                    term.parent_source_ids.append(parent_id)
                del term._parent_name_core  # type: ignore[attr-defined]

        # Properties per class
        for sheet_name, id_col in [
            ("tag class property", "tag class CFIHOS unique code"),
            ("equipment class property", "equipment class CFIHOS unique code"),
        ]:
            sheet = _df(xl, sheet_name)
            if sheet is None:
                continue
            for _, row in sheet.iterrows():
                class_id = _val(row, id_col)
                prop_name = _val(row, "property name")
                if not class_id or not prop_name or class_id not in terms:
                    continue

                unit = _val(row, "SI unit of measure name") or None
                base = prop_defs.get(prop_name.lower())
                existing = {p.name.lower() for p in terms[class_id].properties}
                if prop_name.lower() in existing:
                    continue

                terms[class_id].properties.append(
                    ParsedProperty(
                        name=prop_name,
                        definition=base.definition if base else None,
                        datatype=base.datatype if base else None,
                        unit=unit or (base.unit if base else None),
                    )
                )
