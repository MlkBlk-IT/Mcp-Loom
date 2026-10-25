"""LOOM_ALLOWED_DIRS guard: no prefix bypass, case-insensitive on Windows, symlink-safe."""
import os

import pytest
from fastmcp import Client

from loom.server import _path_allowed, mcp


def _payload(res):
    sc = getattr(res, "structured_content", None)
    return sc if sc is not None else res.data


def test_inside_allowed(tmp_path):
    ok = tmp_path / "ok"
    ok.mkdir()
    f = ok / "a.txt"
    f.write_text("x")
    assert _path_allowed(str(f), [str(ok)])


def test_prefix_sibling_rejected(tmp_path):
    ok = tmp_path / "ok"
    evil = tmp_path / "ok_evil"
    ok.mkdir()
    evil.mkdir()
    f = evil / "a.txt"
    f.write_text("x")
    assert not _path_allowed(str(f), [str(ok)])


def test_dotdot_escape_rejected(tmp_path):
    ok = tmp_path / "ok"
    ok.mkdir()
    (tmp_path / "secret.txt").write_text("x")
    assert not _path_allowed(str(ok / ".." / "secret.txt"), [str(ok)])


@pytest.mark.skipif(os.name != "nt", reason="case-insensitive paths are Windows-specific")
def test_case_insensitive_on_windows(tmp_path):
    ok = tmp_path / "Ok"
    ok.mkdir()
    f = ok / "a.txt"
    f.write_text("x")
    assert _path_allowed(str(f).lower(), [str(ok).upper()])


def test_symlink_escape_rejected(tmp_path):
    ok = tmp_path / "ok"
    out = tmp_path / "out"
    ok.mkdir()
    out.mkdir()
    (out / "s.txt").write_text("x")
    link = ok / "link"
    try:
        os.symlink(out, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted here")
    assert not _path_allowed(str(link / "s.txt"), [str(ok)])


async def test_ctx_store_file_enforces_guard(tmp_path, monkeypatch):
    ok = tmp_path / "ok"
    evil = tmp_path / "ok_evil"
    ok.mkdir()
    evil.mkdir()
    (ok / "a.txt").write_text("alpha 1")
    (evil / "b.txt").write_text("beta 2")
    monkeypatch.setenv("LOOM_ALLOWED_DIRS", str(ok))
    async with Client(mcp) as c:
        good = _payload(await c.call_tool("ctx_store_file", {"path": str(ok / "a.txt")}))
        bad = _payload(await c.call_tool("ctx_store_file", {"path": str(evil / "b.txt")}))
    assert "error" not in good
    assert "outside allowed dirs" in bad.get("error", "")