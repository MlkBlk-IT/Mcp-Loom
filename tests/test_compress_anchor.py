"""P2 — anchor stability, budget and lossless guarantees."""

from __future__ import annotations

from loom import compress
from loom.profile import PROFILES


def _make_log(lines: int = 3000) -> str:
    out = []
    for i in range(lines):
        out.append(
            f"2026-10-21T10:{i % 60:02d}:00Z INFO build step {i} "
            f"file C:\\build\\stage{i % 37}\\artifact{i}.bin "
            f"url https://ci.example.com/job/{i}/log "
            f"exit_code {i % 7}"
        )
    return "\n".join(out) + "\n"


def test_anchor_respects_budget_and_keeps_footer():
    source = _make_log()
    for name in ("strict", "balanced", "aggressive"):
        profile = PROFILES[name]
        anchor, chunks = compress.build_anchor(source, profile=profile)
        assert len(anchor) <= profile.max_anchor_chars, (
            f"{name}: anchor {len(anchor)} > budget {profile.max_anchor_chars}"
        )
        assert anchor.splitlines()[-1].startswith("drawer:"), name
        assert not any(line.startswith("omis") for line in anchor.splitlines()), name
        assert "".join(c["text"] for c in chunks) == source, name


def test_select_invariants_zero_budget_is_unlimited():
    source = _make_log(400)
    invariants = compress.anchor_mod.extract(source)
    lines = compress._select_invariants(invariants, 0)
    listed = [line for line in lines if not line.startswith("- ... ")]
    assert len(listed) == len(invariants)


def test_chunks_are_bounded_in_bytes_for_multibyte():
    source = "\n".join("éà中文" * 30 + f" line {i}" for i in range(500)) + "\n"
    _, chunks = compress.build_anchor(source, profile=PROFILES["strict"])
    for chunk in chunks:
        assert len(chunk["text"].encode("utf-8")) <= 16 * 1024


def test_anchor_has_no_db_dependent_content():
    source = _make_log(200)
    anchor_a, _ = compress.build_anchor(source, profile=PROFILES["strict"])
    anchor_b, _ = compress.build_anchor(source, profile=PROFILES["strict"])
    assert anchor_a == anchor_b
    # no timestamp / id noise beyond the source itself
    assert "session" not in anchor_a.lower().split("drawer:")[0].replace("session_id", "")
