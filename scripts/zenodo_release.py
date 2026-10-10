#!/usr/bin/env python3
"""
Mint a Zenodo DOI for a COPI release through Zenodo's REST API.

Zenodo's GitHub integration is not usable here: it only lists repositories of a
GitHub organisation once the Zenodo OAuth app has been granted access to that
organisation, and that grant is not in place for INF-UFRGS-Ontologies. The REST
API needs nothing from GitHub.

Order matters. FOOPS! reads the DOI from inside the ontology (bibo:doi, or a
dcterms:identifier whose value contains "doi." — see Ontology.java in
oeg-upm/fair_ontologies), so the DOI has to exist before the artefacts are
built. `prereserve_doi` gives the version DOI at creation time, and the concept
DOI — the one that means "all versions", and the one that belongs in the
ontology — is 10.5281/zenodo.<conceptrecid>, also known before publishing. The
published record's own `conceptdoi` is checked against it afterwards.

Usage (from the COPIeditor root, .venv active):

    export ZENODO_TOKEN=...          # scopes: deposit:write, deposit:actions
    python -m scripts.zenodo_release --version 2026-09-24            # dry run
    python -m scripts.zenodo_release --version 2026-09-24 --publish

State (deposition id, concept DOI) is kept in scripts/zenodo-state.json so the
next release becomes a new version of the same record instead of a new one.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

COPIEDITOR_ROOT = Path(__file__).resolve().parents[1]
COPI_REPO_ROOT = COPIEDITOR_ROOT.parent / "copi"
STATE_PATH = COPIEDITOR_ROOT / "scripts" / "zenodo-state.json"
EDIT_OWL_PATH = COPI_REPO_ROOT / "src" / "ontology" / "copi-edit.owl"
ZENODO_API = "https://zenodo.org/api"

RELEASE_FILES = [
    "copi.owl", "copi.ttl",
    "copi-base.owl", "copi-base.ttl",
    "copi-full.owl", "copi-full.ttl",
    "copi-simple.owl", "copi-simple.ttl",
]


class ZenodoError(RuntimeError):
    pass


@dataclass
class ReleaseResult:
    doi: str | None = None
    concept_doi: str | None = None
    deposition_id: int | None = None
    dry_run: bool = False


class ZenodoClient:
    def __init__(self, token: str, session=None, dry_run: bool = False, api: str = ZENODO_API):
        if session is None:
            import requests
            session = requests.Session()
        self.token = token
        self.session = session
        self.dry_run = dry_run
        self.api = api

    # ── HTTP ────────────────────────────────────────────────────────────────
    def _params(self):
        return {"access_token": self.token}

    def _check(self, response, expected: tuple[int, ...], what: str):
        if response.status_code not in expected:
            body = getattr(response, "text", "")
            try:
                body = json.dumps(response.json())
            except Exception:
                pass
            raise ZenodoError(f"{what} failed (HTTP {response.status_code}): {body[:400]}")
        try:
            return response.json()
        except Exception:
            return {}

    # ── steps ───────────────────────────────────────────────────────────────
    def create_deposition(self, metadata: dict) -> dict:
        payload = {"metadata": {**metadata, "prereserve_doi": True}}
        r = self.session.post(f"{self.api}/deposit/depositions", params=self._params(), json=payload)
        return self._check(r, (200, 201), "creating the deposition")

    def new_version(self, deposition_id: int, metadata: dict) -> dict:
        r = self.session.post(
            f"{self.api}/deposit/depositions/{deposition_id}/actions/newversion", params=self._params())
        created = self._check(r, (200, 201), "creating a new version")
        draft_url = created.get("links", {}).get("latest_draft")
        if not draft_url:
            raise ZenodoError("new version created but no latest_draft link was returned")
        draft = self._check(self.session.get(draft_url, params=self._params()), (200,), "reading the draft")
        self._check(
            self.session.put(draft_url, params=self._params(), json={"metadata": metadata}),
            (200,), "updating the draft metadata")
        return draft

    def upload(self, deposition: dict, files: list[Path]) -> None:
        bucket = deposition.get("links", {}).get("bucket")
        if not bucket:
            raise ZenodoError("deposition has no bucket link (old API deposition?)")
        for path in files:
            with open(path, "rb") as fh:
                r = self.session.put(f"{bucket}/{path.name}", params=self._params(), data=fh)
            self._check(r, (200, 201), f"uploading {path.name}")

    def publish(self, deposition: dict) -> dict:
        url = deposition.get("links", {}).get("publish")
        if not url:
            url = f"{self.api}/deposit/depositions/{deposition['id']}/actions/publish"
        return self._check(self.session.post(url, params=self._params()), (200, 202), "publishing")

    # ── orchestration ───────────────────────────────────────────────────────
    def publish_release(self, metadata: dict, files: list[Path],
                        previous_deposition_id: int | None = None) -> ReleaseResult:
        if self.dry_run:
            print(f"[dry run] would {'create a new version of ' + str(previous_deposition_id) if previous_deposition_id else 'create a deposition'}"
                  f" and upload {len(files)} file(s): {', '.join(f.name for f in files)}")
            return ReleaseResult(dry_run=True)

        deposition = (self.new_version(previous_deposition_id, metadata) if previous_deposition_id
                      else self.create_deposition(metadata))
        self.upload(deposition, files)
        published = self.publish(deposition)

        concept_recid = published.get("conceptrecid") or deposition.get("conceptrecid")
        concept_doi = published.get("conceptdoi") or (f"10.5281/zenodo.{concept_recid}" if concept_recid else None)
        return ReleaseResult(doi=published.get("doi"), concept_doi=concept_doi,
                             deposition_id=published.get("id") or deposition.get("id"))


def write_doi_annotation(edit_owl: Path, concept_doi: str) -> bool:
    """Add `Annotation(bibo:doi "<concept doi>")` to the ODK edit file. Idempotent."""
    text = edit_owl.read_text(encoding="utf-8")
    if f'Annotation(bibo:doi "{concept_doi}")' in text:
        return False
    text = re.sub(r'(Annotation\(bibo:doi "[^"]*"\)\n)', "", text)
    anchor = re.search(r'Annotation\(bibo:status "[^"]*"\)\n', text)
    if not anchor:
        raise ZenodoError("could not find the bibo:status annotation to anchor the DOI next to")
    at = anchor.end()
    edit_owl.write_text(text[:at] + f'Annotation(bibo:doi "{concept_doi}")\n' + text[at:], encoding="utf-8")
    return True


def load_state() -> dict:
    return json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def release_metadata(version: str) -> dict:
    """Zenodo metadata from the copi repo's .zenodo.json, with this version."""
    data = json.loads((COPI_REPO_ROOT / ".zenodo.json").read_text(encoding="utf-8"))
    data["version"] = version
    data.setdefault("publication_date", version)
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="release version, e.g. 2026-09-24")
    ap.add_argument("--publish", action="store_true", help="actually create and publish (default: dry run)")
    args = ap.parse_args()

    token = os.environ.get("ZENODO_TOKEN")
    if not token and args.publish:
        sys.exit("ZENODO_TOKEN is not set (scopes: deposit:write, deposit:actions)")

    files = [COPI_REPO_ROOT / name for name in RELEASE_FILES]
    missing = [f.name for f in files if not f.exists()]
    if missing:
        sys.exit(f"missing release artefacts in {COPI_REPO_ROOT}: {', '.join(missing)}")

    state = load_state()
    client = ZenodoClient(token=token or "", dry_run=not args.publish)
    result = client.publish_release(release_metadata(args.version), files,
                                    previous_deposition_id=state.get("deposition_id"))
    if result.dry_run:
        print("dry run — pass --publish to mint the DOI")
        return

    print(f"published: DOI {result.doi} | concept DOI {result.concept_doi}")
    save_state({"deposition_id": result.deposition_id, "concept_doi": result.concept_doi,
                "last_version": args.version})

    if result.concept_doi and write_doi_annotation(EDIT_OWL_PATH, result.concept_doi):
        print(f"added bibo:doi {result.concept_doi} to {EDIT_OWL_PATH.relative_to(COPI_REPO_ROOT)}"
              " — commit it so the next ODK build carries the DOI")


if __name__ == "__main__":
    main()
