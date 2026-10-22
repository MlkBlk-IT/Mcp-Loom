"""Smoke bench Loom vs baseline on LM Studio (NOT the final GO/NO-GO).
Metric: sum(prompt_tokens + completion_tokens) over every model call, from LM Studio `usage`.
Loom arm includes: anchor (in prompt), tool schemas (tool tax), every tool result fed back.
Success = exact needle value present in the final answer (think block stripped).
"""
import argparse, asyncio, json, os, random, re, statistics, time, urllib.request, urllib.error

REPO = r"D:\Loom"
DATA = REPO + r"\_test\bench_data"
OUT = REPO + r"\_test\bench_out"
LM = "http://localhost:1234/v1/chat/completions"
MAXTOK = 400  # overridden by --max-tokens (default keeps old runs reproducible)


def make_needles(size, seed=20261021):
    src = open(f"{REPO}\\dataset\\{size}_02_incident.txt", "rb").read().decode("utf-8")
    nl = "\r\n" if "\r\n" in src else "\n"
    lines = src.split(nl)
    rng = random.Random(seed)
    A = ["Kestrel", "Marrow", "Tilde", "Quill", "Brindle", "Sable", "Orrin", "Vesper"]
    B = ["Fenwick", "Haldane", "Pruitt", "Ashgrove", "Lockhart", "Mereweather"]
    L = "KQWZ"
    n = rng.randint(1000, 9999)
    v1 = f"{rng.choice(A)} {rng.choice(B)}"
    v2 = f"ZX-{rng.randint(1000, 9999)}-{rng.choice(L)}{rng.choice(L)}"
    v3 = f"10.{rng.randint(1, 250)}.{rng.randint(1, 250)}.{rng.randint(1, 250)}:{rng.randint(2000, 9000)}"
    v4 = f"build-{rng.randint(1000, 9999)}-{rng.randint(0, 0xFFFFFF):06x}"
    v5 = f"E{rng.randint(10000, 99999)}"
    needles = [
        (f"POSTMORTEM-NOTE: action item AI-{n} (rotate the vault token) is owned by {v1}.",
         f"Who owns action item AI-{n} (rotate the vault token)?", v1),
        (f"POSTMORTEM-NOTE: the vendor escalation ticket for the billing outage is {v2}.",
         "What is the vendor escalation ticket id for the billing outage?", v2),
        (f"POSTMORTEM-NOTE: the rollback canary host is {v3}.",
         "What is the rollback canary host (address:port)?", v3),
        (f"POSTMORTEM-NOTE: the last known good artifact is {v4}.",
         "What is the last known good artifact?", v4),
        (f"POSTMORTEM-NOTE: the customer-facing error code shown during the outage was {v5}.",
         "What customer-facing error code was shown during the outage?", v5),
    ]
    pos = sorted(rng.sample(range(50, len(lines) - 50), len(needles)))
    for p, nd in reversed(list(zip(pos, needles))):
        lines.insert(p, nd[0])
    os.makedirs(DATA, exist_ok=True)
    path = f"{DATA}\\{size}_needles.txt"
    open(path, "wb").write(nl.join(lines).encode("utf-8"))
    return path, [(q, a) for _, q, a in needles]


def chat(model, messages, tools=None, max_tokens=None, timeout=1800):
    body = {"model": model, "messages": messages, "temperature": 0, "seed": 7, "max_tokens": max_tokens or MAXTOK}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    req = urllib.request.Request(LM, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read())
            resp["_secs"] = time.time() - t0
            return resp, None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}"
    except Exception as e:  # noqa
        return None, f"{type(e).__name__}: {e}"


def show(tag, resp):
    u = resp.get("usage", {})
    c = resp["choices"][0]
    m = c["message"]
    s = resp.get("_secs") or 1e-9
    o = u.get("completion_tokens", 0)
    tcs = [(t["function"]["name"], (t["function"].get("arguments") or "")[:120]) for t in (m.get("tool_calls") or [])]
    print(f"   [{tag}] finish={c.get('finish_reason')} in={u.get('prompt_tokens')} out={o} secs={s:.1f} e2e_tk/s={o / s:.1f}")
    print(f"   content: {(m.get('content') or '')[:300]!r}")
    print(f"   tool_calls: {tcs}")
    if resp.get("stats"):
        print(f"   lmstudio stats: {resp['stats']}")


