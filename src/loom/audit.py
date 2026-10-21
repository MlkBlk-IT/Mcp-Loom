"""Audit logging for Loom MCP server using structlog JSONL.

Logs every tool call with: request_id, session_id, tool, latency, outcome.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path
from typing import Optional

try:
    import structlog
    HAS_STRUCTLOG = True
except ImportError:
    HAS_STRUCTLOG = False

# Configure structlog
if HAS_STRUCTLOG:
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

# Audit log directory
AUDIT_DIR = Path(os.environ.get("LOOM_AUDIT_DIR", Path.home() / ".loom" / "audit"))
AUDIT_DIR.mkdir(parents=True, exist_ok=True)

_audit_logger: Optional[logging.Logger] = None


def get_audit_logger() -> logging.Logger:
    """Get or create the audit logger."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = logging.getLogger("loom.audit")
        _audit_logger.setLevel(logging.INFO)
        # File handler for JSONL
        handler = logging.FileHandler(AUDIT_DIR / "audit.jsonl", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        _audit_logger.addHandler(handler)
        # Prevent propagation to root logger
        _audit_logger.propagate = False
    return _audit_logger


def audit_tool_call(
    tool: str,
    session_id: str = "default",
    request_id: Optional[str] = None,
    latency_ms: float = 0.0,
    outcome: str = "success",
    error: Optional[str] = None,
) -> None:
    """Log a tool call to the audit trail."""
    if request_id is None:
        request_id = str(uuid.uuid4())

    log_entry = {
        "request_id": request_id,
        "session_id": session_id,
        "tool": tool,
        "latency_ms": round(latency_ms, 2),
        "outcome": outcome,
    }
    if error:
        log_entry["error"] = error

    logger = get_audit_logger()
    logger.info(str(log_entry).replace("'", '"') if not HAS_STRUCTLOG else None)

    # Use structlog if available
    if HAS_STRUCTLOG:
        slogger = structlog.get_logger("loom.audit")
        slogger.info("tool_call", **log_entry)


def audit_summary() -> dict:
    """Return audit log summary."""
    log_file = AUDIT_DIR / "audit.jsonl"
    if not log_file.exists():
        return {"total_calls": 0, "by_tool": {}}

    from collections import Counter
    tools = Counter()
    total = 0
    with open(log_file, encoding="utf-8") as f:
        for line in f:
            total += 1
            # Simple parsing — extract tool name
            if '"tool":' in line:
                try:
                    import json
                    # Try to parse the JSON part
                    data = json.loads(line.strip())
                    tools[data.get("tool", "unknown")] += 1
                except Exception:
                    pass

    return {"total_calls": total, "by_tool": dict(tools)}