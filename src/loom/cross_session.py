"""Loom — cross-session / multi-agent context sharing.

Allows session A to store context and session B to retrieve it via a shared
chunk ID, or to transfer chunks between sessions.  Uses SQLite WAL mode
(already enabled in ``store._connect``) plus a lightweight cross-platform file
lock for write safety.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from loom import store
from loom.tokenizer import count_tokens

log = logging.getLogger(__name__)

DB_PATH = Path(os.environ.get("LOOM_DB", Path.home() / ".loom" / "loom.db"))
LOCK_PATH = DB_PATH.with_suffix(".lock")


# =========================================================================
# Cross-platform file lock (write-only)
# =========================================================================

class _FileLock:
    """Minimal advisory lock for serialising concurrent writes.

    On Windows uses ``msvcrt.locking``; on POSIX uses ``fcntl.flock``.
    Fallback: no-op (concurrent writes are rare for an MCP server).
    """

    def __init__(self, path: Path, timeout: float = 5.0):
        self.path = path
        self.timeout = timeout
        self._fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a+")
        deadline = time.time() + self.timeout
        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except (OSError, IOError):
                if time.time() > deadline:
                    log.warning("cross_session: lock timeout on %s", self.path)
                    return self  # proceed anyway — WAL handles concurrency
                time.sleep(0.1)

    def __exit__(self, *exc):
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        except (OSError, IOError):
            pass
        if self._fh:
            self._fh.close()


# =========================================================================
# Schema: session_chunks junction table (many-to-many)
# =========================================================================

def _ensure_junction(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS session_chunks (
            chunk_id    INTEGER NOT NULL,
            session_id  TEXT    NOT NULL,
            added_at    REAL    NOT NULL,
            PRIMARY KEY (chunk_id, session_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sc_session ON session_chunks (session_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sc_chunk ON session_chunks (chunk_id)"
    )
    conn.commit()


def _connect():
    """Open DB with junction table ensured."""
    conn = store._connect()
    _ensure_junction(conn)
    return conn


# =========================================================================
# Transfer API
# =========================================================================

def transfer(
    from_session: str,
    to_session: str,
    chunk_ids: list[int],
) -> dict[str, Any]:
    """Copy chunks from *from_session* to *to_session* via the junction table.

    This does NOT duplicate the chunk data — it adds a (chunk_id, session_id)
    row to ``session_chunks``, making the chunk visible in the target session.

    Returns a dict with ``transferred`` count and per-chunk status.
    """
    if not chunk_ids:
        return {"transferred": 0, "errors": [], "from": from_session, "to": to_session}

    errors: list[str] = []
    transferred = 0

    with _FileLock(LOCK_PATH):
        conn = _connect()
        try:
            # Verify chunks exist in from_session.
            placeholders = ",".join("?" * len(chunk_ids))
            rows = conn.execute(
                f"SELECT id FROM chunks WHERE id IN ({placeholders}) "
                f"AND session_id = ?",
                [*chunk_ids, from_session],
            ).fetchall()
            valid_ids = {r["id"] for r in rows}
            missing = set(chunk_ids) - valid_ids
            if missing:
                errors.append(f"chunks not found in {from_session}: {sorted(missing)}")

            now = time.time()
            for cid in chunk_ids:
                if cid not in valid_ids:
                    continue
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO session_chunks (chunk_id, session_id, added_at) "
                        "VALUES (?, ?, ?)",
                        (cid, to_session, now),
                    )
                    transferred += 1
                except Exception as e:
                    errors.append(f"chunk {cid}: {e}")
            conn.commit()
        finally:
            conn.close()

    # Touch target session updated_at
    from loom import session as sess
    sess.create_session(to_session, label=f"transferred-from:{from_session}")
    sess.touch_session(to_session)

    log.info("cross_session: transferred %d chunks %s → %s", transferred, from_session, to_session)
    return {
        "transferred": transferred,
        "errors": errors,
        "from": from_session,
        "to": to_session,
    }


def get_cross_session(chunk_id: int, session_id: str | None = None) -> dict[str, Any] | None:
    """Retrieve a chunk by ID, optionally verifying it's accessible from *session_id*.

    If *session_id* is provided, checks both the chunk's own session_id AND the
    session_chunks junction table for cross-session access.
    """
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
        if row is None:
            return None

        if session_id is not None and row["session_id"] != session_id:
            # Check junction table
            junction = conn.execute(
                "SELECT 1 FROM session_chunks WHERE chunk_id = ? AND session_id = ?",
                (chunk_id, session_id),
            ).fetchone()
            if junction is None:
                return None  # not accessible from this session
    finally:
        conn.close()

    return store.load_chunk(chunk_id)


def list_cross_sessions(chunk_id: int) -> list[str]:
    """List all sessions that have access to a chunk (own + transferred)."""
    conn = _connect()
    try:
        own = conn.execute(
            "SELECT session_id FROM chunks WHERE id = ?", (chunk_id,)
        ).fetchone()
        sessions = {own["session_id"]} if own else set()

        junction = conn.execute(
            "SELECT session_id FROM session_chunks WHERE chunk_id = ?", (chunk_id,)
        ).fetchall()
        sessions.update(r["session_id"] for r in junction)
    finally:
        conn.close()
    return sorted(sessions)
