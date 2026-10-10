import os
import pytest
from unittest.mock import MagicMock


def _make_request(cookies: dict) -> MagicMock:
    req = MagicMock()
    req.cookies = cookies
    return req


def _reload():
    import importlib
    import enrichment.auth as m
    importlib.reload(m)
    return m


def test_make_and_verify_roundtrip(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.delenv("DEV_USER", raising=False)
    m = _reload()
    cookie = m.make_session_cookie("Alice")
    assert m.verify_session_cookie(cookie) == "Alice"


def test_verify_tampered_cookie_returns_none(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.delenv("DEV_USER", raising=False)
    m = _reload()
    assert m.verify_session_cookie("not-a-valid-cookie") is None


def test_get_current_user_from_cookie(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.delenv("DEV_USER", raising=False)
    m = _reload()
    cookie_value = m.make_session_cookie("Bob")
    req = _make_request({"session": cookie_value})
    assert m.get_current_user(req) == "Bob"


def test_get_current_user_no_cookie_raises(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.delenv("DEV_USER", raising=False)
    m = _reload()
    req = _make_request({})
    with pytest.raises(m.NotAuthenticatedException):
        m.get_current_user(req)


def test_get_current_user_dev_user_fallback(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv("DEV_USER", "dev-alice")
    m = _reload()
    req = _make_request({})
    assert m.get_current_user(req) == "dev-alice"


def test_missing_session_secret_no_dev_user_raises(monkeypatch):
    """No SESSION_SECRET and no DEV_USER must raise RuntimeError (not silently use dev secret)."""
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    monkeypatch.delenv("DEV_USER", raising=False)
    m = _reload()
    with pytest.raises(RuntimeError, match="SESSION_SECRET must be set"):
        m.make_session_cookie("Bob")


def test_missing_session_secret_with_dev_user_uses_fallback(monkeypatch):
    """No SESSION_SECRET but DEV_USER set → allowed to use insecure fallback."""
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    monkeypatch.setenv("DEV_USER", "dev-user")
    m = _reload()
    # Should not raise; round-trip should succeed
    cookie = m.make_session_cookie("Carol")
    assert m.verify_session_cookie(cookie) == "Carol"


def test_get_optional_user_returns_name_from_cookie(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.delenv("DEV_USER", raising=False)
    m = _reload()
    cookie = m.make_session_cookie("Alice")
    req = _make_request({"session": cookie})
    assert m.get_optional_user(req) == "Alice"


def test_get_optional_user_returns_none_for_no_cookie(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.delenv("DEV_USER", raising=False)
    m = _reload()
    req = _make_request({})
    assert m.get_optional_user(req) is None


def test_get_optional_user_returns_dev_user_fallback(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv("DEV_USER", "dev-alice")
    m = _reload()
    req = _make_request({})
    assert m.get_optional_user(req) == "dev-alice"


def test_get_optional_user_tampered_cookie_returns_none(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.delenv("DEV_USER", raising=False)
    m = _reload()
    req = _make_request({"session": "tampered-garbage"})
    assert m.get_optional_user(req) is None
