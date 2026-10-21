"""Local drawer: where moved content lives.

SQLite + FTS5. No server, no network, no vendor SDK. Portable everywhere.
Supports optional encryption via SQLCipher or column-level Fernet.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from loom.crypto import connect_encrypted

DB_PATH = Path(os.environ.get("LOOM_DB", Path.home() / ".loom" / "loom.db"))


def _connect() -> sqlite3.Connection:
    """Get a database connection (encrypted if configured)."""
    conn = connect_encrypted()
    conn.row_factory = sqlite3.Row
    # Enable WAL mode for better concurrency
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    
    # Initialize schema
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            label      TEXT NOT NULL DEFAULT '',
            content    TEXT NOT NULL,
            tokens     INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            hits       INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS anchors (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            label      TEXT NOT NULL DEFAULT '',
            body       TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS invariants (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            kind       TEXT NOT NULL,
            value      TEXT NOT NULL,
            priority   INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_inv_session ON invariants (session_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunk_session ON chunks (session_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_anchor_session ON anchors (session_id)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id   TEXT PRIMARY KEY,
            label        TEXT NOT NULL DEFAULT '',
            created_at   REAL NOT NULL,
            updated_at   REAL NOT NULL,
            ttl_days     INTEGER NOT NULL DEFAULT 30
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions (updated_at)"
    )
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            label, content, content='chunks', content_rowid='id'
        )
        """
    )
    conn.commit()
    return conn


def save_chunks(session_id: str, label: str, chunks: list[dict[str, Any]]) -> list[int]:
    """Persist chunks and return their ids in order."""
    from loom.tokenizer import count_tokens
    from loom.crypto import get_encryption

    crypto = get_encryption()
    conn = _connect()
    ids: list[int] = []
    with conn:
        for chunk in chunks:
            content = chunk["text"]
            if crypto.is_encrypted and not crypto._use_sqlcipher:
                content = crypto.encrypt_content(content)
            cur = conn.execute(
                "INSERT INTO chunks (session_id, label, content, tokens, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, label, content, count_tokens(chunk["text"]), time.time()),
            )
            ids.append(int(cur.lastrowid))
            conn.execute(
                "INSERT INTO chunks_fts (rowid, label, content) VALUES (?, ?, ?)",
                (cur.lastrowid, label, chunk["text"]),  # FTS stores plaintext for search
            )
    conn.close()
    return ids


def save_anchor(session_id: str, label: str, body: str) -> int:
    """Persist the in-context anchor so `verify` can compare against it later."""
    from loom.crypto import get_encryption

    crypto = get_encryption()
    conn = _connect()
    with conn:
        body_to_store = body
        if crypto.is_encrypted and not crypto._use_sqlcipher:
            body_to_store = crypto.encrypt_content(body)
        cur = conn.execute(
            "INSERT INTO anchors (session_id, label, body, created_at) VALUES (?, ?, ?, ?)",
            (session_id, label, body_to_store, time.time()),
        )
    conn.close()
    return int(cur.lastrowid)


def save_invariants(session_id: str, invariants: list[tuple[str, str, int]]) -> None:
    """Persist the invariant set of a session so verification never rescans the content."""
    conn = _connect()
    with conn:
        conn.executemany(
            "INSERT INTO invariants (session_id, kind, value, priority) VALUES (?, ?, ?, ?)",
            [(session_id, k, v, p) for k, v, p in invariants],
        )
    conn.close()


def load_invariants(session_id: str) -> list[tuple[str, str, int]]:
    """Return the persisted invariant set of a session."""
    conn = _connect()
    rows = conn.execute(
        "SELECT kind, value, priority FROM invariants WHERE session_id = ?", (session_id,)
    ).fetchall()
    conn.close()
    return [(r["kind"], r["value"], r["priority"]) for r in rows]


def load_chunk(chunk_id: int) -> dict[str, Any] | None:
    """Return a chunk by id, incrementing its hit counter."""
    from loom.crypto import get_encryption

    crypto = get_encryption()
    conn = _connect()
    row = conn.execute("SELECT * FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
    if row is not None:
        with conn:
            conn.execute("UPDATE chunks SET hits = hits + 1 WHERE id = ?", (chunk_id,))
    conn.close()
    if row is None:
        return None
    content = row["content"]
    if crypto.is_encrypted and not crypto._use_sqlcipher:
        content = crypto.decrypt_content(content)
    return {"content": content, "label": row["label"], "id": row["id"], "tokens": row["tokens"]}


def stats(session_id: str = "default") -> dict[str, Any]:
    """Measured token statistics for a session."""
    conn = _connect()
    row = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(tokens), 0) AS stored_tokens, "
        "COALESCE(SUM(hits), 0) AS hits FROM chunks WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    conn.close()
    stored = int(row["stored_tokens"])
    return {
        "session_id": session_id,
        "chunks": int(row["n"]),
        "stored_tokens": stored,
        "hits": int(row["hits"]),
    }


def search(query: str, session_id: str = "default", limit: int = 10) -> list[dict[str, Any]]:
    """Full-text search over stored chunks."""
    conn = _connect()
    rows = conn.execute(
        "SELECT c.id, c.label, snippet(chunks_fts, 1, '', '', '…', 20) AS snip "
        "FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
        "WHERE chunks_fts MATCH ? AND c.session_id = ? LIMIT ?",
        (query, session_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
