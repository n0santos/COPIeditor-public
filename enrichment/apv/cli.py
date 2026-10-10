"""Command-line interface for the APV ontology verification tool."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional, List

from apv.quality_criteria import retrieve_language_tags, retrieve_class_annotation_coverage, retrieve_class_uri_formation_rule, retrieve_relation_uri_formation_rule, retrieve_instance_uri_formation_rule, retrieve_relation_annotation_coverage, retrieve_instance_annotation_coverage, retrieve_min_annotation_length, retrieve_max_annotation_length, retrieve_annotation_regular_expression, retrieve_instance_of_annotation_coverage
from apv.quality_testing import check_class_uri_formation_rule, check_relation_uri_formation_rule, check_instance_uri_formation_rule, check_class_min_annotation_coverage, check_relation_min_annotation_coverage, check_instance_min_annotation_coverage, check_min_annotation_length, check_max_annotation_length, check_annotation_regular_expression, check_instance_of_min_annotation_coverage
from apv.sparql_client import SparqlClient


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apv",
        description=(
            "Verify OWL ontologies (RDF) by running SPARQL quality checks "
            "against a local file or a remote SPARQL endpoint."
        ),
    )

    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "-l",
        "--local",
        dest="local_file",
        help="Path to a local RDF file (e.g., .ttl, .rdf, .nt).",
    )
    source.add_argument(
        "-r",
        "--remote",
        dest="remote_endpoint",
        help="URL of a SPARQL endpoint to query.",
    )

    parser.add_argument(
        "--user",
        help="Username for the SPARQL endpoint (optional).",
    )
    parser.add_argument(
        "--password",
        help="Password for the SPARQL endpoint (optional).",
    )

    parser.add_argument(
        "--format",
        default="",
        help="RDF serialization format when loading a local file (default: ttl).",
    )

    output = parser.add_mutually_exclusive_group()
    output.add_argument(
        "--text",
        dest="output_mode",
        action="store_const",
        const="text",
        default="text",
        help="Print human-readable validation output (default).",
    )
    output.add_argument(
        "--json",
        dest="output_mode",
        action="store_const",
        const="json",
        help="Print validation output as JSON.",
    )

    return parser


def _load_client(args: argparse.Namespace) -> SparqlClient:
    if args.local_file:
        if not args.format:
            args.format = args.local_file.split(".")[-1]
            args.format = "xml" if args.format == "owl" else args.format
        return SparqlClient.from_local_file(args.local_file, format=args.format)

    return SparqlClient.from_remote_endpoint(
        args.remote_endpoint, user=args.user, password=args.password
    )


def _print_text_constraints(
    class_uri_formation_rule: Optional[str],
    relation_uri_formation_rule: Optional[str],
    instance_uri_formation_rule: Optional[str],
    language_tags: List[str],
    class_annotation_cardinalities: List[tuple[str, int]],
    relation_annotation_cardinalities: List[tuple[str, int]],
    instance_annotation_cardinalities: List[tuple[str, int]],
    min_annotation_lengths: List[tuple[str, int]],
    max_annotation_lengths: List[tuple[str, int]],
    annotation_regex_expressions: List[tuple[str, str]],
    instance_coverage_requirements: List[tuple[str, List[tuple[str, int]]]],
) -> None:
    if class_uri_formation_rule:
        print("apv:ClassURIFormationRule requires the following URI pattern for Classes:")
        print("- ", class_uri_formation_rule)
    else:
        print("No ClassURIFormationRule statement found in ontology. Skipping class URI formation rule checks.")

    if relation_uri_formation_rule:
        print("apv:RelationURIFormationRule requires the following URI pattern for Relations:")
        print("- ", relation_uri_formation_rule)
    else:
        print("No RelationURIFormationRule statement found in ontology. Skipping relation URI formation rule checks.")

    if instance_uri_formation_rule:
        print("apv:InstanceURIFormationRule requires the following URI pattern for Instances:")
        print("- ", instance_uri_formation_rule)
    else:
        print("No InstanceURIFormationRule statement found in ontology. Skipping instance URI formation rule checks.")

    if language_tags:
        print("apv:GlobalMinLanguageCoverage requires the following language tags:")
        for language_tag in language_tags:
            print("- ", language_tag)
    else:
        print("No GlobalMinLanguageCoverage statement found in ontology. Skipping language coverage checks.")

    if class_annotation_cardinalities:
        print("apv:ClassMinAnnotationCoverage requires the following annotations:")
        for annotation_iri, cardinality in class_annotation_cardinalities:
            print("- ", cardinality, annotation_iri)
    else:
        print("No ClassMinAnnotationCoverage statement found in ontology. Skipping class annotation coverage checks.")

    if relation_annotation_cardinalities:
        print("apv:RelationMinAnnotationCoverage requires the following annotations:")
        for annotation_iri, cardinality in relation_annotation_cardinalities:
            print("- ", cardinality, annotation_iri)
    else:
        print("No RelationMinAnnotationCoverage statement found in ontology. Skipping relation annotation coverage checks.")

    if instance_annotation_cardinalities:
        print("apv:InstanceMinAnnotationCoverage requires the following annotations:")
        for annotation_iri, cardinality in instance_annotation_cardinalities:
            print("- ", cardinality, annotation_iri)
    else:
        print("No InstanceMinAnnotationCoverage statement found in ontology. Skipping instance annotation coverage checks.")

    if min_annotation_lengths:
        print("apv:MinAnnotationLength constraints:")
        for annotation_property, min_length in min_annotation_lengths:
            print("- ", annotation_property, ": minimum", min_length, "characters")
    else:
        print("No MinAnnotationLength constraints found in ontology. Skipping minimum annotation length checks.")

    if max_annotation_lengths:
        print("apv:MaxAnnotationLength constraints:")
        for annotation_property, max_length in max_annotation_lengths:
            print("- ", annotation_property, ": maximum", max_length, "characters")
    else:
        print("No MaxAnnotationLength constraints found in ontology. Skipping maximum annotation length checks.")

    if annotation_regex_expressions:
        print("apv:AnnotationRegularExpression constraints:")
        for annotation_property, regex_pattern in annotation_regex_expressions:
            print("- ", annotation_property, ": regex", regex_pattern)
    else:
        print("No AnnotationRegularExpression constraints found in ontology. Skipping annotation regular expression checks.")

    if instance_coverage_requirements:
        print("apv:InstanceOfMinAnnotationCoverage constraints:")
        for class_uri, annotations in instance_coverage_requirements:
            print("- ", class_uri, ": instances require")
            for annotation_iri, cardinality in annotations:
                print("   - ", cardinality, annotation_iri)
    else:
        print("No InstanceOfMinAnnotationCoverage constraints found in ontology. Skipping instance annotation coverage checks.")


def _print_text_results(results: List[dict[str, Any]]) -> None:
    message_by_check = {
        "ClassURIFormationRule": ("Class URI formation violations found:", "No ClassURIFormationRule violations found."),
        "RelationURIFormationRule": ("Relation URI formation violations found:", "No RelationURIFormationRule violations found."),
        "InstanceURIFormationRule": ("Instance URI formation violations found:", "No InstanceURIFormationRule violations found."),
        "GlobalMinLanguageCoverage": ("Global language coverage violations found:", "No GlobalMinLanguageCoverage violations found."),
        "ClassMinAnnotationCoverage": ("Class annotation coverage violations found:", "No ClassMinAnnotationCoverage violations found."),
        "RelationMinAnnotationCoverage": ("Relation annotation coverage violations found:", "No RelationMinAnnotationCoverage violations found."),
        "InstanceMinAnnotationCoverage": ("Instance annotation coverage violations found:", "No InstanceMinAnnotationCoverage violations found."),
        "MinAnnotationLength": ("Minimum annotation length violations found:", "No MinAnnotationLength violations found."),
        "MaxAnnotationLength": ("Maximum annotation length violations found:", "No MaxAnnotationLength violations found."),
        "AnnotationRegularExpression": ("Annotation regular expression violations found:", "No AnnotationRegularExpression violations found."),
        "InstanceOfMinAnnotationCoverage": ("Instance-of annotation coverage violations found:", "No InstanceOfMinAnnotationCoverage violations found."),
    }

    for result in results:
        check = result["check"]
        violations = result["violations"]
        found_message, empty_message = message_by_check[check]

        if violations:
            print(found_message)
            for violation in violations:
                if isinstance(violation, (list, tuple)) and len(violation) == 2:
                    print("- ", violation[0], ":", violation[1])
                else:
                    print("- ", violation)
        else:
            print(empty_message)


def _build_results(
    client: SparqlClient,
    class_uri_formation_rule: Optional[str],
    relation_uri_formation_rule: Optional[str],
    instance_uri_formation_rule: Optional[str],
    language_tags: List[str],
    class_annotation_cardinalities: List[tuple[str, int]],
    relation_annotation_cardinalities: List[tuple[str, int]],
    instance_annotation_cardinalities: List[tuple[str, int]],
    min_annotation_lengths: List[tuple[str, int]],
    max_annotation_lengths: List[tuple[str, int]],
    annotation_regex_expressions: List[tuple[str, str]],
    instance_coverage_requirements: List[tuple[str, List[tuple[str, int]]]],
) -> List[dict[str, Any]]:
    return [
        {
            "check": "ClassURIFormationRule",
            "parameter": class_uri_formation_rule,
            "violations": check_class_uri_formation_rule(client, class_uri_formation_rule),
        },
        {
            "check": "RelationURIFormationRule",
            "parameter": relation_uri_formation_rule,
            "violations": check_relation_uri_formation_rule(client, relation_uri_formation_rule),
        },
        {
            "check": "InstanceURIFormationRule",
            "parameter": instance_uri_formation_rule,
            "violations": check_instance_uri_formation_rule(client, instance_uri_formation_rule),
        },
        {
            "check": "GlobalMinLanguageCoverage",
            "parameter": language_tags,
            "violations": [],
        },
        {
            "check": "ClassMinAnnotationCoverage",
            "parameter": class_annotation_cardinalities,
            "violations": check_class_min_annotation_coverage(
                client, language_tags, class_annotation_cardinalities
            ),
        },
        {
            "check": "RelationMinAnnotationCoverage",
            "parameter": relation_annotation_cardinalities,
            "violations": check_relation_min_annotation_coverage(
                client, language_tags, relation_annotation_cardinalities
            ),
        },
        {
            "check": "InstanceMinAnnotationCoverage",
            "parameter": instance_annotation_cardinalities,
            "violations": check_instance_min_annotation_coverage(
                client, language_tags, instance_annotation_cardinalities
            ),
        },
        {
            "check": "MinAnnotationLength",
            "parameter": min_annotation_lengths,
            "violations": check_min_annotation_length(client, min_annotation_lengths),
        },
        {
            "check": "MaxAnnotationLength",
            "parameter": max_annotation_lengths,
            "violations": check_max_annotation_length(client, max_annotation_lengths),
        },
        {
            "check": "AnnotationRegularExpression",
            "parameter": annotation_regex_expressions,
            "violations": check_annotation_regular_expression(
                client, annotation_regex_expressions
            ),
        },
        {
            "check": "InstanceOfMinAnnotationCoverage",
            "parameter": instance_coverage_requirements,
            "violations": check_instance_of_min_annotation_coverage(
                client, language_tags, instance_coverage_requirements
            ),
        },
    ]


def _build_constraints(
    class_uri_formation_rule: Optional[str],
    relation_uri_formation_rule: Optional[str],
    instance_uri_formation_rule: Optional[str],
    language_tags: List[str],
    class_annotation_cardinalities: List[tuple[str, int]],
    relation_annotation_cardinalities: List[tuple[str, int]],
    instance_annotation_cardinalities: List[tuple[str, int]],
    min_annotation_lengths: List[tuple[str, int]],
    max_annotation_lengths: List[tuple[str, int]],
    annotation_regex_expressions: List[tuple[str, str]],
    instance_coverage_requirements: List[tuple[str, List[tuple[str, int]]]],
) -> dict[str, Any]:
    return {
        "class_uri_formation_rule": class_uri_formation_rule,
        "relation_uri_formation_rule": relation_uri_formation_rule,
        "instance_uri_formation_rule": instance_uri_formation_rule,
        "language_coverage": language_tags,
        "class_min_annotation_coverage": class_annotation_cardinalities,
        "relation_min_annotation_coverage": relation_annotation_cardinalities,
        "instance_min_annotation_coverage": instance_annotation_cardinalities,
        "min_annotation_length": min_annotation_lengths,
        "max_annotation_length": max_annotation_lengths,
        "annotation_regular_expression": annotation_regex_expressions,
        "instance_of_min_annotation_coverage": instance_coverage_requirements,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    client = _load_client(args)

    # Retrieve annotation quality parameters from the ontology
    class_uri_formation_rule = retrieve_class_uri_formation_rule(client)
    relation_uri_formation_rule = retrieve_relation_uri_formation_rule(client)
    instance_uri_formation_rule = retrieve_instance_uri_formation_rule(client)
    language_tags = retrieve_language_tags(client)
    class_annotation_cardinalities = retrieve_class_annotation_coverage(client)
    relation_annotation_cardinalities = retrieve_relation_annotation_coverage(client)
    instance_annotation_cardinalities = retrieve_instance_annotation_coverage(client)
    min_annotation_lengths = retrieve_min_annotation_length(client)
    max_annotation_lengths = retrieve_max_annotation_length(client)
    annotation_regex_expressions = retrieve_annotation_regular_expression(client)
    instance_coverage_requirements = retrieve_instance_of_annotation_coverage(client)
    if args.output_mode == "text":
        _print_text_constraints(
            class_uri_formation_rule,
            relation_uri_formation_rule,
            instance_uri_formation_rule,
            language_tags,
            class_annotation_cardinalities,
            relation_annotation_cardinalities,
            instance_annotation_cardinalities,
            min_annotation_lengths,
            max_annotation_lengths,
            annotation_regex_expressions,
            instance_coverage_requirements,
        )

    results = _build_results(
        client,
        class_uri_formation_rule,
        relation_uri_formation_rule,
        instance_uri_formation_rule,
        language_tags,
        class_annotation_cardinalities,
        relation_annotation_cardinalities,
        instance_annotation_cardinalities,
        min_annotation_lengths,
        max_annotation_lengths,
        annotation_regex_expressions,
        instance_coverage_requirements,
    )

    if args.output_mode == "json":
        report = {
            "constraints": _build_constraints(
                class_uri_formation_rule,
                relation_uri_formation_rule,
                instance_uri_formation_rule,
                language_tags,
                class_annotation_cardinalities,
                relation_annotation_cardinalities,
                instance_annotation_cardinalities,
                min_annotation_lengths,
                max_annotation_lengths,
                annotation_regex_expressions,
                instance_coverage_requirements,
            ),
            "violations": results,
        }
        print(json.dumps(report, indent=2))
    else:
        _print_text_results(results)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
