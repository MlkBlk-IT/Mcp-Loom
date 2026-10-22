"""Search fallback: strict AND first, OR (bm25-ranked) when AND finds nothing.

Regression for the 2026-10-21 bench: query 'billing outage ticket id' returned 0
results because the stored note never contains the word 'id'.
Real SQLite on tmp_path, no mocks.
"""

from __future__ import annotations

from loom import store


def _setup(tmp_path, monkeypatch, name):
    db = tmp_path / name
    monkeypatch.setattr(store, "DB_PATH", db)
    monkeypatch.setenv("LOOM_DB", str(db))


def _chunks(*texts: str) -> list[dict]:
    return [{"text": t, "tokens": len(t.split())} for t in texts]


NOTE = "POSTMORTEM-NOTE: the vendor escalation ticket for the billing outage is ZX-1177-ZZ."


def test_search_or_fallback_finds_chunk_when_a_word_is_absent(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, "fb.db")
    store.save_all(
        "s-fb", "log",
        _chunks("unrelated line about disk usage", NOTE, "another unrelated line about cpu"),
        "anchor", [("k", "v", 1)],
    )
    # strict AND would return nothing: 'id' is not in the note
    res = store.search("billing outage ticket id", session_id="s-fb")
    assert res, "OR fallback must find the chunk"
    assert "ZX-1177-ZZ" in res[0]["content"]


def test_search_strict_and_still_used_when_it_matches(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, "and.db")
    store.save_all(
        "s-and", "log",
        _chunks("billing outage root cause", "billing report monthly", "outage only here"),
        "anchor", [("k", "v", 1)],
    )
    res = store.search("billing outage", session_id="s-and")
    assert len(res) == 1
    assert "root cause" in res[0]["content"]


def test_search_no_match_at_all_returns_empty(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, "none.db")
    store.save_all("s-none", "log", _chunks("hello world"), "anchor", [("k", "v", 1)])
    assert store.search("zzzqqq yyyxxx", session_id="s-none") == []


def test_escape_fts_modes():
    assert store._escape_fts("a b") == '"a" "b"'
    assert store._escape_fts("a b", "OR") == '"a" OR "b"'
    assert store._escape_fts("   ") == ""
