"""
ISA 5.1-2022 parser: Instrumentation Symbols and Identification.

Extracts:
  1. Section 3 definitions (~60 instrument/automation terms)
     Pattern: "3.1.N term name:\ndefinition text"
     term_type = "ISA Definition"

  2. Table 4.1 identification letters (page 28, 6-column table):
     - First-letter meanings (measured/initiating variable)
     - Succeeding-letter meanings (readout, active function, modifier)
     term_type = "ISA Letter Code"

  3. Tag abbreviation expansions (built-in, derived from letter codes):
     e.g. FCV = Flow Control Valve, PSV = Pressure Safety Valve
     term_type = "ISA Tag Abbreviation"

Place the PDF at: data/raw/isa5_1/ISA-5.1-2022.pdf  (any *.pdf will work)

Note: graphical P&ID symbols are not extractable from PDF and are not included.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from config import DATA_DIR
from parsers.base import BaseParser, ParsedTerm

logger = logging.getLogger(__name__)

_RAW_DIR = DATA_DIR / "isa5_1"
_BASE_URI = "https://www.isa.org/standards-and-publications/isa-standards/isa-standards-committees/isa5"

# Pages of Table 4.1 (0-indexed). The 2022 edition has it on page 28.
_TABLE_PAGES = list(range(27, 32))
# Pages of Section 3 definitions (0-indexed).
_DEF_PAGES = list(range(15, 23))

# Built-in tag abbreviations — common P&ID tag prefixes with plain-English expansions.
_TAG_ABBREVIATIONS: dict[str, str] = {
    "AIT": "Analyser Indicating Transmitter",
    "AT":  "Analyser Transmitter",
    "EV":  "Voltage-controlled Valve",
    "FAL": "Flow Alarm Low",
    "FAH": "Flow Alarm High",
    "FCV": "Flow Control Valve",
    "FE":  "Flow Sensor / Primary Element",
    "FIC": "Flow Indicating Controller",
    "FIT": "Flow Indicating Transmitter",
    "FT":  "Flow Transmitter",
    "HCV": "Hand Control Valve",
    "LAL": "Level Alarm Low",
    "LAH": "Level Alarm High",
    "LCV": "Level Control Valve",
    "LE":  "Level Sensor / Primary Element",
    "LIC": "Level Indicating Controller",
    "LIT": "Level Indicating Transmitter",
    "LT":  "Level Transmitter",
    "PAL": "Pressure Alarm Low",
    "PAH": "Pressure Alarm High",
    "PCV": "Pressure Control Valve",
    "PE":  "Pressure Sensor / Primary Element",
    "PIC": "Pressure Indicating Controller",
    "PIT": "Pressure Indicating Transmitter",
    "PRV": "Pressure Relief Valve",
    "PSV": "Pressure Safety Valve",
    "PT":  "Pressure Transmitter",
    "SDV": "Shutdown Valve",
    "TAL": "Temperature Alarm Low",
    "TAH": "Temperature Alarm High",
    "TCV": "Temperature Control Valve",
    "TE":  "Temperature Sensor / Primary Element",
    "TIC": "Temperature Indicating Controller",
    "TIT": "Temperature Indicating Transmitter",
    "TT":  "Temperature Transmitter",
    "XV":  "On/Off Valve (unclassified variable)",
    "XCV": "Unclassified Control Valve",
    "ZCV": "Position Control Valve",
    "ZT":  "Position Transmitter",
}

# Regex to strip ISA note references like "(2)", "(23a)"
_NOTE_RE = re.compile(r'\s*\(\s*\d+[a-z]?\s*\)')
# Regex for Section 3 numbered definitions: "3.1.N term name:\n"
_DEF_RE = re.compile(
    r'3\.1\.(\d+)\s+([^\n:]+?):\s*\n(.*?)(?=3\.1\.\d+|\Z)',
    re.DOTALL,
)


class ISA51Parser(BaseParser):
    source_name = "isa5_1"

    def parse(self) -> list[ParsedTerm]:
        pdfs = list(_RAW_DIR.glob("*.pdf"))
        if not pdfs:
            logger.warning(
                "ISA 5.1: no PDF in %s — emitting built-in tag abbreviations only.",
                _RAW_DIR,
            )
            return self._tag_abbreviation_terms({}, {})

        pdf_path = pdfs[0]
        logger.info("ISA 5.1: parsing %s", pdf_path.name)

        try:
            import pdfplumber
            with pdfplumber.open(str(pdf_path)) as pdf:
                definitions = self._extract_definitions(pdf)
                first_letters, succ_letters = self._extract_letter_table(pdf)
        except Exception as exc:
            logger.error("ISA 5.1: PDF parsing failed (%s)", exc)
            definitions, first_letters, succ_letters = [], {}, {}

        terms: list[ParsedTerm] = []
        terms.extend(definitions)
        terms.extend(self._letter_code_terms(first_letters, succ_letters))
        terms.extend(self._tag_abbreviation_terms(first_letters, succ_letters))

        logger.info("ISA 5.1: %d terms total", len(terms))
        return terms

    # ── Section 3: definitions ────────────────────────────────────────────────

    def _extract_definitions(self, pdf) -> list[ParsedTerm]:
        """Extract numbered definitions from Section 3 (pages 16–22)."""
        # Concatenate text from definition pages
        full_text = ""
        for i in _DEF_PAGES:
            if i < len(pdf.pages):
                full_text += (pdf.pages[i].extract_text() or "") + "\n"

        terms: list[ParsedTerm] = []
        for m in _DEF_RE.finditer(full_text):
            num   = m.group(1).strip()
            label = m.group(2).strip()
            body  = m.group(3).strip()

            # Keep only the first sentence/paragraph (before sub-items a), b))
            body = re.split(r'\n[a-z]\)', body)[0].strip()
            # Collapse internal newlines
            body = re.sub(r'\s+', ' ', body).strip()
            if len(body) < 10:
                continue

            terms.append(ParsedTerm(
                preferred_label=label,
                source=self.source_name,
                source_id=f"def_3_1_{num}",
                source_uri=_BASE_URI,
                definition=body,
                term_type="ISA Definition",
            ))

        logger.info("ISA 5.1: %d Section 3 definitions extracted", len(terms))
        return terms

    # ── Table 4.1: letter codes ───────────────────────────────────────────────

    def _extract_letter_table(self, pdf) -> tuple[dict[str, str], dict[str, str]]:
        """
        Parse Table 4.1.  Returns:
          first_letters:  {A: 'Analysis', F: 'Flow, Flow Rate', ...}
          succ_letters:   {A: 'Alarm', C: 'Control', V: 'Valve, Damper, Louver', ...}
        """
        first: dict[str, str] = {}
        succ:  dict[str, str] = {}

        for i in _TABLE_PAGES:
            if i >= len(pdf.pages):
                break
            for table in pdf.pages[i].extract_tables():
                for row in table:
                    if not row:
                        continue
                    letter = (row[0] or "").strip()
                    if not re.match(r'^[A-Z]$', letter):
                        continue

                    first_meaning = _clean(row[1] if len(row) > 1 else "")
                    readout_fn    = _clean(row[3] if len(row) > 3 else "")
                    active_fn     = _clean(row[4] if len(row) > 4 else "")
                    fn_modifier   = _clean(row[5] if len(row) > 5 else "")

                    if first_meaning:
                        first[letter] = first_meaning
                    # Succeeding-letter meaning: prefer active function, fall back to readout
                    succ_meaning = active_fn or readout_fn or fn_modifier
                    if succ_meaning:
                        succ[letter] = succ_meaning

        logger.info("ISA 5.1: %d first-letters, %d succ-letters from Table 4.1",
                    len(first), len(succ))
        return first, succ

    def _letter_code_terms(
        self,
        first: dict[str, str],
        succ:  dict[str, str],
    ) -> list[ParsedTerm]:
        terms: list[ParsedTerm] = []

        for letter, meaning in first.items():
            terms.append(ParsedTerm(
                preferred_label=f"{letter} (first letter)",
                source=self.source_name,
                source_id=f"first_{letter}",
                source_uri=_BASE_URI,
                definition=(
                    f"ISA 5.1 first letter '{letter}': measured or initiating variable — {meaning}."
                ),
                term_type="ISA Letter Code — First Letter",
            ))

        for letter, meaning in succ.items():
            terms.append(ParsedTerm(
                preferred_label=f"{letter} (succeeding letter)",
                source=self.source_name,
                source_id=f"succ_{letter}",
                source_uri=_BASE_URI,
                definition=(
                    f"ISA 5.1 succeeding letter '{letter}': function/readout/output — {meaning}."
                ),
                term_type="ISA Letter Code — Succeeding Letter",
            ))

        return terms

    # ── Tag abbreviations ─────────────────────────────────────────────────────

    def _tag_abbreviation_terms(
        self,
        first: dict[str, str],
        succ:  dict[str, str],
    ) -> list[ParsedTerm]:
        terms: list[ParsedTerm] = []
        for code, expansion in _TAG_ABBREVIATIONS.items():
            first_meaning = first.get(code[0], "unclassified")
            succ_parts = ", ".join(
                f"'{c}' = {succ.get(c, 'unclassified')}"
                for c in code[1:]
            )
            terms.append(ParsedTerm(
                preferred_label=expansion,
                source=self.source_name,
                source_id=f"tag_{code}",
                source_uri=_BASE_URI,
                definition=(
                    f"ISA 5.1 tag abbreviation '{code}'. "
                    f"First letter '{code[0]}': {first_meaning}. "
                    f"Succeeding letters: {succ_parts}."
                ),
                term_type="ISA Tag Abbreviation",
            ))
        return terms


def _clean(s: str | None) -> str:
    if not s:
        return ""
    s = _NOTE_RE.sub("", s)
    return re.sub(r'\s+', ' ', s).strip()
