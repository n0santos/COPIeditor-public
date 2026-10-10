# tests/test_zenodo_release.py
"""
Zenodo's GitHub integration cannot see this repository: it only lists
organisation repos when the Zenodo OAuth app is granted access to the
organisation, and that grant is not in place. scripts/zenodo_release.py mints
the DOI through Zenodo's REST API instead, which needs nothing from GitHub.

The client takes its HTTP session as an argument so the call sequence can be
tested without touching zenodo.org.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


class FakeSession:
    """Records calls and replays queued responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def _next(self, method, url, **kw):
        self.calls.append((method, url, kw.get("json"), kw.get("data") is not None))
        if not self.responses:
            raise AssertionError(f"unexpected call: {method} {url}")
        return self.responses.pop(0)

    def get(self, url, **kw):
        return self._next("GET", url, **kw)

    def post(self, url, **kw):
        return self._next("POST", url, **kw)

    def put(self, url, **kw):
        return self._next("PUT", url, **kw)


def _mod():
    import zenodo_release
    return zenodo_release


DEPOSITION = {
    "id": 111,
    "conceptrecid": "100",
    "links": {"bucket": "https://zenodo.org/api/files/bucket-1",
              "publish": "https://zenodo.org/api/deposit/depositions/111/actions/publish"},
    "metadata": {"prereserve_doi": {"doi": "10.5281/zenodo.111", "recid": 111}},
}
PUBLISHED = {**DEPOSITION, "doi": "10.5281/zenodo.111", "conceptdoi": "10.5281/zenodo.100"}


def test_first_release_creates_deposition_uploads_and_publishes(tmp_path):
    f = tmp_path / "copi.owl"
    f.write_text("<rdf/>", encoding="utf-8")
    session = FakeSession([FakeResponse(201, DEPOSITION), FakeResponse(201, {}), FakeResponse(202, PUBLISHED)])
    client = _mod().ZenodoClient(token="t", session=session)

    result = client.publish_release(metadata={"title": "COPI", "version": "2026-09-24"}, files=[f])

    methods = [c[0] for c in session.calls]
    assert methods == ["POST", "PUT", "POST"]
    assert session.calls[1][1].endswith("/bucket-1/copi.owl")
    assert result.doi == "10.5281/zenodo.111"
    assert result.concept_doi == "10.5281/zenodo.100"


def test_later_release_uses_newversion_of_the_concept(tmp_path):
    f = tmp_path / "copi.owl"
    f.write_text("<rdf/>", encoding="utf-8")
    newversion = {"links": {"latest_draft": "https://zenodo.org/api/deposit/depositions/222"}}
    draft = {**DEPOSITION, "id": 222,
             "links": {"bucket": "https://zenodo.org/api/files/bucket-2",
                       "publish": "https://zenodo.org/api/deposit/depositions/222/actions/publish"}}
    session = FakeSession([
        FakeResponse(201, newversion),      # POST .../actions/newversion
        FakeResponse(200, draft),           # GET latest_draft
        FakeResponse(200, draft),           # PUT metadata
        FakeResponse(201, {}),              # PUT file
        FakeResponse(202, {**draft, "doi": "10.5281/zenodo.222", "conceptdoi": "10.5281/zenodo.100"}),
    ])
    client = _mod().ZenodoClient(token="t", session=session)

    result = client.publish_release(metadata={"title": "COPI", "version": "2026-10-01"},
                                    files=[f], previous_deposition_id=111)

    assert "actions/newversion" in session.calls[0][1]
    assert result.doi == "10.5281/zenodo.222"
    assert result.concept_doi == "10.5281/zenodo.100"


def test_dry_run_makes_no_http_call(tmp_path):
    f = tmp_path / "copi.owl"
    f.write_text("<rdf/>", encoding="utf-8")
    session = FakeSession([])  # any call raises
    client = _mod().ZenodoClient(token="t", session=session, dry_run=True)

    result = client.publish_release(metadata={"title": "COPI", "version": "2026-09-24"}, files=[f])

    assert session.calls == []
    assert result.doi is None and result.dry_run is True


def test_failed_call_raises_with_response_body(tmp_path):
    f = tmp_path / "copi.owl"
    f.write_text("<rdf/>", encoding="utf-8")
    session = FakeSession([FakeResponse(403, {"message": "insufficient scope"})])
    client = _mod().ZenodoClient(token="t", session=session)

    with pytest.raises(_mod().ZenodoError) as exc:
        client.publish_release(metadata={"title": "COPI"}, files=[f])
    assert "insufficient scope" in str(exc.value)


def test_doi_annotation_is_written_as_bibo_doi(tmp_path):
    """FOOPS reads the DOI from bibo:doi (Ontology.java, PROP_BIBO_DOI)."""
    edit = tmp_path / "copi-edit.owl"
    edit.write_text('Ontology(<x>\nAnnotation(bibo:status "unstable")\n', encoding="utf-8")

    changed = _mod().write_doi_annotation(edit, "10.5281/zenodo.100")
    assert changed is True
    assert 'Annotation(bibo:doi "10.5281/zenodo.100")' in edit.read_text(encoding="utf-8")

    assert _mod().write_doi_annotation(edit, "10.5281/zenodo.100") is False  # idempotent
