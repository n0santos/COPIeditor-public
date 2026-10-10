"""
DEXPI parser — reads the Python DSL model files from the GitLab repository
(https://gitlab.com/dexpi/Specification) or local .py copies in data/raw/dexpi/.

Each .py file uses the DEXPI DSL:
  PACKAGE.ClassName = CONCRETE_CLASS(superTypes=[...], description=r'''...''')
  PACKAGE.ClassName.PropertyName = DATA_PROPERTY(description=r'''...''', type=..., ...)
"""
from __future__ import annotations

import logging
import re
import textwrap
from pathlib import Path
from typing import Optional

import requests

from config import DATA_DIR
from parsers.base import BaseParser, ParsedProperty, ParsedTerm

logger = logging.getLogger(__name__)

GITLAB_BASE = "https://gitlab.com/dexpi/Specification/-/raw/master/src/model"

# Files to fetch from the GitLab repo (namespace → relative URL path)
REMOTE_MODEL_FILES: dict[str, str] = {
    "Core": f"{GITLAB_BASE}/Core/Core.py",
    "Plant.ProcessEquipment": f"{GITLAB_BASE}/Plant/ProcessEquipment/ProcessEquipment.py",
    "Plant.Instrumentation": f"{GITLAB_BASE}/Plant/Instrumentation/Instrumentation.py",
    "Plant.Piping": f"{GITLAB_BASE}/Plant/Piping/Piping.py",
    "Plant.PlantStructure": f"{GITLAB_BASE}/Plant/PlantStructure/PlantStructure.py",
    "Process": f"{GITLAB_BASE}/Process/Process.py",
}

# --- regex patterns ---------------------------------------------------------

# VARNAME = Module.Path = PACKAGE()  → captures VARNAME and Module.Path
_NS_MAP_RE = re.compile(r'^(\w+)\s*=\s*([\w.]+)\s*=\s*PACKAGE\(\)', re.MULTILINE)

# VARNAME.ClassName = CONCRETE_CLASS( or ABSTRACT_CLASS(
_CLASS_RE = re.compile(
    r'^(\w+)\.(\w+)\s*=\s*(CONCRETE_CLASS|ABSTRACT_CLASS)\s*\(',
    re.MULTILINE,
)

# VARNAME.ClassName.PropName = DATA_PROPERTY( / COMPOSITION_PROPERTY( / REFERENCE_PROPERTY(
_PROP_RE = re.compile(
    r'^(\w+)\.(\w+)\.(\w+)\s*=\s*(DATA_PROPERTY|COMPOSITION_PROPERTY|REFERENCE_PROPERTY)\s*\(',
    re.MULTILINE,
)

# superTypes=[...] — captures inner content (may span lines)
_SUPERTYPES_RE = re.compile(r'superTypes\s*=\s*\[([^\]]*)\]', re.DOTALL)

# description=r'''...''' or r"""..."""
_DESC_RE = re.compile(
    r'description\s*=\s*r?(?:\'\'\'(.*?)\'\'\'|"""(.*?)""")',
    re.DOTALL,
)

# lower=<int>, upper=<int or None>
_LOWER_RE = re.compile(r'\blower\s*=\s*(\d+)')
_UPPER_RE = re.compile(r'\bupper\s*=\s*(None|\d+)')

# type= ... (just capture the raw value for data properties)
_TYPE_RE = re.compile(r'\btype\s*=\s*([^\n,)]+)')

# RST markup to strip from descriptions
_RST_CLEANUP = [
    re.compile(r':sp:element:`[^`]*`'),
    re.compile(r'`[^`<>]*`_?'),
    re.compile(r'<[A-Z_!][A-Z_!]*>'),  # <OWNER>, <!OWNER>
    re.compile(r'<[^>]+>'),            # HTML-ish tags
    re.compile(r'\.\. [^\n]+'),        # RST directives
]


