import asyncio, hashlib, json, os, time
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = r"D:\Loom"
env = dict(os.environ)
env.update({
    "PYTHONPATH": REPO + r"\src",
    "LOOM_DB": REPO + r"\_test\loom_scale.db",
    "LOOM_AUDIT_DIR": REPO + r"\_test\audit_scale",
    "LOOM_RATE_LIMIT": "0", "LOOM_RPM": "100000", "LOOM_BURST": "100000",
})
env.pop("LOOM_DB_PASSWORD", None)

FILES = ["small_02_incident.txt", "medium_02_incident.txt", "large_02_incident.txt"]

def txt(res):
    return "".join(c.text for c in res.content if hasattr(c, "text"))

async def main():
    params = StdioServerParameters(command=REPO + r"\.venv\Scripts\python.exe",
                                   args=["-m", "loom.server"], env=env)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            for name in FILES:
                path = REPO + "\\dataset\\" + name
                orig = open(path, "rb").read()
                sid = "scale-" + name.split("_")[0]
                t0 = time.time()
                d = json.loads(txt(await s.call_tool("ctx_store_file", {"path": path, "session_id": sid})))
                t_store = time.time() - t0
                ids = d.get("chunk_ids", [])
                t0 = time.time()
                parts = []
                for cid in ids:
                    g = txt(await s.call_tool("ctx_get", {"chunk_id": str(cid)}))
                    try:
                        j = json.loads(g)
                        parts.append(j.get("content", j.get("text", "")))
                    except Exception:
                        parts.append(g)
                t_get = time.time() - t0
                rebuilt = "".join(parts).encode("utf-8")
                raw_ok = hashlib.sha256(orig).digest() == hashlib.sha256(rebuilt).digest()
                norm_ok = orig.replace(b"\r\n", b"\n") == rebuilt
                tb, ta = d.get("tokens_before"), d.get("tokens_after")
                n = len(ids)
                one_chunk = round(tb / n) if n else 0
                ck = json.loads(txt(await s.call_tool("ctx_check", {"session_id": sid})))
                print(f"{name}: bytes={len(orig)} chunks={n} tok_before={tb} tok_anchor={ta} "
                      f"saved_ratio={d.get('saved_ratio')} anchor_plus_1chunk~={ta + one_chunk} "
                      f"store_s={t_store:.2f} get_all_s={t_get:.2f} "
                      f"roundtrip_raw={raw_ok} roundtrip_CRLFnorm={norm_ok} "
                      f"check_cov={ck.get('coverage')} check_inctx={ck.get('in_context')} "
                      f"critical_missing={ck.get('critical_missing')} inv_total={ck.get('invariants_total')}")
asyncio.run(main())
