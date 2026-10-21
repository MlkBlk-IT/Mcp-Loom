"""Loom — portable MCP server: weave LLM context without cutting a thread.

Business logic lives in the sibling modules; this file only exposes it as MCP tools.
"""

from __future__ import annotations

import logging
import os
import time

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from loom import anchors as anchor_mod
from loom import compress, session, store, verify
from loom.audit import audit_tool_call
from loom.profile import get_profile
from loom.ratelimit import get_rate_limiter
from loom.sandbox import get_sandbox
from loom.tokenizer import count_tokens

log = logging.getLogger(__name__)

SERVER_NAME = "loom"
INSTRUCTIONS = """
Loom keeps context small WITHOUT losing information. It never summarizes by default.

When tool output or file content is bulky:
  1. Call `ctx_store` with the content — Loom moves it into a local drawer and returns a
     dense anchor plus stable IDs.
  2. Keep the anchor in your context; drop the raw bulk.
  3. If you truly need the raw bytes, call `ctx_get` with the returned ID — you get them
     back byte-identical.

Before accepting a compressed context, call `ctx_check` to confirm nothing critical was lost.
Losing a number, a path, a version or an explicit constraint is a bug, not a trade-off.
"""

mcp = FastMCP(name=SERVER_NAME, instructions=INSTRUCTIONS)

_rate_limiter = get_rate_limiter()


def _check_rate_limit(session_id: str) -> dict | None:
    """Check rate limit for session. Returns error dict if limited, None if allowed."""
    if not _rate_limiter.allow(session_id):
        return {"error": f"rate limit exceeded for session {session_id}"}
    return None


def _audit_call(tool: str, session_id: str, start: float, outcome: str, error: str | None = None):
    """Log tool call to audit trail."""
    audit_tool_call(
        tool=tool,
        session_id=session_id,
        latency_ms=(time.perf_counter() - start) * 1000,
        outcome=outcome,
        error=error,
    )


import time


@mcp.tool(
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )
)
def ctx_store(content: str, session_id: str = "default", label: str = "") -> dict:
    """Move bulky content out of the prompt into a local drawer, without losing any of it.

    Returns a dense anchor (the parts that must stay in context) plus stable IDs so the
    original bytes can be retrieved later with `ctx_get`.

    Args:
        content: the bulky text to store (log dump, file body, tool output, etc.)
        session_id: logical session the content belongs to (auto UUIDv7 if "default" or omitted)
        label: short human-readable name, e.g. "build.log"

    Returns:
        dict with anchor, chunk ids, token counts (before/after) and savings ratio.
    """
    start = time.perf_counter()
    rl = _check_rate_limit(session_id)
    if rl is not None:
        _audit_call("ctx_store", session_id, start, "error", rl["error"])
        return rl
    resolved_session = session.resolve_session_id(session_id)
    # Ensure session exists in metadata
    session.create_session(resolved_session, label=label)

    # Redact secrets before storage (Task 4)
    from loom import redact
    content, redaction_count = redact.redact_text(content)

    profile = get_profile()
    tokens_before = count_tokens(content)
    anchor, chunks = compress.build_anchor(content, profile=profile)
    anchor_tokens = count_tokens(anchor)
    ids = store.save_chunks(resolved_session, label, chunks)
    store.save_anchor(resolved_session, label, anchor)
    invariants = anchor_mod.extract(content)
    store.save_invariants(
        resolved_session, [(i.kind, i.value, i.priority) for i in invariants]
    )
    # Touch session updated_at
    session.touch_session(resolved_session)

    result = {
        "session_id": resolved_session,
        "anchor": anchor,
        "chunk_ids": ids,
        "tokens_before": tokens_before,
        "tokens_after": anchor_tokens,
        "saved_ratio": (
            round(1 - (anchor_tokens / tokens_before), 4) if tokens_before else 0.0
        ),
        "lossless": True,
        "redactions": redaction_count,
    }
    _audit_call("ctx_store", resolved_session, start, "success")
    return result


@mcp.tool(
    annotations=ToolAnnotations(
        read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )
)
def ctx_get(chunk_id: str | int) -> dict:
    """Retrieve a stored chunk, byte-identical to what was originally stored.

    Args:
        chunk_id: id returned by `ctx_store` in `chunk_ids` (int or its string form)

    Returns:
        dict with the original content and its metadata.
    """
    start = time.perf_counter()
    rl = _check_rate_limit("default")
    if rl is not None:
        _audit_call("ctx_get", "default", start, "error", rl["error"])
        return rl
    try:
        cid = int(chunk_id)
    except (TypeError, ValueError):
        res = {"found": False, "error": f"invalid chunk_id {chunk_id!r}: expected an integer."}
        _audit_call("ctx_get", "default", start, "error", res["error"])
        return res
    chunk = store.load_chunk(cid)
    if chunk is None:
        res = {
            "found": False,
            "error": f"chunk {chunk_id!r} not found. It may have been pruned; "
            f"call ctx_store again with the content.",
        }
        _audit_call("ctx_get", "default", start, "error", res["error"])
        return res
    _audit_call("ctx_get", "default", start, "success")
    return {"found": True, "content": chunk["content"], "label": chunk["label"]}


