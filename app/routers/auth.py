import logging
import os
import secrets

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from keycloak import KeycloakOpenID

from enrichment.auth import make_session_cookie, MAX_AGE

logger = logging.getLogger(__name__)

router = APIRouter()

_keycloak_instance: KeycloakOpenID | None = None


def _get_keycloak() -> KeycloakOpenID:
    global _keycloak_instance
    if _keycloak_instance is None:
        _keycloak_instance = KeycloakOpenID(
            server_url=os.getenv("KEYCLOAK_URL", ""),
            client_id=os.getenv("KEYCLOAK_CLIENT_ID", ""),
            realm_name=os.getenv("KEYCLOAK_REALM", ""),
            client_secret_key=os.getenv("KEYCLOAK_CLIENT_SECRET", ""),
        )
    return _keycloak_instance


def _redirect_uri() -> str:
    return os.getenv("KEYCLOAK_REDIRECT_URI", "")


def _safe_next_path(next_path: str | None) -> str:
    """
    Only ever redirect back to a same-origin relative path. Reject anything
    that could send the user off-site (absolute URLs, protocol-relative
    "//host/..." paths) -- this value round-trips through a cookie set by
    the caller, so treat it as untrusted input. Falls back to the homepage.
    """
    if not next_path or not next_path.startswith("/") or next_path.startswith("//"):
        return "/"
    return next_path


@router.get("/auth/login")
def login(request: Request, next: str | None = None):
    state = secrets.token_urlsafe(32)
    try:
        auth_url = _get_keycloak().auth_url(
            redirect_uri=_redirect_uri(),
            scope="openid profile",
            state=state,
        )
    except Exception as exc:
        logger.error("Failed to build Keycloak auth URL: %s", exc)
        return RedirectResponse(url="/?error=auth_failed", status_code=302)
    secure = os.getenv("SESSION_SECURE", "true").lower() == "true"
    response = RedirectResponse(url=auth_url, status_code=302)
    response.set_cookie(
        key="oauth_state",
        value=state,
        max_age=300,
        httponly=True,
        secure=secure,
        samesite="lax",
    )
    # Prefer an explicit ?next=, then the page that linked here (Referer),
    # so login() called from a bare link (no ?next=) still returns the user
    # to the page they were on rather than always landing on /enrich/.
    referer_path = ""
    referer = request.headers.get("referer", "")
    if referer:
        from urllib.parse import urlparse
        parsed = urlparse(referer)
        if parsed.netloc == request.url.netloc:
            referer_path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    response.set_cookie(
        key="post_login_redirect",
        value=_safe_next_path(next or referer_path),
        max_age=300,
        httponly=True,
        secure=secure,
        samesite="lax",
    )
    return response


@router.get("/auth/callback")
def callback(
    request: Request,
    code: str | None = None,
    error: str | None = None,
    state: str | None = None,
):
    stored_state = request.cookies.get("oauth_state")
    if not stored_state or stored_state != state:
        logger.warning("CSRF state mismatch in /auth/callback (stored=%r, received=%r)", stored_state, state)
        return RedirectResponse(url="/?error=auth_failed", status_code=302)

    if error or not code:
        logger.warning("Auth callback received error: %s", error)
        response = RedirectResponse(url="/?error=auth_failed", status_code=302)
        response.delete_cookie("oauth_state")
        return response

    try:
        token = _get_keycloak().token(
            grant_type="authorization_code",
            code=code,
            redirect_uri=_redirect_uri(),
        )
        userinfo = _get_keycloak().userinfo(token["access_token"])
        name = userinfo.get("name") or userinfo.get("preferred_username", "unknown")
    except Exception as exc:
        logger.error("Token exchange failed: %s", exc)
        response = RedirectResponse(url="/?error=auth_failed", status_code=302)
        response.delete_cookie("oauth_state")
        return response

    secure = os.getenv("SESSION_SECURE", "true").lower() == "true"
    redirect_to = _safe_next_path(request.cookies.get("post_login_redirect"))
    response = RedirectResponse(url=redirect_to, status_code=302)
    response.set_cookie(
        key="session",
        value=make_session_cookie(name),
        max_age=MAX_AGE,
        httponly=True,
        secure=secure,
        samesite="lax",
    )
    response.delete_cookie("oauth_state")
    response.delete_cookie("post_login_redirect")
    return response
