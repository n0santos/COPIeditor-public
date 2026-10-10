"""
ISO 15926-4 Reference Data Library parser.

Priority order:
  1. Local Excel (.xlsx) files in data/raw/iso15926/  — Ed. 3 modules
  2. Local RDF files (.rdf/.ttl/.owl/.n3/.nt) in data/raw/iso15926/
  3. SPARQL endpoint at http://data.15926.org/sparql  (currently unreachable)

Download the Ed. 3 Excel modules from:
  https://standards.iso.org/iso/15926/-4/reference-data-library/modules-ed3.zip
and place the .xlsx files in data/raw/iso15926/.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from rdflib import OWL, RDF, RDFS, Graph, Namespace, URIRef
from rdflib.namespace import SKOS
from SPARQLWrapper import JSON, SPARQLWrapper

from config import (
    DATA_DIR,
    ISO15926_NAMESPACE,
    ISO15926_SPARQL_ENDPOINT,
    SPARQL_PAGE_SIZE,
)
from parsers.base import BaseParser, ParsedTerm

logger = logging.getLogger(__name__)

RDL = Namespace(ISO15926_NAMESPACE)

# Columns common to all Ed. 3 module sheets (row 1, after the license header row)
_REQUIRED_COLS = {"URI", "UniqueNumber", "UniqueName"}
_SUPERCLASS_COLS = ["SuperClass1", "SuperClass2", "SuperClass3", "SuperClass4", "SuperClass5"]


class ISO15926Parser(BaseParser):
    source_name = "iso15926"

    def parse(self) -> list[ParsedTerm]:
        iso_dir = DATA_DIR / "iso15926"

        excel_files: list[Path] = list(iso_dir.glob("*.xlsx"))
        if excel_files:
            logger.info("ISO 15926-4: parsing %d Excel file(s)", len(excel_files))
            return self._parse_excel(excel_files)

        rdf_files: list[Path] = []
        for ext in ["rdf", "ttl", "owl", "n3", "nt"]:
            rdf_files.extend(iso_dir.glob(f"*.{ext}"))
        if rdf_files:
            logger.info("ISO 15926-4: parsing %d local RDF file(s)", len(rdf_files))
            return self._parse_local(rdf_files)

        logger.info("ISO 15926-4: fetching from SPARQL endpoint %s", ISO15926_SPARQL_ENDPOINT)
        return self._fetch_sparql()

    # ------------------------------------------------------------------
    # Excel path  (Ed. 3 modules)
    # ------------------------------------------------------------------

    def _parse_excel(self, files: list[Path]) -> list[ParsedTerm]:
        # First pass: collect all terms; build name → source_id map for parent resolution
        terms: dict[str, ParsedTerm] = {}        # source_id → ParsedTerm
        name_to_id: dict[str, str] = {}           # UniqueName → source_id
        # Store raw parent names until second pass
        pending_parents: dict[str, list[str]] = {}  # source_id → [parent_names]

        for f in files:
            self._read_excel_file(f, terms, name_to_id, pending_parents)

        # Second pass: resolve parent names → source_ids
        resolved = 0
        unresolved: set[str] = set()
        for source_id, parent_names in pending_parents.items():
            for name in parent_names:
                parent_id = name_to_id.get(name)
                if parent_id and parent_id not in terms[source_id].parent_source_ids:
                    terms[source_id].parent_source_ids.append(parent_id)
                    resolved += 1
                else:
                    unresolved.add(name)

        logger.debug(
            "ISO 15926-4: resolved %d parent edges; %d unique unresolved parent names",
            resolved, len(unresolved),
        )
        logger.info("ISO 15926-4: total %d terms from Excel files", len(terms))
        return list(terms.values())

    def _read_excel_file(
        self,
        path: Path,
        terms: dict[str, ParsedTerm],
        name_to_id: dict[str, str],
        pending_parents: dict[str, list[str]],
    ) -> None:
        try:
            xl = pd.ExcelFile(path)
        except Exception as exc:
            logger.warning("ISO 15926-4: cannot open %s: %s", path.name, exc)
            return

        # Use the first sheet (the data sheet; ignore Change/Addition sheets)
        sheet_name = xl.sheet_names[0]

        try:
            # Row 0 is a license header; row 1 contains the real column names
            df = pd.read_excel(path, sheet_name=sheet_name, header=1)
        except Exception as exc:
            logger.warning("ISO 15926-4: cannot read sheet '%s' in %s: %s", sheet_name, path.name, exc)
            return

        # Validate required columns exist
        if not _REQUIRED_COLS.issubset(df.columns):
            logger.warning("ISO 15926-4: %s missing required columns, skipping", path.name)
            return

        # Drop rows without a URI or UniqueName
        df = df.dropna(subset=["URI", "UniqueName"])

        count = 0
        for _, row in df.iterrows():
            uri = str(row["URI"]).strip()
            if not uri or uri == "nan":
                continue

            # source_id: last path segment of the URI
            source_id = uri.rstrip("/").split("/")[-1]
            if not source_id:
                continue

            unique_name = str(row["UniqueName"]).strip()
            if not unique_name or unique_name == "nan":
                continue

            definition_raw = row.get("TextDefinition")
            definition = (
                str(definition_raw).strip()
                if definition_raw is not None and str(definition_raw).strip() not in ("", "nan")
                else None
            )

            term_type_raw = row.get("ISO15926-2Entity")
            term_type = (
                str(term_type_raw).strip()
                if term_type_raw is not None and str(term_type_raw).strip() not in ("", "nan")
                else "Class"
            )

            # Synonyms
            synonyms: list[str] = []
            for col in ("Synonym1", "Synonym2"):
                val = row.get(col)
                if val is not None and str(val).strip() not in ("", "nan"):
                    syn = str(val).strip()
                    if syn != unique_name and syn not in synonyms:
                        synonyms.append(syn)

            if source_id not in terms:
                term = ParsedTerm(
                    preferred_label=unique_name,
                    source=self.source_name,
                    source_id=source_id,
                    source_uri=uri,
                    definition=definition,
                    term_type=term_type,
                    synonyms=synonyms,
                )
                terms[source_id] = term
                name_to_id[unique_name] = source_id
                count += 1

            # Collect parent names for second-pass resolution
            parent_names: list[str] = []
            for col in _SUPERCLASS_COLS:
                val = row.get(col)
                if val is not None and str(val).strip() not in ("", "nan"):
                    parent_names.append(str(val).strip())

            if parent_names:
                existing = pending_parents.get(source_id, [])
                for pname in parent_names:
                    if pname not in existing:
                        existing.append(pname)
                pending_parents[source_id] = existing

        logger.debug("ISO 15926-4: %s → %d terms", path.name, count)

    # ------------------------------------------------------------------
    # SPARQL path
    # ------------------------------------------------------------------

    def _fetch_sparql(self) -> list[ParsedTerm]:
        sparql = SPARQLWrapper(ISO15926_SPARQL_ENDPOINT)
        sparql.setReturnFormat(JSON)
        sparql.setTimeout(60)

        terms: dict[str, ParsedTerm] = {}
        offset = 0

        while True:
            query = f"""
            PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            PREFIX owl:  <http://www.w3.org/2002/07/owl#>

            SELECT DISTINCT ?subject ?label ?definition ?parent WHERE {{
                ?subject a owl:Class .
                FILTER(STRSTARTS(STR(?subject), "{ISO15926_NAMESPACE}"))
                ?subject rdfs:label ?label .
                OPTIONAL {{ ?subject rdfs:comment ?definition }}
                OPTIONAL {{
                    ?subject rdfs:subClassOf ?parent .
                    FILTER(STRSTARTS(STR(?parent), "{ISO15926_NAMESPACE}"))
                    FILTER(isURI(?parent))
                }}
                FILTER(LANG(?label) = "" || LANG(?label) = "en")
            }}
            ORDER BY ?label
            LIMIT {SPARQL_PAGE_SIZE}
            OFFSET {offset}
            """
            sparql.setQuery(query)

            try:
                results = sparql.query().convert()
                if not isinstance(results, dict):
                    logger.error("ISO 15926-4 SPARQL: unexpected response (endpoint may be down)")
                    break
            except Exception as exc:
                logger.error("ISO 15926-4 SPARQL error: %s", exc)
                break

            bindings = results["results"]["bindings"]
            if not bindings:
                break

            for row in bindings:
                uri = row["subject"]["value"]
                source_id = uri.split("/")[-1]
                label = row["label"]["value"]
                definition = row.get("definition", {}).get("value")
                parent_uri = row.get("parent", {}).get("value")

                if source_id not in terms:
                    terms[source_id] = ParsedTerm(
                        preferred_label=label,
                        source=self.source_name,
                        source_id=source_id,
                        source_uri=uri,
                        definition=definition,
                        term_type="Class",
                    )
                if parent_uri:
                    parent_id = parent_uri.split("/")[-1]
                    if parent_id not in terms[source_id].parent_source_ids:
                        terms[source_id].parent_source_ids.append(parent_id)

            offset += SPARQL_PAGE_SIZE
            logger.debug("ISO 15926-4: fetched %d terms so far", len(terms))

            if len(bindings) < SPARQL_PAGE_SIZE:
                break

        if terms:
            self._fetch_synonyms_sparql(sparql, terms)

        logger.info("ISO 15926-4: total %d terms", len(terms))
        if not terms:
            logger.warning(
                "ISO 15926-4: SPARQL endpoint returned no data. "
                "Place local Excel or RDF files in data/raw/iso15926/ to import offline."
            )
        return list(terms.values())

    def _fetch_synonyms_sparql(
        self, sparql: SPARQLWrapper, terms: dict[str, ParsedTerm]
    ) -> None:
        offset = 0
        while True:
            query = f"""
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            PREFIX skos: <http://www.w3.org/2004/02/skos/core#>

            SELECT DISTINCT ?subject ?altLabel WHERE {{
                ?subject rdfs:label ?altLabel .
                FILTER(STRSTARTS(STR(?subject), "{ISO15926_NAMESPACE}"))
            }}
            LIMIT {SPARQL_PAGE_SIZE}
            OFFSET {offset}
            """
            sparql.setQuery(query)
            try:
                results = sparql.query().convert()
                if not isinstance(results, dict):
                    break
            except Exception:
                break

            bindings = results["results"]["bindings"]
            if not bindings:
                break

            for row in bindings:
                source_id = row["subject"]["value"].split("/")[-1]
                alt = row["altLabel"]["value"]
                if source_id in terms and alt != terms[source_id].preferred_label:
                    if alt not in terms[source_id].synonyms:
                        terms[source_id].synonyms.append(alt)

            offset += SPARQL_PAGE_SIZE
            if len(bindings) < SPARQL_PAGE_SIZE:
                break

    # ------------------------------------------------------------------
    # Local RDF files path
    # ------------------------------------------------------------------

    def _parse_local(self, files: list[Path]) -> list[ParsedTerm]:
        g = Graph()
        for f in files:
            logger.info("Loading %s …", f.name)
            g.parse(str(f))

        terms: dict[str, ParsedTerm] = {}

        for cls in g.subjects(RDF.type, OWL.Class):
            if not isinstance(cls, URIRef):
                continue
            uri = str(cls)
            source_id = uri.split("/")[-1]

            label = (
                g.value(cls, RDFS.label)
                or g.value(cls, SKOS.prefLabel)
            )
            if label is None:
                continue

            definition = g.value(cls, RDFS.comment) or g.value(cls, SKOS.definition)

            term = ParsedTerm(
                preferred_label=str(label),
                source=self.source_name,
                source_id=source_id,
                source_uri=uri,
                definition=str(definition) if definition else None,
                term_type="Class",
            )

            for parent in g.objects(cls, RDFS.subClassOf):
                if isinstance(parent, URIRef):
                    term.parent_source_ids.append(str(parent).split("/")[-1])

            for alt in g.objects(cls, RDFS.label):
                alt_str = str(alt)
                if alt_str != term.preferred_label and alt_str not in term.synonyms:
                    term.synonyms.append(alt_str)

            terms[source_id] = term

        logger.info("ISO 15926-4: total %d terms from local files", len(terms))
        return list(terms.values())
