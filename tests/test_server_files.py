"""Real tests for ctx_store_file, ctx_verify, rate limit, and tool surface.

Every test uses a real DB on tmp_path (no mock sqlite/Fernet/os/hashlib).
"""
from __future__ import annotations

import sqlite3

import pytest

import loom.server as srv
import loom.ratelimit as rl_mod
from loom import store
from loom.ratelimit import RateLimiter, get_rate_limiter


# ---------------------------------------------------------------------------
# Autouse: ensure server._rate_limiter is disabled by default.
# conftest resets ratelimit._rate_limiter to None, but server._rate_limiter
# (set at import time) is NOT reset by conftest — so we do it here.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _reset_srv_rl(monkeypatch):
    monkeypatch.setenv("LOOM_RATE_LIMIT", "0")
    monkeypatch.setattr(srv, "_rate_limiter", RateLimiter(enabled=False))
    yield


# ---------------------------------------------------------------------------
# 1. CRLF roundtrip: file written in rb → store_file → chunks == original bytes
#    + ctx_verify lossless true
# ---------------------------------------------------------------------------
def test_crlf_roundtrip(tmp_path):
    raw = b"line1\r\nline2\r\nline3\r\n"
    f = tmp_path / "crlf.txt"
    f.write_bytes(raw)

    result = srv.ctx_store_file(path=str(f), session_id="s-crlf", label="crlf.txt")
    assert "error" not in result, result

    chunk_ids = result["chunk_ids"]
    rebuilt = "".join(store.load_chunk(cid)["content"] for cid in chunk_ids)
    assert rebuilt.encode("utf-8") == raw

    v = srv.ctx_verify(session_id="s-crlf")
    assert v["lossless"] is True
    assert all(s["ok"] for s in v["sources"])


# ---------------------------------------------------------------------------
# 2. Invalid utf-8: error returned, 0 chunk, 0 source
# ---------------------------------------------------------------------------
def test_invalid_utf8(tmp_path):
    raw = b"\xff\xfe\x00 invalid utf-8"
    f = tmp_path / "bad.txt"
    f.write_bytes(raw)

    result = srv.ctx_store_file(path=str(f), session_id="s-bad", label="bad.txt")
    assert "error" in result

    stats = srv.ctx_stats(session_id="s-bad")
    assert stats["chunks"] == 0
    assert stats["sources"] == 0


# ---------------------------------------------------------------------------
# 3. Corruption: modify a chunk via real sqlite → ctx_verify ok:false, lossless false
# ---------------------------------------------------------------------------
def test_corruption(tmp_path):
    content = "hello world\nthis is a test\nof corruption detection\n"
    result = srv.ctx_store(content=content, session_id="s-corrupt", label="test.txt")
    assert "error" not in result
    chunk_ids = result["chunk_ids"]
    assert len(chunk_ids) > 0

    # Modify chunk 0 directly in sqlite (real connection, no mock)
    conn = sqlite3.connect(str(store.DB_PATH))
    with conn:
        conn.execute(
            "UPDATE chunks SET content = ? WHERE id = ?",
            ("CORRUPTED", chunk_ids[0]),
        )
    conn.close()

    v = srv.ctx_verify(session_id="s-corrupt")
    assert v["lossless"] is False
    assert any(not s["ok"] for s in v["sources"])


# ---------------------------------------------------------------------------
# 4. LOOM_ALLOWED_DIRS: file outside list rejected; file inside accepted
# ---------------------------------------------------------------------------
def test_allowed_dirs(tmp_path, monkeypatch):
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    monkeypatch.setenv("LOOM_ALLOWED_DIRS", str(allowed_dir))

    # Outside → rejected
    outside = tmp_path / "outside.txt"
    outside.write_text("outside content")
    result_out = srv.ctx_store_file(
        path=str(outside), session_id="s-dirs-out", label="outside.txt"
    )
    assert "error" in result_out

    # Inside → accepted
    inside = allowed_dir / "inside.txt"
    inside.write_text("inside content")
    result_in = srv.ctx_store_file(
        path=str(inside), session_id="s-dirs-in", label="inside.txt"
    )
    assert "error" not in result_in


# ---------------------------------------------------------------------------
# 5. LOOM_MAX_FILE_MB=0.001: large file rejected
# ---------------------------------------------------------------------------
def test_max_file_mb(tmp_path, monkeypatch):
    monkeypatch.setenv("LOOM_MAX_FILE_MB", "0.001")
    big = tmp_path / "big.txt"
    big.write_bytes(b"x" * 2048)  # 2 KB > 0.001 MB (~1049 bytes)

    result = srv.ctx_store_file(path=str(big), session_id="s-big", label="big.txt")
    assert "error" in result
    assert "too large" in result["error"]


# ---------------------------------------------------------------------------
# 6. 120 ctx_get with LOOM_RATE_LIMIT=0 → 0 errors
# ---------------------------------------------------------------------------
def test_120_ctx_get_no_limit(monkeypatch):
    monkeypatch.setenv("LOOM_RATE_LIMIT", "0")
    monkeypatch.setattr(rl_mod, "_rate_limiter", None)
    new_rl = get_rate_limiter()
    assert new_rl.enabled is False
    monkeypatch.setattr(srv, "_rate_limiter", new_rl)

    result = srv.ctx_store(content="hello\nworld\n", session_id="s-many", label="many.txt")
    assert "error" not in result
    cid = result["chunk_ids"][0]

    errors = 0
    for _ in range(120):
        r = srv.ctx_get(chunk_id=cid)
        if "error" in r and "rate limit" in r.get("error", ""):
            errors += 1
    assert errors == 0


# ---------------------------------------------------------------------------
# 7. Rate limit config: LOOM_RATE_LIMIT=1 without LOOM_RPM → rpm=60; LOOM_BURST=5 → burst=5
# ---------------------------------------------------------------------------
def test_rl_config_rpm_default(monkeypatch):
    monkeypatch.setattr(rl_mod, "_rate_limiter", None)
    monkeypatch.setenv("LOOM_RATE_LIMIT", "1")
    monkeypatch.delenv("LOOM_RPM", raising=False)
    limiter = get_rate_limiter()
    assert limiter.enabled is True
    assert limiter.rate == 1.0  # 60 requests / 60 seconds


def test_rl_config_burst_explicit(monkeypatch):
    monkeypatch.setattr(rl_mod, "_rate_limiter", None)
    monkeypatch.setenv("LOOM_BURST", "5")
    limiter = get_rate_limiter()
    assert limiter.capacity == 5


# ---------------------------------------------------------------------------
# 8. Surface: 17 tools (14 original + 3 upgrade: ctx_transfer, ctx_rebuild_index, ctx_vector_stats)
# ---------------------------------------------------------------------------
def test_surface_17_tools():
    expected = {
        "ctx_store",
        "ctx_get",
        "ctx_check",
        "ctx_stats",
        "ctx_profile",
        "ctx_list_sessions",
        "ctx_purge_session",
        "ctx_purge_expired",
        "ctx_vacuum",
        "ctx_health",
        "ctx_store_file",
        "ctx_store_cmd",
        "ctx_search",
        "ctx_verify",
        "ctx_transfer",
        "ctx_rebuild_index",
        "ctx_vector_stats",
    }
    found = {
        name
        for name in dir(srv)
        if name.startswith("ctx_") and callable(getattr(srv, name, None))
    }
    assert found == expected
    assert len(expected) == 17
