"""Session management — auto UUIDv7, isolation, TTL, admin tools."""

from __future__ import annotations

import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any

# Single source of truth for the DB path and connection.
# store.py does NOT import session.py, so this is not a circular import.
from loom.store import DB_PATH, _connect


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_TTL_DAYS = int(os.environ.get("LOOM_TTL_DAYS", "30"))
SESSION_ID_ENV = os.environ.get("LOOM_SESSION_ID")


def _connect() -> sqlite3.Connection:
    """Connect to the Loom database and ensure all tables exist.

    Creates the store tables (chunks, anchors, invariants) and the session
    table (sessions) with IF NOT EXISTS, so every module that calls this
    gets a usable schema regardless of which module was first.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    # Store tables — owned by store.py but created here too so session.py
    # can query them on a fresh DB without depending on store having run first.
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
        "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5("
        "label, content, content='chunks', content_rowid='id')"
    )
    conn.execute(_session_table_sql())
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions (updated_at)"
    )
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# UUIDv7 generation (time-ordered, RFC 9562)
# ---------------------------------------------------------------------------

def _uuid7() -> str:
    """Generate UUIDv7 (Unix timestamp ms + random)."""
    ms = int(time.time() * 1000)
    rand = uuid.uuid4().bytes
    time_bytes = ms.to_bytes(6, "big")
    combined = time_bytes + rand[6:]
    combined = bytearray(combined)
    combined[6] = (combined[6] & 0x0F) | 0x70  # version 7
    combined[8] = (combined[8] & 0x3F) | 0x80
    return uuid.UUID(bytes=bytes(combined)).hex


def generate_session_id() -> str:
    """Generate a new session ID (UUIDv7)."""
    return _uuid7()


def resolve_session_id(provided: str | None = None) -> str:
    """
    Resolve session ID: explicit > env > "default" (stable shared session) > generated.

    "default" is a literal stable session ID so that multiple calls without an
    explicit session_id share the same session. This is the expected behavior
    for a "default" session — otherwise ctx_store + ctx_check would never
    see each other's data.
    """
    if provided and provided != "default":
        return provided
    if SESSION_ID_ENV:
        return SESSION_ID_ENV
    return "default"


# ---------------------------------------------------------------------------
# Session metadata
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SessionInfo:
    session_id: str
    label: str
    created_at: float
    updated_at: float
    chunk_count: int
    token_count: int
    anchor_count: int
    expired: bool


def _session_table_sql() -> str:
    return """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id   TEXT PRIMARY KEY,
            label        TEXT NOT NULL DEFAULT '',
            created_at   REAL NOT NULL,
            updated_at   REAL NOT NULL,
            ttl_days     INTEGER NOT NULL DEFAULT 30
        )
    """


def _ensure_session_table(conn: sqlite3.Connection) -> None:
    conn.execute(_session_table_sql())
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions (updated_at)"
    )
    conn.commit()


def _now() -> float:
    return time.time()


def _is_expired(created_at: float, ttl_days: int) -> bool:
    return (_now() - created_at) > (ttl_days * 86400)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_session(session_id: str, label: str = "", ttl_days: int = DEFAULT_TTL_DAYS) -> None:
    """Register a new session."""
    conn = _connect()
    _ensure_session_table(conn)
    now = _now()
    conn.execute(
        "INSERT OR REPLACE INTO sessions (session_id, label, created_at, updated_at, ttl_days) VALUES (?, ?, ?, ?, ?)",
        (session_id, label, now, now, ttl_days),
    )
    conn.commit()
    conn.close()


def touch_session(session_id: str) -> None:
    """Update session's updated_at to now."""
    conn = _connect()
    _ensure_session_table(conn)
    conn.execute(
        "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
        (_now(), session_id),
    )
    conn.commit()
    conn.close()


