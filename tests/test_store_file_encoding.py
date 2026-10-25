"""ctx_store_file: clear errors for non-UTF-8 files, UTF-8 (with BOM) stays byte-exact."""
from fastmcp import Client

from loom.server import mcp


def _payload(res):
    sc = getattr(res, "structured_content", None)
    return sc if sc is not None else res.data


async def test_utf16_file_gets_explicit_hint(tmp_path):
    f = tmp_path / "ps.log"
    f.write_bytes("hello 42".encode("utf-16"))  # BOM + UTF-16LE
    async with Client(mcp) as c:
        res = _payload(await c.call_tool("ctx_store_file", {"path": str(f)}))
    assert "UTF-16" in res["error"]
    assert "re-save it as UTF-8" in res["error"]


async def test_cp1252_file_gets_explicit_hint(tmp_path):
    f = tmp_path / "old.txt"
    f.write_bytes(b"caf\xe9 12")
    async with Client(mcp) as c:
        res = _payload(await c.call_tool("ctx_store_file", {"path": str(f)}))
    assert "not valid UTF-8" in res["error"]


async def test_utf8_bom_roundtrips_exactly(tmp_path):
    f = tmp_path / "bom.txt"
    raw = b"\xef\xbb\xbfversion=1.2.3 path=/a/b value=42"
    f.write_bytes(raw)
    async with Client(mcp) as c:
        stored = _payload(await c.call_tool("ctx_store_file", {"path": str(f)}))
        assert "error" not in stored
        got = _payload(await c.call_tool("ctx_get", {"chunk_id": stored["chunk_ids"][0]}))
    assert got["content"].encode("utf-8") == raw