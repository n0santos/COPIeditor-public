import importlib
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware


def _build_client(monkeypatch, tmp_path, *, follow_redirects=False):
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    import enrichment.guest_log as gl
    importlib.reload(gl)
    import enrichment.middleware as mw
    importlib.reload(mw)

    mini = FastAPI()
    mini.add_middleware(BaseHTTPMiddleware, dispatch=mw.guest_auth_middleware)

    @mini.get("/test")
    def test_get(request: Request):
        return JSONResponse({"user": request.state.user})

    @mini.post("/test")
    def test_post(request: Request):
        return JSONResponse({"user": request.state.user})

    return TestClient(mini, raise_server_exceptions=True, follow_redirects=follow_redirects)


def test_guest_get_passes_through(monkeypatch, tmp_path):
    monkeypatch.delenv("DEV_USER", raising=False)
    client = _build_client(monkeypatch, tmp_path)
    resp = client.get("/test")
    assert resp.status_code == 200
    assert resp.json()["user"] is None


def test_guest_post_redirects_to_login(monkeypatch, tmp_path):
    monkeypatch.delenv("DEV_USER", raising=False)
    client = _build_client(monkeypatch, tmp_path, follow_redirects=False)
    resp = client.post("/test")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/auth/login"


def test_guest_ajax_post_returns_401(monkeypatch, tmp_path):
    monkeypatch.delenv("DEV_USER", raising=False)
    client = _build_client(monkeypatch, tmp_path, follow_redirects=False)
    resp = client.post("/test", headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Autenticação necessária"


def test_authenticated_post_passes(monkeypatch, tmp_path):
    monkeypatch.delenv("DEV_USER", raising=False)
    from enrichment.auth import make_session_cookie
    client = _build_client(monkeypatch, tmp_path)
    cookie = make_session_cookie("Alice")
    resp = client.post("/test", cookies={"session": cookie})
    assert resp.status_code == 200
    assert resp.json()["user"] == "Alice"


def test_state_user_set_for_authenticated_get(monkeypatch, tmp_path):
    monkeypatch.delenv("DEV_USER", raising=False)
    from enrichment.auth import make_session_cookie
    client = _build_client(monkeypatch, tmp_path)
    cookie = make_session_cookie("Bob")
    resp = client.get("/test", cookies={"session": cookie})
    assert resp.status_code == 200
    assert resp.json()["user"] == "Bob"


def test_dev_user_fallback_passes_post(monkeypatch, tmp_path):
    monkeypatch.setenv("DEV_USER", "dev-carol")
    client = _build_client(monkeypatch, tmp_path)
    resp = client.post("/test")
    assert resp.status_code == 200
    assert resp.json()["user"] == "dev-carol"


def test_guest_access_written_to_log(monkeypatch, tmp_path):
    monkeypatch.delenv("DEV_USER", raising=False)
    client = _build_client(monkeypatch, tmp_path)
    client.get("/test")
    log_file = tmp_path / "guest_access.log"
    assert log_file.exists()
    content = log_file.read_text()
    assert "GET | /test" in content


def test_authenticated_access_not_logged(monkeypatch, tmp_path):
    monkeypatch.delenv("DEV_USER", raising=False)
    from enrichment.auth import make_session_cookie
    client = _build_client(monkeypatch, tmp_path)
    cookie = make_session_cookie("Alice")
    client.get("/test", cookies={"session": cookie})
    log_file = tmp_path / "guest_access.log"
    # File should not exist (no guest access logged)
    assert not log_file.exists()