class DEXPIParser(BaseParser):
    source_name = "dexpi"

    def parse(self) -> list[ParsedTerm]:
        # Prefer local .py files if present
        local_files = list((DATA_DIR / "dexpi").glob("*.py"))
        if local_files:
            logger.info("DEXPI: using %d local .py file(s)", len(local_files))
            all_terms: dict[str, ParsedTerm] = {}
            for f in local_files:
                logger.info("  Parsing %s", f.name)
                content = f.read_text(encoding="utf-8", errors="replace")
                self._parse_content(content, all_terms)
            logger.info("DEXPI: %d terms from local files", len(all_terms))
            return list(all_terms.values())

        # Otherwise fetch from GitLab
        logger.info("DEXPI: fetching model files from GitLab …")
        all_terms: dict[str, ParsedTerm] = {}
        for hint, url in REMOTE_MODEL_FILES.items():
            logger.info("  Fetching %s …", url.split("/")[-1])
            try:
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
            except requests.RequestException as exc:
                logger.warning("  Could not fetch %s: %s", url, exc)
                continue
            self._parse_content(resp.text, all_terms)

        logger.info("DEXPI: %d terms total", len(all_terms))
        return list(all_terms.values())

    # ------------------------------------------------------------------
    # Core parsing logic
    # ------------------------------------------------------------------

    def _parse_content(
        self, content: str, terms: dict[str, ParsedTerm]
    ) -> None:
        # Build VARNAME → full namespace mapping from PACKAGE() assignments
        ns_map = self._build_namespace_map(content)

        # ---- Classes ----
        for m in _CLASS_RE.finditer(content):
            var_name, class_name, class_kind = m.groups()
            namespace = ns_map.get(var_name, var_name)
            source_id = f"{namespace}.{class_name}"

            call_body = _extract_call_body(content, m.end())
            description = _extract_description(call_body)
            super_ids = _extract_supertypes(call_body, ns_map)

            if source_id not in terms:
                terms[source_id] = ParsedTerm(
                    preferred_label=class_name,
                    source=self.source_name,
                    source_id=source_id,
                    source_uri=f"https://gitlab.com/dexpi/Specification/-/blob/master/src/model",
                    definition=description,
                    term_type="ConcreteClass" if "CONCRETE" in class_kind else "AbstractClass",
                    parent_source_ids=super_ids,
                )

        # ---- Properties ----
        for m in _PROP_RE.finditer(content):
            var_name, class_name, prop_name, prop_kind = m.groups()
            namespace = ns_map.get(var_name, var_name)
            source_id = f"{namespace}.{class_name}"

            if source_id not in terms:
                continue

            call_body = _extract_call_body(content, m.end())
            description = _extract_description(call_body)
            lower = _extract_lower(call_body)
            datatype = None
            if prop_kind == "DATA_PROPERTY":
                datatype = _extract_type_hint(call_body)

            terms[source_id].properties.append(
                ParsedProperty(
                    name=prop_name,
                    definition=description,
                    datatype=datatype,
                    is_required=(lower > 0),
                )
            )

    def _build_namespace_map(self, content: str) -> dict[str, str]:
        """Build {VARNAME: 'Module.Path'} from PACKAGE() assignment lines."""
        ns_map: dict[str, str] = {}
        for m in _NS_MAP_RE.finditer(content):
            var_name, module_path = m.groups()
            ns_map[var_name] = module_path
        return ns_map


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _extract_call_body(content: str, start: int) -> str:
    """Return text inside the outermost (...) starting at `start`."""
    depth = 1
    i = start
    in_string = False
    str_char = ""
    while i < len(content) and depth > 0:
        ch = content[i]
        if in_string:
            if ch == "\\" :
                i += 2
                continue
            if content[i:i+3] in ("'''", '"""'):
                if content[i:i+3] == str_char:
                    in_string = False
                    i += 3
                    continue
            elif ch == str_char:
                in_string = False
        else:
            if content[i:i+3] in ("r'''", "r\"\"\""):
                in_string = True
                str_char = content[i+1:i+4]
                i += 4
                continue
            elif content[i:i+3] in ("'''", '"""'):
                in_string = True
                str_char = content[i:i+3]
                i += 3
                continue
            elif ch in ("'", '"'):
                in_string = True
                str_char = ch
            elif ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0:
                    return content[start:i]
        i += 1
    return content[start:]


def _extract_description(call_body: str) -> Optional[str]:
    m = _DESC_RE.search(call_body)
    if not m:
        return None
    raw = m.group(1) if m.group(1) is not None else m.group(2)
    if raw is None:
        return None
    # Dedent and clean up RST
    text = textwrap.dedent(raw).strip()
    for pat in _RST_CLEANUP:
        text = pat.sub("", text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text or None


def _extract_supertypes(call_body: str, ns_map: dict[str, str]) -> list[str]:
    m = _SUPERTYPES_RE.search(call_body)
    if not m:
        return []
    raw = m.group(1)
    # Each item looks like: Core.ConceptualObject or INSTRUMENTATION.Transmitter
    items = [tok.strip() for tok in raw.split(',') if tok.strip()]
    result = []
    for item in items:
        parts = item.split('.')
        if len(parts) >= 2:
            var_or_ns = parts[0]
            cls = parts[-1]
            ns = ns_map.get(var_or_ns, var_or_ns)
            result.append(f"{ns}.{cls}")
    return result


def _extract_lower(call_body: str) -> int:
    m = _LOWER_RE.search(call_body)
    return int(m.group(1)) if m else 0


def _extract_type_hint(call_body: str) -> Optional[str]:
    m = _TYPE_RE.search(call_body)
    if not m:
        return None
    raw = m.group(1).strip().rstrip(',').strip()
    # Simplify: keep only the last part after the last dot
    # e.g. DATA_TYPES.MultiLanguageString → MultiLanguageString
    # BUILTIN.Undefined | BUILTIN.String → Undefined|String
    simplified = re.sub(r'\w+\.(\w+)', r'\1', raw)
    simplified = re.sub(r'\s*\|\s*', '|', simplified)
    return simplified or None
