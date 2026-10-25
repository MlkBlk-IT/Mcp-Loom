"""Anchor keeps the RARE structured invariants (port/ip/url/hex_hash).

Regression for the 2026-10-24 selftest: invariants were sorted by kind name, so
a few hundred paths/env vars filled the whole budget and `PORT = 8765` never
reached the anchor. Real build_anchor, no mocks.
"""

from __future__ import annotations

from loom import compress
from loom.profile import PROFILES


def _content() -> str:
    lines = [f"/var/lib/loom/data{i}/file{i}.log" for i in range(300)]
    lines += [f"C:\\Loom\\logs\\run{i}\\out{i}.txt" for i in range(100)]
    lines.append("PORT = 8765")
    lines.append("dashboard at http://127.0.0.1:8765/index.html")
    return "\n".join(lines) + "\n"


def test_rare_kinds_reach_anchor_in_every_budgeted_profile():
    for name in ("strict", "balanced", "lean"):
        anchor, _ = compress.build_anchor(_content(), PROFILES[name])
        assert "8765" in anchor, name
        assert len(anchor) <= PROFILES[name].max_anchor_chars, name


def test_anchor_still_ends_with_footer_and_chunks_are_lossless():
    content = _content()
    anchor, chunks = compress.build_anchor(content, PROFILES["lean"])
    assert anchor.splitlines()[-1].startswith("drawer:")
    assert "".join(c["text"] for c in chunks) == content


def test_no_rare_invariants_same_behaviour():
    content = "\n".join(f"/var/lib/loom/data{i}/file{i}.log" for i in range(50)) + "\n"
    anchor, _ = compress.build_anchor(content, PROFILES["strict"])
    assert "**Invariants**" in anchor
