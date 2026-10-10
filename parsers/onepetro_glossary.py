"""
OnePetro E&P Glossary parser.

The glossary (~5 200 terms) originated from SPE's PetroWiki project and is
now hosted at https://onepetro.org/pages/glossary.

The page is protected by Cloudflare, so a local JSON cache is required.
Generate it with the included helper script:

    python -m scripts.fetch_onepetro_glossary

Or run the Playwright scraper manually and place the output at:
    data/raw/onepetro_glossary/onepetro_glossary.json

The cache format is a JSON array of objects:
    [{"term": "...", "definition": "...", "href": "..."}, ...]
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from config import DATA_DIR
from parsers.base import BaseParser, ParsedTerm

logger = logging.getLogger(__name__)

_CACHE_DIR = DATA_DIR / "onepetro_glossary"
_BASE_URL = "https://onepetro.org/pages/glossary"


class OnePetroGlossaryParser(BaseParser):
    source_name = "onepetro_glossary"

    def parse(self) -> list[ParsedTerm]:
        cache_files = list(_CACHE_DIR.glob("*.json"))
        if not cache_files:
            logger.error(
                "OnePetro Glossary: no cache found in %s. "
                "Run: python -m scripts.fetch_onepetro_glossary",
                _CACHE_DIR,
            )
            return []

        cache_file = cache_files[0]
        logger.info("OnePetro Glossary: loading from %s", cache_file.name)
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("OnePetro Glossary: cannot read cache: %s", exc)
            return []

        terms: list[ParsedTerm] = []
        for entry in data:
            term = self._parse_entry(entry)
            if term:
                terms.append(term)

        logger.info("OnePetro Glossary: %d terms loaded", len(terms))
        return terms

    def _parse_entry(self, entry: dict) -> ParsedTerm | None:
        name = (entry.get("term") or "").strip()
        if not name:
            return None

        definition = (entry.get("definition") or "").strip() or None
        href = (entry.get("href") or "").strip() or None

        # source_id: slugified term name (lowercase, spaces→hyphens)
        source_id = name.lower().replace(" ", "-")

        return ParsedTerm(
            preferred_label=name,
            source=self.source_name,
            source_id=source_id,
            source_uri=href or _BASE_URL,
            definition=definition,
            term_type=None,
        )
