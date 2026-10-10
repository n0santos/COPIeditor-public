"""Quality criteria retrieval functions for OWL ontologies."""

from typing import List, Optional, Tuple
import re

#language_tags docs at: https://github.com/OnroerendErfgoed/language-tags/blob/develop/docs/source/introduction.rst
import language_tags as language_tags_lib

from rdflib import Namespace

from apv.sparql_client import SparqlClient


OWL = Namespace("http://www.w3.org/2002/07/owl#")
APV = Namespace("http://inf.ufrgs.br/ontologies/apv#")
RDFS = Namespace("http://www.w3.org/2000/01/rdf-schema#")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")


def retrieve_language_tags(client: SparqlClient) -> List[str]:
    """Retrieve the list of required language tags from the ontology's GlobalMinLanguageCoverage."""
    query = """
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX apv: <http://inf.ufrgs.br/ontologies/apv#>

        SELECT ?gmlc WHERE {
            ?o a owl:Ontology ;
               apv:GlobalMinLanguageCoverage ?gmlc .
        }
    """
    results = list(client.query(query))
    gmlc_value = str(results[0][0]).strip() if results else ""
    
    unvalidated_language_tags = gmlc_value.split()
    for tag in unvalidated_language_tags:
        if not language_tags_lib.tags.check(tag):
            raise ValueError(f"Invalid language tag in GlobalMinLanguageCoverage: '{tag}'")
    validated_language_tags = unvalidated_language_tags
    return validated_language_tags


def retrieve_class_uri_formation_rule(client: SparqlClient) -> Optional[str]:
    """Retrieve the class URI formation rule from the ontology's ClassURIFormationRule."""
    query = """
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX apv: <http://inf.ufrgs.br/ontologies/apv#>

        SELECT ?cfre WHERE {
            ?o a owl:Ontology ;
               apv:ClassURIFormationRule ?cfre .
        }
    """
    results = list(client.query(query))
    if results:
        cfre_value = str(results[0][0]).strip()
        # Validate the format as a regular expression pattern
        try:
            re.compile(cfre_value)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern for ClassURIFormationRule: '{cfre_value}' - {e}")
        return cfre_value
    return None


def retrieve_relation_uri_formation_rule(client: SparqlClient) -> Optional[str]:
    """Retrieve the relation URI formation rule from the ontology's RelationURIFormationRule."""
    query = """
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX apv: <http://inf.ufrgs.br/ontologies/apv#>

        SELECT ?rfre WHERE {
            ?o a owl:Ontology ;
               apv:RelationURIFormationRule ?rfre .
        }
    """
    results = list(client.query(query))
    if results:
        rfre_value = str(results[0][0]).strip()
        # Validate the format as a regular expression pattern
        try:
            re.compile(rfre_value)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern for RelationURIFormationRule: '{rfre_value}' - {e}")
        return rfre_value
    return None


def retrieve_instance_uri_formation_rule(client: SparqlClient) -> Optional[str]:
    """Retrieve the instance URI formation rule from the ontology's InstanceURIFormationRule."""
    query = """
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX apv: <http://inf.ufrgs.br/ontologies/apv#>

        SELECT ?ifre WHERE {
            ?o a owl:Ontology ;
               apv:InstanceURIFormationRule ?ifre .
        }
    """
    results = list(client.query(query))
    if results:
        ifre_value = str(results[0][0]).strip()
        # Validate the format as a regular expression pattern
        try:
            re.compile(ifre_value)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern for InstanceURIFormationRule: '{ifre_value}' - {e}")
        return ifre_value
    return None


def retrieve_class_annotation_coverage(client: SparqlClient) -> Optional[str]:
    """Retrieve the class annotation coverage requirement from the ontology's ClassMinAnnotationCoverage."""
    query = """
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX apv: <http://inf.ufrgs.br/ontologies/apv#>

        SELECT ?cmac WHERE {
            ?o a owl:Ontology ;
               apv:ClassMinAnnotationCoverage ?cmac .
        }
    """
    results = list(client.query(query))
    class_annotation_cardinalities = []
    if results:
        cmac_values = str(results[0][0]).strip()
        for cmac_value in cmac_values.split(): 
            # Validate the format with regex: sequence of properties or cardinalities^properties
            if re.fullmatch(r'^([\w:./-]+)$', cmac_value):
                cardinality = 1
                annotation_iri = cmac_value
                class_annotation_cardinalities.append((annotation_iri, cardinality))
            elif re.fullmatch(r'^(\d+\^[\w:./-]+)$', cmac_value):
                cardinality, annotation_iri = cmac_value.split('^')
                cardinality = int(cardinality)
                class_annotation_cardinalities.append((annotation_iri, cardinality))
            else:
                raise ValueError(f"Invalid format for ClassMinAnnotationCoverage: '{cmac_value}'")

    return class_annotation_cardinalities


def retrieve_relation_annotation_coverage(client: SparqlClient) -> List[Tuple[str, int]]:
    """Retrieve the relation annotation coverage requirement from the ontology's RelationMinAnnotationCoverage."""
    query = """
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX apv: <http://inf.ufrgs.br/ontologies/apv#>

        SELECT ?rmac WHERE {
            ?o a owl:Ontology ;
               apv:RelationMinAnnotationCoverage ?rmac .
        }
    """
    results = list(client.query(query))
    relation_annotation_cardinalities = []
    if results:
        rmac_values = str(results[0][0]).strip()
        for rmac_value in rmac_values.split(): 
            # Validate the format with regex: sequence of properties or cardinalities^properties
            if re.fullmatch(r'^([\w:./-]+)$', rmac_value):
                cardinality = 1
                annotation_iri = rmac_value
                relation_annotation_cardinalities.append((annotation_iri, cardinality))
            elif re.fullmatch(r'^(\d+\^[\w:./-]+)$', rmac_value):
                cardinality, annotation_iri = rmac_value.split('^')
                cardinality = int(cardinality)
                relation_annotation_cardinalities.append((annotation_iri, cardinality))
            else:
                raise ValueError(f"Invalid format for RelationMinAnnotationCoverage: '{rmac_value}'")

    return relation_annotation_cardinalities