@mcp.tool(
    annotations=ToolAnnotations(
        read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )
)
def ctx_check(session_id: str = "default") -> dict:
    """Verify that nothing critical was lost in the stored context.

    Re-derives the invariants (numbers, paths, URLs, versions, explicit constraints) from
    every chunk of the session and reports coverage.

    Returns:
        dict with coverage ratio, missing invariants and per-chunk detail.
    """
    start = time.perf_counter()
    rl = _check_rate_limit(session_id)
    if rl is not None:
        _audit_call("ctx_check", session_id, start, "error", rl["error"])
        return rl
    resolved_session = session.resolve_session_id(session_id)
    result = verify.check_session(resolved_session)
    _audit_call("ctx_check", resolved_session, start, "success")
    return result


@mcp.tool(
    annotations=ToolAnnotations(
        read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )
)
def ctx_stats(session_id: str = "default") -> dict:
    """Report measured token usage and savings for a session.

    Returns:
        dict with chunk count, total stored tokens, anchor tokens, ratio, hit counts.
    """
    start = time.perf_counter()
    rl = _check_rate_limit(session_id)
    if rl is not None:
        _audit_call("ctx_stats", session_id, start, "error", rl["error"])
        return rl
    resolved_session = session.resolve_session_id(session_id)
    result = store.stats(resolved_session)
    _audit_call("ctx_stats", resolved_session, start, "success")
    return result


@mcp.tool(
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )
)
def ctx_profile(mode: str = "strict") -> dict:
    """Set the compression profile.

    Args:
        mode: "strict" (default, zero loss, move-only), "balanced", or "aggressive"
            (aggressive enables lossy summarization — opt-in, always reported).

    Returns:
        dict with the active profile and its rules.
    """
    start = time.perf_counter()
    rl = _check_rate_limit("default")
    if rl is not None:
        _audit_call("ctx_profile", "default", start, "error", rl["error"])
        return rl
    from loom.profile import set_profile

    result = set_profile(mode)
    _audit_call("ctx_profile", "default", start, "success")
    return result


# --- Session Management Tools ---

@mcp.tool(
    annotations=ToolAnnotations(
        read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )
)
def ctx_list_sessions(include_expired: bool = False) -> dict:
    """List all sessions with metadata and stats.

    Args:
        include_expired: if true, include sessions past their TTL (default: false)

    Returns:
        dict with list of sessions and their info.
    """
    start = time.perf_counter()
    rl = _check_rate_limit("default")
    if rl is not None:
        _audit_call("ctx_list_sessions", "default", start, "error", rl["error"])
        return rl
    sessions = session.list_sessions(include_expired=include_expired)
    result = {
        "sessions": [
            {
                "session_id": s.session_id,
                "label": s.label,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
                "chunk_count": s.chunk_count,
                "token_count": s.token_count,
                "anchor_count": s.anchor_count,
                "expired": s.expired,
            }
            for s in sessions
        ],
        "count": len(sessions),
    }
    _audit_call("ctx_list_sessions", "default", start, "success")
    return result


@mcp.tool(
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False
    )
)
def ctx_purge_session(session_id: str) -> dict:
    """Permanently delete all data for a session (chunks, anchors, invariants, session row).

    Args:
        session_id: the session to purge (must be explicit, not "default")

    Returns:
        dict with deletion counts.
    """
    start = time.perf_counter()
    rl = _check_rate_limit(session_id)
    if rl is not None:
        _audit_call("ctx_purge_session", session_id, start, "error", rl["error"])
        return rl
    if session_id == "default":
        res = {"ok": False, "error": "session_id required (cannot purge 'default')"}
        _audit_call("ctx_purge_session", session_id, start, "error", res["error"])
        return res
    result = session.purge_session(session_id)
    _audit_call("ctx_purge_session", session_id, start, "success")
    return result


@mcp.tool(
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False
    )
)
def ctx_purge_expired() -> dict:
    """Purge all sessions past their TTL.

    Returns:
        dict with purged count and details.
    """
    start = time.perf_counter()
    rl = _check_rate_limit("default")
    if rl is not None:
        _audit_call("ctx_purge_expired", "default", start, "error", rl["error"])
        return rl
    result = session.purge_expired_sessions()
    _audit_call("ctx_purge_expired", "default", start, "success")
    return result


