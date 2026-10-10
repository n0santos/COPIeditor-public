# tests/test_class_annotation_registry.py
"""
class_annotation is the single source of rdfs:label@pt-br and
iof-av:naturalLanguageDefinition (@en/@pt-br) for every class generate_turtle()
emits that is not the entry's own equipment class: functions, processes, their
parent stubs and part stubs.

Before it existed, a function shared by N entries (FlowControlFunction: 19) was
emitted N times with whatever definition each entry's LLM run happened to
write, so APV's "exactly 1" check failed with 0 or several values; part stubs
carried no definition at all. The registry wins field by field; the previous
per-entry sources remain the fallback for fields the registry leaves empty.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "enrichment"))


def _svc():
    import enrichment.enrichment_service as svc
    return svc


REG = {
    "FlowControlFunction": {"label_pt": "função de controle de fluxo",
                            "definition_en": "Registry EN.", "definition_pt": "Registro PT."},
    "HalfFilled": {"label_pt": None, "definition_en": "Only EN in registry.", "definition_pt": ""},
}


def _patch(monkeypatch):
    svc = _svc()
    monkeypatch.setattr(svc, "_lookup_class_annotation", lambda name: REG.get(name))
    return svc


def test_registry_wins_over_fallbacks(monkeypatch):
    svc = _patch(monkeypatch)
    ttl = svc._class_annotation_ttl("FlowControlFunction", label_pt="fallback pt",
                                    definition_en="Fallback EN.", definition_pt="Fallback PT.")
    assert '"função de controle de fluxo"@pt-br' in ttl
    assert 'iof-av:naturalLanguageDefinition "Registry EN."@en' in ttl
    assert 'skos:definition "Registry EN."@en' in ttl
    assert 'iof-av:naturalLanguageDefinition "Registro PT."@pt-br' in ttl
    assert "Fallback" not in ttl and "fallback" not in ttl


def test_shared_function_emits_identical_text_regardless_of_entry(monkeypatch):
    svc = _patch(monkeypatch)
    a = svc._class_annotation_ttl("FlowControlFunction", definition_en="Entry A's own wording.")
    b = svc._class_annotation_ttl("FlowControlFunction", definition_en="Entry B's different wording.")
    assert a == b


def test_empty_registry_fields_fall_back(monkeypatch):
    svc = _patch(monkeypatch)
    ttl = svc._class_annotation_ttl("HalfFilled", label_pt="rótulo", definition_pt="Fallback PT.")
    assert 'iof-av:naturalLanguageDefinition "Only EN in registry."@en' in ttl
    assert '"rótulo"@pt-br' in ttl
    assert '"Fallback PT."@pt-br' in ttl


def test_unknown_class_without_fallbacks_emits_nothing(monkeypatch):
    svc = _patch(monkeypatch)
    assert svc._class_annotation_ttl("NotInRegistry") == ""


def test_text_is_escaped_for_turtle(monkeypatch):
    svc = _svc()
    monkeypatch.setattr(svc, "_lookup_class_annotation",
                        lambda name: {"definition_en": 'Has "quotes" inside.'})
    ttl = svc._class_annotation_ttl("Quoted")
    assert '\\"quotes\\"' in ttl
