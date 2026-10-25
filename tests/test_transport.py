"""LOOM_TRANSPORT selection in main(): stdio by default, loopback HTTP/SSE opt-in."""
import pytest

from loom import server


@pytest.fixture
def calls(monkeypatch):
    seen = []
    monkeypatch.setattr(server.mcp, "run", lambda *a, **k: seen.append((a, k)))
    for var in ("LOOM_TRANSPORT", "LOOM_HOST", "LOOM_PORT"):
        monkeypatch.delenv(var, raising=False)
    return seen


def test_default_is_stdio(calls):
    server.main()
    assert calls == [((), {})]


def test_http_defaults_to_loopback(calls, monkeypatch):
    monkeypatch.setenv("LOOM_TRANSPORT", "http")
    server.main()
    assert calls == [((), {"transport": "http", "host": "127.0.0.1", "port": 8770})]


def test_sse_custom_port(calls, monkeypatch):
    monkeypatch.setenv("LOOM_TRANSPORT", "SSE")
    monkeypatch.setenv("LOOM_PORT", "9001")
    server.main()
    assert calls == [((), {"transport": "sse", "host": "127.0.0.1", "port": 9001})]


def test_non_loopback_host_warns(calls, monkeypatch, caplog):
    monkeypatch.setenv("LOOM_TRANSPORT", "http")
    monkeypatch.setenv("LOOM_HOST", "0.0.0.0")
    with caplog.at_level("WARNING"):
        server.main()
    assert "no authentication" in caplog.text


def test_invalid_transport_exits(calls, monkeypatch):
    monkeypatch.setenv("LOOM_TRANSPORT", "carrier-pigeon")
    with pytest.raises(SystemExit):
        server.main()
    assert calls == []