"""
PPDM Association — "What is a Well?" (R-2.4, September 2014)

Extracts ~9 core well component definitions:
  Well Set, Well, Well Origin, Wellbore, Wellbore Segment,
  Wellbore Contact Interval, Wellbore Completion,
  Wellhead Stream, Well Reporting Stream

Each term includes: Definition + Key Concept(s) + Clarification.

Requires: pdfplumber  (pip install pdfplumber)
Place the PDF in data/raw/ppdm/ (any *.pdf file found there is used).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from config import DATA_DIR
from parsers.base import BaseParser, ParsedTerm

logger = logging.getLogger(__name__)

_RAW_DIR = DATA_DIR / "ppdm"

# Lines that are pure diagram noise (coordinate labels, copyright, page refs)
_NOISE_RE = re.compile(
    r"""^(?:
        (?:WO|WB|WHS|WRS|CI|C)\d+(?:[-–]\w+)*  # wellbore/completion labels
        | ®\s*Copyright                           # copyright line
        | PAGE\s+\d+                              # page number
        | www\.ppdm\.org                          # URL
        | \d+\s+www\.ppdm\.org                   # page + URL
        | Abandoned                               # diagram annotation
        | Active\s+Perforation                    # diagram annotation
        | Squeezed\s+Perforation                  # diagram annotation
        | WO\s*=.*                                # legend lines
        | WB\s*=.*
        | C\s*=.*
        | CI\s*=.*
        | WHS\s*=.*
        | WRS\s*=.*
    )$""",
    re.VERBOSE | re.IGNORECASE,
)

# Section headers within a definition page
_SECTION_RE = re.compile(
    r'^(Definition|Key Concept\(?s?\)?|Clarification|Diagram Note)\s*:?\s*$',
    re.IGNORECASE,
)

# Known parent relationships for hierarchy
_PARENTS: dict[str, list[str]] = {
    "well":                      ["well_set"],
    "well_origin":               ["well"],
    "wellbore":                  ["well"],
    "wellbore_segment":          ["wellbore"],
    "wellbore_contact_interval": ["wellbore", "wellbore_completion"],
    "wellbore_completion":       ["wellbore"],
    "wellhead_stream":           ["well"],
    "well_reporting_stream":     ["well"],
}


def _source_id(label: str) -> str:
    return label.lower().replace(" ", "_")


def _clean_lines(lines: list[str]) -> list[str]:
    """Remove noise lines and strip whitespace."""
    cleaned = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if _NOISE_RE.match(ln):
            continue
        cleaned.append(ln)
    return cleaned


def _parse_page(text: str) -> dict | None:
    """
    Parse a single PDF page text into a term dict.
    Returns None if the page does not contain a term definition.
    """
    if "Definition:" not in text and "Definition :" not in text:
        return None

    lines = text.splitlines()
    lines = _clean_lines(lines)

    # Extract term name: consecutive ALL-CAPS lines before the first section header
    term_lines: list[str] = []
    sections: dict[str, list[str]] = {}
    current_section: str | None = None

    for ln in lines:
        if _SECTION_RE.match(ln):
            key = _SECTION_RE.match(ln).group(1).lower().replace(" ", "_").rstrip("s").rstrip("(")
            # normalise "key_concept" variants
            if key.startswith("key"):
                key = "key_concept"
            current_section = key
            sections[current_section] = []
        elif current_section is None:
            # Still in the term name block
            # Skip if line looks like diagram coordinates
            if re.match(r'^[A-Z]{1,3}\d', ln):
                continue
            term_lines.append(ln)
        else:
            sections[current_section].append(ln)

    if not term_lines:
        return None

    # The term name is the last 1–3 uppercase lines before "Definition:"
    # Filter out any lowercase lines (intro text / page headers)
    name_parts = [ln for ln in term_lines if ln.isupper() or re.match(r'^[A-Z][A-Z\s]+$', ln)]
    if not name_parts:
        return None
    term_name = " ".join(name_parts).strip().title()

    # Build definition: Definition section, then append Key Concept and Clarification
    definition_parts: list[str] = []

    def_text = " ".join(sections.get("definition", [])).strip()
    if def_text:
        definition_parts.append(def_text)

    key_text = " ".join(sections.get("key_concept", [])).strip()
    if key_text:
        definition_parts.append(f"Key concept: {key_text}")

    clarification_text = " ".join(sections.get("clarification", [])).strip()
    if clarification_text:
        definition_parts.append(f"Clarification: {clarification_text}")

    if not definition_parts:
        return None

    return {
        "label": term_name,
        "source_id": _source_id(term_name),
        "definition": " ".join(definition_parts),
    }


class PPDMParser(BaseParser):
    """Parser for PPDM 'What is a Well?' R-2.4 (2014) PDF."""

    source_name = "ppdm"

    def parse(self) -> list[ParsedTerm]:
        try:
            import pdfplumber
        except ImportError:
            logger.error("pdfplumber not installed. Run: pip install pdfplumber")
            return []

        pdfs = list(_RAW_DIR.glob("*.pdf"))
        if not pdfs:
            logger.warning("No PDF found in %s", _RAW_DIR)
            return []

        pdf_path = pdfs[0]
        logger.info("Parsing PPDM PDF: %s", pdf_path.name)

        terms: list[ParsedTerm] = []
        seen: set[str] = set()

        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                result = _parse_page(text)
                if not result:
                    continue
                sid = result["source_id"]
                if sid in seen:
                    continue
                seen.add(sid)

                parents = _PARENTS.get(sid, [])

                terms.append(ParsedTerm(
                    preferred_label=result["label"],
                    source="ppdm",
                    source_id=sid,
                    source_uri="https://ppdm.org/ppdm/PPDM/Standards/What_is_a_Well/PPDM/Standards/What_is_a_Well.aspx",
                    definition=result["definition"],
                    term_type="Well Component",
                    parent_source_ids=parents,
                ))

        logger.info("PPDM: parsed %d terms", len(terms))
        return terms
