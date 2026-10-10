import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "enrichment"))

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.routers.terms import router as terms_router
from app.routers.ontology import router as ontology_router
from app.routers.auth import router as auth_router
from enrichment_routes import router as enrichment_router, _run_type_based_scope_classify
from enrichment.auth import NotAuthenticatedException
from starlette.middleware.base import BaseHTTPMiddleware
from enrichment.middleware import guest_auth_middleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if not os.getenv("ANTHROPIC_API_KEY"):
        logger.warning(
            "ANTHROPIC_API_KEY is not set. "
            "LLM enrichment will fail until the key is provided per-request or via environment."
        )
    if not os.getenv("KEYCLOAK_URL"):
        logger.warning("KEYCLOAK_URL is not set. Keycloak authentication will not work.")
    try:
        result = _run_type_based_scope_classify()
        if result.get("marked", 0):
            logger.info(
                "Type-based scope classify: marked %d new OOS clusters "
                "(of %d candidates).",
                result["marked"], result["total_candidates"],
            )
    except Exception as exc:
        logger.warning("Type-based scope classify failed at startup: %s", exc)
    yield


app = FastAPI(
    title="COPI Editor — Core Ontology for Petroleum Installations",
    lifespan=lifespan,
)

app.add_middleware(BaseHTTPMiddleware, dispatch=guest_auth_middleware)

@app.exception_handler(NotAuthenticatedException)
async def _not_authenticated(request, _exc):
    from urllib.parse import quote
    next_path = quote(str(request.url.path) + (f"?{request.url.query}" if request.url.query else ""))
    return RedirectResponse(url=f"/auth/login?next={next_path}", status_code=302)

_STATIC_DIR = _ROOT / "app" / "static"
_STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

app.include_router(auth_router)                                              # /auth/* — public
app.include_router(ontology_router)
app.include_router(terms_router)
app.include_router(enrichment_router, prefix="/enrich")


@app.get("/version")
def version():
    return JSONResponse({
        "sha":  os.getenv("BUILD_SHA", "dev"),
        "date": os.getenv("BUILD_DATE", "unknown"),
    })
