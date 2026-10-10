import ipaddress
import os

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse

from enrichment.auth import _COOKIE_NAME, verify_session_cookie
from enrichment.guest_log import log_guest_access

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _is_infra_probe(request: Request, ip: str) -> bool:
    """
    kubelet liveness/readiness probes and the Istio/Envoy sidecar's own health
    checks are unauthenticated GETs against "/" that otherwise look exactly
    like guest traffic to this middleware -- on the deployed pod they were
    ~99.97% of guest_access.log (420k+ of 420k+ lines), from source IP
    127.0.0.6 (Envoy's documented convention for its inbound-listener health
    check) with no real guest signal left to find in the noise.

    User-Agent is the primary check (kubelet's probes self-identify as
    "kube-probe/<version>" regardless of which internal IP is used, so this
    survives a change in cluster networking); the loopback-range check is a
    second layer for the Envoy-side probe specifically, since 127.0.0.0/8 can
    never be a genuine external visitor.
    """
    user_agent = request.headers.get("user-agent", "")
    if user_agent.startswith("kube-probe/"):
        return True
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False


async def guest_auth_middleware(request: Request, call_next):
    user: str | None = None
    cookie_value = request.cookies.get(_COOKIE_NAME)
    if cookie_value:
        user = verify_session_cookie(cookie_value)
    if user is None:
        dev_user = os.getenv("DEV_USER")
        if dev_user:
            user = dev_user

    request.state.user = user

    if user is None and request.method not in _SAFE_METHODS:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JSONResponse({"detail": "Autenticação necessária"}, status_code=401)
        return RedirectResponse(url="/auth/login", status_code=302)

    if user is None:
        x_forwarded = request.headers.get("X-Forwarded-For", "")
        ip = (
            x_forwarded.split(",")[0].strip()
            if x_forwarded
            else (request.client.host if request.client else "unknown")
        )
        if not _is_infra_probe(request, ip):
            log_guest_access(ip, request.method, str(request.url.path))

    return await call_next(request)
