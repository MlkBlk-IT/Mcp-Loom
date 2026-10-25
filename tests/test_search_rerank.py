"""Search rerank: the chunk holding the VALUE must reach the top results.

Regression for the 2026-10-24 selftest: 'dashboard port' ranked the chunk with
`PORT = 8765` 11th of 13 by bm25 (short doc chunks that merely talk about the
dashboard and the port won). Real SQLite on tmp_path, no mocks.
"""

from __future__ import annotations

from loom import store


def _setup(tmp_path, monkeypatch, name):
    db = tmp_path / name
    monkeypatch.setattr(store, "DB_PATH", db)
    monkeypatch.setenv("LOOM_DB", str(db))


def _chunks(*texts: str) -> list[dict]:
    return [{"text": t, "tokens": len(t.split())} for t in texts]


DOCS = [f"dashboard port notes {i}: the dashboard port is explained in the docs" for i in range(14)]
TARGET = (
    "import socketserver\n"
    "HOST = '127.0.0.1'\n"
    "PORT = 8765\n"
    "# dashboard server, read-only metrics\n"
    "db_path = None\n"
    "audit_path = None\n"
    "demo = False\n"
)


def test_value_chunk_in_top5_for_port_query(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, "rr.db")
    store.save_all("s-rr", "mix", _chunks(*DOCS, TARGET), "anchor", [("k", "v", 1)])
    res = store.search("dashboard port", session_id="s-rr", limit=5, topup=True)
    assert len(res) == 5
    assert any("8765" in r["content"] for r in res)


def test_version_query_prefers_chunk_with_a_version(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, "rv.db")
    docs = [f"sqlite version policy {i}: sqlite version is checked at preflight" for i in range(12)]
    target = "Env: Python 3.12.10, sqlite 3.49.1, fastmcp 4.1.3\nsqlite version noted at preflight\n"
    store.save_all("s-rv", "mix", _chunks(*docs, target), "anchor", [("k", "v", 1)])
    res = store.search("sqlite version preflight", session_id="s-rv", limit=5, topup=True)
    assert any("3.49.1" in r["content"] for r in res)


def test_single_word_query_unchanged(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, "rs.db")
    store.save_all("s-rs", "log", _chunks("alpha one", "alpha two", "beta"), "anchor", [("k", "v", 1)])
    res = store.search("alpha", session_id="s-rs", limit=10)
    assert len(res) == 2


def test_limit_respected_after_rerank(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, "rl.db")
    store.save_all("s-rl", "mix", _chunks(*DOCS, TARGET), "anchor", [("k", "v", 1)])
    for lim in (1, 3, 5):
        assert len(store.search("dashboard port", session_id="s-rl", limit=lim, topup=True)) <= lim
