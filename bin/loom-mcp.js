#!/usr/bin/env node
// npm wrapper for the Loom MCP server.
//
// Node-only MCP clients (Claude Desktop, Cursor, VS Code...) can spawn
// `npx loom-mcp` without a Python toolchain. This wrapper locates a Python
// that can run Loom and execs the server on stdio.
//
// IMPORTANT: an MCP stdio server owns stdout. This wrapper must never print
// to stdout - every diagnostic goes to stderr.

'use strict';

const { spawn, spawnSync } = require('node:child_process');

const REPO = 'git+https://github.com/MlkBlk-IT/mcp-loom-mcp.git';

function which(cmd) {
  const probe = process.platform === 'win32' ? 'where' : 'which';
  const r = spawnSync(probe, [cmd], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
  if (r.status !== 0) return null;
  const first = (r.stdout || '').split(/\r?\n/).filter(Boolean)[0];
  return first || null;
}

// Candidate launchers, most specific first.
function candidates() {
  const list = [];

  // 1. Loom already installed via pip / uv -> use the console script as-is.
  const installed = which('loom-mcp');
  if (installed) list.push({ cmd: installed, args: [] });

  // 2. uv can provision an isolated env straight from the GitHub repo.
  const uv = which('uv');
  if (uv) list.push({ cmd: uv, args: ['tool', 'run', '--from', REPO, 'loom-mcp'] });

  // 3. Plain python with the package importable.
  for (const py of ['python3', 'python']) {
    const p = which(py);
    if (p) list.push({ cmd: p, args: ['-m', 'loom'] });
  }

  return list;
}

function main() {
  const list = candidates();
  if (list.length === 0) {
    process.stderr.write(
      '[loom-mcp] no Python runtime found. Install Python 3.11+ and `pip install loom-mcp`,\n' +
      '[loom-mcp] or install uv (https://docs.astral.sh/uv/) which this wrapper uses to\n' +
      '[loom-mcp] provision an isolated environment from GitHub.\n'
    );
    process.exit(127);
  }

  let lastError = null;
  for (const { cmd, args } of list) {
    try {
      const child = spawn(cmd, args, { stdio: 'inherit' });
      child.on('error', (err) => { lastError = err; });
      child.on('exit', (code, signal) => {
        if (signal) process.kill(process.pid, signal);
        else process.exit(code === null ? 1 : code);
      });
      return;
    } catch (err) {
      lastError = err;
    }
  }

  process.stderr.write(`[loom-mcp] failed to start: ${lastError && lastError.message}\n`);
  process.exit(1);
}

main();
