"""End-to-end test: store -> retrieve -> verify, over a real SQLite drawer."""

from __future__ import annotations

import pytest

from loom import compress, store, verify


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "loom.db")
    yield


def test_store_and_retrieve_byte_identical():
    content = "exit_code: 0\nsecret_line: abc123\npath C:\\Temp\\x.txt\n"
    anchor, chunks = compress.build_anchor(content)
    ids = store.save_chunks("s1", "log", chunks)
    assert len(ids) == 1

    got = store.load_chunk(ids[0])
    assert got["content"] == chunks[0]["text"]
    assert "abc123" in got["content"]


def test_missing_chunk_is_actionable():
    got = store.load_chunk(999999)
    assert got is None


def test_verify_reports_coverage():
    content = "error: boom\npath C:\\Temp\\y.txt\nport 8080\n"
    anchor, chunks = compress.build_anchor(content)
    ids = store.save_chunks("s2", "log", chunks)
    conn = store._connect()
    with conn:
        conn.execute(
            "INSERT INTO anchors (session_id, label, body, created_at) VALUES (?, ?, ?, ?)",
            ("s2", "log", anchor, 0.0),
        )
    conn.close()

    report = verify.check_session("s2")
    assert report["chunks"] == 1
    assert "coverage" in report


def test_stats_reflects_session():
    content = "hello world " * 100
    _, chunks = compress.build_anchor(content)
    store.save_chunks("s3", "bulk", chunks)
    stats = store.stats("s3")
    assert stats["chunks"] >= 1
    assert stats["stored_tokens"] > 0