def clean(text):
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()


import unicodedata


def norm(s):
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"[\u2010-\u2015\u2212]", "-", s)
    return s.strip().strip("`'\".,;: ")


def run_baseline(model, text, q, a, nothink):
    suffix = " /no_think" if nothink else ""
    msgs = [
        {"role": "system", "content": "Answer using only the document. Reply with the exact value only."},
        {"role": "user", "content": f"DOCUMENT:\n{text}\n\nQUESTION: {q}{suffix}"},
    ]
    t0 = time.time()
    resp, err = chat(model, msgs)
    if err:
        return dict(ok=False, err=err, tin=0, tout=0, calls=1, tool_calls=0, secs=time.time() - t0, answer="")
    u = resp.get("usage", {})
    show("baseline", resp)
    ans = clean(resp["choices"][0]["message"].get("content"))
    return dict(ok=norm(a) in norm(ans), raw_exact=(ans.strip() == a), err=None, tin=u.get("prompt_tokens", 0), tout=u.get("completion_tokens", 0),
                calls=1, tool_calls=0, secs=time.time() - t0, answer=ans[:200])


async def run_loom(model, session, anchor, tools, q, a, nothink, max_iter=6, cap=8000):
    suffix = " /no_think" if nothink else ""
    msgs = [
        {"role": "system", "content": "A large document was stored outside the prompt with Loom. The anchor is a lossy index and is NOT sufficient to answer. Before answering, you MUST call ctx_search, then ctx_get if needed. Never ask the user for the document. Reply with the exact value only."},
        {"role": "user", "content": f"Session: {session}\nAnchor (key invariants of the stored document):\n{anchor}\n\nQUESTION: {q}{suffix}"},
    ]
    tin = tout = calls = ntool = 0
    t0 = time.time()
    ans = ""
    err = None
    for _ in range(max_iter):
        resp, err = chat(model, msgs, tools=tools["openai"])
        calls += 1
        if err:
            break
        u = resp.get("usage", {})
        show(f"call{calls}", resp)
        tin += u.get("prompt_tokens", 0)
        tout += u.get("completion_tokens", 0)
        m = resp["choices"][0]["message"]
        tcs = m.get("tool_calls") or []
        if not tcs:
            ans = clean(m.get("content"))
            break
        msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": tcs})
        for tc in tcs:
            ntool += 1
            fn = tc["function"]["name"]
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except Exception:
                args = {}
            if "session_id" in tools["props"].get(fn, []) and "session_id" not in args:
                args["session_id"] = session
            try:
                res = await tools["session"].call_tool(fn, args)
                out = "".join(c.text for c in res.content if hasattr(c, "text"))
            except Exception as e:  # noqa
                out = f"tool error: {e}"
            print(f"   tool_result[{fn}]: {out[:150]!r}")
            msgs.append({"role": "tool", "tool_call_id": tc.get("id", fn), "content": out[:cap]})
    return dict(ok=bool(ans) and norm(a) in norm(ans), raw_exact=(ans.strip() == a), err=err, tin=tin, tout=tout, calls=calls, tool_calls=ntool,
                secs=time.time() - t0, answer=ans[:200])


def med(xs):
    return statistics.median(xs) if xs else None