def retrieve_instance_annotation_coverage(client: SparqlClient) -> List[Tuple[str, int]]:
    """Retrieve the instance annotation coverage requirement from the ontology's InstanceMinAnnotationCoverage."""
    query = """
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX apv: <http://inf.ufrgs.br/ontologies/apv#>

        SELECT ?imac WHERE {
            ?o a owl:Ontology ;
               apv:InstanceMinAnnotationCoverage ?imac .
        }
    """
    results = list(client.query(query))
    instance_annotation_cardinalities = []
    if results:
        imac_values = str(results[0][0]).strip()
        for imac_value in imac_values.split(): 
            # Validate the format with regex: sequence of properties or cardinalities^properties
            if re.fullmatch(r'^([\w:./-]+)$', imac_value):
                cardinality = 1
                annotation_iri = imac_value
                instance_annotation_cardinalities.append((annotation_iri, cardinality))
            elif re.fullmatch(r'^(\d+\^[\w:./-]+)$', imac_value):
                cardinality, annotation_iri = imac_value.split('^')
                cardinality = int(cardinality)
                instance_annotation_cardinalities.append((annotation_iri, cardinality))
            else:
                raise ValueError(f"Invalid format for InstanceMinAnnotationCoverage: '{imac_value}'")

    return instance_annotation_cardinalities


def retrieve_min_annotation_length(client: SparqlClient) -> List[Tuple[str, int]]:
    """Retrieve the minimum annotation length requirements from annotation properties."""
    query = """
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX apv: <http://inf.ufrgs.br/ontologies/apv#>

        SELECT ?ap ?mal WHERE {
            ?ap a owl:AnnotationProperty ;
                apv:MinAnnotationLength ?mal .
        }
    """
    results = list(client.query(query))
    min_annotation_lengths = []
    for result in results:
        annotation_property = str(result[0]).strip()
        min_length = int(str(result[1]).strip())
        min_annotation_lengths.append((annotation_property, min_length))
    return min_annotation_lengths


def retrieve_max_annotation_length(client: SparqlClient) -> List[Tuple[str, int]]:
    """Retrieve the maximum annotation length requirements from annotation properties."""
    query = """
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX apv: <http://inf.ufrgs.br/ontologies/apv#>

        SELECT ?ap ?mal WHERE {
            ?ap a owl:AnnotationProperty ;
                apv:MaxAnnotationLength ?mal .
        }
    """
    results = list(client.query(query))
    max_annotation_lengths = []
    for result in results:
        annotation_property = str(result[0]).strip()
        max_length = int(str(result[1]).strip())
        max_annotation_lengths.append((annotation_property, max_length))
    return max_annotation_lengths


def retrieve_annotation_regular_expression(client: SparqlClient) -> List[Tuple[str, str]]:
    """Retrieve the annotation regular expression constraints from annotation properties."""
    query = """
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX apv: <http://inf.ufrgs.br/ontologies/apv#>

        SELECT ?ap ?are WHERE {
            ?ap a owl:AnnotationProperty ;
                apv:AnnotationRegularExpression ?are .
        }
    """
    results = list(client.query(query))
    annotation_regex_expressions = []
    for result in results:
        annotation_property = str(result[0]).strip()
        regex_pattern = str(result[1]).strip()
        # Validate the regex pattern
        try:
            re.compile(regex_pattern)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern for AnnotationRegularExpression on {annotation_property}: '{regex_pattern}' - {e}")
        annotation_regex_expressions.append((annotation_property, regex_pattern))
    return annotation_regex_expressions


def retrieve_instance_of_annotation_coverage(client: SparqlClient) -> List[Tuple[str, List[Tuple[str, int]]]]:
    """Retrieve the instance annotation coverage requirements from classes' InstanceOfMinAnnotationCoverage."""
    query = """
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX apv: <http://inf.ufrgs.br/ontologies/apv#>

        SELECT ?class ?ioac WHERE {
            ?class a owl:Class ;
                   apv:InstanceOfMinAnnotationCoverage ?ioac .
        }
    """
    results = list(client.query(query))
    instance_coverage_requirements = []
    for result in results:
        class_uri = str(result[0]).strip()
        ioac_values = str(result[1]).strip()
        class_annotations = []
        for ioac_value in ioac_values.split():
            # Validate the format with regex: sequence of properties or cardinalities^properties
            if re.fullmatch(r'^([\w:./-]+)$', ioac_value):
                cardinality = 1
                annotation_iri = ioac_value
                class_annotations.append((annotation_iri, cardinality))
            elif re.fullmatch(r'^(\d+\^[\w:./-]+)$', ioac_value):
                cardinality, annotation_iri = ioac_value.split('^')
                cardinality = int(cardinality)
                class_annotations.append((annotation_iri, cardinality))
            else:
                raise ValueError(f"Invalid format for InstanceOfMinAnnotationCoverage on {class_uri}: '{ioac_value}'")
        instance_coverage_requirements.append((class_uri, class_annotations))
    return instance_coverage_requirements