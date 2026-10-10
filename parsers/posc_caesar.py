"""
POSC Caesar Association Reference Data Library parser.

The PCA RDL is now hosted at https://rds.posccaesar.org/ontology/sparql as an
OWL ontology (NOT SKOS). Namespaces:
  - http://rds.posccaesar.org/ontology/plm/rdl/   (PLM RDL — main engineering concepts)
  - http://rds.posccaesar.org/ontology/lis14/rdl/  (LIS14 foundational classes)

Falls back to local RDF files in data/raw/posc_caesar/ if present.
"""
from __future__ import annotations

import logging
from pathlib import Path

from rdflib import OWL, RDF, RDFS, Graph, Namespace, URIRef
from rdflib.namespace import SKOS
from SPARQLWrapper import JSON, SPARQLWrapper

from config import (
    DATA_DIR,
    POSC_CAESAR_NAMESPACE,
    POSC_CAESAR_SPARQL_ENDPOINT,
    SPARQL_PAGE_SIZE,
)
from parsers.base import BaseParser, ParsedTerm

logger = logging.getLogger(__name__)

_PLM_NS = "http://rds.posccaesar.org/ontology/plm/rdl/"
_LIS14_NS = "http://rds.posccaesar.org/ontology/lis14/rdl/"


class POSCCaesarParser(BaseParser):
    source_name = "posc_caesar"

    def parse(self) -> list[ParsedTerm]:
        extensions = ["rdf", "ttl", "owl", "n3", "nt"]
        local_files: list[Path] = []
        for ext in extensions:
            local_files.extend((DATA_DIR / "posc_caesar").glob(f"*.{ext}"))

        if local_files:
            logger.info("POSC Caesar: parsing %d local file(s)", len(local_files))
            return self._parse_local(local_files)

        logger.info("POSC Caesar: fetching from SPARQL endpoint %s", POSC_CAESAR_SPARQL_ENDPOINT)
        return self._fetch_sparql()

    # ------------------------------------------------------------------
    # SPARQL path  (OWL structure, rds.posccaesar.org)
    # ------------------------------------------------------------------

    def _fetch_sparql(self) -> list[ParsedTerm]:
        sparql = SPARQLWrapper(POSC_CAESAR_SPARQL_ENDPOINT)
        sparql.setReturnFormat(JSON)
        sparql.setTimeout(60)

        terms: dict[str, ParsedTerm] = {}
        offset = 0

        while True:
            query = f"""
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            PREFIX owl:  <http://www.w3.org/2002/07/owl#>
            PREFIX skos: <http://www.w3.org/2004/02/skos/core#>

            SELECT DISTINCT ?class ?label ?definition ?parent WHERE {{
                ?class a owl:Class .
                FILTER(
                    STRSTARTS(STR(?class), "{_PLM_NS}") ||
                    STRSTARTS(STR(?class), "{_LIS14_NS}")
                )
                ?class rdfs:label ?label .
                FILTER(LANG(?label) = "" || LANG(?label) = "en")
                OPTIONAL {{
                    {{ ?class rdfs:comment ?definition }}
                    UNION
                    {{ ?class skos:definition ?definition }}
                    FILTER(LANG(?definition) = "" || LANG(?definition) = "en")
                }}
                OPTIONAL {{
                    ?class rdfs:subClassOf ?parent .
                    FILTER(isURI(?parent))
                    FILTER(
                        STRSTARTS(STR(?parent), "{_PLM_NS}") ||
                        STRSTARTS(STR(?parent), "{_LIS14_NS}")
                    )
                }}
            }}
            ORDER BY ?label
            LIMIT {SPARQL_PAGE_SIZE}
            OFFSET {offset}
            """
            sparql.setQuery(query)

            try:
                results = sparql.query().convert()
                if not isinstance(results, dict):
                    logger.error("POSC Caesar SPARQL: unexpected response type")
                    break
            except Exception as exc:
                logger.error("POSC Caesar SPARQL error: %s", exc)
                break

            bindings = results["results"]["bindings"]
            if not bindings:
                break

            for row in bindings:
                uri = row["class"]["value"]
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
                else:
                    # Supplement missing definition from additional rows
                    if not terms[source_id].definition and definition:
                        terms[source_id].definition = definition

                if parent_uri:
                    parent_id = parent_uri.split("/")[-1]
                    if parent_id not in terms[source_id].parent_source_ids:
                        terms[source_id].parent_source_ids.append(parent_id)

            offset += SPARQL_PAGE_SIZE
            logger.debug("POSC Caesar: fetched %d terms so far", len(terms))

            if len(bindings) < SPARQL_PAGE_SIZE:
                break

        if terms:
            self._fetch_alt_labels_sparql(sparql, terms)

        logger.info("POSC Caesar: total %d terms", len(terms))
        if not terms:
            logger.warning(
                "POSC Caesar: SPARQL endpoint returned no data. "
                "Place local RDF files in data/raw/posc_caesar/ to import offline."
            )
        return list(terms.values())

    def _fetch_alt_labels_sparql(
        self, sparql: SPARQLWrapper, terms: dict[str, ParsedTerm]
    ) -> None:
        offset = 0
        while True:
            query = f"""
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            PREFIX skos: <http://www.w3.org/2004/02/skos/core#>

            SELECT DISTINCT ?class ?alt WHERE {{
                {{ ?class skos:altLabel ?alt }}
                UNION
                {{ ?class rdfs:label ?alt }}
                FILTER(
                    STRSTARTS(STR(?class), "{_PLM_NS}") ||
                    STRSTARTS(STR(?class), "{_LIS14_NS}")
                )
                FILTER(LANG(?alt) = "" || LANG(?alt) = "en")
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
                source_id = row["class"]["value"].split("/")[-1]
                alt = row["alt"]["value"]
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

            for alt in g.objects(cls, SKOS.altLabel):
                alt_str = str(alt)
                if alt_str not in term.synonyms:
                    term.synonyms.append(alt_str)

            terms[source_id] = term

        logger.info("POSC Caesar: total %d terms from local files", len(terms))
        return list(terms.values())
