"""
SLB (Schlumberger) Energy Glossary parser.

Fetches ~4 800 terms from the JSON-LD endpoint:
  https://glossary.slb.com/en/search?format=json

The response is a Schema.org DefinedTermSet where each term has:
  name        → preferred_label
  description → definition
  url         → source_uri  (pattern: /en/terms/{letter}/{slug})

Falls back to a local JSON cache in data/raw/slb_glossary/ if a file
named slb_glossary.json (or *.json) is present — useful for offline use.
To cache manually:
  curl -o data/raw/slb_glossary/slb_glossary.json \
       'https://glossary.slb.com/en/search?format=json'
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import requests

from config import DATA_DIR
from parsers.base import BaseParser, ParsedTerm

logger = logging.getLogger(__name__)

_URL = "https://glossary.slb.com/en/search"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
}
_JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL,
)


class SLBGlossaryParser(BaseParser):
    source_name = "slb_glossary"

    def parse(self) -> list[ParsedTerm]:
        local_dir = DATA_DIR / "slb_glossary"
        local_files = list(local_dir.glob("*.json"))
        if local_files:
            logger.info("SLB Glossary: loading from local file %s", local_files[0].name)
            return self._parse_json_file(local_files[0])

        logger.info("SLB Glossary: fetching from %s", _URL)
        return self._fetch()

    def _fetch(self) -> list[ParsedTerm]:
        try:
            resp = requests.get(_URL, headers=_HEADERS, timeout=30)
            resp.raise_for_status()
        except Exception as exc:
            logger.error("SLB Glossary: fetch failed: %s", exc)
            return []

        data = self._extract_jsonld(resp.text)
        if data is None:
            logger.error("SLB Glossary: no JSON-LD found in page")
            return []
        return self._parse_data(data)

    def _extract_jsonld(self, html: str) -> dict | None:
        match = _JSONLD_RE.search(html)
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            logger.error("SLB Glossary: JSON-LD parse error: %s", exc)
            return None

    def _parse_json_file(self, path: Path) -> list[ParsedTerm]:
        # Supports both a raw JSON-LD file and cached HTML
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.error("SLB Glossary: cannot read %s: %s", path.name, exc)
            return []
        # Try as plain JSON first, then as HTML with embedded JSON-LD
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            data = self._extract_jsonld(content)
        if data is None:
            logger.error("SLB Glossary: cannot parse %s", path.name)
            return []
        return self._parse_data(data)

    def _parse_data(self, data: dict) -> list[ParsedTerm]:
        terms: list[ParsedTerm] = []

        # Top-level hasPart: list of DefinedTermSet objects, one per letter
        for letter_group in data.get("hasPart", []):
            for entry in letter_group.get("hasDefinedTerm", []):
                term = self._parse_entry(entry)
                if term:
                    terms.append(term)

        logger.info("SLB Glossary: total %d terms", len(terms))
        if not terms:
            logger.warning(
                "SLB Glossary: no terms parsed. "
                "Try caching manually: "
                "curl -o data/raw/slb_glossary/slb_glossary.html '%s'",
                _URL,
            )
        return terms

    def _parse_entry(self, entry: dict) -> ParsedTerm | None:
        name = (entry.get("name") or "").strip()
        if not name:
            return None

        # Strip HTML tags from name (some entries use <i> for italics)
        name = _strip_html(name)
        if not name:
            return None

        definition = (entry.get("description") or "").strip() or None
        if definition:
            definition = _strip_html(definition)

        url = (entry.get("url") or "").strip() or None

        # source_id: last two path segments of URL → "p/pump"
        # (preserves uniqueness across letters)
        if url:
            parts = url.rstrip("/").split("/")
            source_id = "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
        else:
            source_id = name.lower().replace(" ", "_")

        return ParsedTerm(
            preferred_label=name,
            source=self.source_name,
            source_id=source_id,
            source_uri=url,
            definition=definition,
            term_type=None,
        )


def _strip_html(text: str) -> str:
    """Remove simple HTML tags like <i>, <b>, <em> from a string."""
    import re
    return re.sub(r"<[^>]+>", "", text).strip()
