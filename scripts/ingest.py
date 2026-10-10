"""
CLI ingestion script.

Usage:
    python -m scripts.ingest                        # ingest all sources
    python -m scripts.ingest --source iso15926      # single source
    python -m scripts.ingest --source cfihos dexpi  # multiple sources
    python -m scripts.ingest --clear                # drop existing data first
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from sqlalchemy.orm import Session

# Make sure the project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal, init_db
from app.models import Hierarchy, Mapping, Property, Synonym, Term
from parsers.base import ParsedTerm
from parsers.cfihos import CFIHOSParser
from parsers.dexpi import DEXPIParser
from parsers.iso15926 import ISO15926Parser
from parsers.posc_caesar import POSCCaesarParser
from parsers.slb_glossary import SLBGlossaryParser
from parsers.iso14224 import ISO14224Parser
from parsers.isa5_1 import ISA51Parser
from parsers.onepetro_glossary import OnePetroGlossaryParser
from parsers.ppdm import PPDMParser

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ingest")

console = Console()
app = typer.Typer(add_completion=False)

PARSERS = {
    "iso15926": ISO15926Parser,
    "posc_caesar": POSCCaesarParser,
    "cfihos": CFIHOSParser,
    "dexpi": DEXPIParser,
    "slb_glossary": SLBGlossaryParser,
    "iso14224": ISO14224Parser,
    "isa5_1": ISA51Parser,
    "onepetro_glossary": OnePetroGlossaryParser,
    "ppdm": PPDMParser,
}


@app.command()
def main(
    source: Optional[list[str]] = typer.Option(
        None, "--source", "-s",
        help="Sources to ingest. Defaults to all. Options: iso15926, posc_caesar, cfihos, dexpi",
    ),
    clear: bool = typer.Option(False, "--clear", help="Delete existing data for selected sources before ingestion"),
):
    init_db()

    selected = source if source else list(PARSERS.keys())
    invalid = [s for s in selected if s not in PARSERS]
    if invalid:
        console.print(f"[red]Unknown sources: {invalid}. Valid options: {list(PARSERS.keys())}")
        raise typer.Exit(1)

    db = SessionLocal()
    try:
        stats: dict[str, dict] = {}

        for src in selected:
            console.rule(f"[bold blue]{src}")

            if clear:
                deleted = db.query(Term).filter(Term.source == src).count()
                db.query(Term).filter(Term.source == src).delete()
                db.commit()
                console.print(f"  Cleared {deleted} existing terms.")

            parser_cls = PARSERS[src]
            parser = parser_cls()

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                task = progress.add_task(f"Parsing {src} …", total=None)
                parsed_terms = parser.parse()
                progress.update(task, description=f"Parsed {len(parsed_terms)} terms")

            # Build a map of source_id -> Term.id for hierarchy resolution
            source_id_to_db_id: dict[str, int] = {}

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                task = progress.add_task(f"Saving {src} terms …", total=len(parsed_terms))

                new_terms = 0
                for pt in parsed_terms:
                    db_term = _upsert_term(db, pt)
                    source_id_to_db_id[pt.source_id] = db_term.id
                    new_terms += 1
                    progress.advance(task)

                db.commit()

            # Hierarchy
            hier_count = _save_hierarchy(db, parsed_terms, source_id_to_db_id)
            db.commit()

            stats[src] = {
                "terms": new_terms,
                "hierarchy_edges": hier_count,
            }
            console.print(
                f"  [green]✓[/green] {new_terms} terms, {hier_count} hierarchy edges saved."
            )

    finally:
        db.close()

    # Summary table
    table = Table(title="Ingestion Summary")
    table.add_column("Source", style="cyan")
    table.add_column("Terms", justify="right")
    table.add_column("Hierarchy edges", justify="right")

    for src, s in stats.items():
        table.add_row(src, str(s["terms"]), str(s["hierarchy_edges"]))

    console.print(table)


def _upsert_term(db: Session, pt: ParsedTerm) -> Term:
    # Try to find existing term by source + source_id
    db_term = (
        db.query(Term)
        .filter(Term.source == pt.source, Term.source_id == pt.source_id)
        .first()
    )

    if db_term is None:
        db_term = Term(
            preferred_label=pt.preferred_label,
            source=pt.source,
            source_id=pt.source_id,
            source_uri=pt.source_uri,
            definition=pt.definition,
            term_type=pt.term_type,
        )
        db.add(db_term)
        db.flush()
    else:
        db_term.preferred_label = pt.preferred_label
        db_term.definition = pt.definition or db_term.definition
        db_term.source_uri = pt.source_uri or db_term.source_uri
        db_term.term_type = pt.term_type or db_term.term_type

    # Synonyms
    existing_synonyms = {s.label for s in db_term.synonyms}
    for syn in pt.synonyms:
        if syn and syn not in existing_synonyms:
            db.add(Synonym(term_id=db_term.id, label=syn))

    # Properties — replace entirely so re-ingestion clears stale/garbled rows
    if pt.properties:
        # Delete all existing properties for this term; cascade handles the DELETE
        for existing_prop in list(db_term.properties):
            db.delete(existing_prop)
        db.flush()
        for pp in pt.properties:
            db.add(Property(
                term_id=db_term.id,
                name=pp.name,
                definition=pp.definition,
                datatype=pp.datatype,
                unit=pp.unit,
                is_required=pp.is_required,
            ))

    return db_term


def _save_hierarchy(
    db: Session,
    parsed_terms: list[ParsedTerm],
    source_id_to_db_id: dict[str, int],
) -> int:
    count = 0
    for pt in parsed_terms:
        child_db_id = source_id_to_db_id.get(pt.source_id)
        if child_db_id is None:
            continue
        for parent_source_id in pt.parent_source_ids:
            parent_db_id = source_id_to_db_id.get(parent_source_id)
            if parent_db_id is None:
                continue
            exists = (
                db.query(Hierarchy)
                .filter(
                    Hierarchy.parent_term_id == parent_db_id,
                    Hierarchy.child_term_id == child_db_id,
                )
                .first()
            )
            if not exists:
                db.add(Hierarchy(
                    parent_term_id=parent_db_id,
                    child_term_id=child_db_id,
                    relation_type="subClassOf",
                ))
                count += 1
    return count


if __name__ == "__main__":
    app()
