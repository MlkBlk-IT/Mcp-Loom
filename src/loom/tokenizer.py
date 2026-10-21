"""Token counting — measured, not estimated.

tiktoken is optional; the fallback is a deterministic heuristic so Loom never
requires network access or a paid API.
"""

from __future__ import annotations

import re

try:  # pragma: no cover - optional dependency
    import tiktoken

    _ENCODER = tiktoken.get_encoding("cl100k_base")
except Exception:  # pragma: no cover
    _ENCODER = None

_WORD = re.compile(r"\w+|[^\w\s]")


def count_tokens(text: str) -> int:
    """Count tokens with tiktoken when available, else a close heuristic."""
    if not text:
        return 0
    if _ENCODER is not None:
        return len(_ENCODER.encode(text, disallowed_special=()))
    # heuristic: ~4 chars/token, words counted individually
    words = len(_WORD.findall(text))
    return max(words, (len(text) + 3) // 4)


def encoder_name() -> str:
    return "tiktoken:cl100k_base" if _ENCODER is not None else "heuristic"
