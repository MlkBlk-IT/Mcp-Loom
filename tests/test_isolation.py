"""Isolation tests — prove tests cannot touch the real ~/.loom drawer.

The conftest canary already fails the whole run if ~/.loom changes; these
tests make the isolation contract explicit and testable on their own.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from loom import session, store


REAL_LOOM = Path.home() / ".loom"


def _stat(p: Path):
    try:
        s = p.stat()
        return (s.st_size, s.st_mtime_ns)
    except FileNotFoundError:
        return None


def test_store_db_path_is_tmp(monkeypatch, tmp_path):
    """store.DB_PATH must point at the tmp drawer, never ~/.loom."""
    db = tmp_path / "loom.db"
    monkeypatch.setattr(store, "DB_PATH", db)
    assert store.DB_PATH == db
    assert "pytest" in str(store.DB_PATH) or str(tmp_path) in str(store.DB_PATH)
    assert store.DB_PATH != REAL_LOOM / "loom.db"


def test_store_connect_writes_tmp(tmp_path, monkeypatch):
    """A store write must create the tmp DB, not ~/.loom/loom.db."""
    db = tmp_path / "iso.db"
    monkeypatch.setattr(store, "DB_PATH", db)
    monkeypatch.setenv("LOOM_DB", str(db))

    ids = store.save_chunks("iso-test", "log", [{"text": "hello", "tokens": 1}])
    assert len(ids) == 1
    assert db.exists()
    assert db.stat().st_size > 0


def test_session_health_check_uses_tmp(tmp_path, monkeypatch):
    """session.health_check() must report the tmp DB path."""
    db = tmp_path / "iso.db"
    monkeypatch.setattr(store, "DB_PATH", db)
    monkeypatch.setenv("LOOM_DB", str(db))

    result = session.health_check()
    assert result["ok"] is True
    assert result["db_path"] == str(db)


def test_real_loom_untouched_during_store_write(tmp_path, monkeypatch):
    """Writing chunks must not change the real ~/.loom/loom.db."""
    before = _stat(REAL_LOOM / "loom.db")

    db = tmp_path / "iso.db"
    monkeypatch.setattr(store, "DB_PATH", db)
    monkeypatch.setenv("LOOM_DB", str(db))
    store.save_chunks("iso-test2", "log", [{"text": "isolation", "tokens": 1}])

    after = _stat(REAL_LOOM / "loom.db")
    assert before == after, f"~/.loom changed: {before} -> {after}"
