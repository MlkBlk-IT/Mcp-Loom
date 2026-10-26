# Installation — Mcp-Loom

Portable MCP server. Four ways to install; all of them expose the same
`loom-mcp` console script (the server, on stdio) and a `loom` admin CLI.

> **Naming:** the distribution is `mcp-loom-mcp` (PyPI) and the npm package is
> `mcp-loom-mcp` too. `loom-mcp` is the *console script* those packages install;
> `loom` is the import package and the admin CLI.

| Method | Command | Use it when |
|---|---|---|
| uv (recommended) | `uv tool install mcp-loom-mcp` | You want an isolated tool, no venv to manage |
| pip | `pip install mcp-loom-mcp` | You already manage virtualenvs |
| npm | `npx mcp-loom-mcp` | The client is Node-only (Claude Desktop, Cursor, VS Code) |
| From source | `pip install -e .` | You are hacking on Loom |

The npm wrapper needs no Python at all if [uv](https://docs.astral.sh/uv/) is
installed: it provisions an isolated environment straight from GitHub.

---

## 1. Install

### uv

```bash
uv tool install mcp-loom-mcp             # from PyPI
uv tool install "mcp-loom-mcp[semantic]" # + semantic retrieval (faiss, sentence-transformers)
```

### pip

```bash
pip install mcp-loom-mcp
pip install "mcp-loom-mcp[semantic]"  # + semantic retrieval
```

### npm (Node-only clients)

```bash
npx -y mcp-loom-mcp
```

The npm package is a thin launcher: it finds a Python that can run Loom
(`loom-mcp` on PATH, then `uv tool run --from git+… loom-mcp`, then
`python -m loom`) and execs it with stdio inherited.

### From source

```bash
git clone https://github.com/MlkBlk-IT/mcp-loom-mcp.git
cd mcp-loom-mcp
pip install -e ".[dev,semantic]"
pytest
```

## 2. Build the packages yourself

```bash
pip install build        # or: uv build
python -m build          # writes dist/*.whl and dist/*.tar.gz
```

Artifacts:

- `dist/mcp_loom_mcp-<version>-py3-none-any.whl` — the wheel (pure Python, ~50 KB)
- `dist/mcp_loom_mcp-<version>.tar.gz` — the sdist (code + tests + docs, ~85 KB)

The sdist deliberately excludes the benchmark corpus (`dataset/`), the dev
dashboard (`dash/`) and the `*.bak` artefacts — they are not needed to build.

Install a built artifact:

```bash
pip install dist/mcp_loom_mcp-0.1.3-py3-none-any.whl
```

## 3. Wire it into an MCP client

### Claude Desktop

File: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "loom": {
      "command": "uvx",
      "args": ["--from", "mcp-loom-mcp", "loom-mcp"]
    }
  }
}
```

### Hermes

Add to `%LOCALAPPDATA%\hermes\config.yaml` under `mcp_servers:` — or use the CLI:

```bash
hermes mcp add loom -- uvx --from mcp-loom-mcp loom-mcp
```

### Node-only client (npm)

```json
{
  "mcpServers": {
    "loom": {
      "command": "npx",
      "args": ["-y", "mcp-loom-mcp"]
    }
  }
}
```

### Local dev (from this repo)

```json
{
  "mcpServers": {
    "loom": {
      "command": "uv",
      "args": ["run", "--directory", "D:\\Loom", "loom-mcp"]
    }
  }
}
```

## 4. Verify the connection

```bash
npx @modelcontextprotocol/inspector uvx --from mcp-loom-mcp loom-mcp
```

You should see **17 tools**:

`ctx_store`, `ctx_store_file`, `ctx_store_cmd`, `ctx_get`, `ctx_search`,
`ctx_check`, `ctx_verify`, `ctx_stats`, `ctx_profile`, `ctx_list_sessions`,
`ctx_purge_session`, `ctx_purge_expired`, `ctx_vacuum`, `ctx_health`,
`ctx_transfer`, `ctx_rebuild_index`, `ctx_vector_stats`.

## 5. Admin CLI

The MCP tools are the product; `loom` is the maintenance hatch when no MCP
client is attached to the drawer.

```bash
loom health                 # drawer status (db, sessions, chunks, size)
loom stats --session demo   # token stats for a session
loom sessions               # list sessions (--include-expired)
loom search "build failed"  # FTS5 search over stored chunks
loom vacuum                 # compact the SQLite drawer
loom purge-expired          # drop sessions past their TTL
loom purge <session_id>     # drop one session
loom serve                  # run the MCP server on stdio (same as loom-mcp)
loom version
```

`python -m loom …` is equivalent.

## 6. Environment variables

| Var | Default | Meaning |
|---|---|---|
| `LOOM_DB` | `~/.loom/loom.db` | Drawer location |
| `LOOM_DB_PASSWORD` | *(empty)* | Enable encryption (Fernet or SQLCipher) |
| `LOOM_REDACT` | `1` | Secret redaction before storing (`0` = off) |
| `LOOM_STORE_CMD` | `0` | Enable `ctx_store_cmd` (sandboxed) |
| `LOOM_TTL_DAYS` | `30` | Session expiration |
| `LOOM_RATE_LIMIT` | *(on)* | Token bucket per session / IP |
| `LOOM_RPM` / `LOOM_BURST` | — | Token bucket rate and burst |
| `LOOM_LOG_LEVEL` | `INFO` | Log verbosity |
| `LOOM_ALLOWED_DIRS` | *(unset)* | `;;`-separated dirs `ctx_store_file` may read |

## 7. Known caveat

The test suite is **not green** at the time of writing: 83 tests pass, 19 fail
and 1 module fails to collect. Most failures are a stale test suite after the
Phase 2 refactor, but 4 of them are real anchor regressions. See
[`../PROGRESS.md`](../PROGRESS.md) §4 for the breakdown.

That does not block the installation — the server starts and the tools respond —
but do not treat the current code as production-ready.
