"""Integration tests for store.py + session.py — real SQLite on tmp_path.

No mocks of sqlite3, Fernet, os or hashlib: real DB, real crypto.
"""

from __future__ import annotations

import pytest

from loom import session, store


def _chunks(*texts: str) -> list[dict]:
    return [{"text": t, "tokens": len(t.split())} for t in texts]


# ---------------------------------------------------------------------------
# save_all — atomic transaction
# ---------------------------------------------------------------------------

def test_save_all_atomic_rollback_on_failure(tmp_path, monkeypatch):
    """If save_all fails mid-transaction, nothing is written."""
    db = tmp_path / "atom.db"
    monkeypatch.setattr(store, "DB_PATH", db)
    monkeypatch.setenv("LOOM_DB", str(db))

    chunks = _chunks("alpha content", "beta content", "gamma content")
    with pytest.raises((ValueError, TypeError)):
        store.save_all(
            "s-atom", "log", chunks, "anchor-body",
            [("kind", "val", 1)],
            source_meta={"tokens_before": "NOT_AN_INT"},
        )
    stats = store.stats("s-atom")
    assert stats["chunks"] == 0


def test_save_all_success_returns_metadata(tmp_path, monkeypatch):
    """save_all on success returns chunk_ids, anchor_id, source_id, sha256."""
    db = tmp_path / "ok.db"
    monkeypatch.setattr(store, "DB_PATH", db)
    monkeypatch.setenv("LOOM_DB", str(db))

    chunks = _chunks("hello world", "foo bar baz")
    result = store.save_all("s-ok", "log", chunks, "anchor", [("k", "v", 1)])
    assert len(result["chunk_ids"]) == 2
    assert result["anchor_id"] >= 1
    assert result["source_id"] >= 1
    assert len(result["sha256"]) == 64
    assert result["n_chunks"] == 2
    assert result["bytes"] > 0


# ---------------------------------------------------------------------------
# create_session — UPSERT idempotent
# ---------------------------------------------------------------------------

def test_create_session_upsert_preserves_created_at(tmp_path, monkeypatch):
    """Calling create_session twice keeps created_at, updates label."""
    db = tmp_path / "upsert.db"
    monkeypatch.setattr(store, "DB_PATH", db)
    monkeypatch.setenv("LOOM_DB", str(db))

    session.create_session("s-upsert", label="first")
    info1 = session.get_session("s-upsert")
    assert info1 is not None
    created1 = info1.created_at

    session.create_session("s-upsert", label="second")
    info2 = session.get_session("s-upsert")
    assert info2 is not None
    assert info2.created_at == created1
    assert info2.label == "second"


# ---------------------------------------------------------------------------
# TTL — expired purged, fresh kept
# ---------------------------------------------------------------------------

def test_ttl_expired_session_purged(tmp_path, monkeypatch):
    """A session with ttl_days=0 is immediately expired and purged."""
    db = tmp_path / "ttl.db"
    monkeypatch.setattr(store, "DB_PATH", db)
    monkeypatch.setenv("LOOM_DB", str(db))

    session.create_session("s-expired", label="old", ttl_days=0)
    store.save_chunks("s-expired", "log", _chunks("stale data"))

    result = session.purge_expired_sessions()
    purged_ids = [r["session_id"] for r in result["sessions"]]
    assert "s-expired" in purged_ids
    assert session.get_session("s-expired") is None


def test_ttl_fresh_session_kept(tmp_path, monkeypatch):
    """A session with ttl_days=30 is NOT purged."""
    db = tmp_path / "ttl2.db"
    monkeypatch.setattr(store, "DB_PATH", db)
    monkeypatch.setenv("LOOM_DB", str(db))

    session.create_session("s-fresh", label="new", ttl_days=30)
    store.save_chunks("s-fresh", "log", _chunks("fresh data"))

    result = session.purge_expired_sessions()
    purged_ids = [r["session_id"] for r in result["sessions"]]
    assert "s-fresh" not in purged_ids
    assert session.get_session("s-fresh") is not None


# ---------------------------------------------------------------------------
# purge_session — empties chunks + FTS + integrity-check
# ---------------------------------------------------------------------------

