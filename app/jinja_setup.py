"""
Shared Jinja2 environment factory.

Usage:
    from app.jinja_setup import make_env
    from jinja2 import FileSystemLoader
    env = make_env(FileSystemLoader("app/templates"))
    templates = Jinja2Templates(env=env)

All environments built here share:
- cache_size=0  (workaround for Jinja2/Python 3.14 unhashable-dict LRUCache bug)
- autoescape=True
- from_json filter (json.loads)
"""
from __future__ import annotations

import json
import os

from jinja2 import BaseLoader, Environment
from fastapi.templating import Jinja2Templates

_BUILD_SHA  = os.getenv("BUILD_SHA", "dev")
_BUILD_DATE = os.getenv("BUILD_DATE", "unknown")

COPYRIGHTED_SOURCES = frozenset({
    "iso15926", "iso14224", "cfihos", "isa5_1",
    "posc_caesar", "slb_glossary", "onepetro_glossary", "dexpi", "ppdm",
})


def make_env(loader: BaseLoader) -> Environment:
    env = Environment(loader=loader, autoescape=True, cache_size=0)
    env.filters["from_json"] = json.loads
    env.globals["build_sha"]  = _BUILD_SHA
    env.globals["build_date"] = _BUILD_DATE
    env.globals["copyrighted_sources"] = COPYRIGHTED_SOURCES
    return env


def make_templates(loader: BaseLoader) -> Jinja2Templates:
    return Jinja2Templates(env=make_env(loader))
