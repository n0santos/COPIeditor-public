# tests/test_function_definitions.py
"""
generate_turtle() used to read a function's definition only from the stored
llm_raw_response (English only), ignoring the reviewer-editable
function_nl_definition_en / _pt columns that the Nível 1 generator already uses.
A reviewer-written definition therefore never reached the class TTL, and no
Portuguese function definition was ever emitted.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "enrichment"))


def _svc():
    import enrichment.enrichment_service as svc
    return svc


def _raw(defn):
    return json.dumps({"step1_function": {"function_nl_definition": defn}})


def test_columns_take_precedence_over_raw_response():
    e = {"function_nl_definition_en": "Column EN definition.",
         "function_nl_definition_pt": "Definição PT da coluna.",
         "llm_raw_response": _raw("Raw EN definition.")}
    assert _svc()._function_definitions(e) == ("Column EN definition.", "Definição PT da coluna.")


def test_falls_back_to_raw_response_when_columns_empty():
    e = {"function_nl_definition_en": "", "function_nl_definition_pt": None,
         "llm_raw_response": _raw("Raw EN definition.")}
    assert _svc()._function_definitions(e) == ("Raw EN definition.", "")


def test_malformed_raw_response_yields_empty():
    e = {"llm_raw_response": "not json"}
    assert _svc()._function_definitions(e) == ("", "")
