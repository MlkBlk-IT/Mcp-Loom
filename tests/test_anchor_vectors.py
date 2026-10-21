"""P1 — anchor extraction vectors (exact expected values).

Each case states the EXACT string that must be extracted. A regression in the
regexes fails here instead of silently degrading coverage numbers.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from loom import anchors


def _by_kind(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for inv in anchors.extract(text):
        out.setdefault(inv.kind, []).append(inv.value)
    return out


def test_v1_urls():
    text = "see https://example.com/a(b)c, then https://x.io/path. and [l](https://y.com/z) https://a.b/c;"
    urls = _by_kind(text)["url"]
    assert sorted(urls) == sorted([
        "https://example.com/a(b)c",
        "https://x.io/path",
        "https://y.com/z",
        "https://a.b/c",
    ])


def test_v2_ip_and_version():
    text = "host 192.168.1.10 net 10.0.0.1/24 v1.2.3"
    found = _by_kind(text)
    assert sorted(found["ip"]) == ["10.0.0.1/24", "192.168.1.10"]
    assert "v1.2.3" in found["version"]
    assert "1/24" not in found.get("model_id", [])
    assert "192.168.1" not in found["version"]


def test_v3_constraints():
    text = (
        "must not edit config.yaml today\n"
        "never use v1.2 here\n"
        "Never delete x.log. Then run it."
    )
    constraints = _by_kind(text)["constraint"]
    assert constraints == [
        "Never delete x.log",
        "must not edit config.yaml today",
        "never use v1.2 here",
    ]


def test_v4_numbers_port_hash():
    text = (
        "failed after 3. Retry 5 times. port 8080 ts 1700000000 "
        "build 0.5 and 94.2% id a1b2c3d4e5f6"
    )
    found = _by_kind(text)
    assert sorted(found["number"]) == ["0.5", "1700000000", "3", "5", "94.2"]
    assert found["port"] == ["port 8080"]
    assert found["hex_hash"] == ["a1b2c3d4e5f6"]
    assert "1700000000" not in found["hex_hash"]
    assert "0.5" not in found.get("version", [])
    assert "94.2" not in found.get("version", [])


def test_v5_paths():
    text = (
        "/etc/nginx/nginx.conf ~/.loom/loom.db ./src/x.py "
        "C:\\Users\\Tech\\a.txt \\\\srv\\share\\f.txt src/loom/server.py"
    )
    paths = sorted(_by_kind(text)["path"])
    assert paths == sorted([
        "/etc/nginx/nginx.conf",
        "~/.loom/loom.db",
        "./src/x.py",
        "C:\\Users\\Tech\\a.txt",
        "\\\\srv\\share\\f.txt",
        "src/loom/server.py",
    ])


def test_v6_noise_is_not_extracted():
    text = (
        "and/or TCP/IP 2026/10/21 application/json I/O yes/no "
        "ERROR INFO TODO 10.0.0.0/8"
    )
    found = _by_kind(text)
    assert "model_id" not in found
    assert "env_var" not in found


def test_v7_model_ids_and_env_vars():
    text = (
        "openrouter/minimax/minimax-m3 nvidia/nemotron-3-ultra-550b-a55b:free "
        "BAAI/bge-small-en-v1.5 LOOM_DB=1 HOME_DIR"
    )
    found = _by_kind(text)
    assert sorted(found["model_id"]) == sorted([
        "openrouter/minimax/minimax-m3",
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "BAAI/bge-small-en-v1.5",
    ])
    assert sorted(found["env_var"]) == ["HOME_DIR", "LOOM_DB"]


def test_v8_coverage_boundaries():
    assert anchors.present("5", "number", "total 15") is False
    assert anchors.present("5", "number", "total 5 items") is True
    assert anchors.present("1.2.3", "version", "x 11.2.3") is False


def test_v9_every_regex_compiles():
    for name, pattern in anchors.PATTERNS.items():
        assert pattern.pattern, f"empty pattern for {name}"
    # re.compile already happened at import time; assert the module is importable
    # in a FRESH interpreter (catches import-time crashes).
    code = "import loom.anchors, loom.compress, loom.verify, loom.server; print('ok')"
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    assert "ok" in proc.stdout
