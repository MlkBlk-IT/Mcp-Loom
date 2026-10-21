"""Secret redaction — masks common credential patterns before storage.

Enabled by default. Disables via LOOM_REDACT=0 env var.
Redaction breaks byte-identical retrieval for masked parts (documented).
"""
from __future__ import annotations

import os
import re
from typing import Any

# Patterns for common secrets
_PATTERNS = [
    (re.compile(r"Bearer\s+[A-Za-z0-9\-_\.]{20,}", re.IGNORECASE), "Bearer [REDACTED]"),
    (re.compile(r"(?:api[_-]?key|apikey)\s*[=:]\s*['\"]?[A-Za-z0-9\-_\.]{16,}['\"]?", re.IGNORECASE), "api_key=[REDACTED]"),
    (re.compile(r"(?:password|passwd|pwd)\s*[=:]\s*['\"]?[^\s'\"]{4,}['\"]?", re.IGNORECASE), "password=[REDACTED]"),
    (re.compile(r"(?:secret|token)\s*[=:]\s*['\"]?[A-Za-z0-9\-_\.]{16,}['\"]?", re.IGNORECASE), "secret=[REDACTED]"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}", re.IGNORECASE), "sk-[REDACTED]"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}", re.IGNORECASE), "ghp_[REDACTED]"),
    (re.compile(r"gho_[A-Za-z0-9]{20,}", re.IGNORECASE), "gho_[REDACTED]"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}", re.IGNORECASE), "xox[REDACTED]"),
]


def redact_enabled() -> bool:
    return os.environ.get("LOOM_REDACT", "1").lower() not in ("0", "false", "no", "off")


def redact_text(text: str) -> tuple[str, int]:
    """Redact secrets in text. Returns (redacted_text, redaction_count)."""
    if not redact_enabled():
        return text, 0
    count = 0
    result = text
    for pattern, replacement in _PATTERNS:
        new_result = pattern.sub(replacement, result)
        if new_result != result:
            count += len(pattern.findall(result))
            result = new_result
    return result, count


def redact_chunks(chunks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Redact secrets in chunks. Returns (redacted_chunks, total_redaction_count)."""
    total = 0
    out = []
    for chunk in chunks:
        text, n = redact_text(chunk["text"])
        out.append({**chunk, "text": text})
        total += n
    return out, total