"""SPARQL client abstraction for local and remote RDF querying."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Union

from rdflib import Graph
from rdflib.plugins.stores.sparqlstore import SPARQLStore


@dataclass
class SparqlClient:
    """A simple SPARQL client that can query a local graph or a remote endpoint."""

    local_graph: Optional[Graph] = None
    store: Optional[SPARQLStore] = None

    @classmethod
    def from_local_file(cls, path: str, format: str = "") -> "SparqlClient":
        """Create a client backed by a local RDF file."""
        graph = Graph()
        if not format:
            format = path.split(".")[-1]
            format = "xml" if format == "owl" else format
        graph.parse(path, format=format)
        return cls(local_graph=graph)

    @classmethod
    def from_remote_endpoint(
        cls,
        endpoint: str,
        user: Optional[str] = None,
        password: Optional[str] = None,
        auth_header: Optional[str] = None,
    ) -> "SparqlClient":
        """Create a client that queries a remote SPARQL endpoint."""
        store_kwargs = {"method": "POST_FORM", "returnFormat": "json"}
        if auth_header:
            store_kwargs["headers"] = {"Authorization": auth_header}
        store = SPARQLStore(endpoint, **store_kwargs)
        if user or password:
            store.setCredentials(user or "", password or "")
        return cls(store=store)

    def query(self, sparql: str, init_ns: Optional[dict] = None) -> Iterable[tuple]:
        """Execute a SPARQL query, returning the raw results."""
        if self.local_graph is not None:
            return self.local_graph.query(sparql, initNs=init_ns or {})
        if self.store is not None:
            graph = Graph(store=self.store)
            return graph.query(sparql, initNs=init_ns or {})
        raise RuntimeError("No SPARQL backend configured")
