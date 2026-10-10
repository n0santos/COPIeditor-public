import importlib
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI


def _reload_and_build():
    """Reload the auth module and return (module, mini_app).
    Reload must happen BEFORE patch.object so we patch the live module object.
    """
    import app.routers.auth as auth_mod
    importlib.reload(auth_mod)
    mini = FastAPI()
    mini.include_router(auth_mod.router)
    return auth_mod, mini


def test_login_redirects_to_keycloak(monkeypatch):
    monkeypatch.setenv("KEYCLOAK_URL", "https://kc.example.com")
    monkeypatch.setenv("KEYCLOAK_REALM", "myrealm")
    monkeypatch.setenv("KEYCLOAK_CLIENT_ID", "copieditor")
    monkeypatch.setenv("KEYCLOAK_CLIENT_SECRET", "secret")
    monkeypatch.setenv("KEYCLOAK_REDIRECT_URI", "https://app.example.com/auth/callback")
    monkeypatch.setenv("SESSION_SECURE", "false")

    fake_url = "https://kc.example.com/realms/myrealm/protocol/openid-connect/auth?client_id=copieditor"
    auth_mod, mini = _reload_and_build()

    with patch.object(auth_mod, "_get_keycloak") as mock_get_kc:
        mock_kc = MagicMock()
        mock_kc.auth_url.return_value = fake_url
        mock_get_kc.return_value = mock_kc

        client = TestClient(mini, follow_redirects=False)
        resp = client.get("/auth/login")

    assert resp.status_code == 302
    assert resp.headers["location"] == fake_url
    # State cookie must be set
    assert "oauth_state=" in resp.headers.get("set-cookie", "")
    # auth_url must have been called with a state parameter
    call_kwargs = mock_kc.auth_url.call_args
    assert call_kwargs is not None
    assert "state" in call_kwargs.kwargs or (len(call_kwargs.args) >= 3)


def test_callback_sets_cookie_and_redirects(monkeypatch):
    monkeypatch.setenv("KEYCLOAK_URL", "https://kc.example.com")
    monkeypatch.setenv("KEYCLOAK_REALM", "myrealm")
    monkeypatch.setenv("KEYCLOAK_CLIENT_ID", "copieditor")
    monkeypatch.setenv("KEYCLOAK_CLIENT_SECRET", "secret")
    monkeypatch.setenv("KEYCLOAK_REDIRECT_URI", "https://app.example.com/auth/callback")
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv("SESSION_SECURE", "false")

    auth_mod, mini = _reload_and_build()

    with patch.object(auth_mod, "_get_keycloak") as mock_get_kc:
        mock_kc = MagicMock()
        mock_kc.token.return_value = {"access_token": "tok123"}
        mock_kc.userinfo.return_value = {"name": "Alice", "preferred_username": "alice"}
        mock_get_kc.return_value = mock_kc

        client = TestClient(mini, follow_redirects=False)
        # Provide matching state in cookie and query param
        resp = client.get(
            "/auth/callback?code=abc123&state=validstate",
            cookies={"oauth_state": "validstate"},
        )

    assert resp.status_code == 302
    assert resp.headers["location"] == "/enrich/"
    assert "session=" in resp.headers.get("set-cookie", "")


def test_callback_missing_state_is_rejected(monkeypatch):
    """No oauth_state cookie → CSRF check fails → redirect to /?error=auth_failed."""
    monkeypatch.setenv("KEYCLOAK_URL", "https://kc.example.com")
    monkeypatch.setenv("KEYCLOAK_REALM", "myrealm")
    monkeypatch.setenv("KEYCLOAK_CLIENT_ID", "copieditor")
    monkeypatch.setenv("KEYCLOAK_CLIENT_SECRET", "secret")
    monkeypatch.setenv("KEYCLOAK_REDIRECT_URI", "https://app.example.com/auth/callback")

    auth_mod, mini = _reload_and_build()
    client = TestClient(mini, follow_redirects=False)
    resp = client.get("/auth/callback?code=abc123&state=somestate")

    assert resp.status_code == 302
    assert "error=auth_failed" in resp.headers["location"]


def test_callback_state_mismatch_is_rejected(monkeypatch):
    """oauth_state cookie doesn't match query param → CSRF check fails."""
    monkeypatch.setenv("KEYCLOAK_URL", "https://kc.example.com")
    monkeypatch.setenv("KEYCLOAK_REALM", "myrealm")
    monkeypatch.setenv("KEYCLOAK_CLIENT_ID", "copieditor")
    monkeypatch.setenv("KEYCLOAK_CLIENT_SECRET", "secret")
    monkeypatch.setenv("KEYCLOAK_REDIRECT_URI", "https://app.example.com/auth/callback")

    auth_mod, mini = _reload_and_build()
    client = TestClient(mini, follow_redirects=False)
    resp = client.get(
        "/auth/callback?code=abc123&state=differentstate",
        cookies={"oauth_state": "originalstate"},
    )

    assert resp.status_code == 302
    assert "error=auth_failed" in resp.headers["location"]


def test_callback_error_param_redirects_to_root(monkeypatch):
    monkeypatch.setenv("KEYCLOAK_URL", "https://kc.example.com")
    monkeypatch.setenv("KEYCLOAK_REALM", "myrealm")
    monkeypatch.setenv("KEYCLOAK_CLIENT_ID", "copieditor")
    monkeypatch.setenv("KEYCLOAK_CLIENT_SECRET", "secret")
    monkeypatch.setenv("KEYCLOAK_REDIRECT_URI", "https://app.example.com/auth/callback")

    auth_mod, mini = _reload_and_build()
    client = TestClient(mini, follow_redirects=False)
    # Provide matching state so CSRF check passes, then error param triggers auth_failed
    resp = client.get(
        "/auth/callback?error=access_denied&state=mystate",
        cookies={"oauth_state": "mystate"},
    )

    assert resp.status_code == 302
    assert "error=auth_failed" in resp.headers["location"]


def test_login_keycloak_error_redirects_to_root(monkeypatch):
    """If _get_keycloak().auth_url() raises, login returns /?error=auth_failed."""
    monkeypatch.setenv("KEYCLOAK_URL", "https://kc.example.com")
    monkeypatch.setenv("KEYCLOAK_REALM", "myrealm")
    monkeypatch.setenv("KEYCLOAK_CLIENT_ID", "copieditor")
    monkeypatch.setenv("KEYCLOAK_CLIENT_SECRET", "secret")
    monkeypatch.setenv("KEYCLOAK_REDIRECT_URI", "https://app.example.com/auth/callback")
    monkeypatch.setenv("SESSION_SECURE", "false")

    auth_mod, mini = _reload_and_build()

    with patch.object(auth_mod, "_get_keycloak") as mock_get_kc:
        mock_kc = MagicMock()
        mock_kc.auth_url.side_effect = RuntimeError("Keycloak unreachable")
        mock_get_kc.return_value = mock_kc

        client = TestClient(mini, follow_redirects=False)
        resp = client.get("/auth/login")

    assert resp.status_code == 302
    assert "error=auth_failed" in resp.headers["location"]
