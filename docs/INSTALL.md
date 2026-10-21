# Template Claude Desktop / Hermes / Cursor config

Add the `loom` entry to your MCP servers block.

## Claude Desktop

File: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "loom": {
      "command": "uvx",
      "args": ["loom-mcp"]
    }
  }
}
```

## Hermes

Add to `%LOCALAPPDATA%\hermes\config.yaml` under `mcp_servers:` — or use the CLI:

```bash
hermes mcp add loom -- uvx loom-mcp
```

## Local dev (from this repo)

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

## Verify the connection

```bash
npx @modelcontextprotocol/inspector uvx loom-mcp
```

You should see 13 tools:

`ctx_store`, `ctx_store_file`, `ctx_store_cmd`, `ctx_get`, `ctx_search`, `ctx_check`,
`ctx_stats`, `ctx_profile`, `ctx_list_sessions`, `ctx_purge_session`, `ctx_purge_expired`,
`ctx_vacuum`, `ctx_health`.

## Environment variables

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
