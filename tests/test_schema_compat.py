"""MCP client compatibility: flat tool schemas (no anyOf) and tolerant ids."""
import json

from fastmcp import Client

from loom.server import mcp


def _payload(res):
    sc = getattr(res, "structured_content", None)
    return sc if sc is not None else res.data


async def test_no_anyof_in_tool_schemas():
    async with Client(mcp) as c:
        tools = await c.list_tools()
    bad = [t.name for t in tools if "anyOf" in json.dumps(t.input_schema)]
    assert not bad, f"anyOf in tool schemas: {bad}"


async def test_ctx_get_accepts_int_and_str():
    async with Client(mcp) as c:
        stored = _payload(
            await c.call_tool("ctx_store", {"content": "hello 42 /a/b v=1.2.3", "label": "t"})
        )
        cid = stored["chunk_ids"][0]
        by_int = _payload(await c.call_tool("ctx_get", {"chunk_id": cid}))
        by_str = _payload(await c.call_tool("ctx_get", {"chunk_id": str(cid)}))
    assert by_int["found"] is True
    assert by_str["found"] is True
    assert by_int["content"] == by_str["content"]


async def test_ctx_verify_accepts_empty_and_blank():
    async with Client(mcp) as c:
        await c.call_tool("ctx_store", {"content": "verify me 7", "label": "v"})
        a = _payload(await c.call_tool("ctx_verify", {}))
        b = _payload(await c.call_tool("ctx_verify", {"session_id": ""}))
    assert "lossless" in a and "lossless" in b