@mcp.tool(
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )
)
def ctx_vacuum() -> dict:
    """Run SQLite VACUUM to reclaim unused space.

    Returns:
        dict with size before/after and bytes reclaimed.
    """
    start = time.perf_counter()
    rl = _check_rate_limit("default")
    if rl is not None:
        _audit_call("ctx_vacuum", "default", start, "error", rl["error"])
        return rl
    result = session.vacuum_db()
    _audit_call("ctx_vacuum", "default", start, "success")
    return result


@mcp.tool(
    annotations=ToolAnnotations(
        read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )
)
def ctx_health() -> dict:
    """Health check for the Loom drawer (DB connectivity, sizes, counts, WAL mode).

    Returns:
        dict with health status and metrics.
    """
    start = time.perf_counter()
    rl = _check_rate_limit("default")
    if rl is not None:
        _audit_call("ctx_health", "default", start, "error", rl["error"])
        return rl
    result = session.health_check()
    _audit_call("ctx_health", "default", start, "success")
    return result


@mcp.tool(
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )
)
def ctx_store_file(path: str, session_id: str = "default", label: str = "") -> dict:
    """Read a file from disk and store its contents in the Loom drawer.

    Args:
        path: absolute or relative file path
        session_id: logical session the content belongs to
        label: short human-readable name (defaults to basename)

    Returns:
        dict with anchor, chunk ids, token counts, savings ratio, redactions.
    """
    start = time.perf_counter()
    rl = _check_rate_limit(session_id)
    if rl is not None:
        _audit_call("ctx_store_file", session_id, start, "error", rl["error"])
        return rl
    import os as _os
    if not label:
        label = _os.path.basename(path)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    _audit_call("ctx_store_file", session_id, start, "success")
    return ctx_store(content=content, session_id=session_id, label=label)


@mcp.tool(
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True
    )
)
def ctx_store_cmd(cmd: str, session_id: str = "default", label: str = "") -> dict:
    """Run a shell command in a sandbox, capture its output, and store it in the Loom drawer.

    Requires LOOM_STORE_CMD=1 to be set (opt-in). Sandbox enforces CPU, memory,
    process, and network limits. Fails closed if sandbox unavailable.

    Args:
        cmd: shell command to execute
        session_id: logical session the output belongs to
        label: short human-readable name (defaults to cmd)

    Returns:
        dict with anchor, chunk ids, token counts, savings ratio, redactions.
    """
    start = time.perf_counter()
    rl = _check_rate_limit(session_id)
    if rl is not None:
        _audit_call("ctx_store_cmd", session_id, start, "error", rl["error"])
        return rl
    if os.environ.get("LOOM_STORE_CMD") != "1":
        res = {"error": "ctx_store_cmd disabled — set LOOM_STORE_CMD=1 to enable"}
        _audit_call("ctx_store_cmd", session_id, start, "error", res["error"])
        return res

    if not label:
        label = cmd[:60]

    sandbox = get_sandbox()
    if not sandbox.is_available():
        res = {"error": "sandbox unavailable (pywin32 on Windows, bwrap/firejail on Linux) — command rejected"}
        _audit_call("ctx_store_cmd", session_id, start, "error", res["error"])
        return res

    result = sandbox.run(cmd)
    if result.error:
        res = {"error": f"sandbox error: {result.error}", "sandboxed": result.sandboxed}
        _audit_call("ctx_store_cmd", session_id, start, "error", res["error"])
        return res

    content = result.stdout
    if result.stderr:
        content += "\n\n[stderr]\n" + result.stderr

    _audit_call("ctx_store_cmd", session_id, start, "success")
    return ctx_store(content=content, session_id=session_id, label=label)


@mcp.tool(
    annotations=ToolAnnotations(
        read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )
)
def ctx_search(query: str, limit: int = 5, session_id: str = "default") -> dict:
    """Search stored chunks using FTS5 full-text search.

    Args:
        query: search query (FTS5 syntax)
        limit: max results (default 5)
        session_id: session to search (default: all sessions)

    Returns:
        dict with matching chunks and their metadata.
    """
    start = time.perf_counter()
    rl = _check_rate_limit(session_id)
    if rl is not None:
        _audit_call("ctx_search", session_id, start, "error", rl["error"])
        return rl
    results = store.search(query, limit=limit, session_id=session_id)
    result = {
        "query": query,
        "results": [
            {"chunk_id": r["id"], "label": r["label"], "content": r["content"][:500],
             "session_id": r.get("session_id", "")}
            for r in results
        ],
        "count": len(results),
    }
    _audit_call("ctx_search", session_id, start, "success")
    return result


def main() -> None:
    """Entry point for `loom-mcp` console script (stdio transport)."""
    logging.basicConfig(level=os.environ.get("LOOM_LOG_LEVEL", "INFO"))
    log.info("starting loom-mcp")
    mcp.run()


if __name__ == "__main__":
    main()
