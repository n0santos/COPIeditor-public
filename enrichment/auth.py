import os
from fastapi import Request
from itsdangerous import URLSafeTimedSerializer, BadData

_COOKIE_NAME = "session"
MAX_AGE = 8 * 3600  # seconds (public export)


class NotAuthenticatedException(Exception):
    pass


def _serializer() -> URLSafeTimedSerializer:
    secret = os.getenv("SESSION_SECRET")
    if not secret:
        if not os.getenv("DEV_USER"):
            raise RuntimeError(
                "SESSION_SECRET must be set in production. "
                "Set DEV_USER to allow the insecure dev-secret fallback."
            )
        secret = "dev-secret-change-in-production"
    return URLSafeTimedSerializer(secret)


def make_session_cookie(name: str) -> str:
    return _serializer().dumps({"name": name})


def verify_session_cookie(cookie_value: str) -> str | None:
    try:
        data = _serializer().loads(cookie_value, max_age=MAX_AGE)
        return data.get("name")
    except BadData:
        return None


def get_current_user(request: Request) -> str:
    cookie_value = request.cookies.get(_COOKIE_NAME)
    if cookie_value:
        name = verify_session_cookie(cookie_value)
        if name:
            return name
    dev_user = os.getenv("DEV_USER")
    if dev_user:
        return dev_user
    raise NotAuthenticatedException()


def get_optional_user(request: Request) -> str | None:
    cookie_value = request.cookies.get(_COOKIE_NAME)
    if cookie_value:
        name = verify_session_cookie(cookie_value)
        if name:
            return name
    dev_user = os.getenv("DEV_USER")
    if dev_user:
        return dev_user
    return None
