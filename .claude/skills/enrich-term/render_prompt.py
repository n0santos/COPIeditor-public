#!/usr/bin/env python3
"""
Step 1 of the enrich-term skill: fetch cross-source context exactly as the
production pipeline does (enrich_cluster(), enrichment_service.py) and render
the real system/user prompt via build_enrichment_prompt(). No Anthropic API
call — this just does the same gathering + rendering enrich_cluster() does
before it would call call_llm().

Usage:
    python .claude/skills/enrich-term/render_prompt.py "<cluster_label>"

Writes two files next to this script's cwd:
    .enrich_context.json   — everything needed by store_response.py later
                              (definitions, component_terms, cluster_label)
    .enrich_prompt.txt      — the rendered system + user prompt, for display
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "enrichment"))

from enrichment_service import (  # noqa: E402
    get_cluster_definitions,
    get_cluster_subtypes,
    get_related_concepts,
    get_parent_candidates,
    get_existing_ontology_context,
    get_cluster_properties,
    get_cluster_iso14224_properties,
    get_component_terms,
)
from prompts import build_enrichment_prompt  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent


def main():
    if len(sys.argv) != 2:
        print("usage: render_prompt.py '<cluster_label>'", file=sys.stderr)
        sys.exit(1)
    cluster_label = sys.argv[1]

    definitions = get_cluster_definitions(cluster_label)
    if not definitions:
        print(f"ERROR: no definitions found in terms.db for cluster {cluster_label!r} "
              f"(same failure enrich_cluster() would raise)", file=sys.stderr)
        sys.exit(1)

    subtypes = get_cluster_subtypes(cluster_label)
    related = get_related_concepts(cluster_label)
    parent_candidates = get_parent_candidates(cluster_label)
    existing_context = get_existing_ontology_context()
    cfihos_properties = get_cluster_properties(cluster_label)
    iso14224_data = get_cluster_iso14224_properties(cluster_label)
    component_terms = get_component_terms(cluster_label)

    system_prompt, user_prompt = build_enrichment_prompt(
        cluster_label=cluster_label,
        definitions=definitions,
        subtypes=subtypes,
        related_concepts=related,
        parent_candidates=parent_candidates,
        existing_ontology=existing_context,
        cfihos_properties=cfihos_properties,
        iso14224_main_function=iso14224_data["main_function"],
        iso14224_attributes=iso14224_data["attributes"],
        component_terms=component_terms,
    )

    (OUT_DIR / ".enrich_context.json").write_text(json.dumps({
        "cluster_label": cluster_label,
        "definitions": definitions,
        "component_terms": component_terms,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    rendered = (
        f"=== SYSTEM PROMPT ===\n{system_prompt}\n\n"
        f"=== USER PROMPT ===\n{user_prompt}\n"
    )
    (OUT_DIR / ".enrich_prompt.txt").write_text(rendered, encoding="utf-8")

    print(f"Fetched {len(definitions)} cross-source definitions, "
          f"{len(subtypes)} subtypes, {len(parent_candidates)} parent candidates, "
          f"{len(component_terms)} component terms for {cluster_label!r}.")
    print(f"Rendered prompt written to {OUT_DIR / '.enrich_prompt.txt'} "
          f"({len(system_prompt)} + {len(user_prompt)} chars).")
    print(rendered)


if __name__ == "__main__":
    main()