def test_purge_session_clears_chunks_and_fts(tmp_path, monkeypatch):
    """purge_session removes chunks and FTS rows; integrity-check passes after."""
    db = tmp_path / "purge.db"
    monkeypatch.setattr(store, "DB_PATH", db)
    monkeypatch.setenv("LOOM_DB", str(db))

    session.create_session("s-purge", label="test")
    store.save_chunks("s-purge", "log", _chunks("unique searchable text"))
    assert store.stats("s-purge")["chunks"] == 1

    # FTS populated: search finds the text
    assert len(store.search("searchable", session_id="s-purge")) == 1

    result = session.purge_session("s-purge")
    assert result["chunks_deleted"] == 1
    assert result["session_row_deleted"] is True
    assert store.stats("s-purge")["chunks"] == 0

    # FTS cleared: search returns nothing
    assert store.search("searchable", session_id="s-purge") == []

    # integrity-check passes (FTS consistent with empty content table)
    conn = store._connect()
    conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('integrity-check')")
    conn.close()


# ---------------------------------------------------------------------------
# search — FTS escaping + content + snippet
# ---------------------------------------------------------------------------

def test_search_escapes_fts_special_chars(tmp_path, monkeypatch):
    """FTS special chars don't cause OperationalError."""
    db = tmp_path / "esc.db"
    monkeypatch.setattr(store, "DB_PATH", db)
    monkeypatch.setenv("LOOM_DB", str(db))

    store.save_chunks("s-esc", "log", _chunks("normal text here"))
    for q in ['" * : - ( ) AND OR', '*', '"', 'AND OR NOT', 'a* b?']:
        results = store.search(q, session_id="s-esc")
        assert isinstance(results, list)


def test_search_returns_content_and_snippet(tmp_path, monkeypatch):
    """search() returns both 'content' (full text) and 'snippet'."""
    db = tmp_path / "snip.db"
    monkeypatch.setattr(store, "DB_PATH", db)
    monkeypatch.setenv("LOOM_DB", str(db))

    text = "the quick brown fox jumps over the lazy dog"
    store.save_chunks("s-snip", "log", _chunks(text))
    results = store.search("quick", session_id="s-snip")
    assert len(results) >= 1
    r = results[0]
    assert "content" in r
    assert "snippet" in r
    assert r["content"] == text


# ---------------------------------------------------------------------------
# Fernet encryption — FTS not populated, search_disabled True
# ---------------------------------------------------------------------------

def test_fernet_disables_fts_and_search(tmp_path, monkeypatch):
    """With LOOM_DB_PASSWORD set, FTS is not fed and search_disabled() is True."""
    from loom import crypto

    db = tmp_path / "enc.db"
    monkeypatch.setattr(store, "DB_PATH", db)
    monkeypatch.setenv("LOOM_DB", str(db))
    monkeypatch.setenv("LOOM_DB_PASSWORD", "test-pw-123")
    crypto.reset_caches()

    assert store.search_disabled() is True

    store.save_chunks("s-enc", "log", _chunks("encrypted searchable content"))

    # FTS not populated: search for a plaintext word returns no results
    # (COUNT(*) on FTS5 external-content tables returns the content-table
    #  row count, not the FTS index count — so we verify via search instead.)
    assert store.search("searchable", session_id="s-enc") == []

    # Chunk can still be loaded by id (decrypted)
    ids = store.save_chunks("s-enc2", "log", _chunks("roundtrip text"))
    chunk = store.load_chunk(ids[0])
    assert chunk is not None
    assert chunk["content"] == "roundtrip text"

    # Control: without encryption, same text IS searchable
    db_plain = tmp_path / "plain.db"
    monkeypatch.setattr(store, "DB_PATH", db_plain)
    monkeypatch.setenv("LOOM_DB", str(db_plain))
    monkeypatch.delenv("LOOM_DB_PASSWORD", raising=False)
    crypto.reset_caches()
    store.save_chunks("s-plain", "log", _chunks("encrypted searchable content"))
    assert len(store.search("searchable", session_id="s-plain")) == 1
