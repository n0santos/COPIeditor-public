"""
ISO 14224:2016 — Petroleum, petrochemical and natural gas industries:
Collection and exchange of reliability and maintenance data for equipment.

Extracts:
  • Section 3  — ~94 terms and definitions
  • Annex A, Table A.4   — ~78 equipment classes with category hierarchy
  • Annex A, Tables A.7+ — equipment-specific data attributes per class
  • Annex B, Tables B.6–B.15 — failure modes per equipment class (as properties)

Requires: pdfplumber  (pip install pdfplumber)
Place the PDF in data/raw/iso14224/ (any *.pdf file found there is used).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from config import DATA_DIR
from parsers.base import BaseParser, ParsedProperty, ParsedTerm

logger = logging.getLogger(__name__)

# Pages (0-indexed)
_SEC3_PAGES = range(9, 27)
_TABA4_PAGES = range(59, 68)
_ANNEX_A_PAGES = range(68, 183)

# Annex B failure mode tables (rotated 90°: equipment codes appear reversed)
_FM_ROTATED_PAGES: dict[str, list[int]] = {
    "Rotating equipment":           [194],
    "Mechanical equipment":         [195, 196],
    "Electrical equipment":         [197, 198],
    "Safety and control equipment": [199, 200, 201],
    "Subsea equipment":             [202, 203],
    "Well completion equipment":    [204, 205],
    "Drilling equipment":           [206, 207],
}
# Normal-orientation tables (equipment codes as column headers, NOT reversed)
_FM_NORMAL_PAGES: dict[str, int] = {
    "Well intervention equipment": 208,
    "Marine equipment":            209,
}
# Table B.15 overview — complete list of all failure modes with descriptions
_FM_B15_PAGES = range(209, 212)

# Section-3 noise patterns
_SOURCE_RE = re.compile(
    r'\[?3?\[?\s*S[\s.\d]*O[\s.\d]*U[\s.\d]*R[\s.\d]*C[\s.\d]*E[\s.\d]*:',
    re.IGNORECASE,
)
_STANDALONE_NUM_RE = re.compile(r'(?m)^\s*(3\.\d{1,2})\s*$')
_HEADER_RE = re.compile(r'(?:BS EN )?ISO 14224:2016(?:\(E\))?\s*\n?', re.IGNORECASE)
_NOISE_LINE_RE = re.compile(
    r'^(?:Note \d+\s+to\s+entry|NOTE\b|©|\d+\s*©|i+v?\s+[\d©])',
    re.IGNORECASE,
)


class ISO14224Parser(BaseParser):
    source_name = "iso14224"

    def parse(self) -> list[ParsedTerm]:
        try:
            import pdfplumber
        except ImportError:
            logger.error("ISO 14224: pdfplumber not installed. Run: pip install pdfplumber")
            return []

        pdf_files = list((DATA_DIR / "iso14224").glob("*.pdf"))
        if not pdf_files:
            logger.warning("ISO 14224: no PDF found in data/raw/iso14224/.")
            return []

        path = pdf_files[0]
        logger.info("ISO 14224: parsing %s", path.name)

        try:
            with pdfplumber.open(str(path)) as pdf:
                # 1. Section 3 definitions
                sec3 = self._parse_section3(pdf)

                # 2. Table A.4 equipment classes (base terms, no properties yet)
                equip_terms, name_to_code = self._parse_table_a4(pdf)

                # 3. Equipment-specific data attributes (Annex A.2.x tables)
                attr_map = self._parse_equipment_attributes(pdf, name_to_code)

                # 4. Failure mode applicability per equipment code (Annex B)
                fm_desc = self._parse_b15(pdf)           # {fm_code: (desc, on_demand)}
                fm_by_equip = self._build_fm_by_equip(pdf, fm_desc)  # {equip_code: [(code, desc)]}

                # 5. Enrich equipment terms
                for term in equip_terms:
                    code = term.source_id.replace("equip_", "")
                    if code in attr_map:
                        term.properties.extend(attr_map[code])
                    if code in fm_by_equip:
                        fms = fm_by_equip[code]
                        term.properties.append(ParsedProperty(
                            name="failure_modes",
                            definition="; ".join(
                                f"{c} ({d})" for c, d in sorted(fms, key=lambda x: x[0])
                            ),
                        ))

        except Exception as exc:
            logger.error("ISO 14224: PDF read error: %s", exc)
            return []

        all_terms = sec3 + equip_terms
        logger.info(
            "ISO 14224: %d section-3 terms + %d equipment classes = %d total",
            len(sec3), len(equip_terms), len(all_terms),
        )
        return all_terms

    # ------------------------------------------------------------------
    # Section 3 — Terms and definitions
    # ------------------------------------------------------------------

    def _parse_section3(self, pdf) -> list[ParsedTerm]:
        raw = ""
        for i in _SEC3_PAGES:
            if i < len(pdf.pages):
                raw += (pdf.pages[i].extract_text() or "") + "\n"

        raw = _HEADER_RE.sub("", raw)
        raw = _SOURCE_RE.sub("\n§§\n", raw)
        raw = _STANDALONE_NUM_RE.sub("\n§§\n", raw)

        terms: list[ParsedTerm] = []
        seen: set[str] = set()
        counter = 0

        for block in raw.split("§§"):
            result = self._parse_block(block)
            if result is None:
                continue
            name, definition = result
            key = name.lower().strip()
            if key in seen or len(key) < 3:
                continue
            seen.add(key)
            counter += 1
            terms.append(ParsedTerm(
                preferred_label=name,
                source=self.source_name,
                source_id=f"sec3_{counter:03d}",
                source_uri="https://www.iso.org/standard/64076.html",
                definition=definition,
                term_type="Definition",
            ))

        logger.debug("ISO 14224 section 3: extracted %d terms", len(terms))
        return terms

    def _parse_block(self, block: str) -> tuple[str, str | None] | None:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        lines = [
            l for l in lines
            if not _NOISE_LINE_RE.match(l)
            and not re.match(r'^\d{1,3}\s*$', l)
            and l not in ("BS EN ISO 14224:2016", "ISO 14224:2016(E)")
            and not l.startswith("© ISO")
            and not re.match(r'^(?:IEC |ISO[/ ]|EN |BS |API|NORSOK|IEEE|ASME|IMO|Moore|DNV|NFPA|CAN/)', l)
            and not re.match(r'^(?:i{1,4}v?[\.\)]\s|are |the |in |of |by |and )', l, re.IGNORECASE)
            and not l.endswith(');')
            and not l.endswith('];')
            and not l.endswith('].')
            and not re.search(r'[a-z]\d[a-z]', l)
        ]
        if not lines:
            return None

        name_idx = None
        for i, line in enumerate(lines):
            if len(line) > 80:
                continue
            if not re.search(r'[a-z]', line):
                continue
            if re.match(r'^\d', line):
                continue
            if re.match(r'^(?:For the purposes|The following|See |modified|modified\s*[–-])', line, re.IGNORECASE):
                continue
            words = line.split()
            if len(words) > 7 and re.match(r'^[a-z]', line):
                continue
            name_idx = i
            break

        if name_idx is None:
            return None

        name = lines[name_idx]
        if len(name.split()) > 8:
            return None
        if re.search(r'[,;:]\s*\d{4}', name):
            return None
        if re.search(r'modified', name, re.IGNORECASE):
            return None

        def_start = name_idx + 1
        if def_start < len(lines) and re.match(r'^[A-Z]{2,6}$', lines[def_start]):
            def_start += 1

        def_lines = []
        for line in lines[def_start:]:
            if re.match(r'^[Nn]ote\s+\d+', line):
                break
            if re.match(r'^\[', line):
                break
            def_lines.append(line)

        definition = " ".join(def_lines).strip() or None
        if definition and len(definition) < 6:
            definition = None

        return name, definition

    # ------------------------------------------------------------------
    # Annex A, Table A.4 — Equipment classes
    # ------------------------------------------------------------------

    # Map A.2.X section number → canonical category name
    _A2X_TO_CAT: dict[str, str] = {
        "2": "Rotating", "3": "Mechanical", "4": "Electrical",
        "5": "Safety and control", "6": "Subsea", "7": "Well completion",
        "8": "Drilling", "9": "Well intervention", "10": "Marine",
        "11": "Utilities", "12": "Auxiliaries",
    }
    _ANNEX_RE = re.compile(r'\(A\.2\.(\d+)\)')
    # Words that appear as equipment codes but are NOT equipment codes
    _CODE_NOISE = frozenset({
        'BS', 'EN', 'ISO', 'IEC', 'API', 'IMO', 'DNV', 'No', 'UL', 'CSA',
        'IEEE', 'NEMA', 'NFPA', 'FCC', 'CFR', 'CAN', 'DE',
    })

    def _page_category_markers(self, page) -> list[tuple[float, str]]:
        """Scan the equipment-category column (x=0..130) for (A.2.X) references.

        Returns a list of (y_top, category_name) sorted ascending by y.
        Category labels in the PDF are multi-line; the (A.2.X) reference is
        the last line and its y-position is used as the marker anchor.
        """
        crop = page.crop((0, 0, 130, page.height))
        markers = []
        for w in crop.extract_words():
            m = self._ANNEX_RE.match(w['text'])
            if m:
                cat = self._A2X_TO_CAT.get(m.group(1))
                if cat:
                    markers.append((w['top'], cat))
        return sorted(markers)

    def _code_y_positions(self, page) -> list[tuple[float, str]]:
        """Return (y_top, code) for 2–3 letter equipment codes in the code column.

        The code column sits at x≈290..450; broader range handles layout variation.
        """
        result = []
        for w in page.extract_words():
            if (290 <= w['x0'] <= 450
                    and re.match(r'^[A-Z]{2,3}$', w['text'])
                    and w['text'] not in self._CODE_NOISE):
                result.append((w['top'], w['text']))
        return result

    def _category_for_y(
        self,
        code_y: float,
        markers: list[tuple[float, str]],
        fallback: str,
    ) -> str:
        """Return the category for an equipment code at y=code_y.

        The (A.2.X) annex reference is the LAST line of the multi-line category
        label; the first word of the label (e.g. "Well") appears ~30 pt higher.
        We therefore use a 55 pt tolerance so that equipment codes which appear
        on the same text line as the category label's first word are correctly
        assigned to that category.

        The most recently seen marker (largest y_m satisfying the condition)
        wins.
        """
        best = fallback
        for marker_y, cat in markers:      # markers are sorted ascending
            if marker_y <= code_y + 55:
                best = cat
        return best

    def _parse_table_a4(self, pdf) -> tuple[list[ParsedTerm], dict[str, str]]:
        """Return (terms, name_to_code) where name_to_code maps normalised
        equipment names to their 2-letter codes.

        Category is detected using two complementary mechanisms:
        1. Row bounding boxes from find_tables(): a category marker whose y falls
           within a row's top..bottom range triggers a category update for that row.
        2. Post-page update: if the last marker on a page falls below all equipment
           rows (category starts on the next page), current_category is updated for
           the next page's rows.
        """
        terms: list[ParsedTerm] = []
        name_to_code: dict[str, str] = {}
        seen_ids: set[str] = set()
        current_category = "Rotating"   # first category in the table

        for page_idx in _TABA4_PAGES:
            if page_idx >= len(pdf.pages):
                break
            page = pdf.pages[page_idx]

            page_markers = self._page_category_markers(page)   # [(y, cat)] sorted asc

            # Use find_tables() for row bboxes (aligned with extract())
            ft_tables = page.find_tables()
            if not ft_tables:
                continue

            max_equipment_row_y: float = 0.0

            for ft in ft_tables:
                rows_data = ft.extract()
                for row_obj, row_data in zip(ft.rows, rows_data):
                    if not row_data or len(row_data) < 3:
                        continue

                    row_top = row_obj.bbox[1]
                    row_bot = row_obj.bbox[3]

                    # Update category if a marker falls inside this row's y range
                    for marker_y, cat in page_markers:
                        if row_top <= marker_y <= row_bot:
                            current_category = cat

                    name_cell = (row_data[1] or "").strip()
                    code_cell = (row_data[2] or "").strip()

                    if 'Equipment class' in name_cell or not name_cell:
                        continue

                    names = [n.strip() for n in name_cell.split('\n') if n.strip()]
                    codes = [c.strip() for c in code_cell.split('\n') if c.strip()]

                    has_equipment = False
                    for name, code in zip(names, codes):
                        name = re.sub(r'^[a-z]\s+', '', name).strip()
                        if not re.match(r'^[A-Z]{2,3}$', code):
                            continue
                        if not name or len(name) < 3:
                            continue

                        source_id = f"equip_{code}"
                        if source_id in seen_ids:
                            continue
                        seen_ids.add(source_id)
                        has_equipment = True

                        terms.append(ParsedTerm(
                            preferred_label=name,
                            source=self.source_name,
                            source_id=source_id,
                            source_uri="https://www.iso.org/standard/64076.html",
                            definition=None,
                            term_type=f"Equipment — {current_category}",
                        ))
                        name_to_code[name.lower()] = code

                    if has_equipment:
                        max_equipment_row_y = max(max_equipment_row_y, row_bot)

            # If a category marker appears BELOW all equipment rows on this page,
            # that category's items start on the next page — carry it forward.
            for marker_y, cat in reversed(page_markers):   # highest y first
                if marker_y > max_equipment_row_y:
                    current_category = cat
                    break

        logger.debug("ISO 14224 Table A.4: extracted %d equipment classes", len(terms))
        return terms, name_to_code

    # ------------------------------------------------------------------
    # Annex A, Tables A.7+ — Equipment-specific data attributes
    # ------------------------------------------------------------------

    def _parse_equipment_attributes(
        self, pdf, name_to_code: dict[str, str]
    ) -> dict[str, list[ParsedProperty]]:
        """Scan Annex A.2.x pages for 'Equipment-specific data' tables.

        Returns {equip_code: [ParsedProperty, ...]}.
        """
        result: dict[str, list[ParsedProperty]] = {}
        _title_re = re.compile(
            r'Table A\.\d+\s*[—–-]\s*Equipment.specific data\s*[—–-]\s*(.+?)(?:\n|$)',
            re.IGNORECASE,
        )
        _cont_re = re.compile(r'Table A\.\d+\s*\(continued\)', re.IGNORECASE)

        current_code: str | None = None

        for page_idx in _ANNEX_A_PAGES:
            if page_idx >= len(pdf.pages):
                break
            page = pdf.pages[page_idx]
            text = page.extract_text() or ""

            # New table title?
            m = _title_re.search(text)
            if m:
                equip_name = m.group(1).strip()
                # Remove trailing footnote / parenthetical
                equip_name = re.sub(r'\s*\(.*\)\s*$', '', equip_name).strip()
                current_code = self._match_equip_name(equip_name, name_to_code)
                if not current_code:
                    logger.debug("ISO 14224 A.2.x: no code match for %r", equip_name)
            elif not _cont_re.search(text):
                # Not a continuation page — reset context
                current_code = None

            if current_code is None:
                continue

            # Extract attribute rows from tables with Name/Description/Unit/Priority columns
            for t in page.extract_tables():
                if not t or len(t) < 2:
                    continue
                header = ' '.join(c or '' for c in t[0])
                if 'Name' not in header and 'Priority' not in header:
                    continue

                # --- Pass 1: collect raw (name, desc, unit, is_req) from every row ---
                _EMPTY = frozenset({'—', '–', '-', ''})
                raw_attrs: list[tuple[str, str, str, bool]] = []

                for row in t[1:]:
                    if not row or len(row) < 2:
                        continue
                    if not (row[0] or "").strip():
                        continue

                    name_entries = self._join_cell_lines(row[0] or "")
                    desc_entries = self._join_cell_lines(row[1] or "") if len(row) > 1 else []
                    unit_entries = self._join_cell_lines(row[2] or "") if len(row) > 2 else []
                    prio_raw     = (row[3] or "").strip() if len(row) > 3 else ""
                    is_req = bool(re.search(r'\bHigh\b', prio_raw, re.IGNORECASE))

                    for i, name in enumerate(name_entries):
                        desc = desc_entries[i] if i < len(desc_entries) else ""
                        unit = unit_entries[i] if i < len(unit_entries) else ""
                        raw_attrs.append((name, desc, unit, is_req))

                # --- Pass 2: merge cross-row continuations ---
                # Only trigger when the PREVIOUS name clearly ends mid-word:
                #   • ends with "-"  → hyphenated line break  (e.g. "Fluid corro-")
                #   • ends with "/"  → compound split         (e.g. "corrosiveness/")
                #   • current starts with "/"                 (e.g. "/erosiveness")
                # We deliberately do NOT merge just because the current line starts
                # with a lowercase letter — that was too aggressive and merged footnote
                # rows like "class standard …" into "Valve leakage".
                merged: list[tuple[str, str, str, bool]] = []
                for name, desc, unit, is_req in raw_attrs:
                    prev_name = merged[-1][0] if merged else ""
                    is_continuation = bool(merged) and (
                        prev_name.endswith('-')
                        or prev_name.endswith('/')
                        or name.startswith('/')
                    )
                    if is_continuation:
                        p_name, p_desc, p_unit, p_req = merged[-1]
                        joined = (p_name[:-1] + name) if p_name.endswith('-') else (p_name + name)
                        merged[-1] = (joined, p_desc or desc, p_unit or unit, p_req)
                    else:
                        merged.append((name, desc, unit, is_req))

                # --- Pass 3: create ParsedProperty objects ---
                props = result.setdefault(current_code, [])
                existing_names = {p.name for p in props}

                for attr_name, attr_desc, attr_unit, is_req in merged:
                    # Strip leading footnote marker "a Name" or trailing "Name a"
                    attr_name = re.sub(r'^[a-z]\s+', '', attr_name).strip()
                    attr_name = re.sub(r'\s+[a-z]$', '', attr_name).strip()
                    # Strip single-letter footnote words glued inside a name
                    # e.g. "Actuation b principle" → "Actuation principle"
                    attr_name = re.sub(r'(?<=\w)\s+[a-f]\s+(?=\w)', ' ', attr_name).strip()
                    # Skip noise rows: continuations, numbered lists, sentences, footnote text
                    if attr_name and attr_name[0].islower():  # unmerged continuation row
                        continue
                    if re.match(r'^\d+\s', attr_name):        # "1 single-acting = …"
                        continue
                    if attr_name.endswith(('.', ':')):         # sentence or section header
                        continue
                    if '(e.g.' in attr_name.lower():          # footnote exemplification text
                        continue
                    if len(attr_name) > 60:                   # footnote / multi-column bleed
                        continue
                    if len(attr_name) < 3:
                        continue
                    if attr_name in existing_names:
                        continue
                    existing_names.add(attr_name)
                    clean_desc = (attr_desc or "").strip()
                    clean_unit = (attr_unit or "").strip()
                    props.append(ParsedProperty(
                        name=attr_name[:200],
                        definition=clean_desc if clean_desc not in _EMPTY else None,
                        unit=clean_unit[:300] if clean_unit not in _EMPTY else None,
                        is_required=is_req,
                    ))

        logger.debug(
            "ISO 14224 A.2.x: attributes extracted for %d equipment classes", len(result)
        )
        return result

    @staticmethod
    def _join_cell_lines(raw: str) -> list[str]:
        """Split a PDF table cell on newlines and reassemble logical entries.

        Two passes:
        1. Join hyphenated line-breaks: "corro-\\nsiveness" → "corrosiveness".
        2. Merge continuation lines back into the preceding entry:
           - Lines that start with a lowercase letter are word continuations.
           - Lines that start with "/" are the tail of a "word1/\\nword2" split.
           - Lines that follow an entry ending with "/" are the second half of
             a compound like "corrosiveness/\\nerosiveness".

        Returns a list of logical entries (one per stacked attribute in the cell).
        """
        raw_lines = [l.strip() for l in raw.split('\n') if l.strip()]

        # Pass 1: join hyphenated breaks (word ends with '-')
        hyphen_joined: list[str] = []
        for line in raw_lines:
            if hyphen_joined and hyphen_joined[-1].endswith('-'):
                hyphen_joined[-1] = hyphen_joined[-1][:-1] + line
            else:
                hyphen_joined.append(line)

        # Pass 2: merge continuation lines
        entries: list[str] = []
        for line in hyphen_joined:
            prev = entries[-1] if entries else ""
            if entries and (prev.endswith('/') or line.startswith('/')):
                # Compound word split at "/": join directly
                entries[-1] = prev + line
            elif entries and line[0].islower():
                # Lowercase continuation — add a space (may have an inline footnote
                # marker glued to the end of the previous entry, e.g. "Actuationb")
                entries[-1] = prev + ' ' + line
            else:
                entries.append(line)

        return entries

    def _match_equip_name(self, name: str, name_to_code: dict[str, str]) -> str | None:
        """Case-insensitive name → 2-letter code lookup with partial matching."""
        nl = name.lower()
        if nl in name_to_code:
            return name_to_code[nl]
        # Substring match (both directions)
        for equip_name, code in name_to_code.items():
            if nl in equip_name or equip_name in nl:
                return code
        return None

    # ------------------------------------------------------------------
    # Annex B — Failure modes per equipment class
    # ------------------------------------------------------------------

    def _parse_b15(self, pdf) -> dict[str, tuple[str, bool]]:
        """Parse Table B.15 overview (pages 209–211).

        Returns {fm_code: (description, on_demand_flag)}.
        """
        text = ""
        for i in _FM_B15_PAGES:
            if i < len(pdf.pages):
                text += (pdf.pages[i].extract_text() or "") + "\n"

        b15_start = text.find("Table B.15")
        if b15_start == -1:
            logger.warning("ISO 14224: Table B.15 not found")
            return {}
        text = text[b15_start:]

        result: dict[str, tuple[str, bool]] = {}
        for line in text.splitlines():
            line = line.strip()
            m = re.match(r'^([A-Z]{2,3})\s+(.+?)(?:\s+(X))?\s*$', line)
            if not m:
                continue
            code = m.group(1)
            if code in ('BS', 'EN', 'ISO', 'IEC'):
                continue
            desc = m.group(2).strip()
            if desc.lower() in ('mode description', 'mode code'):
                continue
            on_demand = m.group(3) == 'X' if m.group(3) else False
            if code not in result:
                result[code] = (desc, on_demand)

        return result

    def _build_fm_by_equip(
        self, pdf, fm_desc: dict[str, tuple[str, bool]]
    ) -> dict[str, list[tuple[str, str]]]:
        """Build {equip_code (Table A.4): [(fm_code, fm_description), ...]}.

        Aggregates results from Tables B.6–B.14.
        """
        # Intermediate: fm_code → set of equip_codes (A.4 codes)
        fm_to_equip: dict[str, set[str]] = {}

        for _cat, pages in _FM_ROTATED_PAGES.items():
            for page_idx in pages:
                if page_idx >= len(pdf.pages):
                    continue
                page_result = self._parse_rotated_fm_page(pdf.pages[page_idx])
                for fm_code, equip_codes in page_result.items():
                    fm_to_equip.setdefault(fm_code, set()).update(equip_codes)

        for _cat, page_idx in _FM_NORMAL_PAGES.items():
            if page_idx >= len(pdf.pages):
                continue
            _examples, page_result = self._parse_normal_fm_page(pdf.pages[page_idx])
            for fm_code, equip_codes in page_result.items():
                fm_to_equip.setdefault(fm_code, set()).update(equip_codes)

        # Invert: equip_code → [(fm_code, description)]
        equip_to_fms: dict[str, list[tuple[str, str]]] = {}
        for fm_code, equip_codes in fm_to_equip.items():
            desc = fm_desc.get(fm_code, (fm_code, False))[0]
            for ec in equip_codes:
                equip_to_fms.setdefault(ec, []).append((fm_code, desc))

        return equip_to_fms

    def _parse_rotated_fm_page(self, page) -> dict[str, list[str]]:
        """Parse one page of a rotated failure mode table (B.6–B.12).

        Equipment codes appear REVERSED in the row labels (col 0) because the
        table is rotated 90°. Reversal is applied to recover the Table A.4 code.
        Failure mode codes appear REVERSED in the last row; they are reversed back.

        Returns {fm_code: [equip_code_A4, ...]}.
        """
        tables = page.extract_tables()
        if not tables:
            return {}
        t = tables[0]
        if len(t) < 4:
            return {}

        last_row = t[-1]

        # col_idx → [fm_codes] from last row (each code is reversed)
        col_to_fms: dict[int, list[str]] = {}
        for col_idx, cell in enumerate(last_row):
            if col_idx < 3 or not cell or not cell.strip():
                continue
            for raw in cell.strip().split():
                if re.match(r'^[A-Z]{2,3}$', raw):
                    fm = raw[::-1]
                    if re.match(r'^[A-Z]{2,3}$', fm):
                        col_to_fms.setdefault(col_idx, []).append(fm)

        result: dict[str, list[str]] = {}
        for row in t[:-3]:
            raw_equip = (row[0] or "").strip()
            if not re.match(r'^[A-Z]{2,3}$', raw_equip):
                continue
            equip_code = raw_equip[::-1]  # reverse to get Table A.4 code

            # Primary: map X marks via known column → FM codes
            for col_idx, fms in col_to_fms.items():
                if col_idx >= len(row):
                    continue
                if 'X' in (row[col_idx] or ""):
                    for fm in fms:
                        result.setdefault(fm, [])
                        if equip_code not in result[fm]:
                            result[fm].append(equip_code)

            # Supplemental: catch FM codes embedded in overflow merged cells
            for col_idx, cell in enumerate(row):
                if col_idx < 3 or not cell or col_idx in col_to_fms:
                    continue
                cell_str = cell.strip()
                if 'X' not in cell_str:
                    continue
                for raw in re.findall(r'\b([A-Z]{2,3})\b', cell_str):
                    fm = raw[::-1]
                    if re.match(r'^[A-Z]{2,3}$', fm):
                        result.setdefault(fm, [])
                        if equip_code not in result[fm]:
                            result[fm].append(equip_code)

        return result

    def _parse_normal_fm_page(
        self, page
    ) -> tuple[dict[str, str], dict[str, list[str]]]:
        """Parse one normal-orientation failure mode table page (B.13–B.14).

        Equipment codes are column headers (NOT reversed).

        Returns (examples_dict, {fm_code: [equip_code, ...]}).
        """
        tables = page.extract_tables()
        examples: dict[str, str] = {}
        applicability: dict[str, list[str]] = {}

        for table in tables:
            if len(table) < 3:
                continue

            equip_cols: dict[int, str] = {}
            for row in table[:3]:
                if not row or len(row) < 4:
                    continue
                for col_idx in range(3, len(row)):
                    cell = (row[col_idx] or "").strip()
                    if re.match(r'^[A-Z]{2,3}$', cell):
                        equip_cols[col_idx] = cell
                if equip_cols:
                    break

            if not equip_cols:
                continue

            for row in table:
                if not row:
                    continue
                fm_code = (row[0] or "").strip()
                if not re.match(r'^[A-Z]{2,3}$', fm_code):
                    continue
                ex = (row[2] or "").strip().replace('\n', ' ')
                if ex:
                    examples[fm_code] = ex
                for col_idx, equip_code in equip_cols.items():
                    if col_idx < len(row) and 'X' in (row[col_idx] or ""):
                        applicability.setdefault(fm_code, [])
                        if equip_code not in applicability[fm_code]:
                            applicability[fm_code].append(equip_code)

        return examples, applicability
