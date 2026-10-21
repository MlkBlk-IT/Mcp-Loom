"""Safety-net tests — the invariants must survive.

This is the test that decides whether Loom is trustworthy. If it fails, the product
does not ship.
"""

from __future__ import annotations

import pytest

from loom import anchors, compress

SAMPLE_LOG = """
Build started at 2026-10-21T09:00:00Z
Reading config from C:\\Users\\Tech\\AppData\\Local\\hermes\\config.yaml
exit_code: 0
error: Failed to connect to https://api.example.com/v1/models
traceback (most recent call last):
  File "C:\\Python314\\Lib\\site-packages\\httpx\\_client.py", line 1234, in send
    raise ConnectError("connection refused")
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
-OLD_VALUE = 1
+NEW_VALUE = 2
The user constraint: never print secrets in logs.
Version 1.2.3 was deployed on port 8080.
"""


def test_invariants_extracted():
    invs = anchors.extract(SAMPLE_LOG)
    values = {i.value for i in invs}
    assert any("config.yaml" in v for v in values)
    assert any("https://api.example.com/v1/models" in v for v in values)
    assert any("1.2.3" in v for v in values)
    assert any("never print secrets" in v.lower() for v in values)


def test_critical_constraints_are_flagged():
    invs = anchors.extract(SAMPLE_LOG)
    critical = [i for i in invs if i.priority == 3]
    assert critical, "explicit constraints must be detected as critical"


def test_anchor_keeps_every_invariant():
    anchor, chunks = compress.build_anchor(SAMPLE_LOG)
    report = anchors.coverage(anchors.extract(SAMPLE_LOG), anchor)
    missing = report["missing"]
    assert not missing, f"invariants lost: {missing}"


def test_chunks_preserve_all_bytes():
    anchor, chunks = compress.build_anchor(SAMPLE_LOG)
    rejoined = "\n".join(c["text"] for c in chunks)
    for token in ["config.yaml", "8080", "NEW_VALUE = 2", "never print secrets"]:
        assert token in rejoined


@pytest.mark.parametrize(
    "sample",
    [
        SAMPLE_LOG,
        "trailing newline\n",
        "\n\nleading blank\n\n",
        "no blank lines at all",
        "",
        "unicode ✅ accents éàü and emoji 🚀\n\nsecond block\n",
        "   spaces   \n\t\ttabs\t\n",
        "single\n\n\n\nquadruple blank\n",
    ],
)
def test_chunks_are_byte_identical(sample):
    """The core promise: what comes out of ctx_get is exactly what went in."""
    _, chunks = compress.build_anchor(sample)
    assert "".join(c["text"] for c in chunks) == sample


def test_profile_strict_is_not_lossy():
    from loom.profile import PROFILES

    assert PROFILES["strict"].allow_lossy is False
    assert PROFILES["balanced"].allow_lossy is False


@pytest.mark.parametrize("sample", [SAMPLE_LOG, "", "no invariants here at all"])
def test_coverage_handles_edge_cases(sample):
    report = anchors.coverage(anchors.extract(sample), sample)
    assert 0.0 <= report["coverage"] <= 1.0