def get_session(session_id: str) -> SessionInfo | None:
    """Get session metadata + stats."""
    conn = _connect()
    _ensure_session_table(conn)
    row = conn.execute(
        "SELECT session_id, label, created_at, updated_at, ttl_days FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if not row:
        conn.close()
        return None

    # Stats
    stats_row = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM chunks WHERE session_id = ?) as chunks,
            (SELECT COALESCE(SUM(tokens), 0) FROM chunks WHERE session_id = ?) as tokens,
            (SELECT COUNT(*) FROM anchors WHERE session_id = ?) as anchors
        """,
        (session_id, session_id, session_id),
    ).fetchone()
    conn.close()

    expired = _is_expired(row["created_at"], row["ttl_days"])
    return SessionInfo(
        session_id=row["session_id"],
        label=row["label"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        chunk_count=stats_row["chunks"] or 0,
        token_count=stats_row["tokens"] or 0,
        anchor_count=stats_row["anchors"] or 0,
        expired=expired,
    )


def list_sessions(include_expired: bool = False) -> list[SessionInfo]:
    """List all sessions, optionally including expired."""
    conn = _connect()
    _ensure_session_table(conn)
    rows = conn.execute(
        "SELECT session_id, label, created_at, updated_at, ttl_days FROM sessions ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()

    sessions = []
    for row in rows:
        expired = _is_expired(row["created_at"], row["ttl_days"])
        if expired and not include_expired:
            continue
        info = get_session(row["session_id"])
        if info:
            sessions.append(info)
    return sessions


def purge_session(session_id: str) -> dict[str, Any]:
    """Delete all data for a session (chunks, anchors, invariants, session row)."""
    conn = _connect()
    _ensure_session_table(conn)
    with conn:
        chunks_deleted = conn.execute(
            "DELETE FROM chunks WHERE session_id = ?", (session_id,)
        ).rowcount
        anchors_deleted = conn.execute(
            "DELETE FROM anchors WHERE session_id = ?", (session_id,)
        ).rowcount
        invariants_deleted = conn.execute(
            "DELETE FROM invariants WHERE session_id = ?", (session_id,)
        ).rowcount
        session_deleted = conn.execute(
            "DELETE FROM sessions WHERE session_id = ?", (session_id,)
        ).rowcount
    conn.close()
    return {
        "session_id": session_id,
        "chunks_deleted": chunks_deleted,
        "anchors_deleted": anchors_deleted,
        "invariants_deleted": invariants_deleted,
        "session_row_deleted": session_deleted > 0,
    }


def purge_expired_sessions() -> dict[str, Any]:
    """Purge all expired sessions. Returns count and details."""
    conn = _connect()
    _ensure_session_table(conn)
    expired_rows = conn.execute(
        "SELECT session_id, created_at, ttl_days FROM sessions"
    ).fetchall()
    conn.close()

    purged = []
    for row in expired_rows:
        if _is_expired(row["created_at"], row["ttl_days"]):
            result = purge_session(row["session_id"])
            purged.append(result)
    return {"purged_count": len(purged), "sessions": purged}


def vacuum_db() -> dict[str, Any]:
    """Run SQLite VACUUM to reclaim space."""
    conn = _connect()
    start_size = DB_PATH.stat().st_size
    conn.execute("VACUUM")
    conn.close()
    end_size = DB_PATH.stat().st_size
    return {
        "ok": True,
        "size_before_bytes": start_size,
        "size_after_bytes": end_size,
        "reclaimed_bytes": start_size - end_size,
    }


def health_check() -> dict[str, Any]:
    """Health check for the Loom drawer."""
    conn = _connect()
    _ensure_session_table(conn)
    session_count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    anchor_count = conn.execute("SELECT COUNT(*) FROM anchors").fetchone()[0]
    invariant_count = conn.execute("SELECT COUNT(*) FROM invariants").fetchone()[0]
    wal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()

    return {
        "ok": True,
        "db_path": str(DB_PATH),
        "db_exists": DB_PATH.exists(),
        "db_size_bytes": DB_PATH.stat().st_size if DB_PATH.exists() else 0,
        "sessions": session_count,
        "chunks": chunk_count,
        "anchors": anchor_count,
        "invariants": invariant_count,
        "journal_mode": wal_mode,
        "ttl_days_default": DEFAULT_TTL_DAYS,
    }