def summarize(name, rows):
    ok = [r for r in rows if r["ok"]]
    tot = [r["tin"] + r["tout"] for r in rows]
    print(f"[{name}] success {len(ok)}/{len(rows)} (raw_exact {sum(1 for r in rows if r.get('raw_exact'))}/{len(rows)}) | median total tokens {med(tot)} "
          f"(in {med([r['tin'] for r in rows])}, out {med([r['tout'] for r in rows])}) | "
          f"median secs {round(med([r['secs'] for r in rows]), 1)} | median tool calls {med([r['tool_calls'] for r in rows])}")
    errs = [r["err"] for r in rows if r["err"]]
    if errs:
        print(f"   errors: {errs[0]}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--size", default="small", choices=["small", "medium"])
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--arms", default="baseline,loom")
    ap.add_argument("--tools", default="all", choices=["all", "core"])
    ap.add_argument("--nothink", type=int, default=1)
    ap.add_argument("--max-tokens", type=int, default=400, dest="max_tokens")
    a = ap.parse_args()
    global MAXTOK
    MAXTOK = a.max_tokens
    print(f"config: model={a.model} size={a.size} n={a.n} tools={a.tools} nothink={a.nothink} max_tokens={MAXTOK}")
    os.makedirs(OUT, exist_ok=True)
    path, qa = make_needles(a.size)
    qa = qa[: a.n]
    text = open(path, "rb").read().decode("utf-8")
    results = {}
    arms = a.arms.split(",")

    if "baseline" in arms:
        rows = []
        for i, (q, ans) in enumerate(qa, 1):
            print(f"\nQ{i}: {q} | attendu: {ans}")
            r = run_baseline(a.model, text, q, ans, a.nothink)
            rows.append(r)
            print(f"baseline q{i}: ok={r['ok']} raw={r.get('raw_exact')} tin={r['tin']} tout={r['tout']} secs={r['secs']:.1f} {r['err'] or ''}", flush=True)
        results["baseline"] = rows

    if "loom" in arms:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        dbp = f"{REPO}\\_test\\loom_bench_{a.size}.db"
        for suf in ("", "-wal", "-shm"):
            if os.path.exists(dbp + suf):
                os.remove(dbp + suf)
        env = dict(os.environ)
        env.update({"PYTHONPATH": REPO + r"\src", "LOOM_DB": dbp, "LOOM_AUDIT_DIR": REPO + r"\_test\audit_bench",
                    "LOOM_RATE_LIMIT": "0", "LOOM_RPM": "100000", "LOOM_BURST": "100000"})
        env.pop("LOOM_DB_PASSWORD", None)
        params = StdioServerParameters(command=REPO + r"\.venv\Scripts\python.exe", args=["-m", "loom.server"], env=env)
        async with stdio_client(params) as (r_, w_):
            async with ClientSession(r_, w_) as s:
                await s.initialize()
                lt = (await s.list_tools()).tools
                keep = {"ctx_get", "ctx_search"} if a.tools == "core" else None
                oa, props = [], {}
                for t in lt:
                    if keep and t.name not in keep:
                        continue
                    sch = getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {}
                    props[t.name] = list(sch.get("properties", {}).keys())
                    oa.append({"type": "function", "function": {"name": t.name, "description": (t.description or "")[:600], "parameters": sch}})
                print(f"loom tools exposed: {len(oa)} ({a.tools})")
                sid = f"bench-{a.size}"
                st = json.loads("".join(c.text for c in (await s.call_tool("ctx_store_file", {"path": path, "session_id": sid})).content if hasattr(c, "text")))
                print(f"loom store: tokens_before={st.get('tokens_before')} anchor_tokens={st.get('tokens_after')} chunks={len(st.get('chunk_ids', []))}")
                tools = {"openai": oa, "props": props, "session": s}
                rows = []
                for i, (q, ans) in enumerate(qa, 1):
                    print(f"\nQ{i}: {q} | attendu: {ans}")
                    r = await run_loom(a.model, sid, st["anchor"], tools, q, ans, a.nothink)
                    rows.append(r)
                    print(f"loom q{i}: ok={r['ok']} raw={r.get('raw_exact')} tin={r['tin']} tout={r['tout']} calls={r['calls']} tool_calls={r['tool_calls']} secs={r['secs']:.1f} {r['err'] or ''}", flush=True)
                results["loom"] = rows

    print("\n=== SUMMARY (smoke, N=%d, pas le verdict GO/NO-GO) ===" % len(qa))
    for k, v in results.items():
        summarize(k, v)
    if "baseline" in results and "loom" in results:
        both = [(b, l) for b, l in zip(results["baseline"], results["loom"]) if b["ok"] and l["ok"]]
        if both:
            bt = med([b["tin"] + b["tout"] for b, _ in both])
            lt_ = med([l["tin"] + l["tout"] for _, l in both])
            print(f"questions reussies par les 2 bras: {len(both)} | median baseline {bt} vs loom {lt_} | reduction {round((1 - lt_ / bt) * 100, 1)} %")
        else:
            print("aucune question reussie par les 2 bras: pas de comparaison valide")
    json.dump(results, open(f"{OUT}\\bench_{a.size}_{a.tools}_{int(time.time())}.json", "w"), indent=1)


asyncio.run(main())
