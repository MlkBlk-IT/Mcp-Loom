# Mcp-Loom — Release notes

> This file is the release annotation for each published version. It is maintained in English;
> the rest of the repository (code, comments, internal docs) is written in French.

---

## v0.1.1 — 2026-10-26

**Documentation accuracy + dashboard configuration.** This release contains no change to the
context engine itself — it fixes the documentation and the local dashboard wiring.

### Added
- **Configurable dashboard port** — `dash/server.py` reads `LOOM_DASH_PORT` (default `8775`).
  The port was previously hard-coded to `8765`, which collided with other local services.
- **`UPDATE-NOTES.md`** — this file, the release annotation for each version.
- **README version badge** pointing at the GitHub releases.

### Fixed
- **Dashboard pointed at a test database** — `dash/tray.py` opened `D:\Loom\_test\loom_claude.db`
  instead of the real drawer. It now uses the standard `C:\Users\Tech\.loom\loom.db` location, and
  the tray opens the dashboard on the configurable port.
- **README tool count** — the tool table listed 13 tools; the server actually exposes **17**
  (`ctx_verify`, `ctx_transfer`, `ctx_rebuild_index` and `ctx_vector_stats` were missing).
- **README test count** — the README claimed "38 green tests" and the banner claimed "72 tests
  pass". The measured state is **83 passed / 19 failed / 1 collection error** out of 103 test
  functions in 20 files.

### Removed
- Stale dashboard captures (`dash/shot-*.png`, `loom-shot-v4.js`) and the `.bak` editing backups
  under `dash/static/` — working artefacts, not deliverables. `*.bak*` is now git-ignored.

### Changed
- `README.md` — tool table completed to 17 tools, the test-suite section rewritten to state the
  real numbers, the WIP banner refreshed (2026-10-26) and pointed at `PROGRESS.md`.
- Version bumped to 0.1.1 (`pyproject.toml`, `package.json`).

### Honest status — read before using this
- **Not ready for production.** No token savings have been demonstrated yet: the published
  `saved_pct` figures (94–99%) measured the anchor size alone and are **invalid**.
- The current real measurement (LM Studio, small local models, small documents) shows Loom
  **costing more** tokens than the baseline, because of the fixed anchor overhead and the tool
  schemas. The large-context test with a cloud model has not been run.
- The decision criterion was frozen before the benchmark: the same success rate with **≥ 35% fewer
  total tokens** (in + out), retrieval and tool tax included. Otherwise: pivot or stop.
- 4 of the 19 test failures are **real anchor regressions** (`port` kind no longer produced, rare
  kinds no longer reaching the `strict` anchor, dates still extracted as numbers). The other 15
  come from a code refactor that was not followed by a test update.
- The `saved_pct` numbers in the benchmark tables below are kept for history, with the invalidation
  notice above.

---

## v0.1.0 — 2026-10-25

- First installable release: `pip install loom-mcp`, `npx loom-mcp`.
- Portable MCP server — 17 tools, SQLite + FTS5 drawer, admin CLI (`loom health`, `loom stats`,
  `loom vacuum`, `loom search`…), wheel + sdist + npm wrapper.
