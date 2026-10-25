"""Loom — auto-store hook (zero-friction context caching).

Wraps any function that produces large output.  When the output exceeds a
token threshold, it's automatically stored via ``ctx_store`` and a short
anchor + chunk IDs are returned instead of the full text.

Usage::

    from loom.auto_store import auto_store

    @auto_store(threshold_tokens=500)
    def run_build(cmd: str) -> str:
        return subprocess.run(cmd, capture_output=True).stdout

If the output is ≤ threshold, the original text is returned unchanged.
The threshold is also configurable via the ``LOOM_AUTO_STORE_THRESHOLD``
environment variable.
"""

from __future__ import annotations

import functools
import logging
import os
from typing import Any, Callable

log = logging.getLogger(__name__)

DEFAULT_THRESHOLD = int(os.environ.get("LOOM_AUTO_STORE_THRESHOLD", "500"))


def auto_store(
    threshold_tokens: int | None = None,
    session_id: str = "auto",
    label_prefix: str = "cmd.",
) -> Callable:
    """Decorator that auto-stores large function outputs.

    Args:
        threshold_tokens: store if output ≥ this many tokens (default: 500,
            or ``LOOM_AUTO_STORE_THRESHOLD`` env var).
        session_id: session to store under (default: "auto" → auto-generated).
        label_prefix: prefix for the stored label (default: "cmd.").

    Returns:
        The original output if small, or a dict ``{anchor, chunk_ids, tokens_before,
        tokens_after, stored: True}`` if the output was stored.
    """
    threshold = threshold_tokens if threshold_tokens is not None else DEFAULT_THRESHOLD

    def decorator(fn: Callable) -> Callable:
        label_name = label_prefix + fn.__name__

        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> Any:
            result = fn(*args, **kwargs)

            # Only auto-store string outputs.
            if not isinstance(result, str):
                return result

            from loom.tokenizer import count_tokens
            token_count = count_tokens(result)

            if token_count < threshold:
                # Small enough — passthrough unchanged.
                return result

            # Large output — store it and return the anchor.
            try:
                from loom import store, compress
                from loom.profile import get_profile
                from loom import session as sess

                resolved = sess.resolve_session_id(session_id)
                sess.create_session(resolved, label=label_name)

                profile = get_profile()
                tokens_before = count_tokens(result)
                anchor, chunks = compress.build_anchor(result, profile=profile)
                anchor_tokens = count_tokens(anchor)

                from loom import anchors as anchor_mod
                invariants = anchor_mod.extract(result)

                saved = store.save_all(
                    resolved,
                    label_name,
                    chunks,
                    anchor,
                    [(i.kind, i.value, i.priority) for i in invariants],
                    source_meta={
                        "tokens_before": tokens_before,
                        "anchor_tokens": anchor_tokens,
                    },
                )

                sess.touch_session(resolved)

                log.info(
                    "auto_store: %s → %d tokens stored, anchor %d tokens (%.1f%% saved)",
                    label_name,
                    tokens_before,
                    anchor_tokens,
                    (1 - anchor_tokens / tokens_before) * 100 if tokens_before else 0,
                )

                return {
                    "stored": True,
                    "anchor": anchor,
                    "chunk_ids": saved["chunk_ids"],
                    "session_id": resolved,
                    "tokens_before": tokens_before,
                    "tokens_after": anchor_tokens,
                    "saved_ratio": round(
                        1 - (anchor_tokens / tokens_before), 4
                    ) if tokens_before else 0.0,
                    "label": label_name,
                }
            except Exception as e:
                log.warning("auto_store: failed to store %s: %s — returning raw", label_name, e)
                return result  # fail-safe: return the raw output

        # Expose threshold for introspection.
        wrapper._loom_threshold = threshold
        wrapper._loom_session = session_id
        return wrapper

    return decorator
