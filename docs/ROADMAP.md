# Roadmap — Loom

Status legend: `[ ]` todo · `[~]` in progress · `[x]` done

## P0 — Core (must exist before anything ships)

- [ ] `anchors.py` — invariant extractor (numbers, paths, URLs, versions, constraints)
- [ ] `compress.py` — tool-output cleansing + anchor building
- [ ] `store.py` — SQLite drawer with FTS5 index
- [ ] `verify.py` — coverage checker
- [ ] `server.py` — 5 MCP tools over FastMCP
- [ ] `test_safety_net.py` — 100 % invariant coverage over a corpus
- [ ] `test_roundtrip.py` — store/retrieve byte-identical

**Exit criteria:** `pytest` green; a 50 KB log yields ≥ 80 % token reduction with
`lossless=true` and `coverage=1.0`.

## P1 — Portability

- [ ] Streamable HTTP transport (remote / shared drawer)
- [ ] Package on PyPI (`uvx loom-mcp` works)
- [ ] npm wrapper (`npx loom-mcp`) for Node-only clients
- [ ] API/SDK mode: `loom.wrap(client)` middleware for non-MCP apps
- [ ] Second client integration test (Claude Code / Hermes)

**Exit criteria:** same server, 2 different clients, identical results.

## P2 — Agentic workflow integration

- [ ] MCP prompts: `loom_usage` (auto-usage instructions for the agent)
- [ ] Tool annotations tuned (`readOnlyHint`, `idempotentHint`)
- [ ] Context-budget guard mode: warn when context exceeds N tokens
- [ ] `ctx_search` (FTS over stored chunks)

## P3 — Multi-agent shared drawer

- [ ] Lineage: who stored what, when, derived from what
- [ ] Cross-client cache hits (Hermes stores → Claude retrieves)
- [ ] Concurrency-safe SQLite (WAL)

## P4 — Research & proof

- [ ] Eval harness (promptfoo-style): tasks × {baseline, loom} → tokens vs quality
- [ ] Published benchmark table
- [ ] Optional lossy mode behind explicit opt-in, with delta report
- [ ] Local embedding backend (optional) for semantic retrieval

## Risks to retire early

1. **Silent information loss** → mitigated by the safety net being written first.
2. **Agent never calls the tools** → mitigated by P2 prompts + budget guard.
3. **Latency** → target < 100 ms per `ctx_store`; measure, don't assume.
