import asyncio, json, os, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = r"D:\Loom"
env = dict(os.environ)
env.update({
    "PYTHONPATH": REPO + r"\src",
    "LOOM_DB": REPO + r"\_test\loom_smoke.db",
    "LOOM_AUDIT_DIR": REPO + r"\_test\audit_smoke",
})
env.pop("LOOM_DB_PASSWORD", None)
if os.environ.get("SMOKE_NORATE") == "1":
    env.update({"LOOM_RATE_LIMIT": "0", "LOOM_RPM": "100000", "LOOM_BURST": "100000"})

async def main():
    params = StdioServerParameters(
        command=REPO + r"\.venv\Scripts\python.exe",
        args=["-m", "loom.server"], env=env)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = (await s.list_tools()).tools
            print("TOOLS", len(tools))
            for t in tools:
                sch = getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {}
                props = list(sch.get("properties", {}).keys())
                print(" -", t.name, props)
            if len(sys.argv) > 1 and sys.argv[1] == "list":
                return
            path = REPO + r"\dataset\medium_02_incident.txt"
            res = await s.call_tool("ctx_store_file", {"path": path})
            txt = "".join(c.text for c in res.content if hasattr(c, "text"))
            import hashlib
            try:
                d0 = json.loads(txt)
            except Exception:
                d0 = {}
            print("STORE_ANCHOR_CHARS", len(d0.get("anchor", "")))
            try:
                d = json.loads(txt)
            except Exception:
                d = {}
            print("STORE_META", {k: d[k] for k in d if k not in ("anchor",)})
            parts = []
            for cid in d.get("chunk_ids", []):
                g = await s.call_tool("ctx_get", {"chunk_id": str(cid)})
                gt = "".join(c.text for c in g.content if hasattr(c, "text"))
                try:
                    gj = json.loads(gt)
                    parts.append(gj.get("content", gj.get("text", "")))
                except Exception:
                    parts.append(gt)
            rebuilt = "".join(parts).encode("utf-8")
            orig = open(path, "rb").read()
            print("ROUNDTRIP n_chunks", len(parts), "bytes_orig", len(orig), "bytes_rebuilt", len(rebuilt))
            print("ROUNDTRIP identical:", hashlib.sha256(orig).hexdigest() == hashlib.sha256(rebuilt).hexdigest())
            ck = await s.call_tool("ctx_check", {})
            print("CHECK", "".join(c.text for c in ck.content if hasattr(c, "text"))[:600])
            st = await s.call_tool("ctx_stats", {})
            print("STATS", "".join(c.text for c in st.content if hasattr(c, "text"))[:600])
asyncio.run(main())
