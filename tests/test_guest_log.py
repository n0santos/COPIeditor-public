import importlib
import pytest


def test_log_guest_access_writes_to_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import enrichment.guest_log as gl
    gl._logger = None  # Reset _logger before reload
    importlib.reload(gl)

    gl.log_guest_access("203.0.113.5", "GET", "/search")

    log_file = tmp_path / "guest_access.log"
    assert log_file.exists(), "log file should be created"
    content = log_file.read_text()
    assert "203.0.113.5" in content
    assert "GET" in content
    assert "/search" in content


def test_log_line_contains_timestamp(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import enrichment.guest_log as gl
    gl._logger = None  # Reset _logger before reload
    importlib.reload(gl)

    gl.log_guest_access("1.2.3.4", "GET", "/terms/1")

    content = (tmp_path / "guest_access.log").read_text()
    # Timestamp starts with year
    assert "2026" in content or "2027" in content


def test_multiple_calls_append_lines(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import enrichment.guest_log as gl
    gl._logger = None  # Reset _logger before reload
    importlib.reload(gl)

    gl.log_guest_access("1.1.1.1", "GET", "/search")
    gl.log_guest_access("2.2.2.2", "GET", "/cluster")

    lines = (tmp_path / "guest_access.log").read_text().strip().splitlines()
    assert len(lines) == 2
    assert "1.1.1.1" in lines[0]
    assert "2.2.2.2" in lines[1]
