import os
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).parent


def _git_version(fallback: str = "1.1.0") -> str:
    """Derive editor version from APP_VERSION env var, then nearest v* git tag."""
    if env_ver := os.getenv("APP_VERSION"):
        return env_ver.removeprefix("v")
    try:
        raw = subprocess.check_output(
            ["git", "describe", "--tags", "--always", "--match", "v[0-9]*"],
            cwd=BASE_DIR,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return raw.removeprefix("v")  # "v1.1.0" → "1.1.0"
    except Exception:
        return fallback


# ── COPI — Core Ontology for Petroleum Installations ──────────────────────
COPI_IRI       = "https://www.inf.ufrgs.br/ontologies/copi"
COPI_NS        = "https://www.inf.ufrgs.br/ontologies/copi/"
COPI_VERSION   = _git_version()
COPI_GITHUB    = "https://github.com/INF-UFRGS-Ontologies/copi"
COPI_GROUP          = "INF-UFRGS-Ontologies"
COPI_CNPQ           = "INF-UFRGS-ENERGIA"
COPI_PROJECT        = "OntoKG"
COPI_PROJECT_FULL   = "OntoKG - Petrobras"
COPI_FULL_NAME      = "COPI — Core Ontology for Petroleum Installations"
COPI_RESEARCH_GROUP = "INF-UFRGS-ENERGIA"
COPI_PUBLISHER      = "Universidade Federal do Rio Grande do Sul (UFRGS)"
COPI_AUTHOR         = "Nicolau Oyhenard dos Santos"
COPI_CREATED        = "2026"

# Contributors — used in dcterms:contributor and displayed on the home page
COPI_CONTRIBUTORS = [
    "Cauã Antunes",
    "Haroldo Rojas",
    "Rafael Petry",
    "Régis Romeu",
    "Mara Abel",
]
# dcterms:description — short one-liner shown in the documentation hero
COPI_DESCRIPTION = (
    "BFO/IOF-Core conformant ontology of equipment classes for petroleum production plants.",
    "Ontologia de classes de equipamentos para plantas de produção de petróleo, conforme BFO/IOF-Core.",
)

# dcterms:license
COPI_LICENSE = ("CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/")

COPI_IMPORTS   = [
    ("BFO 2020",              "http://purl.obolibrary.org/obo/bfo/2020/bfo.owl"),
    ("IOF-Core Release_202603", "https://spec.industrialontologies.org/ontology/core/Core/"),
]
COPI_SCOPE_DEFAULT = (
    "An OWL 2 DL ontology of equipment classes used in petroleum production plants, "
    "grounded in BFO 2020 and conformant with IOF-Core. Developed as part of the "
    "OntoKG research project at UFRGS/INF to provide a formal, reusable reference "
    "data layer for oil & gas plant models."
)

# skos:scopeNote annotations — included verbatim in the owl:Ontology header
COPI_SCOPE_NOTES = [
    # Ontological scope boundary (what counts as in-scope)
    (
        "Material artifacts (bfo:material_entity) that "
        "(i) are part of a petroleum production plant, and "
        "(ii) bear at least one function whose realization involves the transport "
        "(e.g. production and injection), processing (separation and other processes), "
        "control, monitoring, measurement, containment or offloading of material or energy.",
        "en",
    ),
    (
        "Artefatos materiais (bfo:material_entity) que "
        "(i) fazem parte de uma planta de produção de petróleo, e "
        "(ii) possuem ao menos uma função cuja realização envolve o transporte "
        "(p. ex. produção e injeção), processamento (separação e outros processos), "
        "controle, monitoramento, medição, contenção ou escoamento de material ou energia.",
        "pt-br",
    ),
    # Positioning note — COPI is not a reference data library
    (
        "COPI provides high-level equipment categories defined by function to demonstrate "
        "the defined-class mechanism. Equipment subtypes are annotated with references to "
        "CFIHOS and PCA RDL terms. "
        "COPI is not a reference data library; organizations should use CFIHOS, PCA RDL, "
        "or ISO 14224 for comprehensive equipment classification.",
        "en",
    ),
    (
        "COPI fornece categorias de alto nível de equipamentos definidas por função para "
        "demonstrar o mecanismo de classe definida. Os subtipos de equipamentos são anotados "
        "com referências aos termos do CFIHOS e do PCA RDL. "
        "COPI não é uma biblioteca de dados de referência; organizações devem utilizar o "
        "CFIHOS, o PCA RDL ou a ISO 14224 para classificação abrangente de equipamentos.",
        "pt-br",
    ),
]

DATABASE_URL = f"sqlite:///{BASE_DIR}/data/terms.db"

DATA_DIR = BASE_DIR / "data" / "raw"

# SPARQL endpoints
# ISO 15926-4: both known public endpoints are currently unreachable.
# Place local RDF/TTL/OWL files in data/raw/iso15926/ to import offline.
ISO15926_SPARQL_ENDPOINT = "http://data.15926.org/sparql"   # kept for future use
ISO15926_NAMESPACE = "http://data.15926.org/rdl/"

# POSC Caesar: Apache Jena Fuseki at rds.posccaesar.org (OWL, not SKOS)
# Namespace moved from data.posccaesar.org → rds.posccaesar.org
POSC_CAESAR_SPARQL_ENDPOINT = "https://rds.posccaesar.org/ontology/sparql"
POSC_CAESAR_NAMESPACE = "http://rds.posccaesar.org/"   # covers both plm/rdl/ and lis14/rdl/

# Pagination size for SPARQL queries
SPARQL_PAGE_SIZE = 500
