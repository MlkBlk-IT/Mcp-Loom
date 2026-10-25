"""Admin CLI for Loom.

The MCP tools are the product; this CLI is the maintenance hatch for when you
have no MCP client attached to the drawer:

    loom health                 # drawer status
    loom stats --session demo   # token stats for a session
    loom sessions               # list sessions
    loom vacuum                 # compact the SQLite drawer
    loom purge-expired          # drop sessions past their TTL
    loom purge <session_id>     # drop one session
    loom search "build failed"  # FTS5 search over stored chunks
    loom serve                  # run the MCP server on stdio
    loom version
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

__all__ = ["main"]


def _dump(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="loom",
        description="Loom admin CLI - inspect and maintain the local drawer.",
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("serve", help="Run the MCP server on stdio (same as `loom-mcp`).")
    sub.add_parser("version", help="Print the installed version.")
    sub.add_parser("health", help="Drawer health status.")

    p = sub.add_parser("stats", help="Token stats for a session.")
    p.add_argument("--session", default="default")

    p = sub.add_parser("sessions", help="List sessions.")
    p.add_argument("--include-expired", action="store_true")

    sub.add_parser("vacuum", help="Compact the SQLite drawer.")
    sub.add_parser("purge-expired", help="Purge sessions past their TTL.")

    p = sub.add_parser("purge", help="Purge one session.")
    p.add_argument("session_id")

    p = sub.add_parser("search", help="FTS5 search over stored chunks.")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--session", default="default")
    p.add_argument("--no-semantic", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    cmd = args.cmd or "serve"

    if cmd == "version":
        from loom import __version__

        print(__version__)
        return 0

    if cmd == "serve":
        from loom import server

        server.main()
        return 0

    # Every remaining command is a thin wrapper over an existing MCP tool.
    from loom import server

    if cmd == "health":
        _dump(server.ctx_health())
    elif cmd == "stats":
        _dump(server.ctx_stats(session_id=args.session))
    elif cmd == "sessions":
        _dump(server.ctx_list_sessions(include_expired=args.include_expired))
    elif cmd == "vacuum":
        _dump(server.ctx_vacuum())
    elif cmd == "purge-expired":
        _dump(server.ctx_purge_expired())
    elif cmd == "purge":
        _dump(server.ctx_purge_session(args.session_id))
    elif cmd == "search":
        _dump(
            server.ctx_search(
                args.query,
                limit=args.limit,
                session_id=args.session,
                semantic=not args.no_semantic,
            )
        )
    else:  # pragma: no cover - argparse rejects unknown commands first
        print(f"unknown command: {cmd}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
